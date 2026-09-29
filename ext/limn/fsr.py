# Limn - tool alignment with an FSR array (BED_5)
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Z: the tool is jogged down onto a cell, coarse then fine steps, until the
#    array feels it. The FSR is too slow for the probe endstop, so we move
#    and look ourselves, with a floor below which we never go.
# XY: between two cells there is a dead zone (<0.5mm) where neither responds.
#    Taps find the last point where cell A still responds and the last point
#    where cell B does; the edge is halfway, so the gap width cancels out.
#    An edge between cols gives one axis, an edge between rows the other.
# Where the tip is: first contact at the array's `aim`, where any cell may
#    respond. That cell, and how far the tip goes before leaving it, give the
#    tip to a few tenths; every search after aims that much off, so a tool
#    a few mm off still lands on the cells it measures. Off the array
#    nothing responds: down to the floor, up, and stop.
# A tool is compared with the reference tool (T4) on the same cells, so the
# array positions only need to be roughly right.
#
# The arrays run in matrix mode meanwhile: every cell every frame, so we also
# know they are alive. No frame for `alive` seconds, a press above
# `press_limit`, or no contact down to the floor: lift to park and stop.
from collections import Counter

import numpy as np

from .geometry import FsrArray, mesh_z
from .samples import FSR, RTP, S_MATRIX
from .machine import JOG_SPEED, lifted_on_error


class FsrError(RuntimeError):
    pass


class Fsr:

    def __init__(self, machine, dock, samples, cfg):
        self.machine = machine
        self.dock = dock
        self.samples = samples
        self.cfg = cfg
        self.arrays = {a['hop']: a for a in cfg['arrays']}
        self.surface = None         # the array's bed mesh profile, see follow()
        self.depth = {}             # hop -> how far past contact this tool's taps press, see press_depth()
        self.before_measure = None  # called before / after measuring a tool: the wipe
        self.after_measure = None   # between pens, see __init__.py _fsr_hooks

    def array(self, hop):
        a = self.arrays[hop]
        if a['origin'] is None:
            raise FsrError(f"[LRT] the origin of the FSR array at hop {hop} is not set (ext/limn/beds.py)")
        return FsrArray(hop, a['origin'], a['col_dir'], a['row_dir'], pitch=self.cfg['pitch'])

    # Reading the arrays
    def matrix(self, on):
        for hop in self.arrays:
            try:
                self.dock.send_to(hop, 'matrix(on)' if on else 'matrix(off)')
            except ConnectionError:
                if on:
                    raise   # turning it off can fail quietly: the error that got us here matters more

    def read(self, hop, limit=True):
        '''After a move: waits for it and for fresh frames -> {(row, col): strength},
        without the array's dead rows. limit: a press over press_limit stops us.'''
        self.machine.wait_moves()
        since = self.machine.now()
        self.machine.pause(self.cfg['settle'])
        while not self.samples.since(since, hop=hop, kind=FSR, state=S_MATRIX):
            if self.machine.now() - since > self.cfg['alive']:
                raise FsrError(f"[LRT] no frames from the FSR at hop {hop}: {self.heard(since)}")
            self.machine.pause(0.02)

        dead = self.arrays[hop].get('dead_rows', ())
        cells = {}
        for frame in self.samples.since(since, hop=hop, kind=FSR, state=S_MATRIX):
            for row, col, strength in frame.values:
                if row not in dead:
                    cells.setdefault((row, col), []).append(strength)
        strengths = {cell: float(np.median(v)) for cell, v in cells.items()}
        hardest = max(strengths.values(), default=0)
        if limit and hardest >= self.cfg['press_limit']:
            raise FsrError(f"[LRT] pressing too hard on the FSR at hop {hop} ({hardest:.0f})")
        return strengths

    def heard(self, until, window=5.0):
        '''What the chain did send in the `window` s before `until`, for the error.'''
        recent = [s for s in self.samples.since(until - window) if s.t <= until + self.cfg['alive']]
        if not recent:
            return f"nothing from any node in {window:.0f}s (is the Dock connected? LRT_CHAIN)"
        seen = Counter((s.hop, {FSR: 'FSR', RTP: 'RTP'}.get(s.kind, s.kind), s.state) for s in recent)
        heard = ', '.join(f"hop {h} {kind} state {state} x{n}" for (h, kind, state), n in sorted(seen.items()))
        return (f"heard {heard} in {window:.0f}s. Matrix frames are FSR state {S_MATRIX}: without them, "
                f"the node's firmware may be from before matrix mode (mcu.py update)")

    def responds(self, strengths, cell):
        '''Over `respond`, and close to the strongest cell: a press also lifts
        the other rows of its column a little (crosstalk), row 3 a lot.'''
        s = strengths.get(tuple(cell), 0)
        return s >= self.cfg['respond'] and s >= self.cfg['dominance'] * max(strengths.values(), default=0)

    def top(self, strengths, n=3):
        '''The strongest cells, for messages.'''
        cells = sorted(strengths, key=lambda c: -strengths[c])[:n]
        return ', '.join(f"{c}={strengths[c]:.0f}" for c in cells)

    # Z
    def window(self, bed_z, prior=None):
        '''(floor, top) of the z search: tool_z over the BLTouch z, or, with the
        contact z expected (prior['z']), `prior_margin` below it, never lower.'''
        low, high = self.cfg['tool_z']
        floor, top = bed_z + low, bed_z + high + 1.0
        if prior and prior.get('z') is not None:
            floor = max(floor, prior['z'] - self.cfg['prior_margin'])
            top = min(top, prior['z'] + 1.0)
        return floor, top

    def contact_z(self, hop, row, col, bed_z, shift=(0, 0), top=None, prior=None):
        '''z where the tool starts to press on (row, col), median of `repeats`.
        bed_z: BLTouch z at that cell; the search stays within tool_z of it.
        shift: where the tip sits off the toolhead, as far as we know (locate).
        top: start there instead of above the window. prior: see window().'''
        cfg = self.cfg
        x, y = self.array(hop).center(row, col) - np.asarray(shift)
        floor, z = self.window(bed_z, prior)
        z = z if top is None else top
        found = []
        with lifted_on_error(self.machine, cfg['z_park']):
            self.machine.move(z=cfg['z_park'])
            self.machine.move(float(x), float(y))
            self.machine.move(z=z)
            if self.touched(self.read(hop), hop):
                raise FsrError(f"[LRT] already touching at z={z:.2f}, above the search window")
            for _ in range(cfg['repeats']):
                z, _ = self._descend(hop, (row, col), z, cfg['step'], floor)
                z = self._back_off(hop, z + cfg['back_off'])
                z, _ = self._descend(hop, (row, col), z, cfg['fine_step'], floor)
                found.append(z)
                z = self._back_off(hop, z + cfg['back_off'])
            self.machine.move(z=cfg['z_park'])
            self.machine.wait_moves()
        return float(np.median(found))

    def touched(self, strengths, hop):
        '''The cells that respond, strongest first. A cell in one of the array's
        crosstalk_rows only when no other row of its column responds, or when
        it is a real press: a press elsewhere in the column lifts it too.'''
        cells = [c for c in strengths if self.responds(strengths, c)]
        crosstalk = self.arrays[hop].get('crosstalk_rows', ())
        cells = [c for c in cells if c[0] not in crosstalk or strengths[c] >= self.cfg['sure']
                 or not any(o[1] == c[1] and o[0] != c[0] for o in cells)]
        return sorted(cells, key=lambda c: -strengths[c])

    def _descend(self, hop, cell, z, step, floor):
        '''Down until `cell` responds (None: any cell) -> (z, the cells that do).'''
        cfg = self.cfg
        while True:
            z -= step
            if z < floor:
                raise FsrError(f"[LRT] no contact down to z={floor:.2f}: is the tool over the array at hop {hop}?")
            self.machine.move(z=z, speed=JOG_SPEED)
            strengths = self.read(hop)
            touched = self.touched(strengths, hop)
            if touched and (cell is None or tuple(cell) in touched):
                return z, touched
            # At first touch the crosstalk can lead the pressed cell: only a
            # real press elsewhere means the tip is not over `cell`.
            if touched and strengths[touched[0]] >= cfg['sure']:
                raise FsrError(f"[LRT] cell {touched[0]} of hop {hop} responds instead of {cell} "
                               f"({self.top(strengths)}): check the array origin")

    def _back_off(self, hop, z):
        self.machine.move(z=z, speed=JOG_SPEED)
        if self.touched(self.read(hop), hop):
            raise FsrError(f"[LRT] still touching after backing off to z={z:.2f}")
        return z

    # Where the tip is
    def locate(self, hop, bed_z, prior=None):
        '''Down at the array's `aim` until any cell responds, then along the
        cols and the rows to where that cell stops -> (shift, z): the tip's
        offset from the toolhead to a few tenths, and a z just above contact.
        prior['tip']: where the tip is thought to be, so it comes down on the aim.'''
        cfg = self.cfg
        array = self.array(hop)
        aim = array.point(*self.arrays[hop]['aim'])
        if prior and prior.get('tip') is not None:
            aim = aim - np.asarray(prior['tip'], dtype=float)
        floor, z = self.window(bed_z, prior)
        with lifted_on_error(self.machine, cfg['z_park']):
            self.machine.move(z=cfg['z_park'])
            self.machine.move(float(aim[0]), float(aim[1]))
            self.machine.move(z=z)
            if self.touched(self.read(hop), hop):
                raise FsrError(f"[LRT] already touching at z={z:.2f}, above the search window")
            z, _ = self._descend(hop, None, z, cfg['step'], floor)
            z = self._back_off(hop, z + cfg['back_off'])
            z, _ = self._descend(hop, None, z, cfg['fine_step'], floor)
            self.depth[hop] = self.press_depth(hop, None, z)
            z_press, z_lift = z - self.depth[hop], z + 1.0
            # Which cell: pressed in, where the crosstalk has fallen behind.
            strengths = self.tap(hop, aim, z_press, z_lift, aim)
            touched = self.touched(strengths, hop)
            if not touched:
                raise FsrError(f"[LRT] nothing responds pressed in at {aim.round(2)} ({self.top(strengths)})")
            # Along each axis the tip leaves the strongest cell where it reaches
            # the cell's far side, within two cells. On an edge, that is the edge.
            # (Two cells responding is no edge to go by: the column's crosstalk
            # can come close to a tip split between two cells, 2026-09-28.)
            cell = touched[0]
            shift = np.zeros(2)
            for axis, direction in ((1, array.col_dir), (0, array.row_dir)):
                last = self.last_response(hop, cell, aim, aim + 2 * array.pitch * direction,
                                          z_press, z_lift, resolution=0.1, at=aim)
                tip = (cell[axis] + 1) * array.pitch - np.dot(last - aim, direction)
                shift += (tip - np.dot(aim - array.origin, direction)) * direction
            self.machine.move(z=cfg['z_park'])
            self.machine.wait_moves()
        self.machine.say(f"[LRT] tip at about {shift.round(2).tolist()} from the toolhead (cells {touched}), "
                         f"taps press {self.depth[hop]:.2f}mm")
        return shift, z + cfg['back_off']

    def press_depth(self, hop, cell, z):
        '''How far past contact the taps press, the tip at contact (z) over
        `cell` (None: the strongest): until it reads `press_strength`, `press`
        at most. A felt tip gets there in ~0.05mm, a fine one needs ~0.3;
        deeper only adds force: a Stabilo read ~460 at 0.05mm and ~670 at
        0.3mm, and 0.3mm taps left marks on the sheet (2026-09-29).'''
        cfg = self.cfg
        target = cfg.get('press_strength')
        if not target:
            return cfg['press']
        depth = 0.0
        while depth < cfg['press'] - 1e-9:
            depth = round(min(depth + cfg['fine_step'], cfg['press']), 3)
            self.machine.move(z=z - depth, speed=JOG_SPEED)
            strengths = self.read(hop)
            strength = strengths.get(tuple(cell), 0) if cell else max(strengths.values(), default=0)
            if strength >= target:
                break
        return depth

    # XY
    def follow(self, xy, at):
        '''How much higher the sheet is at `xy` than at `at`, where the contact z
        was found: the moves are raw, the bed mesh does not do this for us. 0
        without the array's mesh.'''
        if self.surface is None or at is None:
            return 0.0
        return mesh_z(self.surface, *xy) - mesh_z(self.surface, *at)

    def tap(self, hop, xy, z_press, z_lift, at=None):
        '''Down onto `xy`, read, back up. Never moves sideways while pressing.
        at: where z_press is right; elsewhere it follows the sheet.'''
        dz = self.follow(xy, at)
        self.machine.move(z=z_lift + max(dz, 0), speed=JOG_SPEED * 5)
        self.machine.move(float(xy[0]), float(xy[1]))
        self.machine.move(z=z_press + dz, speed=JOG_SPEED)
        strengths = self.read(hop)
        self.machine.move(z=z_lift, speed=JOG_SPEED * 5)
        return strengths

    def last_response(self, hop, cell, start, end, z_press, z_lift, resolution=None, at=None):
        '''The last point from `start` (centre of `cell`) towards `end` (centre
        of its neighbour) where `cell` still responds.'''
        resolution = resolution or self.cfg['resolution']
        start, end = np.array(start, dtype=float), np.array(end, dtype=float)
        if not self.responds(self.tap(hop, start, z_press, z_lift, at), cell):
            raise FsrError(f"[LRT] cell {cell} of hop {hop} does not respond at its centre {start.round(2)}: check the array origin")
        if self.responds(self.tap(hop, end, z_press, z_lift, at), cell):
            raise FsrError(f"[LRT] cell {cell} of hop {hop} responds at its neighbour's centre {end.round(2)}: check the array origin")
        lo, hi = 0.0, 1.0
        length = float(np.linalg.norm(end - start))
        while (hi - lo) * length > resolution:
            mid = (lo + hi) / 2
            if self.responds(self.tap(hop, start + mid * (end - start), z_press, z_lift, at), cell):
                lo = mid
            else:
                hi = mid
        return start + (lo + hi) / 2 * (end - start)

    def find_edge(self, edge, z_contact, shift=(0, 0)):
        '''edge: (hop, (row, col) of cell a, (row, col) of its neighbour b)
        -> (edge point, gap width). shift: as for contact_z.'''
        hop, cell_a, cell_b = edge
        array = self.array(hop)
        a = array.center(*cell_a) - np.asarray(shift)
        b = array.center(*cell_b) - np.asarray(shift)
        z_lift = z_contact + 1.0
        with lifted_on_error(self.machine, self.cfg['z_park']):
            self.machine.move(z=self.cfg['z_park'])
            self.machine.move(float(a[0]), float(a[1]))
            if hop not in self.depth:       # no locate() before (LRT_FSR_EDGE): find it on cell a
                self.machine.move(z=z_lift)
                self.machine.move(z=z_contact, speed=JOG_SPEED)
                self.depth[hop] = self.press_depth(hop, tuple(cell_a), z_contact)
            z_press = z_contact - self.depth[hop]
            a_off = self.last_response(hop, tuple(cell_a), a, b, z_press, z_lift, at=a)
            b_on = self.last_response(hop, tuple(cell_b), b, a, z_press, z_lift, at=a)
            self.machine.move(z=self.cfg['z_park'])
            self.machine.wait_moves()
        return (a_off + b_on) / 2, float(np.linalg.norm(b_on - a_off))

    # Whole measurements
    def z_cells(self):
        '''Cells that need a BLTouch z: the z cell and the first cell of each edge.'''
        cells = [tuple(self.cfg['z_cell'])]
        for hop, cell_a, _ in self.cfg['x_edges'] + self.cfg['y_edges']:
            if (hop, *cell_a) not in cells:
                cells.append((hop, *cell_a))
        return cells

    def bltouch_z(self, cell):
        '''BLTouch z at the centre of a cell, the probe moved over it.'''
        hop, row, col = cell
        x, y = self.array(hop).center(row, col)
        x_offset, y_offset, _ = self.machine.probe_offsets()
        z_park = self.cfg['z_park']
        self.machine.move(z=z_park)
        self.machine.move(x - x_offset, y - y_offset)
        result = self.machine.probe()
        self.machine.move(z=z_park)
        return float(result.test_z)

    def measure(self, bed_z, prior=None):
        '''The docked tool: contact z on the z cell, and the X and Y edges.
        bed_z: {cell: BLTouch z} for z_cells(). prior: what is known of the
        tool already, {'tip': (x, y), 'z': contact z}, see locate() and window().'''
        cfg = self.cfg
        shift, contact = {}, {}
        self.depth = {}             # this tool's, found again
        self.surface = self.machine.mesh_profile(cfg['surface_mesh']) if cfg.get('surface_mesh') else None
        if cfg.get('surface_mesh') and self.surface is None:
            self.machine.say(f"[LRT] no {cfg['surface_mesh']} mesh: the taps take the sheet as flat")

        def on(hop, row, col):
            '''The tip found on this array, and its contact z on (row, col).'''
            if hop not in contact:
                shift[hop], top = self.locate(hop, bed_z[(hop, row, col)], prior)
                contact[hop] = self.contact_z(hop, row, col, bed_z[(hop, row, col)], shift[hop], top, prior)
            return contact[hop]

        if self.before_measure:
            self.before_measure()
        self.matrix(True)
        try:
            z = on(*cfg['z_cell'])
            points, gaps = {'x': [], 'y': []}, []
            for axis, edges in (('x', cfg['x_edges']), ('y', cfg['y_edges'])):
                for edge in edges:
                    e_hop, cell_a, _ = edge
                    point, gap = self.find_edge(edge, on(e_hop, *cell_a), shift[e_hop])
                    points[axis].append(point[0 if axis == 'x' else 1])
                    gaps.append(gap)
                    self.machine.say(f"[LRT] {axis} edge {edge}: {point.round(3)} gap={gap:.3f}")
        finally:
            self.matrix(False)
            if self.after_measure:
                self.after_measure()        # it touched the sheet, even when it stopped
        return {
            'z': z,
            'x': float(np.mean(points['x'])),
            'y': float(np.mean(points['y'])),
            'gaps': gaps,
            'tip': [float(v) for v in shift[cfg['z_cell'][0]]],
        }

    # Between pens
    def wait_clean(self):
        '''Ink from the last pen on the sheet would end up on the next one: park the
        carried tool away from the array and wait for the sheet to be wiped, that
        is presses on `wipe_cells` cells or more, then `quiet` seconds with none.'''
        cfg, clean = self.cfg, self.cfg['clean']
        self.machine.move(z=cfg['z_park'])
        self.machine.move(*clean['park'])
        self.machine.gcode_run("_BUZZ_WARN")
        self.machine.say(f"[LRT] Wipe the FSR sheet, then take your hand off it (waiting up to {clean['timeout']}s)")
        seen, quiet_since = set(), None
        start = self.machine.now()
        self.matrix(True)
        try:
            while True:
                now = self.machine.now()
                if now - start > clean['timeout']:
                    raise FsrError(f"[LRT] the FSR sheet wasn't wiped within {clean['timeout']}s "
                                   f"({len(seen)} of {clean['wipe_cells']} cells pressed)")
                pressed = {(hop, c) for hop in self.arrays
                           for c, s in self.read(hop, limit=False).items() if s >= cfg['respond']}
                seen |= pressed
                if pressed or len(seen) < clean['wipe_cells']:
                    quiet_since = None
                elif quiet_since is None:
                    quiet_since = now
                elif now - quiet_since >= clean['quiet']:
                    break
        finally:
            self.matrix(False)
        self.machine.gcode_run("_BUZZ_DOOP")
        self.machine.say(f"[LRT] Sheet wiped ({len(seen)} cells pressed), carrying on")

    def calibrate(self):
        '''With the reference tool (T4). -> profile for the [limn] section.'''
        run = self.machine.gcode_run
        run("UNDOCK")
        run("G28")
        run("_CLEAR_OFFSETS")
        bed_z = self.probe_bed_z()
        run("T4")
        return self.calibrate_reference(bed_z)

    def probe_bed_z(self):
        '''BLTouch z of the z_cells(), no tool on the carriage -> {cell: z}.'''
        bed_z = {cell: self.bltouch_z(cell) for cell in self.z_cells()}
        self.machine.gcode_run("_BUZZ_DOOP")
        return bed_z

    def bed_z_update(self, profile, bed_z):
        '''The profile with a new bed z only: the reference tool's edges stay.'''
        return {'fsr_ref': {**profile['fsr_ref'], 'bed_z': [[*cell, z] for cell, z in bed_z.items()]}}

    def calibrate_reference(self, bed_z):
        '''The reference tool on the carriage, bed_z just probed -> profile.'''
        ref = self.measure(bed_z)
        tool_z = round(ref['z'] - bed_z[tuple(self.cfg['z_cell'])], 3)
        self.machine.gcode_run(f"WRITE_TOOL_TAG DX=0 DY=0 DZ={tool_z:.3f} REFERENCE=1")
        ref['bed_z'] = [[*cell, z] for cell, z in bed_z.items()]
        return {'fsr_ref': ref}

    def probe_tool(self, profile):
        '''The docked tool against the reference -> (dx, dy, dz).
        The edges give where the tool was *sent* when it met them, so a tool
        tip that sits +0.5mm off meets them 0.5mm early: dx = tool - reference.'''
        ref = profile['fsr_ref']
        bed_z = {tuple(c[:3]): c[3] for c in ref['bed_z']}
        self.machine.gcode_run("_CLEAR_OFFSETS")
        m = self.measure(bed_z)
        dx = round(m['x'] - ref['x'], 3)
        dy = round(m['y'] - ref['y'], 3)
        dz = round(m['z'] - bed_z[tuple(self.cfg['z_cell'])], 3)
        self.machine.say(f"[LRT] offsets dx={dx} dy={dy} dz={dz} gaps={[round(g, 3) for g in m['gaps']]}")
        return dx, dy, dz
