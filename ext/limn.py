#

import re
import serial
import logging

from serial import SerialException

try:
    from queue import Queue, Empty
except ImportError:
    from Queue import Queue, Empty

SERIAL_TIMER = 0.1

def avg_coords(samples, scale=100):
    if len(samples) > 12:
        samples = samples[10:]
    n = max(len(samples), 1) * scale
    avg_x = sum(s[0] for s in samples) / n
    avg_y = sum(s[1] for s in samples) / n
    avg_z = sum(s[2] for s in samples) / n
    return avg_x, avg_y, avg_z


class ToolTouchProbeExtension:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object('gcode')
        self.probe = self.printer.lookup_object('probe')


        self.serial = None
        self.serial_port = config.get("serial")
        if not self.serial_port:
            raise config.error("Invalid serial port specific for Palette 2")
        self.baud = config.getint("baud", default=115200)


        self.TOUCH_MIN_X = 40
        self.TOUCH_AT = (50, 50)
        self.PARK_AT = (50, 50, 10)
        self.TRAVEL_SPEED = 50
        self.Z_SPEED = 3

        self.read_timer = None
        self.read_buffer = ""
        self.read_queue = Queue()
        self.write_timer = None
        self.write_queue = Queue()
        self.signal_disconnect = False


        self.samples = []


        self.gcode.register_command(
            "LRT_CONNECT", self.connect, desc=self.connect_help)
        self.gcode.register_command(
            "LRT_DISCONNECT",
            self.disconnect,
            desc=self.disconnect_help)
        self.gcode.register_command(
            "LRT_PROBE", self.cmd_PROBE_TOOL, desc="Probe tool using touch probe")

        self.printer.register_event_handler("klippy:connect", self.on_connect)


    def on_connect(self):
        self.connect(self.gcode)

    def _parse_touch(self, line: str):
        pattern = r'.*xpt2046.* Touchscreen Update \[(\d+), (\d+)\], z = (\d+)'
        match = re.match(pattern, line)
        if match:
            x, y, z = match.groups()
            return float(x), float(y), float(z)
        return None

    def _read_serial(self, eventtime):
        if self.signal_disconnect:
            self.disconnect()
            return self.reactor.NEVER

        while True:
            # copied from pallete2
            try:
                raw_bytes = self.serial.read()
            except SerialException:
                logging.error("Unable to communicate with the Palette 2")
                self.disconnect()
                return self.reactor.NEVER

            if len(raw_bytes):
                new_buffer = str(raw_bytes.decode(encoding='UTF-8',
                                                  errors='ignore'))
                text_buffer = self.read_buffer + new_buffer
                while True:
                    i = text_buffer.find("\n")
                    if i >= 0:
                        line = text_buffer[0:i + 1]
                        self.read_queue.put(line.strip())
                        text_buffer = text_buffer[i + 1:]
                    else:
                        break
                self.read_buffer = text_buffer
            else:
                break

        # Process any decoded lines from the device
        while not self.read_queue.empty():
            try:
                text_line = self.read_queue.get_nowait()
            except Empty:
                pass

            coords = self._parse_touch(text_line)

            if coords:
                self.samples.append(coords)

        return eventtime + SERIAL_TIMER

    connect_help = "Connect to LRT via serial port"
    def connect(self, gcmd):
        if self.serial:
            gcmd.respond_info("[LRT] Already connected")
            return

        self.signal_disconnect = False
        logging.info("[LRT] Connecting to (%s) at (%s)" %
                     (self.serial_port, self.baud))
        gcmd.respond_info("[LRT] Connecting")
        try:
            self.serial = serial.Serial(
                self.serial_port, self.baud, timeout=0, write_timeout=0)
        except SerialException:
            gcmd.respond_info("[LRT] Unable to connect")
            return
    
        gcmd.respond_info("[LRT] Connected")
        self.read_timer = self.reactor.register_timer(self._read_serial, self.reactor.NOW)

    disconnect_help = ("Disconnect from LRT")
    def disconnect(self, gcmd=None):
        self.gcode.respond_info("[LRT] Disconnecting")
        if self.serial:
            self.serial.close()
            self.serial = None

        self.reactor.unregister_timer(self.read_timer)
        self.read_timer = None
        self.is_printing = False


    def begin_sample_collection(self):
        self.samples = []

    def pull_samples(self):
        res = self.samples
        self.samples = []
        return res, avg_coords(res)
    
    def _move(self, coords, speed):
        toolhead = self.printer.lookup_object('toolhead')
        toolhead.manual_move(coords, speed)

    def probe_at(self, coords, gcmd):
        self._move(coords, self.TRAVEL_SPEED)
        self.begin_sample_collection()
        probe_session = self.probe.start_probe_session(gcmd)
        probe_session.run_probe(gcmd)

        pos = probe_session.pull_probed_results()[0]
        _, touch_pos = self.pull_samples()

        probe_session.end_probe_session()
        gcmd.respond_info(f"[LRT] {coords=} {touch_pos=}")

        self._move(coords, self.TRAVEL_SPEED)
        return pos, touch_pos
      
    def cmd_PROBE_TOOL(self, gcmd):
        H_PARK = 10
        rect_coords = [
            # Rect (loop)
            (50, 35, H_PARK),
            (90, 35, H_PARK),
            (90, 70, H_PARK),
            (50, 70, H_PARK),
            (50, 35, H_PARK),
        ]
        fine_coords = [
            (50, 35, H_PARK),
            (55, 40, H_PARK),
            (60, 45, H_PARK),
            (65, 50, H_PARK),
            (75, 50, H_PARK),
            (65, 50, H_PARK),
            (69, 55, H_PARK),
            (71, 50, H_PARK),
            (73, 55, H_PARK),
        ]
        coords = [*rect_coords, *fine_coords]
        data = []
        for coord in coords:
            pos, touch_pos = self.probe_at(coord, gcmd)
            data.append([coord, touch_pos])
        gcmd.respond_info(f"[LRT] Probe data: {data}")

    def get_status(self, eventtime):
        last_output = str(self.samples)
        return {'sample_len': len(self.samples), 'samples': last_output}


def load_config(config):
    return ToolTouchProbeExtension(config)
