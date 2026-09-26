# Limn - tool alignment with two FSR arrays at right angles (BED_5)
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
#    The arrays are at right angles: one gives X, the other Y.
# A tool is compared with the reference tool (T4) on the same cells, so the
# array positions only need to be roughly right.
#
# The arrays run in matrix mode meanwhile: every cell every frame, so we also
# know they are alive. No frame for `alive` seconds, a press above
# `press_limit`, or no contact down to the floor: lift to park and stop.
import numpy as np

from .geometry import FsrArray
from .samples import FSR, S_MATRIX
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
        '''After a move: waits for it and for fresh frames -> {(row, col): strength}.'''
        self.machine.wait_moves()
        since = self.machine.now()
        self.machine.pause(self.cfg['settle'])
        while not self.samples.since(since, hop=hop, kind=FSR, state=S_MATRIX):
            if self.machine.now() - since > self.cfg['alive']:
                raise FsrError(f"[LRT] no frames from the FSR at hop {hop}")
            self.machine.pause(0.02)

        cells = {}
        for frame in self.samples.since(since, hop=hop, kind=FSR, state=S_MATRIX):
            for row, col, strength in frame.values:
                cells.setdefault((row, col), []).append(strength)
        strengths = {cell: float(np.median(v)) for cell, v in cells.items()}
        hardest = max(strengths.values(), default=0)
        if hardest >= self.cfg['press_limit']:
            raise FsrError(f"[LRT] pressing too hard on the FSR at hop {hop} ({hardest:.0f})")
        return strengths

    def responds(self, strengths, cell):
        return strengths.get(tuple(cell), 0) >= self.cfg['respond']

    # Z
    def contact_z(self, hop, row, col, bed_z):
        '''z where the tool starts to press on (row, col), median of `repeats`.
        bed_z: BLTouch z at that cell; the search stays within tool_z of it.'''
        cfg = self.cfg
        x, y = self.array(hop).center(row, col)
        low, high = cfg['tool_z']
        floor = bed_z + low
        z = bed_z + high + 1.0
        found = []
        with lifted_on_error(self.machine, cfg['z_park']):
            self.machine.move(z=cfg['z_park'])
            self.machine.move(x, y)
            self.machine.move(z=z)
            if self.responds(self.read(hop), (row, col)):
                raise FsrError(f"[LRT] already touching at z={z:.2f}, above the search window")
            for _ in range(cfg['repeats']):
                z = self._descend(hop, (row, col), z, cfg['step'], floor)
                z = self._back_off(hop, (row, col), z + 2 * cfg['step'])
                z = self._descend(hop, (row, col), z, cfg['fine_step'], floor)
                found.append(z)
                z = self._back_off(hop, (row, col), z + 2 * cfg['step'])
            self.machine.move(z=cfg['z_park'])
            self.machine.wait_moves()
        return float(np.median(found))

    def _descend(self, hop, cell, z, step, floor):
        while True:
            z -= step
            if z < floor:
                raise FsrError(f"[LRT] no contact down to z={floor:.2f}")
            self.machine.move(z=z, speed=JOG_SPEED)
            strengths = self.read(hop)
            if self.responds(strengths, cell):
                return z
            others = [c for c in strengths if self.responds(strengths, c)]
            if others:
                raise FsrError(f"[LRT] cell {others[0]} of hop {hop} responds instead of {cell}: check the array origin")

    def _back_off(self, hop, cell, z):
        self.machine.move(z=z, speed=JOG_SPEED)
        if self.responds(self.read(hop), cell):
            raise FsrError(f"[LRT] still touching after backing off to z={z:.2f}")
        return z

    # XY
    def tap(self, hop, xy, z_press, z_lift):
        '''Down onto `xy`, read, back up. Never moves sideways while pressing.'''
        self.machine.move(z=z_lift, speed=JOG_SPEED * 5)
        self.machine.move(float(xy[0]), float(xy[1]))
        self.machine.move(z=z_press, speed=JOG_SPEED)
        strengths = self.read(hop)
        self.machine.move(z=z_lift, speed=JOG_SPEED * 5)
        return strengths

    def last_response(self, hop, cell, start, end, z_press, z_lift):
        '''The last point from `start` (centre of `cell`) towards `end` (centre
        of its neighbour) where `cell` still responds.'''
        start, end = np.array(start, dtype=float), np.array(end, dtype=float)
        if not self.responds(self.tap(hop, start, z_press, z_lift), cell):
            raise FsrError(f"[LRT] cell {cell} of hop {hop} does not respond at its centre {start.round(2)}: check the array origin")
        if self.responds(self.tap(hop, end, z_press, z_lift), cell):
            raise FsrError(f"[LRT] cell {cell} of hop {hop} responds at its neighbour's centre {end.round(2)}: check the array origin")
        lo, hi = 0.0, 1.0
        length = float(np.linalg.norm(end - start))
        while (hi - lo) * length > self.cfg['resolution']:
            mid = (lo + hi) / 2
            if self.responds(self.tap(hop, start + mid * (end - start), z_press, z_lift), cell):
                lo = mid
            else:
                hi = mid
        return start + (lo + hi) / 2 * (end - start)

    def find_edge(self, edge, z_contact):
        '''edge: (hop, row, col_a, col_b) -> (edge point, gap width)'''
        hop, row, col_a, col_b = edge
        array = self.array(hop)
        a, b = array.center(row, col_a), array.center(row, col_b)
        z_press = z_contact - self.cfg['press']
        z_lift = z_contact + 1.0
        with lifted_on_error(self.machine, self.cfg['z_park']):
            self.machine.move(z=self.cfg['z_park'])
            self.machine.move(float(a[0]), float(a[1]))
            a_off = self.last_response(hop, (row, col_a), a, b, z_press, z_lift)
            b_on = self.last_response(hop, (row, col_b), b, a, z_press, z_lift)
            self.machine.move(z=self.cfg['z_park'])
            self.machine.wait_moves()
        return (a_off + b_on) / 2, float(np.linalg.norm(b_on - a_off))

    # Whole measurements
    def z_cells(self):
        '''Cells that need a BLTouch z: the z cell and the first cell of each edge.'''
        cells = [tuple(self.cfg['z_cell'])]
        for hop, row, col_a, _ in self.cfg['x_edges'] + self.cfg['y_edges']:
            if (hop, row, col_a) not in cells:
                cells.append((hop, row, col_a))
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

    def measure(self, bed_z):
        '''The docked tool: contact z on the z cell, and the X and Y edges.
        bed_z: {cell: BLTouch z} for z_cells().'''
        cfg = self.cfg
        self.matrix(True)
        try:
            hop, row, col = cfg['z_cell']
            z = self.contact_z(hop, row, col, bed_z[(hop, row, col)])
            contact = {hop: z}
            points, gaps = {'x': [], 'y': []}, []
            for axis, edges in (('x', cfg['x_edges']), ('y', cfg['y_edges'])):
                for edge in edges:
                    e_hop, e_row, e_col, _ = edge
                    if e_hop not in contact:
                        contact[e_hop] = self.contact_z(e_hop, e_row, e_col, bed_z[(e_hop, e_row, e_col)])
                    point, gap = self.find_edge(edge, contact[e_hop])
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
        }

    def calibrate(self):
        '''With the reference tool (T4). -> profile for the [limn] section.'''
        run = self.machine.gcode_run
        run("UNDOCK")
        run("G28")
        run("_CLEAR_OFFSETS")
        bed_z = {cell: self.bltouch_z(cell) for cell in self.z_cells()}
        run("_BUZZ_DOOP")

        run("T4")
        ref = self.measure(bed_z)
        tool_z = round(ref['z'] - bed_z[tuple(self.cfg['z_cell'])], 3)
        run(f"WRITE_TOOL_TAG DX=0 DY=0 DZ={tool_z:.3f}")
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
