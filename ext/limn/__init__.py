# Limn - Klipper extension: the Dock, the beds, and tool calibration
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
#   [limn]
#   serial: /dev/serial/by-id/usb-MicroPython_...
#   tool_holder_i2c_bus: 1                  # optional, the Pi's I2C: holders and tags
#   tool_holder_address: 0x20
#   tool_holder_pins: 15:41, 14:42, 13:45, 12:43, 11:44
#   tool_holder_tag_address: 0x24
#   tool_holder_macros: 41:T0, 42:T1, 43:T2, 44:T3, 45:T4     # Fluidd's tool buttons
#   tool_holder_tag_retries: 2              # reads again after _RFID_NUDGE
#
# Install: ln -sfn ~/limn/ext/limn ~/klipper/klippy/extras/limn
#
# dock.py      the Dock's USB serial
# samples.py   sensor samples from the Dock
# machine.py   what the routines need from Klipper
# geometry.py  calibration math
# beds.py      what is on each bed, and where
# placement.py what stays true about the bed on the plotter: its meshes, the next test mark
# marks.py     the test marks on the paper
# rtp.py       tool alignment on the resistive panel (BED_3)
# fsr.py       tool alignment on the FSR array (BED_5)
# i2c.py       the Pi's I2C bus: MCP23017 and PN532
# tool_holder.py  which holders have their tool, and the tools' tags
# leds.py      what the dock and UI LEDs show
import os
import json
import logging

from .dock import Dock
from .samples import Samples, Sample, FSR, RTP, S_SAMPLE, S_MATRIX
from .machine import Machine
from .geometry import ProbeValue, gen_mark_grid, mark_strokes
from .beds import BEDS, NO_BED_MESHES, REFERENCE_TOOL
from .placement import placement_key, mesh_fingerprint, mesh_bounds, stale_meshes, next_mark
from . import marks
from .rtp import Rtp
from .fsr import Fsr
from .i2c import Bus
from .tool_holder import ToolHolder, parse_pins
from .leds import ToolLeds, tool_buttons

LRT_CONF_VERSION = 'v2.0'
RTP_KEYS = ('touch_params', 'ref_samples', 'ref_z_panel', 'ref_z_paper')
ROUTINE_ERRORS = (RuntimeError, TimeoutError, ConnectionError)
TAG_ERRORS = (OSError, RuntimeError, TimeoutError)
HOLDER_PINS = '15:41, 14:42, 13:45, 12:43, 11:44'
HOLDER_MACROS = '41:T0, 42:T1, 43:T2, 44:T3, 45:T4'
CARRIAGE_VARS = {'currently_docked_tool': 0, 'tool_offset_x': 0, 'tool_offset_y': 0,
                 'tool_offset_z': 0, 'tool_name': ''}


def parse_macros(text):
    '''"41:T0, 42:T1" -> {41: 'T0', 42: 'T1'}'''
    return {int(tool): name.strip() for tool, _, name in (item.strip().partition(':') for item in text.split(','))}


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
        for kind in ('bed_detected', 'bed_removed'):
            self.dock.on(kind, lambda data, kind=kind: self._on_bed_moved(kind, data))
        for kind in ('hello', 'stats'):
            self.dock.on(kind, lambda data, kind=kind: self._on_chain_report(kind, data))
        for kind in ('log', 'error'):
            self.dock.on(kind, lambda data, kind=kind: self._on_log(kind, data))

        self.debug = False
        self.bed = None
        self.placement = None       # placement_key() of the bed on the plotter, None: not known
        self._session = os.urandom(4).hex()
        self._bed_lines = 0         # bed_detected / bed_removed lines seen
        self.profile = self._load_profile(config)
        self._chain_report_until = 0

        self.holder = None
        self.tag = {'ok': False}
        self.last_manual = None
        self.leds = None
        self._led_states = {}       # led_effect name -> STATE we set, None: stopped
        self._led_missing = set()
        self._led_pending = False
        self._led_timer = None
        self._leds_from = None      # no LED redraws before Klipper is ready
        self.tool_macros = {}       # tool -> its T<n> macro, whose variables Fluidd shows
        self.tag_retries = 2
        self._macro_missing = set()
        bus = config.getint('tool_holder_i2c_bus', None)
        if bus is not None:
            self._attach_holder(ToolHolder(
                self.reactor, Bus(bus), parse_pins(config.get('tool_holder_pins', HOLDER_PINS)),
                int(config.get('tool_holder_address', '0x20'), 0),
                int(config.get('tool_holder_tag_address', '0x24'), 0),
                say=self.gcode.respond_info))
            self.tool_macros = parse_macros(config.get('tool_holder_macros', HOLDER_MACROS))
            self.tag_retries = config.getint('tool_holder_tag_retries', 2)

        for name, handler, desc in (
            ('LRT_CONNECT', self.cmd_CONNECT, "Connect to the Dock"),
            ('LRT_DISCONNECT', self.cmd_DISCONNECT, "Disconnect from the Dock"),
            ('LRT_READ_BED_ID', self.cmd_READ_BED_ID, "Read which bed is on the plotter"),
            ('LRT_MESH_CALIBRATE', self.cmd_MESH_CALIBRATE,
             "LRT_MESH_CALIBRATE [IF_STALE=1]: meshes of the bed on the plotter, the whole bed without one"),
            ('LRT_MARKS', self.cmd_MARKS, "LRT_MARKS [RESET=1]: where the next test mark goes, RESET: new paper"),
            ('LRT_CALIBRATE', self.cmd_CALIBRATE, "Calibrate the bed with the reference tool (T4)"),
            ('LRT_PROBE_TOOL', self.cmd_PROBE_TOOL, "Measure the docked tool's offsets and write its tag"),
            ('LRT_FSR_Z', self.cmd_FSR_Z, "Jog the tool onto an FSR cell, report the contact z"),
            ('LRT_FSR_EDGE', self.cmd_FSR_EDGE, "Find an FSR cell edge with the tool"),
            ('LRT_FSR_MEASURE', self.cmd_FSR_MEASURE,
             "LRT_FSR_MEASURE [BED_Z=] [TIP=x,y] [Z=] [PRESS=]: measure the carried tool on the FSR "
             "like LRT_PROBE_TOOL, only report it"),
            ('LRT_FSR_MATRIX', self.cmd_FSR_MATRIX,
             "LRT_FSR_MATRIX [SECONDS=1]: the FSR arrays in matrix mode, what arrives per hop. Nothing moves"),
            ('LRT_CHAIN', self.cmd_CHAIN, "Show the MCUs on the chain and the link counters"),
            ('LRT_DEBUG', self.cmd_DEBUG, "LRT_DEBUG ON=0|1: show sensor data"),
            ('TOOL_HOLDERS', self.cmd_TOOL_HOLDERS, "Show which tool holders have their tool"),
            ('TOOL_HOLDER_CHECK', self.cmd_TOOL_HOLDER_CHECK,
             "TOOL_HOLDER_CHECK T=41 EXPECT=occupied|empty [ARM=1]: stop unless the holder is so"),
            ('TOOL_TAG_READ', self.cmd_TOOL_TAG_READ, "Read the carried tool's tag [MOVE=0]"),
            ('TOOL_TAG_WRITE', self.cmd_TOOL_TAG_WRITE,
             "TOOL_TAG_WRITE [DX= DY= DZ= NAME= REFERENCE=0|1] [MOVE=0]: write these to the carried tool's tag"),
            ('TOOL_CHANGE_PHASE', self.cmd_TOOL_CHANGE_PHASE,
             "TOOL_CHANGE_PHASE PHASE=engage|leave|idle: the tool change's step, for the LEDs"),
            ('TOOL_LEDS', self.cmd_TOOL_LEDS, "Redraw the tool holder and UI LEDs, show their states"),
        ):
            self.gcode.register_command(name, handler, desc=desc)
        self.printer.register_event_handler("klippy:connect", self._on_connect)
        self.printer.register_event_handler("klippy:ready", self._on_ready)

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
        if self.holder:
            self.holder.start()
        if self.dock.connect():
            self.dock.send('read_bed_id()')

    def _on_ready(self):
        if self.holder:
            # The holders may have settled already, during startup: draw now anyway
            self._leds_from = self.reactor.monotonic()
            self._led_timer = self.reactor.register_timer(self._on_led_timer, self.reactor.NOW)
            self.reactor.register_callback(lambda e: self._probe_tag_reader())

    def _on_data(self, data):
        if not (isinstance(data, dict) and {'hop', 'kind', 'state', 'values'} <= data.keys()):
            logging.warning("[LRT] data line that is not a sample: %r", str(data)[:200])
            return
        sample = Sample(self.reactor.monotonic(), data['hop'], data['kind'], data['state'], data['values'])
        self.samples.add(sample)
        if self.debug and sample.state == S_SAMPLE:
            name = {FSR: 'FSR', RTP: 'RTP'}.get(sample.kind, sample.kind)
            self.gcode.respond_info(f"[LRT] {name} hop {sample.hop}: {sample.values}")

    def _on_bed_id(self, data):
        self.bed = data[0]
        live = f"live:{self._session}:{self.dock.connects}:{self._bed_lines}"
        self.placement = placement_key(data, live)

    def _on_bed_moved(self, kind, data):
        self._bed_lines += 1
        self.bed, self.placement = None, None
        if kind == 'bed_removed':
            self.gcode.respond_info("[LRT] The bed was removed: meshes and test marks start over")

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
        self._on_bed_id(data)
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

    # Meshes: of this placement of the bed (placement.py)
    def _bed_meshes(self, gcmd):
        '''The meshes of the bed on the plotter, the whole bed without one.'''
        if self.bed == 'NONE':
            return NO_BED_MESHES
        if self.bed not in BEDS:
            raise gcmd.error(f"[LRT][Mesh] no meshes known for bed {self.bed}: not probing a bed "
                             f"we don't know the shape of")
        return BEDS[self.bed]['meshes']

    def _mesh_profiles(self):
        bed_mesh = self.printer.lookup_object('bed_mesh', None)
        if bed_mesh is None:
            return {}
        return bed_mesh.get_status(self.reactor.monotonic()).get('profiles', {})

    def _stale_meshes(self, names):
        return stale_meshes(self._vars().get('lrt_meshes'), self.placement, self._mesh_profiles(), names)

    def _empty_holders(self):
        '''The holders without their tool now, empty when they can't be read.'''
        if not self.holder:
            return set()
        try:
            return self.holder.tools - self.holder.sample()
        except (OSError, RuntimeError):
            return set()

    def _guess_carried(self, gcmd, tag):
        '''Before the BLTouch probes: a pen on the carriage would run into the bed,
        or, over the FSR, into the holders. With no tool saved as carried and only one
        holder empty, that tool is taken as the carried one, so UNDOCK puts it away:
        undocking it with nothing on the carriage makes the same moves as docking, and
        its holder check stops there. -> the tool on the carriage, 0: none.'''
        empty = self._empty_holders()
        if len(empty) == 1 and not self._carried():
            tool, = empty
            gcmd.respond_info(f"[LRT]{tag} Holder {tool} is empty and no tool is saved as carried: "
                              f"taking {tool} as the one on the carriage, to put it away")
            self._save_vars({'currently_docked_tool': tool})
        return self._carried()

    def _run_meshes(self, gcmd, meshes, rebase=True):
        '''Takes the meshes -> the tool that was on the carriage, 0: none. With `rebase`,
        the calibration's bed z too, see _rebase(). BED_MESH_CALIBRATE
        (limn.cfg) puts it away first, see _guess_carried().'''
        key = self.placement
        if key is None:
            raise gcmd.error("[LRT][Mesh] the bed has only just been placed, try again in a moment")
        carried = self._guess_carried(gcmd, '[Mesh]')
        for mesh in meshes:
            gcmd.respond_info(f"[LRT][Mesh] Starting mesh calibration with profile={mesh}")
            if 'origin' in mesh:
                x0, y0 = mesh['origin']
                w, h = mesh['size']
                self.gcode.run_script_from_command(
                    f"BED_MESH_CALIBRATE PROFILE={mesh['profile']} mesh_min={x0},{y0} "
                    f"mesh_max={x0 + w},{y0 + h} probe_count={mesh['probe_count']}")
            else:
                self.gcode.run_script_from_command(f"BED_MESH_CALIBRATE PROFILE={mesh['profile']}")
        if rebase and self.bed in BEDS and self.calibrated(BEDS[self.bed]['sensor']):
            self._rebase(gcmd, BEDS[self.bed])
        self._read_bed_id(gcmd)
        if self.placement != key:
            raise gcmd.error("[LRT][Mesh] the bed moved while it was meshed, LRT_MESH_CALIBRATE again")
        profiles = self._mesh_profiles()
        self._save_vars({'lrt_meshes': {'placement': key, 'profiles': {
            m['profile']: mesh_fingerprint(profiles.get(m['profile'])) for m in meshes}}})
        gcmd.respond_info("[LRT][Mesh] Done, SAVE_CONFIG to keep the meshes over a restart")
        return carried

    def _rebase(self, gcmd, bed):
        '''The bed moved: the calibration's bed z (BLTouch, the carriage empty) again.
        The reference tool in its holder, tagged so: its points too, a full calibration.
        Without it the reference points stay: a tool probed now is a little off in XY
        by how far the bed moved, but still in step with the other tools in Z.'''
        routine = self._routine(gcmd, bed)
        run = self.gcode.run_script_from_command
        run("UNDOCK")                   # the BLTouch probes: nothing lower on the carriage
        run("_CLEAR_OFFSETS")
        try:
            bed_z = routine.probe_bed_z()
        except ROUTINE_ERRORS as e:
            raise gcmd.error(str(e))
        why = self._no_reference(gcmd)
        if not why:
            run(f"DOCK T={REFERENCE_TOOL}")
            if not self.tag.get('ok'):
                why = f"its tag didn't read ({self.tag.get('error')})"
            elif not self.tag.get('reference'):
                why = f"its tag ({self.tag.get('name')}) isn't the reference's (TOOL_TAG_WRITE REFERENCE=1)"
            else:
                try:
                    self._save_profile(routine.calibrate_reference(bed_z))
                except ROUTINE_ERRORS as e:
                    raise gcmd.error(str(e))
                gcmd.respond_info(f"[LRT] Calibrated again with the reference tool {REFERENCE_TOOL}, "
                                  f"SAVE_CONFIG to keep it")
            run("UNDOCK")
            if not why:
                return
        self._save_profile(routine.bed_z_update(self.profile, bed_z))
        gcmd.respond_info(f"[LRT] New bed z only, the reference tool {REFERENCE_TOOL} can't calibrate: {why}. "
                          f"Tools probed now may be a little off in XY; SAVE_CONFIG to keep it")

    def _no_reference(self, gcmd):
        '''Why the reference tool can't be docked to read its tag, None when it can.'''
        if not self.holder:
            return "no tool holders to find it and read its tag"
        try:
            if REFERENCE_TOOL not in self.holder.sample():
                return f"holder {REFERENCE_TOOL} is empty"
        except (OSError, RuntimeError) as e:
            return f"can't read the holders ({e})"
        return None

    def _ensure_meshes(self, gcmd):
        '''Meshes the bed again when its meshes aren't of the bed as it sits, then
        takes the carried tool back. The tools' tags stay as they are.'''
        meshes = self._bed_meshes(gcmd)
        stale = self._stale_meshes([m['profile'] for m in meshes])
        if not stale:
            return
        gcmd.respond_info(f"[LRT][Mesh] Meshing the bed again first: {'; '.join(stale)}")
        carried = self._run_meshes(gcmd, meshes)
        if carried:
            self.gcode.run_script_from_command(f"DOCK T={carried}")

    # Test marks (marks.py), where the last one ended, per placement of the bed
    def _draw_test_mark(self, gcmd, bed):
        if 'marks' not in bed:
            return
        points = gen_mark_grid(**bed['marks'])
        record = self._vars().get('lrt_marks')
        why = []
        try:
            self._read_bed_id(gcmd)
        except self.gcode.error as e:
            why.append(str(e))
        i = next_mark(record, self.placement)
        if i + 1 >= len(points):
            why.append(f"the paper is full ({len(points) - 1} marks), LRT_MARKS RESET=1 once there is a new sheet")
        if not self._carried():
            why.append("no tool on the carriage")
        why += self._stale_meshes(['lrt_paper'])
        paper = self._mesh_profiles().get('lrt_paper')
        if not why:
            strokes = mark_strokes(points[i], points[i + 1], bed['marks']['arm'])
            svv = self._vars()
            offsets = tuple(float(svv.get(k, 0) or 0) for k in ('tool_offset_x', 'tool_offset_y', 'tool_offset_z'))
            why += marks.problems(strokes, offsets, mesh_bounds(paper))
        if why:
            gcmd.respond_info(f"[LRT][Mark] Not drawing the test mark: {'; '.join(why)}")
            return
        marks.draw(Machine(self.printer, gcmd), strokes)
        self._save_vars({'lrt_marks': {'placement': self.placement, 'next': i + 1}})
        gcmd.respond_info(f"[LRT][Mark] Mark {i + 1} of {len(points) - 1} drawn at {points[i]} -> {points[i + 1]}")

    # Commands
    def cmd_CONNECT(self, gcmd):
        self.dock.connect()

    def cmd_DISCONNECT(self, gcmd):
        self.dock.disconnect()

    def cmd_READ_BED_ID(self, gcmd):
        self._read_bed_id(gcmd)

    def cmd_MESH_CALIBRATE(self, gcmd):
        self._read_bed_id(gcmd)
        meshes = self._bed_meshes(gcmd)
        if self.bed == 'NONE':
            gcmd.respond_info("[LRT][Mesh] No bed on the plotter: meshing the whole bed")
        if gcmd.get_int('IF_STALE', 0):
            stale = self._stale_meshes([m['profile'] for m in meshes])
            if not stale:
                gcmd.respond_info("[LRT][Mesh] The meshes are of the bed as it sits, not meshing")
                return
            gcmd.respond_info(f"[LRT][Mesh] Meshing: {'; '.join(stale)}")
        self._run_meshes(gcmd, meshes)

    def cmd_MARKS(self, gcmd):
        if gcmd.get_int('RESET', 0):
            self._save_vars({'lrt_marks': {'placement': None, 'next': 0}})
            gcmd.respond_info("[LRT][Mark] The next test mark is the first on the paper")
            return
        self._read_bed_id(gcmd)
        if self.bed not in BEDS or 'marks' not in BEDS[self.bed]:
            gcmd.respond_info(f"[LRT][Mark] No test marks on bed {self.bed}")
            return
        n = len(gen_mark_grid(**BEDS[self.bed]['marks'])) - 1
        i = next_mark(self._vars().get('lrt_marks'), self.placement)
        gcmd.respond_info(f"[LRT][Mark] Next test mark: {i + 1} of {n} on {self.bed}")

    def cmd_CALIBRATE(self, gcmd):
        bed = self._bed(gcmd)
        self._run_meshes(gcmd, bed['meshes'], rebase=False)
        try:
            profile = self._routine(gcmd, bed).calibrate()
        except ROUTINE_ERRORS as e:
            raise gcmd.error(str(e))
        self._save_profile(profile)
        self._draw_test_mark(gcmd, bed)
        self.gcode.run_script_from_command("_BUZZ_DOOP")
        gcmd.respond_info("[LRT] Calibrated, SAVE_CONFIG to keep it")

    def cmd_PROBE_TOOL(self, gcmd):
        bed = self._bed(gcmd)
        if not self.calibrated(bed['sensor']):
            gcmd.respond_info("[LRT] Not calibrated yet, calibrating first.")
            self.cmd_CALIBRATE(gcmd)
        else:
            self._ensure_meshes(gcmd)
        try:
            dx, dy, dz = self._routine(gcmd, bed).probe_tool(self.profile)
        except ROUTINE_ERRORS as e:
            raise gcmd.error(str(e))
        self.gcode.run_script_from_command(f"WRITE_TOOL_TAG DX={dx} DY={dy} DZ={dz}")
        self._draw_test_mark(gcmd, bed)

    def _fsr_bed_z(self, gcmd, fsr, cell):
        '''BLTouch z of a cell: from the calibration, or probed now, the carried
        tool put away for it and taken back. The probe sits 34mm left of the pen:
        over the array, the carriage is in the lane of holder 41.'''
        for c in self.profile.get('fsr_ref', {}).get('bed_z', []):
            if tuple(c[:3]) == cell:
                return c[3]
        carried = self._guess_carried(gcmd, '[FSR]')
        run = self.gcode.run_script_from_command
        run("UNDOCK")
        z = fsr.bltouch_z(cell)
        if carried:
            run(f"DOCK T={carried}")
        return z

    def _need_tool(self, gcmd):
        '''The FSR only feels a tool: nothing on the carriage, nothing to jog down.'''
        if not self._guess_carried(gcmd, '[FSR]'):
            raise gcmd.error("[LRT] no tool on the carriage: DOCK T=<holder> first")

    def cmd_FSR_Z(self, gcmd):
        bed = self._bed(gcmd, 'fsr')
        self._need_tool(gcmd)
        cell = gcmd.get('CELL', None)
        cell = tuple(int(v) for v in cell.split(',')) if cell else tuple(bed['fsr']['z_cell'])
        fsr = self._routine(gcmd, bed)
        try:
            fsr.matrix(True)
            try:
                z = fsr.contact_z(*cell, self._fsr_bed_z(gcmd, fsr, cell))
            finally:
                fsr.matrix(False)
        except ROUTINE_ERRORS as e:
            raise gcmd.error(str(e))
        gcmd.respond_info(f"[LRT] contact at z={z:.3f} on {cell}")

    def cmd_FSR_EDGE(self, gcmd):
        bed = self._bed(gcmd, 'fsr')
        self._need_tool(gcmd)
        axis = gcmd.get('AXIS', 'X').lower()
        edge = bed['fsr'][axis + '_edges'][gcmd.get_int('INDEX', 0)]
        fsr = self._routine(gcmd, bed)
        hop, (row, col_a), _ = edge
        try:
            fsr.matrix(True)
            try:
                z = fsr.contact_z(hop, row, col_a, self._fsr_bed_z(gcmd, fsr, (hop, row, col_a)))
                point, gap = fsr.find_edge(edge, z)
            finally:
                fsr.matrix(False)
        except ROUTINE_ERRORS as e:
            raise gcmd.error(str(e))
        gcmd.respond_info(f"[LRT] {axis} edge {edge}: {point.round(3).tolist()} gap={gap:.3f} (contact z={z:.3f})")

    def cmd_FSR_MEASURE(self, gcmd):
        '''What LRT_CALIBRATE and LRT_PROBE_TOOL measure with the carried tool (where
        its tip is, contact z, the edges), only reported: no tag, no profile.'''
        bed = self._bed(gcmd, 'fsr')
        self._need_tool(gcmd)
        self._ensure_meshes(gcmd)              # the taps follow the sheet with lrt_fsr
        fsr = self._routine(gcmd, bed)
        # What is known of the tool already: a precious pen comes down where expected
        # (TIP=x,y as locate reports it), never far past its contact (Z=), gently (PRESS=).
        tip = gcmd.get('TIP', None)
        prior = {'tip': [float(v) for v in tip.split(',')] if tip else None,
                 'z': gcmd.get_float('Z', None)}
        press = gcmd.get_float('PRESS', None, minval=0.05, maxval=0.5)
        if press is not None:
            fsr.cfg = {**fsr.cfg, 'press': press}
        bed_z_given = gcmd.get_float('BED_Z', None)
        try:
            bed_z = {cell: bed_z_given if bed_z_given is not None else self._fsr_bed_z(gcmd, fsr, cell)
                     for cell in fsr.z_cells()}
            self.gcode.run_script_from_command("_CLEAR_OFFSETS")
            m = fsr.measure(bed_z, prior)
        except ROUTINE_ERRORS as e:
            raise gcmd.error(str(e))
        z_bed = bed_z[tuple(bed['fsr']['z_cell'])]
        gcmd.respond_info(f"[LRT] measured x={m['x']:.3f} y={m['y']:.3f} z={m['z']:.3f} (dz={m['z'] - z_bed:.3f} "
                          f"over bed_z={z_bed:.3f}) tip={[round(v, 2) for v in m['tip']]} "
                          f"gaps={[round(g, 3) for g in m['gaps']]}")

    def cmd_FSR_MATRIX(self, gcmd):
        '''The bed's arrays in matrix mode for SECONDS: what arrives, per hop. Nothing moves.'''
        bed = self._bed(gcmd, 'fsr')
        fsr = self._routine(gcmd, bed)
        seconds = gcmd.get_float('SECONDS', 1.0, minval=0.1, maxval=10.0)
        start = self.reactor.monotonic()
        try:
            fsr.matrix(True)
            self.reactor.pause(start + seconds)
        except ROUTINE_ERRORS as e:
            raise gcmd.error(str(e))
        finally:
            try:
                fsr.matrix(False)
            except ROUTINE_ERRORS:
                pass
        heard = {}
        for s in self.samples.since(start):
            heard.setdefault((s.hop, s.kind, s.state), []).append(s)
        for hop in fsr.arrays:
            if not any(key[0] == hop and key[1:] == (FSR, S_MATRIX) for key in heard):
                gcmd.respond_info(f"[LRT] hop {hop}: no matrix frames (FSR state {S_MATRIX}) in {seconds:.1f}s")
        if not heard:
            gcmd.respond_info("[LRT] nothing at all from the chain: LRT_CHAIN")
        for (hop, kind, state), frames in sorted(heard.items()):
            cells = max(len(f.values) for f in frames)
            strongest = max((v[2] for f in frames for v in f.values if len(v) == 3), default=0)
            gcmd.respond_info(f"[LRT] hop {hop} kind {kind} state {state}: {len(frames)} frames "
                              f"({len(frames) / seconds:.0f}/s), up to {cells} cells, strongest {strongest}")

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

    # Tool holder
    def _attach_holder(self, holder):
        self.holder = holder
        self.leds = ToolLeds(holder.tools)
        holder.on('ready', self._on_holders_ready)
        holder.on('change', self._on_holders_change)
        holder.on('status', self._on_holders_status)

    def _probe_tag_reader(self):
        try:
            self.holder.begin_tag_reader()
        except TAG_ERRORS as e:
            self.gcode.respond_info(f"[Tag] no PN532: {e}")

    def _vars(self):
        return self.printer.lookup_object('save_variables').allVariables

    def _save_vars(self, values):
        save_variables = self.printer.lookup_object('save_variables')
        for key, value in values.items():
            gcmd = self.gcode.create_gcode_command(
                'SAVE_VARIABLE', 'SAVE_VARIABLE', {'VARIABLE': key, 'VALUE': repr(value)})
            save_variables.cmd_SAVE_VARIABLE(gcmd)

    def _reconcile(self, occupied, startup=False):
        '''The saved carried tool against the holders.'''
        carried = int(self._vars().get('currently_docked_tool', 0) or 0)
        if carried and carried in occupied:
            self._save_vars(CARRIAGE_VARS)
            self.gcode.respond_info(f"[Tool holder] {carried} is in its holder, not on the carriage: "
                                    f"cleared the carried tool")
        elif startup and not carried and self.holder.tools - occupied:
            self.leds.manual((), self.reactor.monotonic())
            self.gcode.respond_info(f"[Tool holder] holders {sorted(self.holder.tools - occupied)} are "
                                    f"empty and no tool is saved as carried")

    def _on_holders_status(self, ok):
        if not ok:
            self.leds.lost(self.reactor.monotonic())
        self._request_leds()

    def _on_holders_ready(self, occupied):
        logging.info("[Tool holder] occupied: %s", sorted(occupied))
        self._reconcile(occupied, startup=True)
        self._request_leds()

    def _on_holders_change(self, occupied, added, removed, manual):
        for tool in sorted(added | removed):
            how = 'manual' if tool in manual else 'expected'
            what = 'returned' if tool in added else 'removed'
            msg = f"[Tool holder] {tool}: tool {what} ({how})"
            logging.info(msg)
            self.gcode.respond_info(msg)
        if manual:
            self.last_manual = {'at': self.holder.changed_at, 'added': sorted(added & manual),
                                'removed': sorted(removed & manual)}
            self.leds.manual(manual, self.holder.changed_at)
            if not self.holder.busy():
                self._reconcile(occupied)
        self._request_leds()
        self.printer.send_event("limn:tool_holder_changed", occupied, added, removed, manual)

    def _require_holder(self, gcmd):
        if not self.holder:
            raise gcmd.error("[Tool holder] not configured, see tool_holder_i2c_bus in [limn]")

    def _wait_moves(self):
        self.printer.lookup_object('toolhead').wait_moves()

    def cmd_TOOL_HOLDERS(self, gcmd):
        self._require_holder(gcmd)
        try:
            occupied = self.holder.sample()
        except (OSError, RuntimeError) as e:
            raise gcmd.error(f"[Tool holder] can't read the holders: {e}")
        gcmd.respond_info(f"[Tool holder] occupied: {sorted(occupied)}, "
                          f"empty: {sorted(self.holder.tools - occupied)}")

    def cmd_TOOL_HOLDER_CHECK(self, gcmd):
        tool = gcmd.get_int('T')
        expect = gcmd.get('EXPECT').lower()
        if expect not in ('occupied', 'empty'):
            raise gcmd.error("[Tool holder] EXPECT=occupied|empty")
        if not self.holder:
            gcmd.respond_info("[Tool holder] not configured, not checking")
            return
        if tool not in self.holder.tools:
            raise gcmd.error(f"[Tool holder] no holder for tool {tool}")
        self._wait_moves()
        arm = gcmd.get_int('ARM', 0)
        try:
            occupied = tool in self.holder.sample()
        except (OSError, RuntimeError) as e:
            self._check_failed(tool)
            raise gcmd.error(f"[Tool holder] can't read the holders: {e}")
        if occupied != (expect == 'occupied'):
            self._check_failed(tool)
            raise gcmd.error(f"[Tool holder] holder {tool} is {'occupied' if occupied else 'empty'}, "
                             f"expected {expect}")
        if arm:
            self.holder.expect(tool, not occupied)
            self.leds.start(tool)
        elif tool == self.leds.active and self.leds.phase in ('approach', 'engage', 'leave'):
            self.leds.done(self.reactor.monotonic())
        self._request_leds()

    def _check_failed(self, tool):
        self.holder.forget(tool)
        self.leds.failed(tool, self.reactor.monotonic())
        self._request_leds()

    def cmd_TOOL_CHANGE_PHASE(self, gcmd):
        phase = gcmd.get('PHASE').lower()
        if phase not in ('engage', 'leave', 'idle'):
            raise gcmd.error("[Tool holder] PHASE=engage|leave|idle")
        if self.leds:
            self.leds.set_phase(phase)
            self._request_leds()

    def cmd_TOOL_LEDS(self, gcmd):
        if not self.leds:
            raise gcmd.error("[Tool holder] not configured, no LEDs to draw")
        self._led_states.clear()
        states = self._render_leds()
        gcmd.respond_info("[LEDs] " + ", ".join(f"{k}={v}" for k, v in states.items() if v))

    # LEDs: ToolLeds says what, the led_effect sections of leds.cfg how
    def _carried(self):
        try:
            return int(self._vars().get('currently_docked_tool', 0) or 0)
        except (KeyError, ValueError, TypeError):
            return 0

    def _request_leds(self):
        '''Redraw soon: after the command running now, so saved variables are in.'''
        if self.leds and self._leds_from is not None and not self._led_pending \
                and self.reactor.monotonic() >= self._leds_from:
            self._led_pending = True
            self.reactor.register_callback(lambda e: self._render_leds())

    def _on_led_timer(self, eventtime):
        self._request_leds()
        return self.reactor.NEVER

    def _render_leds(self):
        self._led_pending = False
        now = self.reactor.monotonic()
        states = self.leds.desired(now, self.holder.occupied, self.holder.ok, self._carried())
        for name, state in states.items():
            self._set_led(name, state)
        for tool, button in tool_buttons(states, self._carried()).items():
            if tool in self.tool_macros:
                self._set_macro_vars(self.tool_macros[tool], button)
        next_change = self.leds.next_change(now)
        if next_change is not None and self._led_timer is not None:
            self.reactor.update_timer(self._led_timer, next_change + 0.05)
        return states

    def _set_macro_vars(self, name, values):
        '''Sets the macro's variables that changed; they must be declared (variable_color: '').'''
        macro = self.printer.lookup_object('gcode_macro ' + name, None)
        if macro is None:
            return
        for key, value in values.items():
            if macro.variables.get(key) == value:
                continue
            try:
                macro.cmd_SET_GCODE_VARIABLE(self.gcode.create_gcode_command(
                    'SET_GCODE_VARIABLE', 'SET_GCODE_VARIABLE', {'VARIABLE': key, 'VALUE': repr(value)}))
            except self.gcode.error:
                if (name, key) not in self._macro_missing:
                    self._macro_missing.add((name, key))
                    logging.info("[Tool holder] [gcode_macro %s] has no variable_%s, not showing it", name, key)

    def _set_led(self, name, state):
        effect = self.printer.lookup_object('led_effect ' + name, None)
        if effect is None:
            if name not in self._led_missing:
                self._led_missing.add(name)
                logging.info("[LEDs] no [led_effect %s], not showing it", name)
            return
        if name in self._led_states and self._led_states[name] == state \
                and bool(getattr(effect, 'enabled', False)) == (state is not None):
            return
        params = {'STOP': '1', 'FADETIME': '0.3'} if state is None else {'STATE': state}
        effect.cmd_SET_LED_EFFECT(self.gcode.create_gcode_command('SET_LED_EFFECT', 'SET_LED_EFFECT', params))
        self._led_states[name] = state

    def _at_reader(self, gcmd, attempt):
        '''Goes to the reader and runs `attempt` (-> Tag, None: no tag), nudging the
        reader between tries: it doesn't always extend all the way. -> (Tag, tries, error)'''
        move = gcmd.get_int('MOVE', 1)
        tries = 1 + (self.tag_retries if move else 0)
        if move:
            self.gcode.run_script_from_command("_RFID_HOME")
        self._wait_moves()
        self._set_tag(self.tag, 'reading')
        error = None
        for n in range(1, tries + 1):
            if n > 1:
                gcmd.respond_info(f"[Tag] {error}, nudging the reader ({n}/{tries})")
                self._nudge_reader(n - 1)
            try:
                tag = attempt()
            except TAG_ERRORS as e:
                error = str(e)
                continue
            if tag is not None:
                if n > 1:
                    logging.info("[Tag] read on try %d/%d", n, tries)
                return tag, n, None
            error = 'no tag'
        return None, tries, error

    def _set_tag(self, tag, state):
        self.tag = tag
        self.leds.tag(state, self._carried(), self.reactor.monotonic())
        self._request_leds()

    def _nudge_reader(self, attempt):
        '''_RFID_NUDGE: with T= it goes into the carried tool's holder and out again,
        which pushes the reader out. Only when that holder reads empty.'''
        tool = self._carried()
        try:
            reenter = tool in self.holder.tools and tool not in self.holder.sample()
        except (OSError, RuntimeError):
            reenter = False
        if not reenter:
            tool = 0
        if tool:
            self.holder.quiet(tool)         # the tool in its holder for a moment is ours
        try:
            self.gcode.run_script_from_command(f"_RFID_NUDGE ATTEMPT={attempt} T={tool}")
            self._wait_moves()
        finally:
            if tool:
                try:
                    self.holder.resync()
                except (OSError, RuntimeError):
                    pass
                self.holder.forget(tool)
                self._request_leds()

    def _apply_tag(self, tag, tries):
        self._save_vars({'tool_offset_x': tag.dx, 'tool_offset_y': tag.dy, 'tool_offset_z': tag.dz,
                         'tool_name': tag.name, 'tool_tag_uid': tag.uid})
        self._set_tag({'ok': True, 'uid': tag.uid, 'dx': tag.dx, 'dy': tag.dy, 'dz': tag.dz,
                       'name': tag.name, 'reference': tag.reference, 'tries': tries,
                       'read_at': self.reactor.monotonic()}, 'ok')

    def cmd_TOOL_TAG_READ(self, gcmd):
        self._require_holder(gcmd)
        tag, tries, error = self._at_reader(gcmd, self.holder.read_tag)
        if tag is None:
            self._set_tag({'ok': False, 'error': error, 'tries': tries}, 'error')
            gcmd.respond_info(f"[Tag] read failed after {tries} tries: {error}")
            return
        self._apply_tag(tag, tries)
        gcmd.respond_info(f"[Tag] {tag.name}{' (reference)' if tag.reference else ''}: "
                          f"dx={tag.dx} dy={tag.dy} dz={tag.dz}")

    def cmd_TOOL_TAG_WRITE(self, gcmd):
        self._require_holder(gcmd)
        fields = {'dx': gcmd.get_float('DX', None), 'dy': gcmd.get_float('DY', None),
                  'dz': gcmd.get_float('DZ', None), 'name': gcmd.get('NAME', None),
                  'reference': gcmd.get_int('REFERENCE', None)}
        if all(v is None for v in fields.values()):
            raise gcmd.error("[Tag] nothing to write, give DX, DY, DZ, NAME or REFERENCE")
        tag, tries, error = self._at_reader(gcmd, lambda: self.holder.write_tag(**fields))
        if tag is None:
            self._set_tag({'ok': False, 'error': error, 'tries': tries}, 'error')
            raise gcmd.error(f"[Tag] write failed after {tries} tries: {error}")
        self._apply_tag(tag, tries)
        gcmd.respond_info(f"[Tag] wrote {tag.name}{' (reference)' if tag.reference else ''}: "
                          f"dx={tag.dx} dy={tag.dy} dz={tag.dz}")

    def get_status(self, eventtime):
        holder = self.holder
        return {
            'bed': self.bed,
            'placement': self.placement,
            'rtp_calibrated': self.calibrated('rtp'),
            'fsr_calibrated': self.calibrated('fsr'),
            'connected': self.dock.connected,
            'tool_holder': {
                'enabled': holder is not None,
                'ok': bool(holder and holder.ok),
                'occupied': sorted(holder.occupied) if holder and holder.occupied is not None else None,
                'changed_at': holder.changed_at if holder else 0,
                'last_manual': self.last_manual,
                'phase': self.leds.phase if self.leds else None,
                'changing': self.leds.active if self.leds else None,
            },
            'tag': self.tag,
        }


def load_config(config):
    return Limn(config)
