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
# i2c.py       the Pi's I2C bus: MCP23017 and PN532
# tool_holder.py  which holders have their tool, and the tools' tags
import json
import logging

from .dock import Dock
from .samples import Samples, Sample, FSR, RTP, S_SAMPLE
from .machine import Machine
from .geometry import ProbeValue, gen_draw_grid
from .beds import BEDS
from .rtp import Rtp
from .fsr import Fsr
from .i2c import Bus
from .tool_holder import ToolHolder, parse_pins

LRT_CONF_VERSION = 'v2.0'
RTP_KEYS = ('touch_params', 'ref_samples', 'ref_z_panel', 'ref_z_paper')
ROUTINE_ERRORS = (RuntimeError, TimeoutError, ConnectionError)
TAG_ERRORS = (OSError, RuntimeError, TimeoutError)
HOLDER_PINS = '15:41, 14:42, 13:45, 12:43, 11:44'
CARRIAGE_VARS = {'currently_docked_tool': 0, 'tool_offset_x': 0, 'tool_offset_y': 0,
                 'tool_offset_z': 0, 'tool_name': ''}


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

        self.holder = None
        self.tag = {'ok': False}
        self.last_manual = None
        bus = config.getint('tool_holder_i2c_bus', None)
        if bus is not None:
            self._attach_holder(ToolHolder(
                self.reactor, Bus(bus), parse_pins(config.get('tool_holder_pins', HOLDER_PINS)),
                int(config.get('tool_holder_address', '0x20'), 0),
                int(config.get('tool_holder_tag_address', '0x24'), 0),
                say=self.gcode.respond_info))

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
            ('TOOL_HOLDERS', self.cmd_TOOL_HOLDERS, "Show which tool holders have their tool"),
            ('TOOL_HOLDER_CHECK', self.cmd_TOOL_HOLDER_CHECK,
             "TOOL_HOLDER_CHECK T=41 EXPECT=occupied|empty [ARM=1]: stop unless the holder is so"),
            ('TOOL_TAG_READ', self.cmd_TOOL_TAG_READ, "Read the carried tool's tag [MOVE=0]"),
            ('TOOL_TAG_WRITE', self.cmd_TOOL_TAG_WRITE,
             "TOOL_TAG_WRITE [DX= DY= DZ= NAME=] [MOVE=0]: write these to the carried tool's tag"),
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
            self.reactor.register_callback(lambda e: self._probe_tag_reader())

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

    # Tool holder
    def _attach_holder(self, holder):
        self.holder = holder
        holder.on('ready', self._on_holders_ready)
        holder.on('change', self._on_holders_change)

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
            self.gcode.respond_info(f"[Tool holder] holders {sorted(self.holder.tools - occupied)} are "
                                    f"empty and no tool is saved as carried")

    def _on_holders_ready(self, occupied):
        logging.info("[Tool holder] occupied: %s", sorted(occupied))
        self._reconcile(occupied, startup=True)

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
            if not self.holder.busy():
                self._reconcile(occupied)
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
        try:
            occupied = tool in self.holder.sample()
        except (OSError, RuntimeError) as e:
            self.holder.forget(tool)
            raise gcmd.error(f"[Tool holder] can't read the holders: {e}")
        if occupied != (expect == 'occupied'):
            self.holder.forget(tool)
            raise gcmd.error(f"[Tool holder] holder {tool} is {'occupied' if occupied else 'empty'}, "
                             f"expected {expect}")
        if gcmd.get_int('ARM', 0):
            self.holder.expect(tool, not occupied)

    def _tag_home(self, gcmd):
        if gcmd.get_int('MOVE', 1):
            self.gcode.run_script_from_command("_RFID_HOME")
        self._wait_moves()

    def _apply_tag(self, tag):
        self._save_vars({'tool_offset_x': tag.dx, 'tool_offset_y': tag.dy, 'tool_offset_z': tag.dz,
                         'tool_name': tag.name, 'tool_tag_uid': tag.uid})
        self.tag = {'ok': True, 'uid': tag.uid, 'dx': tag.dx, 'dy': tag.dy, 'dz': tag.dz,
                    'name': tag.name, 'read_at': self.reactor.monotonic()}

    def cmd_TOOL_TAG_READ(self, gcmd):
        self._require_holder(gcmd)
        self._tag_home(gcmd)
        try:
            tag = self.holder.read_tag()
        except TAG_ERRORS as e:
            self.tag = {'ok': False, 'error': str(e)}
            gcmd.respond_info(f"[Tag] read failed: {e}")
            return
        if tag is None:
            self.tag = {'ok': False, 'error': 'no tag'}
            gcmd.respond_info("[Tag] no tag found")
            return
        self._apply_tag(tag)
        gcmd.respond_info(f"[Tag] {tag.name}: dx={tag.dx} dy={tag.dy} dz={tag.dz}")

    def cmd_TOOL_TAG_WRITE(self, gcmd):
        self._require_holder(gcmd)
        fields = {'dx': gcmd.get_float('DX', None), 'dy': gcmd.get_float('DY', None),
                  'dz': gcmd.get_float('DZ', None), 'name': gcmd.get('NAME', None)}
        if all(v is None for v in fields.values()):
            raise gcmd.error("[Tag] nothing to write, give DX, DY, DZ or NAME")
        self._tag_home(gcmd)
        try:
            tag = self.holder.write_tag(**fields)
        except TAG_ERRORS as e:
            self.tag = {'ok': False, 'error': str(e)}
            raise gcmd.error(f"[Tag] write failed: {e}")
        self._apply_tag(tag)
        gcmd.respond_info(f"[Tag] wrote {tag.name}: dx={tag.dx} dy={tag.dy} dz={tag.dz}")

    def get_status(self, eventtime):
        holder = self.holder
        return {
            'bed': self.bed,
            'rtp_calibrated': self.calibrated('rtp'),
            'fsr_calibrated': self.calibrated('fsr'),
            'connected': self.dock.connected,
            'tool_holder': {
                'enabled': holder is not None,
                'ok': bool(holder and holder.ok),
                'occupied': sorted(holder.occupied) if holder and holder.occupied is not None else None,
                'changed_at': holder.changed_at if holder else 0,
                'last_manual': self.last_manual,
            },
            'tag': self.tag,
        }


def load_config(config):
    return Limn(config)
