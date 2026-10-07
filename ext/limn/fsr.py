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


class WrongCell(FsrError):
    '''The tip came down on another cell than the one aimed at, surely (twice over `sure`).'''
    def __init__(self, msg, hop, cell, found):
        super().__init__(msg)
        self.hop, self.cell, self.found = hop, tuple(cell), tuple(found)


HIGH_AT_REST = 40      # a cell this far over the sheet's median at rest, untouched, is faulty (BED_5's col 3: 75-100)


def judge_survey(result, cfg, hop):
    '''A survey (Fsr.survey) -> what to go by: {'faulty': [cell], 'weak': [cell], 'noise',
    'early', 'warnings': [str]}. Faulty: high at rest (with nothing on it), never touched,
    or another cell as strong while it is pressed. Weak: under half the median strength
    0.08mm in. `early` from the noise at rest, never under 30 nor near `respond`.'''
    cells = {tuple(c): v for c, v in result['cells'].items()}
    rest = {tuple(c): v for c, v in result['rest'].items() if tuple(c) in cells}       # (strengths: over rest)
    floor = float(np.median(list(rest.values()))) if rest else 0.0
    high = {c for c, v in rest.items() if v >= floor + HIGH_AT_REST}
    faulty = sorted(high | {c for c, v in cells.items() if v['z'] is None or not v['ok']})
    good = [v['s08'] for c, v in cells.items() if c not in faulty and v['s08']]
    median = float(np.median(good)) if good else 0.0
    weak = sorted(c for c, v in cells.items() if c not in faulty and (v['s08'] or 0) < 0.5 * median)
    spread = {tuple(c): v for c, v in (result.get('spread') or {}).items() if tuple(c) in cells}
    noise = max((v for c, v in (spread or rest).items() if c not in faulty), default=0.0)
    early = int(min(max(30, round(2 * noise + 20)), 0.8 * cfg['respond']))
    spec = next(a for a in cfg['arrays'] if a['hop'] == hop)
    used = {'z cell': [tuple(cfg['z_cell'][1:])]}
    for axis in ('x', 'y'):
        for h, a, b in cfg[f'{axis}_edges']:
            if h == hop:
                used[f'{axis} edge'] = [tuple(a), tuple(b)]
    warnings = []
    best = sorted((c for c in cells if c not in faulty and c not in weak), key=lambda c: -(cells[c]['s08'] or 0))
    for what, cs in used.items():
        bad = [c for c in cs if c in faulty or c in weak]
        if bad:
            warnings.append(f"the {what} uses {', '.join(map(str, bad))}: "
                            f"{'faulty' if any(c in faulty for c in bad) else 'weak'}; strongest: {best[:4]} (ext/limn/beds.py)")
    # The aim: where the reference pen's tip (the survey's) comes down on a good cell, mid
    # cell, none of its neighbours faulty. Other pens are ~1mm either way of it.
    aim = list(spec['aim'])
    shift = result.get('shift')
    if shift is not None:
        pitch = cfg['pitch']
        dr = float(np.dot(shift, spec['row_dir'])) / pitch
        dc = float(np.dot(shift, spec['col_dir'])) / pitch
        land = (spec['aim'][0] + dr, spec['aim'][1] + dc)
        near = lambda c: [(c[0] + i, c[1] + j) for i in (-1, 0, 1) for j in (-1, 0, 1) if (i, j) != (0, 0)]
        ok = [c for c in cells if c not in faulty and c not in weak and not any(n in faulty for n in near(c))]
        if ok:
            target = min(ok, key=lambda c: np.hypot(c[0] + 0.5 - land[0], c[1] + 0.5 - land[1]))
            aim = [round(target[0] + 0.5 - dr, 2), round(target[1] + 0.5 - dc, 2)]
        else:
            warnings.append("no good cell clear of faulty ones to aim at: the config's aim stays")
    return {'faulty': faulty, 'weak': weak, 'noise': noise, 'early': early, 'median': median,
            'warnings': warnings, 'shift': shift, 'aim': aim}


class Fsr:

    def __init__(self, machine, dock, samples, cfg):
        self.machine = machine
        self.dock = dock
        self.samples = samples
        self.cfg = cfg
        self.arrays = {a['hop']: a for a in cfg['arrays']}
        self.surface = None         # the array's bed mesh profile, see follow()
        self.depth = {}             # hop -> how far past contact this tool's taps press, see press_depth()
        self.press_cap = None       # mm the taps press at most past contact, None: cfg['press'] (ext/limn _fsr_hooks)
        self.verbose = False        # every tap on the console too, not only what each search found (VERBOSE=1)
        self.air = None             # readings in the air before a descent: what `early` rises from
        self.before_measure = None  # called before / after measuring a tool: the wipe
        self.after_measure = None   # between pens, see __init__.py _fsr_hooks

    def _boundary(self, hop, axis):
        '''The point between the two cells of the axis' first edge (cfg x_edges / y_edges).'''
        h, a, b = next(e for e in self.cfg[f'{axis}_edges'] if e[0] == hop)
        array = self.array(hop)
        return (np.asarray(array.center(*a)) + np.asarray(array.center(*b))) / 2

    def apply_survey(self, hop, judged):
        '''Go by a survey of this sheet (judge_survey): its faulty cells aren't read, its
        `early` instead of the config's. The config itself stays as it is.'''
        self.cfg = {**self.cfg, 'early': judged['early']}
        self.arrays = {**self.arrays, hop: {**self.arrays[hop], 'aim': tuple(judged.get('aim') or self.arrays[hop]['aim']),
                                            'faulty_cells': [tuple(c) for c in judged['faulty']]}}

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

    def read(self, hop, limit=True, raw=False):
        '''After a move: waits for it and for fresh frames -> {(row, col): strength},
        without the array's dead rows, faulty columns and faulty cells (a survey's;
        raw: every cell). limit: a press over press_limit stops us.'''
        self.machine.wait_moves()
        since = self.machine.now()
        self.machine.pause(self.cfg['settle'])
        while not self.samples.since(since, hop=hop, kind=FSR, state=S_MATRIX):
            if self.machine.now() - since > self.cfg['alive']:
                raise FsrError(f"[LRT] no frames from the FSR at hop {hop}: {self.heard(since)}")
            self.machine.pause(0.02)

        spec = self.arrays[hop]
        dead, faulty = (), ()
        bad = set()
        if not raw:
            dead, faulty = spec.get('dead_rows', ()), spec.get('faulty_cols', ())
            bad = {tuple(c) for c in spec.get('faulty_cells', ())}
        cells = {}
        for frame in self.samples.since(since, hop=hop, kind=FSR, state=S_MATRIX):
            for row, col, strength in frame.values:
                if row not in dead and col not in faulty and (row, col) not in bad:
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

    def rise(self, strengths):
        '''The most any cell reads over the baseline taken in the air before this descent
        (self.air): the sheet's own level drifts by tens, cell by cell (2026-10-07).'''
        air = self.air or {}
        return max((v - air.get(c, 0.0) for c, v in strengths.items()), default=0.0)

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
            here = self.read(hop)
            if (row, col) in self.touched(here, hop):               # other cells: a reading in the air
                raise FsrError(f"[LRT] already touching at z={z:.2f}, above the search window")
            self.air = here                         # the baseline the coarse steps rise from
            # Coarse steps only while nothing is known of the contact (no `top` from
            # locate): a coarse step goes up to `step` past it before it is seen. Then
            # fine steps from just above it (eyed on the plotter, 2026-10-07: the
            # repeats' coarse descents pressed the pen in for nothing).
            for i in range(cfg['repeats']):
                if i == 0 and top is None:
                    z, _ = self._descend(hop, (row, col), z, cfg['step'], floor, early=True)
                    z = self._back_off(hop, z + cfg['back_off'], (row, col))
                z, _ = self._descend(hop, (row, col), z, cfg['fine_step'], floor)
                found.append(z)
                self.machine.say(f"[LRT] contact {i + 1}/{cfg['repeats']} on {(row, col)} at X{x:.3f} Y{y:.3f}: "
                                 f"z={z:.3f}")
                z = self._back_off(hop, z + cfg['back_off'], (row, col))
            self.machine.move(z=cfg['z_park'])
            self.machine.wait_moves()
        z = float(np.median(found))
        self.machine.say(f"[LRT] contact on {(row, col)}: z={z:.3f} (median, spread {max(found) - min(found):.3f})")
        return z

    def touched(self, strengths, hop):
        '''The cells that respond, strongest first. A cell in one of the array's
        crosstalk_rows only when no other row of its column responds, or when
        it is a real press: a press elsewhere in the column lifts it too.'''
        cells = [c for c in strengths if self.responds(strengths, c)]
        crosstalk = self.arrays[hop].get('crosstalk_rows', ())
        cells = [c for c in cells if c[0] not in crosstalk or strengths[c] >= self.cfg['sure']
                 or not any(o[1] == c[1] and o[0] != c[0] for o in cells)]
        return sorted(cells, key=lambda c: -strengths[c])

    def _descend(self, hop, cell, z, step, floor, early=False):
        '''Down until `cell` responds (None: any cell) -> (z, the cells that do).
        early (the coarse steps): back as soon as any cell reads `early`, well over the
        sheet's noise and well before `respond`: a fine tip registers late, and a coarse
        step on to `respond` pressed it in deeper than the taps ever do (2026-10-07).
        Another cell responding: on down only `wrong_depth` mm more (crosstalk can lead
        at first touch), then stop: the tip is pressing elsewhere, and going on down to
        the floor would dig it in (a fineliner off by a cell, LRT_FSR_Z, 2026-10-07).'''
        cfg = self.cfg
        elsewhere = None                # z where another cell first responded
        while True:
            z -= step
            if z < floor:
                raise FsrError(f"[LRT] no contact down to z={floor:.2f}: is the tool over the array at hop {hop}?")
            self.machine.move(z=z, speed=JOG_SPEED)
            strengths = self.read(hop)
            touched = self.touched(strengths, hop)
            if touched and (cell is None or tuple(cell) in touched):
                return z, touched
            if early and self.rise(strengths) >= cfg.get('early', cfg['respond']):
                return z, touched       # coarse: something presses, the fine steps find where
            # At first touch the crosstalk can lead the pressed cell: only a
            # real press elsewhere means the tip is not over `cell`.
            if touched and strengths[touched[0]] >= cfg['sure']:
                # One reading isn't enough to stop on: read again where it is
                strengths = self.read(hop)
                touched = self.touched(strengths, hop)
                if touched and tuple(cell) in touched:
                    return z, touched
                if touched and strengths[touched[0]] >= cfg['sure']:
                    raise WrongCell(f"[LRT] cell {touched[0]} of hop {hop} responds instead of {cell} "
                                    f"({self.top(strengths)}): check the array origin", hop, cell, touched[0])
            if touched:
                elsewhere = z if elsewhere is None else elsewhere
                if elsewhere - z >= cfg.get('wrong_depth', 0.2) - 1e-9:
                    raise FsrError(f"[LRT] cell {touched[0]} of hop {hop} responds, not {cell} ({self.top(strengths)}): "
                                   f"the tip is over another cell, stopped {elsewhere - z:.2f}mm past its first "
                                   f"touch. LRT_FSR_MEASURE finds where the tip is first")

    def _back_off(self, hop, z, cell=None):
        '''Up to z, where nothing may press any more: `cell`, or with none any cell
        as hard as `sure` (weaker is a reading in the air, see locate).'''
        self.machine.move(z=z, speed=JOG_SPEED)
        strengths = self.read(hop)
        touched = self.touched(strengths, hop)
        pressing = tuple(cell) in touched if cell else bool(touched) and strengths[touched[0]] >= self.cfg['sure']
        if pressing:
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
            here = self.read(hop)
            if self.touched(here, hop):
                raise FsrError(f"[LRT] already touching at z={z:.2f}, above the search window")
            self.air = here                         # the baseline the coarse steps rise from
            # Coarse, at three spots by turns: a tip in the dead zone between cells reads
            # nothing however deep it goes (to the floor: a fineliner, 2026-10-07). Offset
            # by (0, 0), (1/2, 1/4), (1/4, 1/2) of a cell: whatever border lines a tip is on,
            # not all three are on one (two spots could be: a row border and a column border).
            # Towards the array's middle (lower rows and cols from BED_5's aim): not off its end.
            rd, cd = -np.asarray(array.row_dir, float), -np.asarray(array.col_dir, float)
            spots = [aim, aim + array.pitch * (0.5 * rd + 0.25 * cd), aim + array.pitch * (0.25 * rd + 0.5 * cd)]
            z, aim = self._descend_spots(hop, spots, z, cfg['step'], floor)
            while True:
                z = self._back_off(hop, z + cfg['back_off'])
                z, first = self._descend(hop, None, z, cfg['fine_step'], floor)
                self.machine.say(f"[LRT] first contact at X{aim[0]:.3f} Y{aim[1]:.3f}: z={z:.3f} on {first[:3]}")
                # Only enough to tell which cell: a weak one (BED_5's (2, 4) tops out at ~220)
                # went the whole press for press_strength, 0.16mm past first touch (simulated)
                self.depth[hop] = self.press_depth(hop, None, z, cfg.get('locate_strength'))
                z_press, z_lift = z - self.depth[hop], z + 1.0
                # Which cell: pressed in, where the crosstalk has fallen behind.
                strengths = self.tap(hop, aim, z_press, z_lift, aim)
                touched = self.touched(strengths, hop)
                if touched:
                    break
                # A reading in the air (a bent 0.05 liner, 2026-09-30): the tip isn't
                # down yet. On down from where it pressed, to the floor at most.
                self.machine.say(f"[LRT] a false start at z={z:.2f}, nothing pressed in at {aim.round(2)} "
                                 f"({self.top(strengths)}): going on down")
                z = z_press
                self.machine.move(z=z, speed=JOG_SPEED)
                z, _ = self._descend(hop, None, z, cfg['step'], floor, early=True)
            # Along each axis the tip leaves the strongest cell where it reaches
            # the cell's far side, within two cells. On an edge, that is the edge.
            # (Two cells responding is no edge to go by: the column's crosstalk
            # can come close to a tip split between two cells, 2026-09-28.)
            # Not towards a dead row: pressed, it lifts its column's other rows, so the
            # cell seems to go on responding over it (BED_5's row 3: locate put the tip
            # 1.3mm too far in X, 2026-09-29 and 10-07). Then towards the near side.
            # The search reaches up to two cells over: both must read (in the array, not a
            # dead row or a faulty column), or it goes the other way.
            cell = touched[0]
            shift = np.zeros(2)
            spec = self.arrays[hop]
            for axis, direction in ((1, array.col_dir), (0, array.row_dir)):
                n = array.rows if axis == 0 else array.cols
                bad = spec.get('dead_rows', ()) if axis == 0 else spec.get('faulty_cols', ())
                blocked = lambda i: not 0 <= i < n or i in bad
                sign = -1 if blocked(cell[axis] + 1) or blocked(cell[axis] + 2) else 1
                last = self.last_response(hop, cell, aim, aim + sign * 2 * array.pitch * direction,
                                          z_press, z_lift, resolution=0.1, at=aim)
                edge = (cell[axis] + 1) * array.pitch if sign > 0 else cell[axis] * array.pitch
                tip = edge - np.dot(last - aim, direction)
                shift += (tip - np.dot(aim - array.origin, direction)) * direction
            self.machine.move(z=cfg['z_park'])
            self.machine.wait_moves()
        self.machine.say(f"[LRT] tip at about {shift.round(2).tolist()} from the toolhead (cells {touched}), "
                         f"taps press {self.depth[hop]:.2f}mm")
        return shift, z + cfg['back_off']

    def _descend_spots(self, hop, points, z, step, floor):
        '''Coarse steps down, at each of `points` by turns, lifted between: -> (z, the point
        where something presses). Like _descend(early=True), at several spots.'''
        cfg = self.cfg
        lift = cfg['back_off']
        while True:
            z -= step
            if z < floor:
                raise FsrError(f"[LRT] no contact down to z={floor:.2f}: is the tool over the array at hop {hop}?")
            for p in points:
                self.machine.move(z=z + lift, speed=JOG_SPEED * 5)
                self.machine.move(float(p[0]), float(p[1]))
                self.machine.move(z=z, speed=JOG_SPEED)
                strengths = self.read(hop)
                if self.touched(strengths, hop) or self.rise(strengths) >= cfg.get('early', cfg['respond']):
                    return z, np.asarray(p, dtype=float)

    def press_depth(self, hop, cell, z, target=None):
        '''How far past contact the taps press, the tip at contact (z) over
        `cell` (None: the strongest): until it reads `press_strength`, `press`
        at most. A felt tip gets there in ~0.05mm, a fine one needs ~0.3;
        deeper only adds force: a Stabilo read ~460 at 0.05mm and ~670 at
        0.3mm, and 0.3mm taps left marks on the sheet (2026-09-29). press_cap,
        when set, instead of `press`: no deeper than the pen presses plotting.'''
        cfg = self.cfg
        most = self.press_cap or cfg['press']
        target = target or cfg.get('press_strength')
        if not target:
            return most
        depth = 0.0
        while depth < most - 1e-9:
            depth = round(min(depth + cfg['fine_step'], most), 3)
            self.machine.move(z=z - depth, speed=JOG_SPEED)
            strengths = self.read(hop)
            strength = strengths.get(tuple(cell), 0) if cell else max(strengths.values(), default=0)
            if strength >= target:
                break
        return depth

    def depth_on(self, hop, cell, z, shift=(0, 0)):
        '''press_depth() with the tip over `cell`, from its contact z.'''
        x, y = self.array(hop).center(*cell) - np.asarray(shift)
        with lifted_on_error(self.machine, self.cfg['z_park']):
            self.machine.move(z=z + self.cfg['back_off'], speed=JOG_SPEED * 5)
            self.machine.move(float(x), float(y))
            self.machine.move(z=z, speed=JOG_SPEED)
            depth = self.press_depth(hop, cell, z)
            self.machine.move(z=z + self.cfg['back_off'], speed=JOG_SPEED * 5)
        self.machine.say(f"[LRT] on {cell} the taps press {depth:.2f}mm")
        return depth

    # The sheet, cell by cell (LRT_FSR_SURVEY): after a swap, what the config can't know
    def survey(self, hop, bed_z, depth=0.08, step=0.02, rest_s=2.0):
        # bed_z: {cell: BLTouch z} for z_cells(), as for measure()
        '''Every cell of the array (but its dead rows) pressed by the carried tool, a felt
        tip: -> {'rest': {cell: median at rest}, 'cells': {cell: {...}}, 'shift': tip}.
        At rest first, untouched. Then where the tip is (locate), and over each cell's
        centre down in `step`s until it reads `early` over its rest (first touch), on to
        `depth` past that: its rise over rest, and the strongest other cell's, at each step.
        Cells high at rest (a faulty column) don't count as answering.'''
        cfg = self.cfg
        array = self.array(hop)
        rows = [r for r in range(array.rows) if r not in self.arrays[hop].get('dead_rows', ())]
        out = {'rest': {}, 'cells': {}}
        self.matrix(True)
        try:
            # At rest: the carried tool parked over the paper, clear of the sheet
            self.machine.move(z=cfg['z_park'])
            self.machine.move(*cfg['clean']['park'])
            frames = {}
            start = self.machine.now()
            while self.machine.now() - start < rest_s:
                for c, v in self.read(hop, limit=False, raw=True).items():
                    frames.setdefault(c, []).append(v)
            out['rest'] = {c: float(np.median(v)) for c, v in frames.items()}
            out['spread'] = {c: float(np.percentile(v, 90) - np.percentile(v, 10)) for c, v in frames.items()}
            levels = out['rest']
            floor_rest = float(np.median([v for c, v in levels.items() if c[0] in rows])) if levels else 0.0
            high = {c for c, v in levels.items() if v >= floor_rest + HIGH_AT_REST}
            # Where the tip is, exactly: from the edges, as a calibration has it (locate's guess
            # was 1.65mm out on the plotter, 2026-10-07: every cell pressed near its border)
            m = self.measure(bed_z)
            self.matrix(True)                       # measure() turned it off
            shift = np.array([self._boundary(hop, 'x')[0] - m['x'], self._boundary(hop, 'y')[1] - m['y']])
            top = m['z'] + cfg['back_off']
            out['shift'] = [float(v) for v in shift]
            self.machine.say(f"[LRT][Survey] the tip is {shift.round(3).tolist()} from the toolhead (from the edges)")
            early = cfg.get('survey_touch', 30)     # over rest: a weak cell's first touch too, not 0.05mm on
            for row in rows:
                for col in range(array.cols):
                    cell = (row, col)
                    x, y = array.center(row, col) - shift
                    z = top + max(self.follow((x, y), array.point(*self.arrays[hop]['aim'])), 0.0) + 0.2
                    floor = z - 0.8                  # the sheet is flat to ~0.15: never further
                    steps, first = [], None
                    with lifted_on_error(self.machine, cfg['z_park']):
                        self.machine.move(z=z + 0.4, speed=JOG_SPEED * 5)
                        self.machine.move(float(x), float(y))
                        self.machine.move(z=z, speed=JOG_SPEED)
                        # Its own baseline, here in the air just before: the sheet's drifts by tens
                        # from minute to minute and cell to cell (2026-10-07: everything 'touched' in
                        # the air against a rest taken a minute before)
                        here = [self.read(hop, limit=False, raw=True) for _ in range(3)]
                        base = {c: float(np.median([h.get(c, 0.0) for h in here])) for c in here[0]}
                        while z > floor and (first is None or first - z < depth - 1e-9):
                            z = round(z - step, 4)
                            self.machine.move(z=z, speed=JOG_SPEED)
                            s = self.read(hop, limit=False, raw=True)
                            live = {c: v - base.get(c, 0.0) for c, v in s.items() if c[0] in rows}
                            mine = live.get(cell, 0.0)
                            other = max(((c, v) for c, v in live.items() if c != cell and c not in high),
                                        key=lambda cv: cv[1], default=(None, 0.0))
                            if first is None and mine >= early:           # its own rise: nobody else's
                                first = z
                            if first is not None:
                                steps.append([round(first - z, 3), mine, list(other[0]) if other[0] else None, other[1]])
                            if max(s.values(), default=0) >= cfg['press_limit'] * 0.85:
                                break
                        self.machine.move(z=z + 0.6, speed=JOG_SPEED * 5)
                    at = lambda d: next((m_ for dd, m_, _, _ in steps if dd >= d - 1e-6), None)
                    deep = [(m_, o) for dd, m_, _, o in steps if dd >= 0.04 - 1e-6]
                    # Another cell answers: clearly stronger than this one at most of its deeper steps
                    ok = bool(deep) and 2 * sum(o > 1.1 * m_ for m_, o in deep) < len(deep)
                    info = {'z': first, 'steps': steps, 's04': at(0.04), 's08': at(0.08), 'ok': ok,
                            'rest': out['rest'].get(cell, 0.0), 'air': base.get(cell, 0.0), 'at': [float(x), float(y)]}
                    out['cells'][cell] = info
                    self.machine.say(
                        f"[LRT][Survey] {cell} at X{x:.3f} Y{y:.3f}: "
                        + (f"touch z={first:.3f}, +0.04: {info['s04']:.0f}, +0.08: {info['s08'] or 0:.0f}"
                           if first is not None else "nothing")
                        + f", rest {info['rest']:.0f}, in the air {info['air']:.0f}"
                        + ("" if ok else f" (another cell answers: {steps[-1][2] if steps else '-'})"))
            self.machine.move(z=cfg['z_park'])
        finally:
            self.matrix(False)
        return out

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
        s = self.tap(hop, start, z_press, z_lift, at)
        if not self.responds(s, cell):
            raise FsrError(f"[LRT] cell {cell} of hop {hop} does not respond at its centre {start.round(2)} "
                           f"({self.top(s) or 'nothing'}): check the array origin")
        s = self.tap(hop, end, z_press, z_lift, at)
        if self.responds(s, cell):
            raise FsrError(f"[LRT] cell {cell} of hop {hop} responds at its neighbour's centre {end.round(2)} "
                           f"({self.top(s)}): check the array origin")
        lo, hi = 0.0, 1.0
        length = float(np.linalg.norm(end - start))
        taps = 2
        while (hi - lo) * length > resolution:
            mid = (lo + hi) / 2
            p = start + mid * (end - start)
            s = self.tap(hop, p, z_press, z_lift, at)
            taps += 1
            if self.verbose:
                self.machine.say(f"[LRT]   tap at X{p[0]:.3f} Y{p[1]:.3f} z={z_press:.3f}: {self.top(s)}"
                                 f"{' (in)' if self.responds(s, cell) else ''}")
            if self.responds(s, cell):
                lo = mid
            else:
                hi = mid
        last = start + (lo + hi) / 2 * (end - start)
        self.machine.say(f"[LRT] {cell} from X{start[0]:.3f} Y{start[1]:.3f} towards X{end[0]:.3f} Y{end[1]:.3f}: "
                         f"responds to X{last[0]:.3f} Y{last[1]:.3f} ({taps} taps at z={z_press:.3f})")
        return last

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
                # top is just above contact at the aim: where the sheet is higher, higher
                array = self.array(hop)
                top += max(self.follow(array.center(row, col), array.point(*self.arrays[hop]['aim'])), 0.0)
                # locate's tip is a few tenths, now and then a mm or two off (2026-10-07: Y 3.87
                # for 2.13): came down on a neighbour instead, the tip is that much further
                # over. Aim again, twice at most.
                for tries in range(3):
                    try:
                        contact[hop] = self.contact_z(hop, row, col, bed_z[(hop, row, col)], shift[hop], top, prior)
                        # The taps' depth again, on this cell: locate's first cell may be a weak one
                        # (BED_5's (2, 4) tops out at ~220, never press_strength: the taps all went
                        # the whole press; (1, 1) has 450 ~0.07mm past first touch, 2026-10-07)
                        self.depth[hop] = self.depth_on(hop, (row, col), contact[hop], shift[hop])
                        break
                    except WrongCell as e:
                        if tries == 2:
                            raise
                        moved = array.center(*e.found) - array.center(row, col)
                        shift[hop] = np.asarray(shift[hop], float) + moved
                        self.machine.say(f"[LRT] came down on {e.found}, not {(row, col)}: the tip is about "
                                         f"{shift[hop].round(2).tolist()} from the toolhead, aiming again")
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
