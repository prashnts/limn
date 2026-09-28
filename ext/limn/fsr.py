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

from .geometry import FsrArray
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

    def read(self, hop):
        '''After a move: waits for it and for fresh frames -> {(row, col): strength},
        without the array's dead rows.'''
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
        if hardest >= self.cfg['press_limit']:
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
            if self.touched(self.read(hop)):
                raise FsrError(f"[LRT] already touching at z={z:.2f}, above the search window")
            for _ in range(cfg['repeats']):
                z, _ = self._descend(hop, (row, col), z, cfg['step'], floor)
                z = self._back_off(hop, z + 2 * cfg['step'])
                z, _ = self._descend(hop, (row, col), z, cfg['fine_step'], floor)
                found.append(z)
                z = self._back_off(hop, z + 2 * cfg['step'])
            self.machine.move(z=cfg['z_park'])
            self.machine.wait_moves()
        return float(np.median(found))

    def touched(self, strengths):
        '''The cells that respond, strongest first.'''
        return sorted((c for c in strengths if self.responds(strengths, c)), key=lambda c: -strengths[c])

    def _descend(self, hop, cell, z, step, floor):
        '''Down until `cell` responds (None: any cell) -> (z, the cells that do).'''
        cfg = self.cfg
        while True:
            z -= step
            if z < floor:
                raise FsrError(f"[LRT] no contact down to z={floor:.2f}: is the tool over the array at hop {hop}?")
            self.machine.move(z=z, speed=JOG_SPEED)
            strengths = self.read(hop)
            touched = self.touched(strengths)
            if touched and (cell is None or tuple(cell) in touched):
                return z, touched
            # At first touch the crosstalk can lead the pressed cell: only a
            # real press elsewhere means the tip is not over `cell`.
            if touched and strengths[touched[0]] >= cfg['sure']:
                raise FsrError(f"[LRT] cell {touched[0]} of hop {hop} responds instead of {cell} "
                               f"({self.top(strengths)}): check the array origin")

    def _back_off(self, hop, z):
        self.machine.move(z=z, speed=JOG_SPEED)
        if self.touched(self.read(hop)):
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
            if self.touched(self.read(hop)):
                raise FsrError(f"[LRT] already touching at z={z:.2f}, above the search window")
            z, _ = self._descend(hop, None, z, cfg['step'], floor)
            z = self._back_off(hop, z + 2 * cfg['step'])
            z, _ = self._descend(hop, None, z, cfg['fine_step'], floor)
            z_press, z_lift = z - cfg['press'], z + 1.0
            # Which cell: pressed in, where the crosstalk has fallen behind.
            strengths = self.tap(hop, aim, z_press, z_lift)
            touched = self.touched(strengths)
            if not touched:
                raise FsrError(f"[LRT] nothing responds pressed in at {aim.round(2)} ({self.top(strengths)})")
            # Only the strongest and its neighbours: crosstalk shows further up the column.
            touched = [c for c in touched if max(abs(c[0] - touched[0][0]), abs(c[1] - touched[0][1])) <= 1]
            # Along each axis: two cells respond, the tip is on the edge
            # between them. One does: the tip leaves it where it reaches the
            # cell's far side, which is within two cells. The dead zone puts
            # either a few tenths out, enough to aim.
            shift = np.zeros(2)
            for axis, direction in ((1, array.col_dir), (0, array.row_dir)):
                on = sorted({cell[axis] for cell in touched})
                if len(on) > 1:
                    tip = on[-1] * array.pitch
                else:
                    cell = touched[0]
                    last = self.last_response(hop, cell, aim, aim + 2 * array.pitch * direction,
                                              z_press, z_lift, resolution=0.1)
                    tip = (on[0] + 1) * array.pitch - np.dot(last - aim, direction)
                shift += (tip - np.dot(aim - array.origin, direction)) * direction
            self.machine.move(z=cfg['z_park'])
            self.machine.wait_moves()
        self.machine.say(f"[LRT] tip at about {shift.round(2).tolist()} from the toolhead (cells {touched})")
        return shift, z + 2 * cfg['step']

    # XY
    def tap(self, hop, xy, z_press, z_lift):
        '''Down onto `xy`, read, back up. Never moves sideways while pressing.'''
        self.machine.move(z=z_lift, speed=JOG_SPEED * 5)
        self.machine.move(float(xy[0]), float(xy[1]))
        self.machine.move(z=z_press, speed=JOG_SPEED)
        strengths = self.read(hop)
        self.machine.move(z=z_lift, speed=JOG_SPEED * 5)
        return strengths

    def last_response(self, hop, cell, start, end, z_press, z_lift, resolution=None):
        '''The last point from `start` (centre of `cell`) towards `end` (centre
        of its neighbour) where `cell` still responds.'''
        resolution = resolution or self.cfg['resolution']
        start, end = np.array(start, dtype=float), np.array(end, dtype=float)
        if not self.responds(self.tap(hop, start, z_press, z_lift), cell):
            raise FsrError(f"[LRT] cell {cell} of hop {hop} does not respond at its centre {start.round(2)}: check the array origin")
        if self.responds(self.tap(hop, end, z_press, z_lift), cell):
            raise FsrError(f"[LRT] cell {cell} of hop {hop} responds at its neighbour's centre {end.round(2)}: check the array origin")
        lo, hi = 0.0, 1.0
        length = float(np.linalg.norm(end - start))
        while (hi - lo) * length > resolution:
            mid = (lo + hi) / 2
            if self.responds(self.tap(hop, start + mid * (end - start), z_press, z_lift), cell):
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
        z_press = z_contact - self.cfg['press']
        z_lift = z_contact + 1.0
        with lifted_on_error(self.machine, self.cfg['z_park']):
            self.machine.move(z=self.cfg['z_park'])
            self.machine.move(float(a[0]), float(a[1]))
            a_off = self.last_response(hop, tuple(cell_a), a, b, z_press, z_lift)
            b_on = self.last_response(hop, tuple(cell_b), b, a, z_press, z_lift)
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

        def on(hop, row, col):
            '''The tip found on this array, and its contact z on (row, col).'''
            if hop not in contact:
                shift[hop], top = self.locate(hop, bed_z[(hop, row, col)], prior)
                contact[hop] = self.contact_z(hop, row, col, bed_z[(hop, row, col)], shift[hop], top, prior)
            return contact[hop]

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
        return {
            'z': z,
            'x': float(np.mean(points['x'])),
            'y': float(np.mean(points['y'])),
            'gaps': gaps,
            'tip': [float(v) for v in shift[cfg['z_cell'][0]]],
        }

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
