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
#   tool_dry_idle: 600                      # s a known pen may be out of its cap in the machine,
#   tool_dry_printing: 1200                 #   idle / printing; then its LEDs go red and it beeps
#   tool_dry_beep: 3                        # s between beeps (0: none), on [pwm_cycle_time beeper]
#   tool_dry_pens: ~/limn/plot/profiles/pens.toml   # a pen's own `dry` minutes, by the pen on its tag
#   tool_holder_scan_idle: 2                # s between listens for a tag held to the reader
#   tool_holder_scan_printing: 5            #   by hand, idle / printing; 0: only after a hand
#                                           #   was on the holders (then every 0.5 s for a minute)
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
# drying.py    how long each known pen has been out of its cap
import os
import json
import logging
import time

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
from .leds import ToolLeds, tool_buttons, CHANGE_PHASES
from .drying import Drying

LRT_CONF_VERSION = 'v2.0'
RTP_KEYS = ('touch_params', 'ref_samples', 'ref_z_panel', 'ref_z_paper')
ROUTINE_ERRORS = (RuntimeError, TimeoutError, ConnectionError)
TAG_ERRORS = (OSError, RuntimeError, TimeoutError)
HOLDER_PINS = '15:41, 14:42, 13:45, 12:43, 11:44'
HOLDER_MACROS = '41:T0, 42:T1, 43:T2, 44:T3, 45:T4'
KEY_ENDSTOP = 'manual_stepper axis_k'       # triggered: the key fully open
# A tool is scanned by hand (held to the reader), then put into a holder within
# SCAN_WINDOW: that holder has that tool, until a hand empties it.
SCAN_WINDOW = 8.0       # s from the scan until the tool is in its holder
SCAN_LATE = 60.0        # s after which a scan is forgotten without a word
SCAN_SAME = 3.0         # s: the same tag again within this is the same scan
SCAN_FAST = 0.5         # s between listens after a hand was on the holders,
SCAN_AWAKE = 60.0       #   for this long
INKY = ('pen', 'pencil', 'brush')      # tool kinds (plot/tools.py) that dry out uncapped
PENS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'plot', 'profiles', 'pens.toml')
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
        self._fsr_last = None       # the tool the FSR sheet last had, None: wiped or unknown

        self.holder = None
        self.tag = {'ok': False}
        self._holder_tags = None    # holder -> its tool's last tag, see _tags()
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
        self.scan = None            # the tag last held to the reader by hand: {'tag', 'seen'}
        self._awake_until = 0.0     # listening fast: a hand was on the holders
        self._at_reader_now = False # the carriage brings its own tool to the reader
        self.scan_idle, self.scan_printing = 2.0, 5.0
        self.clock = time.time      # wall clock, for how long pens have been out of their caps
        self.drying = None          # Drying: the known pens out of their caps, once the holders are there
        self._dry_stages = {}       # tool -> stage, what the LEDs show
        self._dry_silenced = set()  # overdue pens TOOL_DRY SILENCE=1 was given for
        self._dry_beep_at = 0.0
        self.dry_idle, self.dry_printing, self.dry_beep = 600.0, 1200.0, 3.0
        self.dry_pens = PENS_FILE
        self._pens = (None, {}, set())  # (mtime, {pen key: dry minutes}, keys with no ink) of the pen library
        bus = config.getint('tool_holder_i2c_bus', None)
        if bus is not None:
            self._attach_holder(ToolHolder(
                self.reactor, Bus(bus), parse_pins(config.get('tool_holder_pins', HOLDER_PINS)),
                int(config.get('tool_holder_address', '0x20'), 0),
                int(config.get('tool_holder_tag_address', '0x24'), 0),
                say=self.gcode.respond_info))
            self.tool_macros = parse_macros(config.get('tool_holder_macros', HOLDER_MACROS))
            self.tag_retries = config.getint('tool_holder_tag_retries', 2)
            self.dry_idle = float(config.get('tool_dry_idle', 600))
            self.dry_printing = float(config.get('tool_dry_printing', 1200))
            self.dry_beep = float(config.get('tool_dry_beep', 3))
            self.dry_pens = os.path.expanduser(config.get('tool_dry_pens', PENS_FILE))
            self.scan_idle = float(config.get('tool_holder_scan_idle', 2.0))
            self.scan_printing = float(config.get('tool_holder_scan_printing', 5.0))

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
             "TOOL_TAG_WRITE [DX= DY= DZ= NAME= REFERENCE=0|1 PEN= COLOR=rrggbb] [MOVE=0]: write these to the "
             "carried tool's tag"),
            ('TOOL_TAGS', self.cmd_TOOL_TAGS, "The last tag read of each holder's tool (TOOL_SCAN reads them all)"),
            ('TOOL_CHANGE_PHASE', self.cmd_TOOL_CHANGE_PHASE,
             "TOOL_CHANGE_PHASE PHASE=engage|leave|idle: the tool change's step, for the LEDs"),
            ('TOOL_LEDS', self.cmd_TOOL_LEDS, "Redraw the tool holder and UI LEDs, show their states"),
            ('TOOL_DRY', self.cmd_TOOL_DRY,
             "TOOL_DRY [RESET=1 [T=41]] [SILENCE=1]: how long each known pen has been out of its cap"),
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
            self.holder.start_scanning(self._scan_gate)
            self.reactor.register_timer(self._dry_tick, self.reactor.NOW)

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
        self._fsr_last = None       # off the plotter, it may have been wiped
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
        routine = cls(machine, self.dock, self.samples, bed[sensor])
        if sensor == 'fsr':
            self._fsr_hooks(gcmd, routine)
        return routine

    def _fsr_hooks(self, gcmd, fsr):
        '''A tool other than the one the FSR sheet last had waits for the sheet to
        be wiped first, so no pen gets another's ink (CLEAN=0: it doesn't).'''
        def before():
            carried = self._carried()
            if self._fsr_last and carried != self._fsr_last and gcmd.get_int('CLEAN', 1):
                gcmd.respond_info(f"[LRT] The sheet last had tool {self._fsr_last}, now {carried}: wipe it first")
                fsr.wait_clean()

        def after():
            self._fsr_last = self._carried()

        fsr.before_measure, fsr.after_measure = before, after

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

    def _key_open(self):
        '''The tool lock's endstop triggers with the key fully open: nothing is locked
        on the carriage. None: no such endstop.'''
        query = self.printer.lookup_object('query_endstops', None)
        for endstop, name in getattr(query, 'endstops', ()):
            if name == KEY_ENDSTOP:
                return bool(endstop.query_endstop(self.printer.lookup_object('toolhead').get_last_move_time()))
        return None

    def _guess_carried(self, gcmd, tag):
        '''Before the BLTouch probes: a pen on the carriage would run into the bed,
        or, over the FSR, into the holders. With no tool saved as carried, the key
        locked and only one holder empty, that tool is taken as the carried one, so
        UNDOCK puts it away: undocking it with nothing on the carriage makes the same
        moves as docking, and its holder check stops there. With the key open nothing
        is guessed: an empty carriage is up to whoever emptied it.
        -> the tool on the carriage, 0: none.'''
        empty = self._empty_holders()
        if len(empty) == 1 and not self._carried() and not self._key_open():
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
            if (kind, state) == (FSR, S_MATRIX):
                # median of each cell over the frames, strongest first: what the routines go by
                per_cell = {}
                for f in frames:
                    for row, col, v in f.values:
                        per_cell.setdefault((row, col), []).append(v)
                median = {c: sorted(v)[len(v) // 2] for c, v in per_cell.items()}
                top = sorted(median, key=lambda c: -median[c])[:6]
                gcmd.respond_info(f"[LRT] hop {hop} cells: " + ', '.join(f"{c}={median[c]}" for c in top))

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
        holder.on('scan', self._on_scan)

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
        self._sync_drying()
        self._request_leds()

    def _on_holders_change(self, occupied, added, removed, manual):
        for tool in sorted(added | removed):
            how = 'manual' if tool in manual else 'expected'
            what = 'returned' if tool in added else 'removed'
            msg = f"[Tool holder] {tool}: tool {what} ({how})"
            logging.info(msg)
            self.gcode.respond_info(msg)
        if manual:
            now = self.holder.changed_at
            self.last_manual = {'at': now, 'added': sorted(added & manual),
                                'removed': sorted(removed & manual)}
            scanned = self._take_scan(sorted(added & manual), now)
            tags = self._tags()
            if scanned or any(str(t) in tags and not tags[str(t)].get('stale') for t in manual):
                for t in manual:
                    if str(t) in tags:
                        tags[str(t)]['stale'] = True
                if scanned:
                    holder, tag = scanned
                    tags[str(holder)] = self._tag_entry(tag, 'hand')
                self._save_vars({'tool_tags': tags})
            self.leds.manual(manual, now)
            self._wake(now)
            if not self.holder.busy():
                self._reconcile(occupied)
        self._sync_drying()
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
        states = self.leds.desired(now, self.holder.occupied, self.holder.ok, self._carried(), self._dry_stages)
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
        self._at_reader_now = True
        try:
            return self._at_reader_tries(gcmd, attempt)
        finally:
            self._at_reader_now = False

    def _at_reader_tries(self, gcmd, attempt):
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

    def _tags(self):
        '''The last tag read of each holder's tool, by holder (as a string: it goes through
        JSON), kept as `tool_tags` in the saved variables: the web UI takes the pens from
        it. `stale`: a hand changed that holder since, it may hold another tool now.'''
        if self._holder_tags is None:
            saved = self._vars().get('tool_tags') or {}
            self._holder_tags = {str(k): dict(v) for k, v in saved.items()} if isinstance(saved, dict) else {}
        return self._holder_tags

    @staticmethod
    def _tag_entry(tag, by):
        '''A holder's entry in `tool_tags`; by: dock (read on the carriage) or hand (scanned).'''
        return {'uid': tag.uid, 'name': tag.name, 'pen': tag.pen, 'color': tag.color,
                'dx': tag.dx, 'dy': tag.dy, 'dz': tag.dz, 'reference': tag.reference,
                'at': round(time.time()), 'stale': False, 'by': by}

    def _apply_tag(self, tag, tries):
        self._save_vars({'tool_offset_x': tag.dx, 'tool_offset_y': tag.dy, 'tool_offset_z': tag.dz,
                         'tool_name': tag.name, 'tool_tag_uid': tag.uid})
        holder = self._carried()
        if holder:
            tags = self._tags()
            tags[str(holder)] = self._tag_entry(tag, 'dock')
            self._save_vars({'tool_tags': tags})
            self._sync_drying()
        self._set_tag({'ok': True, 'uid': tag.uid, 'dx': tag.dx, 'dy': tag.dy, 'dz': tag.dz,
                       'name': tag.name, 'reference': tag.reference, 'pen': tag.pen, 'color': tag.color,
                       'tries': tries, 'read_at': self.reactor.monotonic()}, 'ok')

    @staticmethod
    def _describe(tag):
        extra = ''.join(f" {v}" for v in (tag.pen, tag.color) if v)
        return (f"{tag.name}{' (reference)' if tag.reference else ''}{extra}: "
                f"dx={tag.dx} dy={tag.dy} dz={tag.dz}")

    # Tags held to the reader by hand (ToolHolder.start_scanning)
    def _printing(self):
        stats = self.printer.lookup_object('print_stats', None)
        return stats is not None and stats.get_status(self.reactor.monotonic()).get('state') == 'printing'

    def _scan_gate(self):
        '''-> s until the next listen, None: not now. Never in a tool change or a read
        at the reader: the carriage brings its own tool there.'''
        if self._at_reader_now or self.holder.busy() or (self.leds and self.leds.phase in CHANGE_PHASES):
            return None
        now = self.reactor.monotonic()
        if now < self._awake_until or (self.scan and now - self.scan['seen'] < SCAN_WINDOW):
            return SCAN_FAST
        return (self.scan_printing if self._printing() else self.scan_idle) or None

    def _wake(self, now):
        '''A hand on the holders: listen fast for a while, the tag LED says so.'''
        self._awake_until = now + SCAN_AWAKE
        if not (self.leds.hand_state != 'listening' and now < self.leds.hand_until):
            self.leds.hand('listening', now, self._awake_until)
        self._request_leds()

    def _beep(self, macro):
        '''From a timer: the G-code runs when Klipper has a moment, between a plot's lines.'''
        def run(eventtime):
            try:
                self.gcode.run_script(macro)
            except Exception:
                logging.exception("[Tag] %s", macro)
        self.reactor.register_callback(run)

    def _on_scan(self, tag):
        now = self.reactor.monotonic()
        if self._carried() and tag.uid in (self.tag.get('uid'), self._vars().get('tool_tag_uid')):
            return                  # the carried tool, near the reader
        last = self.scan
        self.scan = {'tag': tag, 'seen': now}
        self.leds.hand('scanned', now, now + SCAN_WINDOW)
        self._request_leds()
        if last and last['tag'].uid == tag.uid and now - last['seen'] < SCAN_SAME:
            return                  # still held there
        self.gcode.respond_info(f"[Tag] Scanned {self._describe(tag)}: put it into its holder "
                                f"within {SCAN_WINDOW:.0f} s")
        self._beep("_BUZZ_RFID_OK")

    def _take_scan(self, added, now):
        '''The holders a hand just filled -> (holder, Tag) when one took the scanned tool.'''
        scan = self.scan
        if not scan or not added:
            return None
        age = now - scan['seen']
        if age > SCAN_LATE:
            self.scan = None
            return None
        self.scan = None
        name = scan['tag'].name
        if age > SCAN_WINDOW:
            why = f"{name} was scanned {age:.0f} s ago, over {SCAN_WINDOW:.0f} s"
        elif len(added) > 1:
            why = f"{len(added)} holders filled at once ({', '.join(map(str, added))}), which one has {name}?"
        else:
            holder, = added
            self.gcode.respond_info(f"[Tag] Holder {holder} has {self._describe(scan['tag'])}")
            self.leds.hand('taken', now, now + SCAN_WINDOW)
            self._beep("_BUZZ_711")
            return holder, scan['tag']
        self.gcode.respond_info(f"[Tag] Not taking the scan: {why}. Scan it again and put it back, "
                                f"or TOOL_SCAN")
        self.leds.hand('late', now, now + SCAN_WINDOW)
        self._beep("_BUZZ_RFID_ERR")
        return None

    def cmd_TOOL_TAG_READ(self, gcmd):
        self._require_holder(gcmd)
        tag, tries, error = self._at_reader(gcmd, self.holder.read_tag)
        if tag is None:
            self._set_tag({'ok': False, 'error': error, 'tries': tries}, 'error')
            gcmd.respond_info(f"[Tag] read failed after {tries} tries: {error}")
            return
        self._apply_tag(tag, tries)
        gcmd.respond_info(f"[Tag] {self._describe(tag)}")

    def cmd_TOOL_TAG_WRITE(self, gcmd):
        self._require_holder(gcmd)
        # COLOR without the # (it starts a comment in G-code); COLOR=none clears it
        color = gcmd.get('COLOR', None)
        if color is not None:
            color = '' if color.strip().lower() in ('', 'none') else '#' + color.strip().lstrip('#')
        fields = {'dx': gcmd.get_float('DX', None), 'dy': gcmd.get_float('DY', None),
                  'dz': gcmd.get_float('DZ', None), 'name': gcmd.get('NAME', None),
                  'reference': gcmd.get_int('REFERENCE', None), 'pen': gcmd.get('PEN', None), 'color': color}
        if all(v is None for v in fields.values()):
            raise gcmd.error("[Tag] nothing to write, give DX, DY, DZ, NAME, REFERENCE, PEN or COLOR")
        try:
            from .tool_holder import encode_color, encode_pen
            if fields['pen'] is not None:
                encode_pen(fields['pen'])
            if color is not None:
                encode_color(color)
        except ValueError as e:
            raise gcmd.error(f"[Tag] {e}")
        tag, tries, error = self._at_reader(gcmd, lambda: self.holder.write_tag(**fields))
        if tag is None:
            self._set_tag({'ok': False, 'error': error, 'tries': tries}, 'error')
            raise gcmd.error(f"[Tag] write failed after {tries} tries: {error}")
        self._apply_tag(tag, tries)
        gcmd.respond_info(f"[Tag] wrote {self._describe(tag)}")

    def cmd_TOOL_TAGS(self, gcmd):
        tags = self._tags()
        holders = sorted(self.holder.tools) if self.holder else sorted(int(k) for k in tags)
        lines = []
        for h in holders:
            t = tags.get(str(h))
            if not t:
                lines.append(f"{h}: not read")
                continue
            pen = ' '.join(v for v in (t.get('pen'), t.get('color')) if v) or 'no pen/colour (format 1)'
            lines.append(f"{h}: {t['name']}{' (reference)' if t.get('reference') else ''}, {pen}, "
                         f"dx={t['dx']} dy={t['dy']} dz={t['dz']}{', scanned by hand' if t.get('by') == 'hand' else ''}"
                         f"{', STALE: rescan' if t.get('stale') else ''}")
        gcmd.respond_info("[Tag] " + "\n".join(lines))

    def _scan_status(self, eventtime):
        '''The tag held to the reader last, while a holder can still take it.'''
        if not self.scan or eventtime - self.scan['seen'] > SCAN_WINDOW:
            return None
        t = self.scan['tag']
        return {'uid': t.uid, 'name': t.name, 'pen': t.pen, 'color': t.color,
                'left': round(SCAN_WINDOW - (eventtime - self.scan['seen']), 1)}

    # Pens drying out (drying.py): a known pen in the machine is out of its cap
    def _pens_in(self):
        '''The known pens in the machine now: a tag that isn't stale, in its holder or on the carriage.'''
        occupied = self.holder.occupied or frozenset()
        carried = self._carried()
        self._pen_dry()
        never = self._pens[2]                   # no ink: a camera, a laser, a knife
        return {int(h) for h, t in self._tags().items()
                if not t.get('stale') and t.get('pen') not in never and (int(h) in occupied or int(h) == carried)}

    def _sync_drying(self):
        if not self.holder or self.holder.occupied is None:
            return
        if self.drying is None:
            self.drying = Drying(self.dry_idle, self.dry_printing, self._vars().get('pen_since'))
        if self.drying.update(self._pens_in(), self.clock()):
            self._save_vars({'pen_since': self.drying.saved()})
        dry = self._pen_dry()
        self.drying.limits = {int(h): dry[t['pen']] * 60 for h, t in self._tags().items()
                              if t.get('pen') in dry}

    def _pen_dry(self):
        '''{pen key: minutes uncapped} from the pen library (plot/profiles/pens.toml),
        read again when it changes; {} without it.'''
        try:
            mtime = os.path.getmtime(self.dry_pens)
            if mtime != self._pens[0]:
                import tomllib
                with open(self.dry_pens, 'rb') as f:
                    lib = tomllib.load(f)
                lib = {k: v for k, v in lib.items() if isinstance(v, dict)}
                self._pens = (mtime, {k: float(v['dry']) for k, v in lib.items() if v.get('dry')},
                              {k for k, v in lib.items() if v.get('kind', 'pen') not in INKY})
        except (OSError, ImportError, ValueError) as e:
            if self._pens[0] != 'missing':
                logging.info("[Tool holder] no pen library for drying times (%s): %s", self.dry_pens, e)
            self._pens = ('missing', {}, set())
        return self._pens[1]

    def _dry_tick(self, eventtime):
        self._sync_drying()
        if self.drying is None:
            return eventtime + 1.0
        stages = self.drying.stages(self.clock(), self._printing())
        turn = len(stages) > 1 and int(eventtime) % 2 == 0          # several: their digits take turns
        if stages != self._dry_stages or turn:
            self._dry_stages = stages
            self._request_leds()
        self._dry_silenced &= set(stages)
        loud = set(stages) - self._dry_silenced
        if loud and self.dry_beep > 0 and eventtime - self._dry_beep_at >= self.dry_beep:
            self._dry_beep_at = eventtime
            self._beep_twice()
        return eventtime + 1.0

    def _beep_twice(self):
        '''Beep beep on [pwm_cycle_time beeper] with SET_PIN only: M300 dwells (G4),
        which would stall a plot that is running.'''
        on, off = "SET_PIN PIN=beeper VALUE=0.8 CYCLE_TIME=0.00033", "SET_PIN PIN=beeper VALUE=0"
        now = self.reactor.monotonic()
        for i, script in enumerate((on, off, on, off)):
            def run(eventtime, script=script):
                try:
                    self.gcode.run_script(script)
                except Exception:
                    logging.exception("[Tool holder] beeping")
                return self.reactor.NEVER
            self.reactor.register_timer(run, now + 0.12 * i)

    def cmd_TOOL_DRY(self, gcmd):
        self._require_holder(gcmd)
        self._sync_drying()
        if self.drying is None:
            raise gcmd.error("[Tool holder] the holders haven't been read yet")
        now = self.clock()
        if gcmd.get_int('RESET', 0):
            tool = gcmd.get_int('T', None)
            self.drying.reset(now, tool)
            self._save_vars({'pen_since': self.drying.saved()})
            self._dry_stages = self.drying.stages(now, self._printing())
            self._request_leds()
        if gcmd.get_int('SILENCE', 0):
            self._dry_silenced = set(self.drying.stages(now, self._printing()))
        status = self.drying.status(now, self._printing())
        if not status:
            gcmd.respond_info("[Tool holder] No known pen is out of its cap")
            return
        gcmd.respond_info("[Tool holder] Out of their caps:\n" + "\n".join(
            f"{h}: {s['uncapped'] // 60} min of {s['limit'] // 60:.0f}"
            + (f", OVERDUE (stage {s['stage']})" if s['stage'] else '') for h, s in status.items()))

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
            'scan': self._scan_status(eventtime),
            'drying': self.drying.status(self.clock(), self._printing()) if self.drying else {},
            'tools': self._tags() if self._holder_tags is not None or self.holder else {},
            'leds': {k: v for k, v in self._led_states.items() if v},     # what the UI and dock LEDs show (leds.py)
        }


def load_config(config):
    return Limn(config)
