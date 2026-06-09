#

import re
import random
import serial
import logging
import numpy as np
import pandas as pd
import json

from collections import namedtuple
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
ProbeValue = namedtuple('PV', ['mx', 'my', 'mz', 'tx', 'ty', 'tz'])

FSR_ID_LM = 0x4
RTP_ID_LM = 0x5

def bounded_pos(pos):
    xmin, xmax = PANEL_XRANGE
    ymin, ymax = PANEL_YRANGE
    x, y, z = pos
    x = max(xmin, min(xmax, x))
    y = max(ymin, min(ymax, y))
    return x, y, PANEL_ZHOME

def gen_bb_grid(*, nx=5, ny=5, xrange=PANEL_XRANGE, yrange=PANEL_YRANGE, deviation=0, z_park=PANEL_ZHOME):
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
            coords.append((x, y, z_park))
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
        self.ref_z_panel = None
        self.ref_z_paper = None
        self.debug = False
        
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
        self.gcode.register_command("LRT_PANEL_CALIBRATE",
            self.cmd_LRT_PANEL_CALIBRATE,
            desc="Probe tool using touch probe")

        self.printer.register_event_handler("klippy:connect", self.on_connect)

        stored_profs = config.get_prefix_sections(self.name)
        self.gcode.respond_info(f"[LRT] Stored profiles: {stored_profs}")
        for prof in stored_profs:
            version = prof.get('version', None)
            touch_params = prof.get('touch_params', None)
            ref_samples = prof.get('ref_samples', None)
            ref_z_panel = prof.get('ref_z_panel', None)
            ref_z_paper = prof.get('ref_z_paper', None)
            load_values = lambda x: [ProbeValue(*pt) for pt in json.loads(x)]
            if all([ref_samples, touch_params, ref_z_panel, ref_z_paper]):
                self.touch_params = json.loads(touch_params)
                self.ref_samples = load_values(ref_samples)
                self.ref_z_panel = load_values(ref_z_panel)
                self.ref_z_paper = load_values(ref_z_paper)
                self.gcode.respond_info(f"[LRT] Loaded profile {prof.get_name()}")
                break

    def on_connect(self):
        self.connect(self.gcode)
        self.write_queue.put('power_off()')
        self.write_queue.put('power_on()')

    def _parse_touch(self, line: str):
        if not '>>' in line:
            return None
        segments = line.split('>>')

        if len(segments) < 3:
            return None

        if segments[0] == '!LRT' and segments[1] == 'SMP':
            try:
                pkt = json.loads(segments[2])
            except json.JSONDecodeError:
                return None
            if pkt["4"]:
                coords = [tuple(x) for x in pkt["4"]]
                xy_coords = [(x, y) for x, y, z in coords]
                z_coords = {(x, y): z for x, y, z in coords}
                z_vals = list(zip(*coords))[2]
                max_z = max(z_vals)
                med_z = np.median(z_vals)
                symbol = lambda x: '*' if x == max_z else ('+' if x >= med_z else '.')

                preview = '+-' * 4 + '+'
                for y in range(8):
                    preview += '\n|' + '|'.join([symbol(z_coords[(x, y)]) if (x, y) in xy_coords else ' ' for x in range(4)]) + '|'
                preview += '\n' + '+-' * 4 + '+\n'
                if self.debug:
                    self.gcode.respond_info(line)
                    self.gcode.respond_info(preview)
            if pkt["5"]:
                if self.debug:
                    self.gcode.respond_info(f"RTP Touch: {pkt['5']}")
                return pkt['5']
                
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
                new_buffer = str(raw_bytes.decode(encoding='UTF-8', errors='ignore'))
                text_buffer = self.read_buffer + new_buffer
                while True:
                    i = text_buffer.find("\r\n")
                    if i >= 0:
                        line = text_buffer[0:i + 1]
                        self.read_queue.put(line.strip())
                        text_buffer = text_buffer[i + 1:]
                    else:
                        break
                self.read_buffer = text_buffer
            else:
                break

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
        logging.info("[LRT] Connecting to (%s) at (%s)" % (self.serial_port, self.baud))
        self.gcode.respond_info("[LRT] Connecting")
        try:
            self.serial = serial.Serial(
                self.serial_port, self.baud, timeout=0, write_timeout=0)
        except SerialException:
            gcmd.respond_info("[LRT] Unable to connect")
            return
    
        self.gcode.respond_info("[LRT] Connected")
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
        data = [[s[1], s[0], pos[0], pos[1], pos[2]] for s in samples]

        self._move(coords, self.TRAVEL_SPEED)

        self.end_sample_collection()
        probe_session.end_probe_session()

        return pos, pd.DataFrame(data, columns=['x', 'y', 'cx', 'cy', 'pz'])

    def _probe_tool(self, gcmd, coords, n_samples=1):
        H_PARK = 9

        data = []
        for ix, coord in enumerate(coords):
            gcmd.respond_info(f"[LRT] TOOL_PROBE [{ix + 1}/{len(coords)}]")
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
                gcmd.respond_info(f"[LRT] probed [{i}/{n_samples}] {mean_std=}")

                if len(frames) >= n_samples:
                    df = pd.concat([df for _, df in frames])
                    tx, ty = np.median(df.x), np.median(df.y)
                    std = np.std([df.x, df.y], axis=1).tolist()
                    if np.mean(std) < MAX_DEV:
                        data.append(ProbeValue(*coord, *(tx, ty, pos.test_z)))
                        self.gcode.run_script_from_command("_BUZZ_TOUCH")
                        break
                    else:
                        gcmd.respond_info(f"[LRT] VARIANCE HIGH, retrying... (std={std})")
                        self.gcode.run_script_from_command("_BUZZ_ERR")

        gcmd.respond_info(f"lrt_data = {data}")
        return data
    
    def _probe_mesh(self, gcmd, coords):
        '''Probe (BL-Touch) right side of the calibration bed.'''
        x_offset, y_offset, z_offset = self.probe.get_offsets()
        probe_offset = np.array([x_offset, y_offset, -z_offset])
        
        data = []
        for ix, coord in enumerate(coords):
            gcmd.respond_info(f"[LRT] MESH_PROBE [{ix + 1}/{len(coords)}]")
            _coord = (np.array(coord) - probe_offset).tolist()
            gcmd.respond_info(f"Probing at {_coord} with offset {probe_offset}")
            pos, _ = self.probe_at(_coord, gcmd)
            data.append(ProbeValue(*coord, pos.test_x, pos.test_y, pos.test_z))
        return data
    
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

        # random.shuffle(coords)
        # coords = coords[:8]
        coords = [(c.mx, c.my, PANEL_ZHOME) for c in self.ref_samples]
        samples = self._probe_tool(gcmd, coords, n_samples=3)

        def diff_samples(ref, sample):
            return 
        xydiff = np.round(np.median(np.array(samples) - np.array(self.ref_samples), axis=0), 3) * -1
        zdiff = np.round(np.median(np.array(samples) - np.array(self.ref_z_panel), axis=0), 3)

        gcmd.respond_info(f"[LRT] {xydiff=} {zdiff=}")
        self.gcode.run_script_from_command(f"WRITE_TOOL_TAG DX={xydiff[3]} DY={xydiff[4]} DZ={zdiff[5]}")
        do = self.ref_z_paper[2]
        de = self.ref_z_paper[3]
        self.gcode.run_script_from_command(f"G1 F2600")
        self.gcode.run_script_from_command(f"G90")
        self.gcode.run_script_from_command(f"G1 Z9")
        self.gcode.run_script_from_command(f"G1 X{do.mx} Y{do.my} ALIGN0")
        self.gcode.run_script_from_command(f"G1 Z7")
        self.gcode.run_script_from_command(f"G1 X{do.mx} Y{do.my} ALIGN1")
        self.gcode.run_script_from_command(f"G1 Z{do.tz} ALIGN1")
        self.gcode.run_script_from_command(f"G1 X{de.mx} Y{de.my} Z{de.tz} ALIGN1")
        self.gcode.run_script_from_command(f"G1 Z9 ALIGN0")

    @property
    def is_calibrated(self):
        return self.touch_params is not None and self.ref_samples is not None

    def cmd_LRT_PANEL_CALIBRATE(self, gcmd):
        self.write_queue.put('calibrate()')

    def cmd_LRT_TOUCH_CALIBRATE(self, gcmd):
        N_SAMPLES = 3
        N_SAMPLES_CALIB = 4
        coords = [
            *gen_bb_grid(nx=4, ny=4, xrange=(30, 90), yrange=(42, 65), deviation=0),
        ]
        coords_paper = [
            *gen_bb_grid(nx=4, ny=4, xrange=(30, 90), yrange=(110, 160), deviation=0, z_park=6),
        ]
        res_touch_calib_pts = [
            (100, 52, PANEL_ZHOME),
            (65, 40, PANEL_ZHOME),
            (25, 70, PANEL_ZHOME),
        ]

        self.gcode.run_script_from_command("UNDOCK")
        self.gcode.run_script_from_command("G28")
        self.ref_z_panel = self._probe_mesh(gcmd, coords)
        self.gcode.run_script_from_command("_BUZZ_DOOP")
        self.ref_z_paper = self._probe_mesh(gcmd, coords_paper)
        self.gcode.run_script_from_command("_BUZZ_DOOP")

        gcmd.respond_info(f"[LRT] Z mesh collected")
        self.gcode.run_script_from_command("T4")
        self.gcode.run_script_from_command("WRITE_TOOL_TAG DX=0 DY=0 DZ=0")

        self.gcode.run_script_from_command("SET_LED_EFFECT EFFECT=ui_alert_blink REPLACE=1")
        # Touch Panel Parameters
        data = []
        for k, coord in enumerate(res_touch_calib_pts):
            touch_samples = []
            for i in range(N_SAMPLES_CALIB):
                _, df = self.probe_at(coord, gcmd)
                tx, ty, *_ = df.median()
                touch_samples.append((tx, ty))
            self.gcode.run_script_from_command("_BUZZ_TOUCH")
            touch_coord = np.median(touch_samples, axis=0)
            data.append((coord, touch_coord))
            gcmd.respond_info(f"[LRT][{k + 1}/{len(res_touch_calib_pts)}] got {touch_coord.round(2)} ")
        
        self.touch_params = get_touch_transform(data)
        gcmd.respond_info(f"[LRT] {self.touch_params=}")
        self.gcode.run_script_from_command("SET_LED_EFFECT EFFECT=ui_alert_blink STOP=1")

        self.ref_samples = self._probe_tool(gcmd, coords, n_samples=N_SAMPLES)

        z_diff = np.array(self.ref_samples) - np.array(self.ref_z_panel)
        tool_z = np.median(z_diff[:, 5])
        self.gcode.run_script_from_command(f"WRITE_TOOL_TAG DZ={tool_z:.3f}")

        do = self.ref_z_paper[0]
        de = self.ref_z_paper[1]

        self.gcode.run_script_from_command(f"G1 F2000")
        self.gcode.run_script_from_command(f"G1 X{do.mx} Y{do.my} ALIGN=1")
        self.gcode.run_script_from_command(f"G1 Z{do.tz} ALIGN=1")
        self.gcode.run_script_from_command(f"G1 X{de.mx} Y{de.my} Z{de.tz} ALIGN=1")
        self.gcode.run_script_from_command(f"G1 Z9 ALIGN=1")

        configfile = self.printer.lookup_object('configfile')
        cfgname = self.name
        configfile.set(cfgname, 'version', LRT_CONF_VERSION)
        configfile.set(cfgname, 'touch_params', json.dumps(self.touch_params))
        configfile.set(cfgname, 'ref_samples', json.dumps(self.ref_samples))
        configfile.set(cfgname, 'ref_z_panel', json.dumps(self.ref_z_panel))
        configfile.set(cfgname, 'ref_z_paper', json.dumps(self.ref_z_paper))
        self.gcode.run_script_from_command("_BUZZ_DOOP")

    def cmd_LRT_Z_PROBE(self, gcmd):
        self.probe.probe_offsets

    def cmd_DEBUG(self, gcmd):
        self.debug = True
        gcmd.respond_info(f"[LRT] Debug info: {self.ref_samples=} {self.ref_z_panel=} {self.ref_z_paper=} {self.touch_params=}")

    def get_status(self, eventtime):
        last_output = str(self.samples)
        return {'sample_len': len(self.samples), 'samples': last_output}


def load_config(config):
    return ToolTouchProbeExtension(config)
