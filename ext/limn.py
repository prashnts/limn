#

import re
import random
import serial
import logging
import numpy as np
import pandas as pd
import json

from serial import SerialException

try:
    from queue import Queue, Empty
except ImportError:
    from Queue import Queue, Empty

SERIAL_TIMER = 0.1
LRT_CONF_VERSION = 'v2.0'
PANEL_XRANGE = (45, 106)
PANEL_YRANGE = (40, 70)
PANEL_ZHOME = 9
MAX_DEV = 5


def bounded_pos(pos):
    xmin, xmax = PANEL_XRANGE
    ymin, ymax = PANEL_YRANGE
    x, y, z = pos
    x = max(xmin, min(xmax, x))
    y = max(ymin, min(ymax, y))
    return x, y, PANEL_ZHOME

def gen_bb_grid(*, nx=5, ny=5, xrange=PANEL_XRANGE, yrange=PANEL_YRANGE, deviation=0):
    xmin, xmax = xrange
    ymin, ymax = yrange

    coords = [
        # (xmin, ymin, PANEL_ZHOME),
        # (xmin, ymax, PANEL_ZHOME),
        # (xmax, ymin, PANEL_ZHOME),
        # (xmax, ymax, PANEL_ZHOME),
    ]

    stepx = (xmax - xmin) / (nx - 1)
    stepy = (ymax - ymin) / (ny - 1)
    
    for x in np.arange(xmin, xmax + 1, stepx):
        for y in np.arange(ymin, ymax + 1, stepy):
            x += random.uniform(-deviation, deviation)
            y += random.uniform(-deviation, deviation)
            x = np.round(x, 2).tolist()
            y = np.round(y, 2).tolist()
            coords.append((x, y, PANEL_ZHOME))
    return coords


def gen_bb_coords(inset=5):
    xmin, xmax = PANEL_XRANGE
    ymin, ymax = PANEL_YRANGE
    ratio = (xmax - xmin) / (ymax - ymin)
    inset_x = inset * ratio
    inset_y = inset / ratio

    return [
        # corners
        (xmin + inset_x, ymin + inset_y, PANEL_ZHOME),
        (xmax - inset_x, ymin + inset_y, PANEL_ZHOME),
        (xmax - inset_x, ymax - inset_y, PANEL_ZHOME),
        (xmin + inset_x, ymax - inset_y, PANEL_ZHOME),
        # midways
        (xmin + (xmax - xmin) / 2, ymin + inset_y, PANEL_ZHOME),
        (xmin + (xmax - xmin) / 2, ymax - inset_y, PANEL_ZHOME),
        (xmin + inset_x, ymin + (ymax - ymin) / 2, PANEL_ZHOME),
        (xmax - inset_x, ymin + (ymax - ymin) / 2, PANEL_ZHOME),
    ]

def get_touch_transform(data):
    # Taken from ATMEL application note.
    Xd1 = data[0][0][0]
    Yd1 = data[0][0][1]
    Xd2 = data[1][0][0]
    Yd2 = data[1][0][1]
    Xd3 = data[2][0][0]
    Yd3 = data[2][0][1]

    Xt1 = data[0][1][0]
    Yt1 = data[0][1][1]
    Xt2 = data[1][1][0]
    Yt2 = data[1][1][1]
    Xt3 = data[2][1][0]
    Yt3 = data[2][1][1]

    A = (((Xd1 * (Yt2 - Yt3)) + (Xd2 * (Yt3 - Yt1)) + (Xd3 * (Yt1 - Yt2)))
         /((Xt1 * (Yt2 - Yt3)) + (Xt2 * (Yt3 - Yt1)) + (Xt3 * (Yt1 - Yt2))))
    B = ((A * (Xt3 - Xt2)) + Xd2 - Xd3) / (Yt2 - Yt3)
    C = Xd3 - (A * Xt3) - (B * Yt3)

    D = (((Yd1 * (Yt2 - Yt3)) + (Yd2 * (Yt3 - Yt1)) + (Yd3 * (Yt1 - Yt2)))
         /((Xt1 * (Yt2 - Yt3)) + (Xt2 * (Yt3 - Yt1)) + (Xt3 * (Yt1 - Yt2))))
    E = ((D * (Xt3 - Xt2)) + Yd2 - Yd3)/(Yt2 - Yt3)
    F = Yd3 - (D * Xt3) - (E * Yt3)

    return (A, B, C, D, E, F)

class ToolTouchProbeExtension:
    def __init__(self, config):
        self.name = config.get_name()
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object('gcode')
        self.probe = self.printer.lookup_object('probe')
        self.bed_mesh = self.printer.lookup_object('bed_mesh')

        self.serial = None
        self.serial_port = config.get("serial")
        if not self.serial_port:
            raise config.error("Invalid serial port specific for Palette 2")
        self.baud = config.getint("baud", default=115200)

        self.TRAVEL_SPEED = 50

        self.read_timer = None
        self.read_buffer = ""
        self.read_queue = Queue()
        self.write_timer = None
        self.write_queue = Queue()
        self.signal_disconnect = False

        self.samples = []
        self.is_collecting_samples = False
        self.touch_params = None
        self.ref_samples = None

        self.gcode.register_command("LRT_CONNECT",
            self.connect,
            desc="Connect to LRT via serial port")
        self.gcode.register_command("LRT_DISCONNECT",
            self.disconnect,
            desc="Disconnect from LRT")
        self.gcode.register_command("LRT_PROBE_TOOL",
            self.cmd_PROBE_TOOL,
            desc="Probe tool using touch probe")
        self.gcode.register_command("LRT_CALIBRATE",
            self.cmd_LRT_TOUCH_CALIBRATE,
            desc="Probe tool using touch probe")
        self.gcode.register_command("LRT_DEBUG",
            self.cmd_DEBUG,
            desc="Probe tool using touch probe")

        self.printer.register_event_handler("klippy:connect", self.on_connect)

        stored_profs = config.get_prefix_sections(self.name)
        self.gcode.respond_info(f"[LRT] Stored profiles: {stored_profs}")
        for prof in stored_profs:
            version = prof.get('version', None)
            touch_params = prof.get('touch_params', None)
            ref_samples = prof.get('ref_samples', None)
            ref_z_mesh = prof.get('ref_z_mesh', None)
            if touch_params and ref_samples and ref_z_mesh:
                self.touch_params = json.loads(touch_params)
                self.ref_samples = json.loads(ref_samples)
                self.ref_z_mesh = json.loads(ref_z_mesh)
                self.gcode.respond_info(f"[LRT] Loaded profile {prof.get_name()}")
                break

    def on_connect(self):
        self.connect(self.gcode)
        self.write_queue.put('debug_on()')

    def _parse_touch(self, line: str):
        if not '>>>' in line:
            return None
        # self.gcode.respond_info(line.strip())
        segments = line.split('>>>')

        if len(segments) < 3:
            return None

        try:
            data = json.loads(segments[3])
        except (json.JSONDecodeError, IndexError):
            data = {}    

        if segments[2] == 'touch_point':
            return data if 'coord' in data else None
        if segments[2] == 'sample':
            if 'coords' in data and type(data['coords']) == list:
                coords = [tuple(x) for x in data['coords']]
                xy_coords = [(x, y) for x, y, z in coords]
                z_coords = {(x, y): z for x, y, z in coords}
                z_vals = list(zip(*coords))[2]
                max_z = max(z_vals)
                med_z = np.median(z_vals)
                symbol = lambda x: '*' if x == max_z else ('+' if x >= med_z else '.')

                preview = '+-' * 8 + '+'
                for y in range(8):
                    preview += '\n|' + '|'.join([symbol(z_coords[(x, y)]) if (x, y) in xy_coords else ' ' for x in range(4)]) + '|'
                preview += '\n' + '+-' * 8 + '+\n'
                self.gcode.respond_info(line)
                self.gcode.respond_info(preview)
        if segments[2] == 'ping':
            # self.gcode.respond_info(line.strip())
            ...

                
    def _read_serial(self, eventtime):
        if self.signal_disconnect:
            self.disconnect()
            return self.reactor.NEVER

        while True:
            # copied from pallete2
            try:
                raw_bytes = self.serial.read()
            except SerialException:
                logging.error("Unable to communicate with LRT dock.")
                self.gcode.respond_info("ERROR - Unable to communicate with LRT dock.")
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

            if coords and self.is_collecting_samples:
                self.samples.append(coords)

        return eventtime + SERIAL_TIMER


    def _write_serial(self, eventtime):
        while not self.write_queue.empty():
            try:
                text_line = self.write_queue.get_nowait()
            except Empty:
                continue

            if text_line:
                l = text_line.strip()
                terminated_line = "%s\r\n" % (l)
                try:
                    self.serial.write(terminated_line.encode())
                    self.gcode.respond_info("cmd written")
                except SerialException:
                    self.gcode.respond_info("ERROR - Unable to communicate with LRT dock.")
                    logging.error("Unable to communicate with LRT")
                    # self.signal_disconnect = True
                    # return self.reactor.NEVER
                return eventtime + SERIAL_TIMER
        return eventtime + SERIAL_TIMER

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
        self.write_timer = self.reactor.register_timer(self._write_serial, self.reactor.NOW)

    def disconnect(self, gcmd=None):
        self.gcode.respond_info("[LRT] Disconnecting")
        if self.serial:
            self.serial.close()
            self.serial = None

        self.reactor.unregister_timer(self.read_timer)
        self.read_timer = None
        self.is_printing = False
        self.reactor.unregister_timer(self.write_timer)
        self.write_timer = None

    def begin_sample_collection(self):
        if not self.serial:
            self.connect(self.gcode)
        self.is_collecting_samples = True
        self.samples = []
    
    def end_sample_collection(self):
        self.is_collecting_samples = False

    def pull_samples(self):
        res = self.samples
        self.samples = []
        return res
    
    def _move(self, coords, speed):
        toolhead = self.printer.lookup_object('toolhead')
        toolhead.manual_move(coords, speed)

    def _transform_touch_coords(self, df):
        if not self.touch_params:
            tx, ty, *_ = df.median()
            return tx, ty

        dft = df.copy()
        A, B, C, D, E, F = self.touch_params
        dft.x = A * df.x + B * df.y + C
        dft.y = D * df.x + E * df.y + F
        return dft

    def probe_at(self, coords, gcmd):
        self._move(coords, self.TRAVEL_SPEED)
        self.begin_sample_collection()
        probe_session = self.probe.start_probe_session(gcmd)
        probe_session.run_probe(gcmd)

        pos = probe_session.pull_probed_results()[0]
        samples = self.pull_samples()
        data = [[s['coord'][1], s['coord'][0], pos[0], pos[1], pos[2]] for s in samples]

        self._move(coords, self.TRAVEL_SPEED)

        self.end_sample_collection()
        probe_session.end_probe_session()

        return pos, pd.DataFrame(data, columns=['x', 'y', 'cx', 'cy', 'pz'])

    def _probe_tool(self, gcmd, coords, n_samples=1):
        H_PARK = 9

        data = []
        variances = []
        for ix, coord in enumerate(coords):
            gcmd.respond_info(f"[LRT] Probing [{ix + 1}/{len(coords)}] at {coord}")
            i = 0
            frames = []
            while i < (3 * n_samples):
                pos, df = self.probe_at(coord, gcmd)
                dft = self._transform_touch_coords(df)
                std = np.std([dft.x, dft.y], axis=1).tolist()
                mean_std = np.round(np.mean(std), 3).tolist()
                if mean_std < MAX_DEV:
                    frames.append((coord, dft))
                    i += 1
                gcmd.respond_info(f"[LRT] Probed [{i}/{n_samples}] at {coord}, got {mean_std=}")

                if len(frames) >= n_samples:
                    df = pd.concat([df for _, df in frames])
                    tx, ty = np.median(df.x), np.median(df.y)
                    std = np.std([df.x, df.y], axis=1).tolist()
                    if np.mean(std) < MAX_DEV:
                        data.append((coord, (tx, ty, pos[2])))
                        break
                    else:
                        gcmd.respond_info(f"[LRT] High variance detected at {coord}, retrying... (std={std})")

        gcmd.respond_info(f"lrt_data = {data}")
        m_coords, tool_coords = zip(*data)
        return {
            'machine': m_coords,
            'tool': tool_coords,
            'variances': variances,
        }
    
    def _probe_mesh(self, gcmd, coords):
        data = []
        for ix, coord in enumerate(coords):
            gcmd.respond_info(f"[LRT] Probing mesh [{ix + 1}/{len(coords)}] at {coord}")
            pos, _ = self.probe_at(coord, gcmd)
            data.append((coord, pos))

        gcmd.respond_info(f"lrt_mesh_data = {data}")
        m_coords, tool_coords = zip(*data)
        return {
            'machine': m_coords,
            'tool': tool_coords,
        }
    
    def _diff_tool(self, ref_coords, tool_coords):
        ref = np.array(ref_coords)
        tool = np.array(tool_coords)
        diff = tool - ref
        o_x, o_y, _ = np.median(diff, axis=0)
        o_z = np.median(tool[:, 2])
        return {
            'offset_x': np.round(o_x, 3),
            'offset_y': np.round(o_y, 3),
            'offset_z': np.round(o_z, 3),
        }

    def cmd_PROBE_TOOL(self, gcmd):
        if not self.is_calibrated:
            gcmd.respond_info("[LRT] Calibrating touch panel.")
            self.cmd_LRT_TOUCH_CALIBRATE(gcmd)
        
        coords = list(zip(self.ref_samples['machine'], self.ref_samples['machine']))
        random.shuffle(coords)
        coords = coords[:5]
        machine_c, ref_tool_c = zip(*coords)
        samples = self._probe_tool(gcmd, machine_c)

        diff = self._diff_tool(ref_tool_c, samples['tool'])
        gcmd.respond_info(f"[LRT] Tool probe diff: {diff}")


    @property
    def is_calibrated(self):
        return self.touch_params is not None and self.ref_samples is not None


    def cmd_LRT_TOUCH_CALIBRATE(self, gcmd):
        N_SAMPLES = 4
        x_offset, y_offset, z_offset = self.probe.get_offsets()
        coords = np.array([
            *gen_bb_grid(nx=4, ny=4, xrange=(30, 90), yrange=(42, 65), deviation=3),
            *gen_bb_grid(nx=4, ny=2, xrange=(50, 70), yrange=(50, 60), deviation=3),
        ])
        coords_bare = (coords - np.array([x_offset, y_offset, 0])).tolist()
        res_touch_calib_pts = [
            (100, 52, PANEL_ZHOME),
            (65, 40, PANEL_ZHOME),
            (25, 70, PANEL_ZHOME),
        ]

        self.gcode.run_script_from_command("UNDOCK")
        self.ref_z_mesh = self._probe_mesh(gcmd, coords_bare)
        gcmd.respond_info(f"[LRT] {self.ref_z_mesh=}")
        self.gcode.run_script_from_command("T4")

        # Touch Panel Parameters
        data = []
        for k, coord in enumerate(res_touch_calib_pts):
            touch_samples = []
            for i in range(N_SAMPLES):
                _, df = self.probe_at(coord, gcmd)
                tx, ty, *_ = df.median()
                touch_samples.append((tx, ty))
            touch_coord = np.median(touch_samples, axis=0)
            data.append((coord, touch_coord))
            gcmd.respond_info(f"[LRT][{k + 1}/{len(res_touch_calib_pts)}] At {coord}, got {touch_coord.round(2)} ")
        
        self.touch_params = get_touch_transform(data)
        gcmd.respond_info(f"[LRT] {self.touch_params=}")

        self.ref_samples = self._probe_tool(gcmd, coords.tolist(), n_samples=5)

        configfile = self.printer.lookup_object('configfile')
        cfgname = self.name
        configfile.set(cfgname, 'version', LRT_CONF_VERSION)
        configfile.set(cfgname, 'touch_params', json.dumps(self.touch_params))
        configfile.set(cfgname, 'ref_samples', json.dumps(self.ref_samples))
        configfile.set(cfgname, 'ref_z_mesh', json.dumps(self.ref_z_mesh))

    def cmd_LRT_Z_PROBE(self, gcmd):
        self.probe.probe_offsets

    def cmd_DEBUG(self, gcmd):
        gcmd.respond_info(f"[LRT] Debug info: {self.ref_samples=} {self.touch_params=}")

    def get_status(self, eventtime):
        last_output = str(self.samples)
        return {'sample_len': len(self.samples), 'samples': last_output}


def load_config(config):
    return ToolTouchProbeExtension(config)
