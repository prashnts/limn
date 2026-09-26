# Limn - Klipper extension: the Dock, the beds, and tool calibration
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
#   [limn]
#   serial: /dev/serial/by-id/usb-MicroPython_...
#
# Install: ln -sfn ~/limn/ext/limn ~/klipper/klippy/extras/limn
#
# dock.py      the Dock's USB serial
# samples.py   sensor samples from the Dock
# machine.py   what the routines need from Klipper
# geometry.py  calibration math
# beds.py      what is on each bed, and where
# rtp.py       tool alignment on the resistive panel (BED_3)
# fsr.py       tool alignment on the FSR arrays (BED_5)
import json

from .dock import Dock
from .samples import Samples, Sample, FSR, RTP, S_SAMPLE
from .machine import Machine
from .geometry import ProbeValue, gen_draw_grid
from .beds import BEDS
from .rtp import Rtp
from .fsr import Fsr

LRT_CONF_VERSION = 'v2.0'
RTP_KEYS = ('touch_params', 'ref_samples', 'ref_z_panel', 'ref_z_paper')
ROUTINE_ERRORS = (RuntimeError, TimeoutError, ConnectionError)


class Limn:

    def __init__(self, config):
        self.name = config.get_name()
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object('gcode')

        self.dock = Dock(self.reactor, config.get('serial'), config.getint('baud', 115200),
                         say=self.gcode.respond_info)
        self.samples = Samples()
        self.dock.on('data', self._on_data)
        self.dock.on('read_bed_id', self._on_bed_id)
        for kind in ('hello', 'stats'):
            self.dock.on(kind, lambda data, kind=kind: self._on_chain_report(kind, data))
        for kind in ('log', 'error'):
            self.dock.on(kind, lambda data, kind=kind: self._on_log(kind, data))

        self.debug = False
        self.bed = None
        self.profile = self._load_profile(config)
        self._draw_grid = gen_draw_grid()
        self._chain_report_until = 0

        for name, handler, desc in (
            ('LRT_CONNECT', self.cmd_CONNECT, "Connect to the Dock"),
            ('LRT_DISCONNECT', self.cmd_DISCONNECT, "Disconnect from the Dock"),
            ('LRT_READ_BED_ID', self.cmd_READ_BED_ID, "Read which bed is on the plotter"),
            ('LRT_MESH_CALIBRATE', self.cmd_MESH_CALIBRATE, "Bed meshes of the bed on the plotter"),
            ('LRT_CALIBRATE', self.cmd_CALIBRATE, "Calibrate the bed with the reference tool (T4)"),
            ('LRT_PROBE_TOOL', self.cmd_PROBE_TOOL, "Measure the docked tool's offsets and write its tag"),
            ('LRT_FSR_Z', self.cmd_FSR_Z, "Jog the tool onto an FSR cell, report the contact z"),
            ('LRT_FSR_EDGE', self.cmd_FSR_EDGE, "Find an FSR cell edge with the tool"),
            ('LRT_CHAIN', self.cmd_CHAIN, "Show the MCUs on the chain and the link counters"),
            ('LRT_DEBUG', self.cmd_DEBUG, "LRT_DEBUG ON=0|1: show sensor data"),
        ):
            self.gcode.register_command(name, handler, desc=desc)
        self.printer.register_event_handler("klippy:connect", self._on_connect)

    # Profile, in the [limn] section (SAVE_CONFIG)
    def _load_profile(self, config):
        profile = {}
        loaders = {
            'touch_params': json.loads,
            'ref_samples': lambda v: [ProbeValue(*pt) for pt in json.loads(v)],
            'ref_z_panel': lambda v: [ProbeValue(*pt) for pt in json.loads(v)],
            'ref_z_paper': json.loads,
            'fsr_ref': json.loads,
        }
        for key, load in loaders.items():
            value = config.get(key, None)
            if value:
                profile[key] = load(value)
        return profile

    def _save_profile(self, update):
        self.profile.update(update)
        configfile = self.printer.lookup_object('configfile')
        configfile.set(self.name, 'version', LRT_CONF_VERSION)
        for key, value in update.items():
            configfile.set(self.name, key, json.dumps(value))

    def calibrated(self, sensor):
        if sensor == 'rtp':
            return all(k in self.profile for k in RTP_KEYS)
        return 'fsr_ref' in self.profile

    # Dock lines
    def _on_connect(self):
        if self.dock.connect():
            self.dock.send('read_bed_id()')

    def _on_data(self, data):
        sample = Sample(self.reactor.monotonic(), data['hop'], data['kind'], data['state'], data['values'])
        self.samples.add(sample)
        if self.debug and sample.state == S_SAMPLE:
            name = {FSR: 'FSR', RTP: 'RTP'}.get(sample.kind, sample.kind)
            self.gcode.respond_info(f"[LRT] {name} hop {sample.hop}: {sample.values}")

    def _on_bed_id(self, data):
        self.bed = data[0]

    def _on_chain_report(self, kind, data):
        if self.reactor.monotonic() < self._chain_report_until:
            self.gcode.respond_info(f"[LRT] {kind}: {data}")

    def _on_log(self, kind, data):
        text = data.get('text', '') if isinstance(data, dict) else str(data)
        if kind == 'error' or 'error' in text:
            self.gcode.respond_info(f"[LRT] {kind}: {data}")

    # Helpers
    def _read_bed_id(self, gcmd):
        try:
            data = self.dock.request('read_bed_id()', 'read_bed_id', timeout=3)
        except (TimeoutError, ConnectionError) as e:
            raise gcmd.error(f"[LRT] could not read the bed id: {e}")
        self.bed = data[0]
        gcmd.respond_info(f"[LRT] Bed: {self.bed}")
        return self.bed

    def _bed(self, gcmd, sensor=None):
        bed = self._read_bed_id(gcmd)
        if bed not in BEDS:
            raise gcmd.error(f"[LRT] no calibration known for bed {bed}")
        if sensor and BEDS[bed]['sensor'] != sensor:
            raise gcmd.error(f"[LRT] needs a bed with the {sensor.upper()}, this is {bed}")
        return BEDS[bed]

    def _routine(self, gcmd, bed):
        machine = Machine(self.printer, gcmd)
        sensor = bed['sensor']
        cls = Rtp if sensor == 'rtp' else Fsr
        return cls(machine, self.dock, self.samples, bed[sensor])

    def _draw_test_mark(self):
        if len(self._draw_grid) < 2:
            self._draw_grid = gen_draw_grid()
        start = self._draw_grid.pop(0)
        end = self._draw_grid[0]
        run = self.gcode.run_script_from_command
        run("_APPLY_OFFSETS MESH=lrt_paper")
        run("G1 F2000")
        run(f"G1 X{start[0]} Y{start[1]}")
        run("G1 Z1 ACT1")
        run(f"G1 X{end[0]} Y{end[1]}")
        run("G1 Z1 ACT2")
        run("_CLEAR_OFFSETS")

    # Commands
    def cmd_CONNECT(self, gcmd):
        self.dock.connect()

    def cmd_DISCONNECT(self, gcmd):
        self.dock.disconnect()

    def cmd_READ_BED_ID(self, gcmd):
        self._read_bed_id(gcmd)

    def cmd_MESH_CALIBRATE(self, gcmd):
        bed = self._bed(gcmd)
        for mesh in bed['meshes']:
            x0, y0 = mesh['origin']
            w, h = mesh['size']
            gcmd.respond_info(f"[LRT][Mesh] Starting mesh calibration with profile={mesh}")
            self.gcode.run_script_from_command(
                f"BED_MESH_CALIBRATE PROFILE={mesh['profile']} mesh_min={x0},{y0} "
                f"mesh_max={x0 + w},{y0 + h} probe_count={mesh['probe_count']}")

    def cmd_CALIBRATE(self, gcmd):
        bed = self._bed(gcmd)
        try:
            profile = self._routine(gcmd, bed).calibrate()
        except ROUTINE_ERRORS as e:
            raise gcmd.error(str(e))
        self._save_profile(profile)
        self._draw_test_mark()
        self.gcode.run_script_from_command("_BUZZ_DOOP")
        gcmd.respond_info("[LRT] Calibrated, SAVE_CONFIG to keep it")

    def cmd_PROBE_TOOL(self, gcmd):
        bed = self._bed(gcmd)
        if not self.calibrated(bed['sensor']):
            gcmd.respond_info("[LRT] Not calibrated yet, calibrating first.")
            self.cmd_CALIBRATE(gcmd)
        try:
            dx, dy, dz = self._routine(gcmd, bed).probe_tool(self.profile)
        except ROUTINE_ERRORS as e:
            raise gcmd.error(str(e))
        self.gcode.run_script_from_command(f"WRITE_TOOL_TAG DX={dx} DY={dy} DZ={dz}")
        self._draw_test_mark()

    def _fsr_bed_z(self, fsr, cell):
        '''BLTouch z of a cell: from the calibration, or probed now.'''
        for c in self.profile.get('fsr_ref', {}).get('bed_z', []):
            if tuple(c[:3]) == cell:
                return c[3]
        return fsr.bltouch_z(cell)

    def cmd_FSR_Z(self, gcmd):
        bed = self._bed(gcmd, 'fsr')
        cell = gcmd.get('CELL', None)
        cell = tuple(int(v) for v in cell.split(',')) if cell else tuple(bed['fsr']['z_cell'])
        fsr = self._routine(gcmd, bed)
        try:
            fsr.matrix(True)
            try:
                z = fsr.contact_z(*cell, self._fsr_bed_z(fsr, cell))
            finally:
                fsr.matrix(False)
        except ROUTINE_ERRORS as e:
            raise gcmd.error(str(e))
        gcmd.respond_info(f"[LRT] contact at z={z:.3f} on {cell}")

    def cmd_FSR_EDGE(self, gcmd):
        bed = self._bed(gcmd, 'fsr')
        axis = gcmd.get('AXIS', 'X').lower()
        edge = bed['fsr'][axis + '_edges'][gcmd.get_int('INDEX', 0)]
        fsr = self._routine(gcmd, bed)
        hop, row, col_a, _ = edge
        try:
            fsr.matrix(True)
            try:
                z = fsr.contact_z(hop, row, col_a, self._fsr_bed_z(fsr, (hop, row, col_a)))
                point, gap = fsr.find_edge(edge, z)
            finally:
                fsr.matrix(False)
        except ROUTINE_ERRORS as e:
            raise gcmd.error(str(e))
        gcmd.respond_info(f"[LRT] {axis} edge {edge}: {point.round(3).tolist()} gap={gap:.3f} (contact z={z:.3f})")

    def cmd_CHAIN(self, gcmd):
        if not self.dock.connect():
            raise gcmd.error("[LRT] Failed to connect to the Dock.")
        self._chain_report_until = self.reactor.monotonic() + 2
        self.dock.send('ping()')
        self.dock.send('stats()')

    def cmd_DEBUG(self, gcmd):
        self.debug = bool(gcmd.get_int('ON', 0 if self.debug else 1))
        gcmd.respond_info(f"[LRT] debug {'on' if self.debug else 'off'}; bed={self.bed} "
                          f"calibrated rtp={self.calibrated('rtp')} fsr={self.calibrated('fsr')}")

    def get_status(self, eventtime):
        return {
            'bed': self.bed,
            'rtp_calibrated': self.calibrated('rtp'),
            'fsr_calibrated': self.calibrated('fsr'),
            'connected': self.dock.connected,
        }


def load_config(config):
    return Limn(config)
