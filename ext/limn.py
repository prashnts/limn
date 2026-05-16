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


class ToolTouchProbeExtension:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object('gcode')
        self.probe = self.printer.lookup_object('probe')


        self.serial = None
        self.serial_port = config.get("serial")
        if not self.serial_port:
            raise config.error("Invalid serial port specific for Palette 2")
        self.baud = config.getint("baud", default=115200)


        self.read_timer = None
        self.read_buffer = ""
        self.read_queue = Queue()
        self.write_timer = None
        self.write_queue = Queue()
        self.signal_disconnect = False


        self.samples = []


        self.gcode.register_command(
            "LRT_CONNECT", self.cmd_Connect, desc=self.cmd_Connect_Help)
        self.gcode.register_command(
            "LRT_DISCONNECT",
            self.cmd_Disconnect,
            desc=self.cmd_Disconnect_Help)

    def start_probe(self):
        self.gcode.run_script_from_command(cmd_str)

    def _parse_touch(self, line: str):
        pattern = r'.*xpt2046.* Touchscreen Update \[(\d+), (\d+)\], z = (\d+)'
        match = re.match(pattern, line)
        if match:
            x, y, z = match.groups()
            return float(x), float(y), float(z)
        return None

    def _read_serial(self, eventtime):
        if self.signal_disconnect:
            self.cmd_Disconnect()
            return self.reactor.NEVER

        while True:
            # copied from pallete2
            try:
                raw_bytes = self.serial.read()
            except SerialException:
                logging.error("Unable to communicate with the Palette 2")
                self.cmd_Disconnect()
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

    cmd_Connect_Help = "Connect to LRT via serial port"
    def cmd_Connect(self, gcmd):
        if self.serial:
            gcmd.respond_info("[LRT] Already connected")
            return

        self.signal_disconnect = False
        logging.info("[LRT] Connecting to (%s) at (%s)" %
                     (self.serial_port, self.baud))
        try:
            self.serial = serial.Serial(
                self.serial_port, self.baud, timeout=0, write_timeout=0)
        except SerialException:
            gcmd.respond_info("[LRT] Unable to connect")
            return
    
        self.read_timer = self.reactor.register_timer(self._read_serial, self.reactor.NOW)


    cmd_Disconnect_Help = ("Disconnect from LRT")
    def cmd_Disconnect(self, gcmd=None):
        self.gcode.respond_info("[LRT] Disconnecting")
        if self.serial:
            self.serial.close()
            self.serial = None

        self.reactor.unregister_timer(self.read_timer)
        self.reactor.unregister_timer(self.write_timer)
        self.read_timer = None
        self.write_timer = None
        self.is_printing = False


    def pull_samples(self):
        res = self.samples
        self.samples = []
        return res

    def get_status(self, eventtime):
        last_output = str(self.samples)
        return {'sample_len': len(self.samples), 'samples': last_output}


def load_config(config):
    return ToolTouchProbeExtension(config)
