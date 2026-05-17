#

import re
import serial
import logging
import numpy as np
import pandas as pd

from serial import SerialException

try:
    from queue import Queue, Empty
except ImportError:
    from Queue import Queue, Empty

SERIAL_TIMER = 0.1

def avg_coords(samples):
    if len(samples) > 4:
        samples = samples[5:]
    n = len(samples)
    avg_x = sum(s['x_raw'] for s in samples) // n
    avg_y = sum(s['y_raw'] for s in samples) // n
    return avg_x, avg_y

PANEL_COORDS = [
    (26, 50, 'left'),
    (106, 50, 'right'),
    (66, 70, 'top'),
    (66, 30, 'bottom'),
    (66, 50, 'center'),
]
CALIB_COORDS = [
    (26, 70, 'top left'),
    (106, 70, 'top right'),
    (26, 30, 'bottom left'),
    (106, 30, 'bottom right'),
    (66, 50, 'center'),
]
PANEL_XRANGE = (26, 106)
PANEL_YRANGE = (30, 70)
PANEL_ZHOME = 9

def bounded_pos(pos):
    xmin, xmax = PANEL_XRANGE
    ymin, ymax = PANEL_YRANGE
    x, y, z = pos
    x = max(xmin, min(xmax, x))
    y = max(ymin, min(ymax, y))
    return x, y, PANEL_ZHOME

def gen_bb_coords(inset=5):
    xmin, xmax = PANEL_XRANGE
    ymin, ymax = PANEL_YRANGE
    return [
        (xmin + inset, ymin + inset, PANEL_ZHOME),
        (xmax - inset, ymin + inset, PANEL_ZHOME),
        (xmax - inset, ymax - inset, PANEL_ZHOME),
        (xmin + inset, ymax - inset, PANEL_ZHOME),
    ]


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
            "LRT_PROBE", self.cmd_LRT_PROBE, desc="Probe tool using touch probe")

        self.gcode.register_command(
            "LRT_PROBE_TOOL", self.cmd_PROBE_TOOL, desc="Probe tool using touch probe")

        self.printer.register_event_handler("klippy:connect", self.on_connect)


    def on_connect(self):
        self.connect(self.gcode)

    def _parse_touch(self, line: str):
        if 'LMNRT' in line:
            line = line.split('<<<')[1]
            vars = map(lambda x: x.split('='), line.split(', '))
            return dict((k, int(v)) for k, v in vars)

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
        return res
    
    def _move(self, coords, speed):
        toolhead = self.printer.lookup_object('toolhead')
        toolhead.manual_move(coords, speed)

    def probe_at(self, coords, gcmd):
        self._move(coords, self.TRAVEL_SPEED)
        self.begin_sample_collection()
        probe_session = self.probe.start_probe_session(gcmd)
        probe_session.run_probe(gcmd)

        pos = probe_session.pull_probed_results()[0]
        samples = self.pull_samples()
        data = [{'x': s['x'], 'y': s['y'], 'cx': pos[0], 'cy': pos[1]} for s in samples]

        probe_session.end_probe_session()

        self._move(coords, self.TRAVEL_SPEED)
        return pos, pd.DataFrame(data)

    def cmd_LRT_PROBE(self, gcmd):
        curr_pos = self.printer.lookup_object('toolhead').get_position()
        new_pos = bounded_pos(curr_pos[:3])
        pos, df = self.probe_at(new_pos, gcmd)
        # gcmd.respond_info(f"[LRT] Probed at {new_pos}, got {samples=} {touch_pos=}")
        gcmd.respond_info(f"[LRT] Sample stats at {new_pos}: {df.median()}")


    def cmd_PROBE_TOOL(self, gcmd):
        H_PARK = 9
        touch_coords = [
            # Rect (loop)
            (50, 50, H_PARK),
            (55, 50, H_PARK),
            (65, 40, H_PARK),
            (50, 40, H_PARK),
            (50, 41, H_PARK),
            (70, 45, H_PARK),
            (68, 42, H_PARK),
            (45, 45, H_PARK),
            (80, 45, H_PARK),
            (80, 35, H_PARK),
            (75, 52, H_PARK),
            (45, 55, H_PARK),
            (62, 52, H_PARK),
            (62, 55, H_PARK),
        ]
        calibration_corners = [*gen_bb_coords(inset=10), *gen_bb_coords(inset=15), *gen_bb_coords(inset=22)]
        data = []
        for coord in calibration_corners:
            pos, df = self.probe_at(coord, gcmd)
            tx, ty, *_ = df.median()
            gcmd.respond_info(f"[LRT] Probed at {coord}, got {tx=} {ty=}")
            data.append((coord, (tx, ty, coord[2])))

        gcmd.respond_info(f"[LRT] Probe data: {data}")

    def get_status(self, eventtime):
        last_output = str(self.samples)
        return {'sample_len': len(self.samples), 'samples': last_output}


def load_config(config):
    return ToolTouchProbeExtension(config)
