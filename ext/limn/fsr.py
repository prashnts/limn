# Limn - tool alignment with an FSR array (BED_5)
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# The sheet answers how hard, and in which column, well: a tap again on one spot
#    reads the same to 2%, deeper always reads more. Which cell of a row or a
#    column is pressed it answers badly: crosstalk up the column and along the
#    row, a cell's reading halving within a mm. So no decision here hangs on one
#    reading of one cell against a threshold (notebooks/act-9-fsr-rework.md).
# Z: the tool is jogged down, coarse then fine steps, until the sheet rises
#    under it, whichever cell, and goes on rising (not a reading in the air).
#    The FSR is too slow for the probe endstop, so we move and look ourselves,
#    with a floor below which we never go.
# XY: taps across the border of two cells, each judged by the second cell's
#    share of the two; the border is where the fewest taps disagree, with how
#    sure that is. An edge between cols gives one axis, between rows the other.
# Where the tip is: first contact at the array's `aim`, and the cell pressed
#    there: the tip to half a cell, which the edges' sweeps reach either way.
#    Off the array nothing responds: down to the floor, up, and stop.
# A measurement too unsure (sigma over `max_sigma`) writes no tag: better none
# than a wrong one.
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


def border(taps, floor, lead=0.9):
    '''taps: {t: (a, b, top)}, the rise of two neighbouring cells and of the strongest cell at
    points t (mm) along a line from a into b -> (t0, gap, sigma, wrong, ends), or None without a
    clear border. A tap is on b's side when b has more than half of a + b. It votes only when
    a + b reaches `floor` (in the dead zone between the cells neither does) and one of them is
    at least `lead` of the strongest: the tip is on one of them, not on a third cell lifting
    both (rows 0-1 pressed lift row 3 over row 2, 2026-10-07; a row lifted by 0.73 of its
    pressed cell, 2026-09-29, makes the two even), and the two are more than (1 - lead) apart:
    two even cells say nothing of which side the tip is on (lifted alike by a pressed cell that
    isn't read, BED_5's old column 3; or a tip right on the border). A tap that doesn't vote is
    lost, not counted wrong. The border splits the votes leaving the fewest on the wrong side (`wrong`), at most
    a quarter of them, at least two on each side.
    t0 is halfway between where a's side ends and b's begins, each known to lie between a
    voting tap and the next tap; gap is how far apart they are. sigma: from those two spans,
    the spread of equally good splits, and the taps on the wrong side, each as far off as it
    lies from t0. ends: the two spans, ((from, to) of a's end, of b's), for taps to narrow them.'''
    ts = sorted(taps)
    floor = max(floor, 0.3 * max((a + b for a, b, _ in taps.values()), default=0.0))
    votes = [(t, b / (a + b)) for t, (a, b, top) in sorted(taps.items())
             if a + b >= floor and max(a, b) >= lead * top and abs(a - b) >= (1 - lead) * max(a, b)]
    sides = [r > 0.5 for _, r in votes]
    n = len(votes)
    if sum(sides) < 2 or n - sum(sides) < 2:
        return None
    costs = [sum(sides[:k]) + sides[k:].count(False) for k in range(1, n)]
    best = min(costs)
    if best > 0.25 * n:
        return None
    ks = [k for k, c in zip(range(1, n), costs) if c == best]
    k = ks[len(ks) // 2]
    last_a, first_b = votes[k - 1][0], votes[k][0]
    end_a = (last_a, ts[ts.index(last_a) + 1])          # a's side ends after its last vote, before the next tap
    end_b = (ts[ts.index(first_b) - 1], first_b)
    lo, hi = sum(end_a) / 2, sum(end_b) / 2
    t0 = (lo + hi) / 2
    var = ((end_a[1] - end_a[0]) ** 2 + (end_b[1] - end_b[0]) ** 2) / 48
    var += ((votes[ks[-1]][0] - votes[ks[0] - 1][0]) / 2) ** 2 / 3 if len(ks) > 1 else 0.0
    wrong = [t for (t, _), on_b in zip(votes, sides) if on_b != (t > t0)]
    var += sum((t - t0) ** 2 for t in wrong) / n
    return t0, hi - lo, float(np.sqrt(var)), len(wrong), (end_a, end_b)


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

    def map_sheet(self, hop, bed_z, step=1.25, margin=1.0, rise=40.0, depth=0.02, tip=(0.0, 0.0)):
        '''The sheet spot by spot (LRT_FSR_MAP, fsr_map.py): a grid `step` apart over the array and
        `margin` round it, in tip coordinates (`tip`: where the carried tool's tip is from the
        toolhead; (0, 0): toolhead coordinates). The sheet is found once at the aim; at each spot
        down from where the mesh puts it, in 0.01 steps, until a cell rises `rise` over its
        reading in the air, then `depth` deeper: every cell's rise there. A spot where nothing
        answers (the margin, a dead cell) goes 0.06 under where the last touch and the mesh put
        the sheet, no further. -> [points].'''
        cfg = self.cfg
        array = self.array(hop)
        tip = np.asarray(tip, float)
        self.surface = self.machine.mesh_profile(cfg['surface_mesh']) if cfg.get('surface_mesh') else None
        corners = np.array([array.point(r, c) for r in (0, array.rows) for c in (0, array.cols)])
        lo, hi = corners.min(axis=0) - margin, corners.max(axis=0) + margin
        aim = array.point(*self.arrays[hop]['aim'])
        floor, z = self.window(bed_z)
        points = []
        with lifted_on_error(self.machine, cfg['z_park']):
            # The sheet, once: coarse then fine, at whichever of a few spots across the array
            # answers first (a dead column under the aim would be pressed in to the floor)
            spots = [aim] + [array.center(r, c) for r, c in ((1, 1), (2, 2), (1, 6)) if r < array.rows and c < array.cols]
            self.machine.move(z=cfg['z_park'])
            self.machine.move(*(spots[0] - tip))
            self.machine.move(z=z)
            self.baseline(hop, z)
            # half the coarse step: a spot on a dead cell is pressed until another answers
            z, at = self._descend_spots(hop, [s - tip for s in spots], z, cfg['step'] / 2, floor)
            aim = at + tip
            z = self._back_off(hop, z + cfg['back_off'])
            # its first touch (a clear rise), not where a cell responds: the spots start from it
            z0, _ = self._descend(hop, z, cfg['fine_step'], floor, early=True)
            self.machine.say(f"[LRT][Map] the sheet at X{aim[0]:.3f} Y{aim[1]:.3f}: z={z0:.3f}")
            ys = np.arange(hi[1], lo[1] - 1e-9, -step)
            xs = np.arange(lo[0], hi[0] + 1e-9, step)
            ref = (z0, aim)             # the last spot touched: the next is predicted from it, the mesh's slope
            for j, y in enumerate(ys):
                line = []
                for x in (xs if j % 2 == 0 else xs[::-1]):
                    pred = ref[0] + self.follow((x, y), ref[1])
                    z = pred + 0.05
                    self.machine.move(z=z + 0.5, speed=JOG_SPEED * 5)
                    self.machine.move(float(x - tip[0]), float(y - tip[1]))
                    self.machine.move(z=z, speed=JOG_SPEED)
                    air = self.read(hop, limit=False, raw=True)
                    touch, cells = None, {}
                    while z > pred - 0.06:      # a spot that never answers (a dead cell) isn't pressed in
                        z = round(z - 0.01, 4)
                        self.machine.move(z=z, speed=JOG_SPEED)
                        s = self.read(hop, limit=False, raw=True)
                        up = {c: v - air.get(c, 0.0) for c, v in s.items()}
                        if max(s.values(), default=0) >= cfg['press_limit'] or max(up.values(), default=0) >= rise:
                            touch = z
                            ref = (z, np.array([x, y]))
                            self.machine.move(z=z - depth, speed=JOG_SPEED)
                            s = self.read(hop, limit=False, raw=True)
                            cells = {c: round(v - air.get(c, 0.0), 1) for c, v in s.items() if v - air.get(c, 0.0) > 10}
                            break
                    self.machine.move(z=z + 0.5, speed=JOG_SPEED * 5)
                    points.append({'xy': (round(float(x), 3), round(float(y), 3)), 'touch': touch, 'cells': cells})
                    best = max(cells.items(), key=lambda kv: kv[1], default=None)
                    line.append(f"{best[0][0]},{best[0][1]}" if best and best[1] >= cfg['respond'] else '-')
                self.machine.say(f"[LRT][Map] Y{y:7.2f}: " + ' '.join(f'{v:>3}' for v in (line if j % 2 == 0 else line[::-1])))
            self.machine.move(z=cfg['z_park'])
            self.machine.wait_moves()
        return points

    def refine_origin(self, hop, points, coarse, tip=(0.0, 0.0), respond=None):
        '''The array's origin to a few hundredths: the coarse map's (`coarse`, tip coordinates)
        is only good to about half its step, its spots fixed against the cells. Edge searches
        (find_edge, the calibration's) across two row borders and two column borders between
        cells that answered, near the middle -> (origin, [edges found]), None if too few.'''
        from .fsr_map import strongest
        respond = respond or self.cfg['respond']
        array = self.array(hop)
        spec = self.arrays[hop]
        row_dir, col_dir = np.asarray(spec['row_dir'], float), np.asarray(spec['col_dir'], float)
        delta = np.asarray(coarse, float) - array.origin    # where the sheet is against the config
        shift = np.asarray(tip, float) - delta              # aims the config's cells at the sheet's
        answered = {}
        for p in points:
            s = strongest(p['cells'], respond)
            if s and p['touch'] is not None:
                answered.setdefault(s[0], []).append(p['touch'])
        good = {c for c, v in answered.items() if len(v) >= 2}
        mid = ((array.rows - 1) / 2, (array.cols - 1) / 2)
        near = lambda c: abs(c[0] - mid[0]) + abs(c[1] - mid[1])
        pairs = {'x': [], 'y': []}
        for (r, c) in sorted(good, key=near):
            if (r + 1, c) in good and len(pairs['x']) < 2 and all(e[1][1] != c for e in pairs['x']):
                pairs['x'].append((hop, (r, c), (r + 1, c)))
            if (r, c + 1) in good and len(pairs['y']) < 2 and all(e[1][0] != r for e in pairs['y']):
                pairs['y'].append((hop, (r, c), (r, c + 1)))
        if not pairs['x'] or not pairs['y']:
            return None, []
        ox, oy, found = [], [], []
        self.depth.pop(hop, None)
        for axis, edges in pairs.items():
            for edge in edges:
                _, a, b = edge
                z = float(np.median(answered[a]))
                point, gap, _ = self.find_edge(edge, z, shift)
                tip_point = point + np.asarray(tip, float)
                found.append((edge, tip_point.round(3).tolist(), round(gap, 3)))
                # the border between a and b: origin + pitch * ((col + 0.5) col_dir + (row + 0.5) row_dir) +- pitch/2
                k = (b[0] if axis == 'x' else b[1])
                border = (np.asarray(row_dir) if axis == 'x' else np.asarray(col_dir)) * k * array.pitch
                o = tip_point - border
                (ox if axis == 'x' else oy).append(o)
                self.machine.say(f"[LRT][Map] {axis} border {a}|{b}: X{tip_point[0]:.3f} Y{tip_point[1]:.3f} (gap {gap:.2f})")
        # each border pins the origin along its own axis only
        ax = int(np.argmax(np.abs(row_dir)))
        ay = int(np.argmax(np.abs(col_dir)))
        origin = np.asarray(coarse, float).copy()
        origin[ax] = float(np.mean([o[ax] for o in ox]))
        origin[ay] = float(np.mean([o[ay] for o in oy]))
        return origin.round(3).tolist(), found

    def _roomier(self, hop, axis, at):
        '''+1 or -1: the way along rows (axis 0) or cols (1) from `at` (in cells) with more
        room before the array's end, a dead row or a faulty column.'''
        array, spec = self.array(hop), self.arrays[hop]
        n = array.rows if axis == 0 else array.cols
        bad = set(spec.get('dead_rows', ()) if axis == 0 else spec.get('faulty_cols', ()))
        bad |= {c[axis] for c in spec.get('faulty_cells', ())}
        up = min([n] + [i for i in bad if i > at - 1e-9]) - at
        down = at - max([0] + [i + 1 for i in bad if i + 1 < at + 1e-9])
        return 1 if up >= down else -1

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
        if not raw and self.air is not None:
            # Over the descent's baseline in the air: a cell's own level (a preload, the
            # toolhead over the sheet) isn't a press (the new sheet's (3, 0) rests at 80-130
            # and row 3 reads 30-50 with the pen above it: a 'touch' 4mm up, 2026-10-07)
            strengths = {c: max(0.0, v - self.air.get(c, 0.0)) for c, v in strengths.items()}
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
        '''The most any cell reads over the baseline taken in the air before this descent:
        read() gives them so (self.air). The sheet's own level drifts by tens, cell by cell.'''
        return max(strengths.values(), default=0.0)

    def baseline(self, hop, z):
        '''The readings in the air here, before a descent: what the cells rise from (self.air).
        Already pressing firmly (`sure`): not in the air, stop.'''
        self.air = None
        here = self.read(hop)
        if max(here.values(), default=0) >= self.cfg['sure']:
            raise FsrError(f"[LRT] already touching at z={z:.2f}, above the search window ({self.top(here)})")
        self.air = here

    def responds(self, strengths, cell, level=None):
        '''Over `respond` (or `level`), and close to the strongest cell: a press also lifts
        the other rows of its column a little (crosstalk), row 3 a lot.'''
        s = strengths.get(tuple(cell), 0)
        return s >= (level or self.cfg['respond']) and s >= self.cfg['dominance'] * max(strengths.values(), default=0)

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
        '''z where the tool starts to press on the sheet over (row, col) -> (z, sigma): the
        median of `repeats`, sigma half their spread (0.01 at least), `off_cell` more when
        another cell answered first: the tip touched all the same, only that cell's gain
        differs (a few hundredths in where it crosses `respond`, the ladders of 2026-10-07).
        bed_z: BLTouch z at that cell; the search stays within tool_z of it.
        shift: where the tip sits off the toolhead, as far as we know (locate).
        top: start there instead of above the window. prior: see window().'''
        cfg = self.cfg
        x, y = self.array(hop).center(row, col) - np.asarray(shift)
        floor, z = self.window(bed_z, prior)
        z = z if top is None else top
        found, on = [], []
        with lifted_on_error(self.machine, cfg['z_park']):
            self.machine.move(z=cfg['z_park'])
            self.machine.move(float(x), float(y))
            self.machine.move(z=z)
            self.baseline(hop, z)                   # what the cells rise from
            # Coarse steps only while nothing is known of the contact (no `top` from
            # locate): a coarse step goes up to `step` past it before it is seen. Then
            # fine steps from just above it (eyed on the plotter, 2026-10-07: the
            # repeats' coarse descents pressed the pen in for nothing).
            for i in range(cfg['repeats']):
                if i == 0 and top is None:
                    z, _ = self._descend(hop, z, cfg['step'], floor, early=True)
                    z = self._back_off(hop, z + cfg['back_off'])
                z, touched = self._descend(hop, z, cfg['fine_step'], floor)
                found.append(z)
                on.append(touched[0])
                self.machine.say(f"[LRT] contact {i + 1}/{cfg['repeats']} over {(row, col)} at X{x:.3f} Y{y:.3f}: "
                                 f"z={z:.3f}" + ("" if touched[0] == (row, col) else f", {touched[0]} first"))
                z = self._back_off(hop, z + cfg['back_off'])
            self.machine.move(z=cfg['z_park'])
            self.machine.wait_moves()
        z = float(np.median(found))
        sigma = max((max(found) - min(found)) / 2, 0.01)
        if any(c != (row, col) for c in on):
            sigma += cfg.get('off_cell', 0.02)
        self.machine.say(f"[LRT] contact over {(row, col)}: z={z:.3f} ±{sigma:.3f} (median, spread "
                         f"{max(found) - min(found):.3f})")
        return z, sigma

    def touched(self, strengths, hop, level=None):
        '''The cells that respond (see responds()), strongest first. A cell in one of the array's
        crosstalk_rows only when no other row of its column responds, or when
        it is a real press: a press elsewhere in the column lifts it too.'''
        cells = [c for c in strengths if self.responds(strengths, c, level)]
        crosstalk = self.arrays[hop].get('crosstalk_rows', ())
        cells = [c for c in cells if c[0] not in crosstalk or strengths[c] >= self.cfg['sure']
                 or not any(o[1] == c[1] and o[0] != c[0] for o in cells)]
        return sorted(cells, key=lambda c: -strengths[c])

    def _descend(self, hop, z, step, floor, early=False):
        '''Down until the tip presses on the sheet -> (z, the cells that answer there, strongest
        first). Its onset: the first step any cell rises `early` over the air, well over the
        sheet's noise. Not `respond`: where a cell gets there depends on its gain, BED_5's weak
        (2, 4) ~0.07mm past first touch, a strong cell ~0.015, and a contact found on one and
        used on another pressed the taps that much deeper; `early` is ~0.01 on either. Whichever
        cell: which one lights up first is the sheet's business (a column's crosstalk leads at
        first touch, a neighbour of a tip near its border), that the tip touched is not.
        Confirmed `confirm` fine steps on: a press grows as it goes deeper (every ladder on
        BED_5, 2026-10-07), a reading in the air doesn't (a bent liner, 2026-09-30), and then
        it goes on down. z is where it rose `early`, between the step before and the first over
        it as their readings say: a step late, every press past contact was that much deeper.
        early (the coarse steps): back at once, unconfirmed: the fine steps find where.'''
        cfg = self.cfg
        onset = cfg.get('early', cfg['respond'])
        before = 0.0                    # the rise one step up
        while True:
            z -= step
            if z < floor:
                raise FsrError(f"[LRT] no contact down to z={floor:.2f}: is the tool over the array at hop {hop}?")
            self.machine.move(z=z, speed=JOG_SPEED)
            strengths = self.read(hop)
            level = self.rise(strengths)
            if level < onset:
                before = level
                continue
            if early:
                return z, self.touched(strengths, hop)
            first = z + step * (level - onset) / max(level - before, 1e-9)
            for _ in range(cfg.get('confirm', 2)):
                z -= cfg['fine_step']
                self.machine.move(z=z, speed=JOG_SPEED)
                strengths = self.read(hop)
            if self.rise(strengths) >= level + 0.1 * cfg['respond']:
                return first, self.touched(strengths, hop, onset) or sorted(strengths, key=lambda c: -strengths[c])[:1]
            self.machine.say(f"[LRT] the sheet rose at z={first:.3f} but no more deeper ({self.top(strengths)}): "
                             f"in the air, going on down")

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
        '''Down at the array's `aim` until any cell responds, and which cell that is, pressed
        in -> (shift, z, at): the tip's offset from the toolhead to half a cell (that cell's
        centre), the contact z there, and where the toolhead was (at).
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
            self.baseline(hop, z)                   # what the cells rise from
            # Coarse, at three spots by turns: a tip in the dead zone between cells reads
            # nothing however deep it goes (to the floor: a fineliner, 2026-10-07). Offset
            # by (0, 0), (1/2, 1/4), (1/4, 1/2) of a cell: whatever border lines a tip is on,
            # not all three are on one (two spots could be: a row border and a column border).
            # Each way it has more room: away from the array's ends, dead rows and faulty
            # columns (BED_5: towards row 1, away from cols 3 and 4; a corner on col 4 touched
            # first and the tip estimate went 1.2-1.65mm out, 2026-10-07)
            rd = self._roomier(hop, 0, self.arrays[hop]['aim'][0]) * np.asarray(array.row_dir, float)
            cd = self._roomier(hop, 1, self.arrays[hop]['aim'][1]) * np.asarray(array.col_dir, float)
            spots = [aim, aim + array.pitch * (0.5 * rd + 0.25 * cd), aim + array.pitch * (0.25 * rd + 0.5 * cd)]
            z, aim = self._descend_spots(hop, spots, z, cfg['step'], floor)
            while True:
                z = self._back_off(hop, z + cfg['back_off'])
                z, first = self._descend(hop, z, cfg['fine_step'], floor)
                self.machine.say(f"[LRT] first contact at X{aim[0]:.3f} Y{aim[1]:.3f}: z={z:.3f} on {first[:3]}")
                # Only enough to tell which cell: a weak one (BED_5's (2, 4) tops out at ~220)
                # went the whole press for press_strength, 0.16mm past first touch (simulated)
                # At least `identify` in: at first touch a row's or a column's crosstalk is ~0.95 of
                # the pressed cell (2026-10-07), and seven cells of a row tie (simulated, 0.02 in)
                self.depth[hop] = max(self.press_depth(hop, None, z, cfg.get('locate_strength')),
                                      min(cfg.get('identify', 0.06), self.press_cap or cfg['press']))
                z_press, z_lift = z - self.depth[hop], z + 1.0
                # Which cell: pressed in, where the crosstalk has fallen behind. Pressed is a rise
                # of `early`, as contact is: a fine tip only `press_cap` past its onset is ~130
                strengths = self.tap(hop, aim, z_press, z_lift, aim)
                touched = self.touched(strengths, hop, cfg.get('early'))
                if touched:
                    break
                # A reading in the air (a bent 0.05 liner, 2026-09-30): the tip isn't
                # down yet. On down from where it pressed, to the floor at most.
                self.machine.say(f"[LRT] a false start at z={z:.2f}, nothing pressed in at {aim.round(2)} "
                                 f"({self.top(strengths)}): going on down")
                z = z_press
                self.machine.move(z=z, speed=JOG_SPEED)
                z, _ = self._descend(hop, z, cfg['step'], floor, early=True)
            # The tip is somewhere on that cell: its centre is good to half a cell, which is
            # all the edge sweeps need (they reach a cell either way). Bounding it here by where
            # the cell stops answering was a threshold search on one reading a tap, and gave up
            # or went 1-2mm out with the sheet's ripple and crosstalk (2026-10-07).
            shift = np.asarray(array.center(*touched[0]), float) - aim
            self.machine.move(z=cfg['z_park'])
            self.machine.wait_moves()
        self.machine.say(f"[LRT] tip at about {shift.round(2).tolist()} from the toolhead, on {touched[0]} "
                         f"(cells {touched}), taps press {self.depth[hop]:.2f}mm")
        return shift, z, aim

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

    def depth_on(self, hop, xy, z):
        '''press_depth() with the toolhead at xy, from its contact z there: the strongest cell,
        whichever it is (the tip is only known to half a cell yet).'''
        with lifted_on_error(self.machine, self.cfg['z_park']):
            self.machine.move(z=z + self.cfg['back_off'], speed=JOG_SPEED * 5)
            self.machine.move(float(xy[0]), float(xy[1]))
            self.machine.move(z=z, speed=JOG_SPEED)
            depth = self.press_depth(hop, None, z)
            self.machine.move(z=z + self.cfg['back_off'], speed=JOG_SPEED * 5)
        self.machine.say(f"[LRT] at X{xy[0]:.3f} Y{xy[1]:.3f} the taps press {depth:.2f}mm")
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

    def find_edge(self, edge, z_contact, shift=(0, 0), at=None):
        '''edge: (hop, (row, col) of cell a, (row, col) of its neighbour b) -> (edge point, gap,
        sigma): where the toolhead is when the tip is on the border from a to b, the dead
        zone's width there, and how sure that point is (mm, one sigma).
        Taps along the line through the two centres, each judged by b's share of the two
        cells' rise alone: the sheet's ripple (a cell read 208 to 784 within a mm, 2026-10-07),
        its cells' gains and a column's crosstalk move both cells' readings, much less their
        share, and the other 30 cells (row 3, a leaking column) don't vote at all. The border
        is where the fewest taps fall on the wrong side (border()): a stray tap is one vote,
        not a search sent the wrong way. Coarse first, a cell and a half either side (the tip is
        known to half a cell), as far as the array goes; then finer over the border; then a tap
        in the middle of where each side ends, twice. A line that finds no border (along the dead
        zone beside the two cells, or beyond them: locate a cell off across it) is swept again
        to either side, up to most of a cell.
        z_contact: contact z with the toolhead at `at` (default: over a's centre).'''
        cfg = self.cfg
        hop, cell_a, cell_b = edge
        cell_a, cell_b = tuple(cell_a), tuple(cell_b)
        array = self.array(hop)
        a = np.asarray(array.center(*cell_a), float) - np.asarray(shift, float)
        b = np.asarray(array.center(*cell_b), float) - np.asarray(shift, float)
        u = (b - a) / np.linalg.norm(b - a)
        across = np.array([-u[1], u[0]])
        at = a if at is None else np.asarray(at, float)
        z_lift = z_contact + 1.0
        coarse, fine, span = cfg.get('sweep', (0.25, 0.05, 0.4))
        onset = cfg.get('early', cfg['respond'])          # a tap presses: see _descend
        reach = 1.5 * array.pitch

        spec = self.arrays[hop]
        unread = {tuple(c) for c in spec.get('faulty_cells', ())}

        def inside(p, margin=0.25):
            '''The tip, as far as we know where it is, on a cell that is read: never a tap beyond
            the cells, nor on a dead row or a faulty column (pressed, it lifts its line's other
            cells evenly, a and b alike: a coin toss for a vote, BED_5's old row 3).'''
            local = p + np.asarray(shift, float) - array.origin
            u_, v_ = np.dot(local, array.col_dir), np.dot(local, array.row_dir)
            if not (margin <= u_ <= array.cols * array.pitch - margin and margin <= v_ <= array.rows * array.pitch - margin):
                return False
            row, col = int(v_ // array.pitch), int(u_ // array.pitch)
            return row not in spec.get('dead_rows', ()) and col not in spec.get('faulty_cols', ()) and (row, col) not in unread
        found, taps = None, {}
        with lifted_on_error(self.machine, cfg['z_park']):
            self.machine.move(z=cfg['z_park'])
            self.machine.move(float(a[0]), float(a[1]))
            if hop not in self.depth:       # no measure() before (LRT_FSR_EDGE): find it on cell a
                self.machine.move(z=z_lift)
                self.machine.move(z=z_contact, speed=JOG_SPEED)
                self.depth[hop] = self.press_depth(hop, None, z_contact)
            z_press = z_contact - self.depth[hop]
            self.machine.move(z=z_lift, speed=JOG_SPEED * 5)
            self.baseline(hop, z_lift)              # in the air over a: what the taps rise from
            for side in np.array([0.0, 0.4, -0.4, 0.8, -0.8]) * array.pitch:
                line, taps = (a + b) / 2 + side * across, {}

                def sweep(ts):
                    for t in ts:
                        t = round(float(t), 4)
                        p = line + t * u
                        if t in taps or abs(t) > reach + 1e-9 or not inside(p):
                            continue
                        s = self.tap(hop, p, z_press, z_lift, at)
                        taps[t] = (s.get(cell_a, 0.0), s.get(cell_b, 0.0), max(s.values(), default=0.0))
                        if self.verbose:
                            self.machine.say(f"[LRT]   tap at X{p[0]:.3f} Y{p[1]:.3f} z={z_press:.3f}: "
                                             f"{cell_a}={taps[t][0]:.0f} {cell_b}={taps[t][1]:.0f} ({self.top(s)})")
                sweep(np.arange(-reach, reach + 1e-9, coarse))
                found = border(taps, onset, cfg['dominance'])
                if found is not None:
                    sweep(np.arange(found[0] - span, found[0] + span + 1e-9, fine))
                    found = border(taps, onset, cfg['dominance'])
                for _ in range(2 if found is not None else 0):    # each end's span halved, twice
                    sweep([sum(end) / 2 for end in found[4]])
                    found = border(taps, onset, cfg['dominance']) or found
                if found is not None:
                    break
                self.machine.say(f"[LRT] no border from {cell_a} to {cell_b} {side:+.2f}mm across: "
                                 f"{sum(a_ + b_ >= onset for a_, b_, _ in taps.values())} of {len(taps)} taps "
                                 f"answered, again beside it")
            self.machine.move(z=cfg['z_park'])
            self.machine.wait_moves()
        if found is None:
            raise FsrError(f"[LRT] no border from {cell_a} to {cell_b} of hop {hop} on five lines across it: "
                           f"is the tip over these cells (check the array origin), do they answer (LRT_FSR_SURVEY)?")
        t0, gap, sigma, wrong, _ = found
        point = line + t0 * u
        self.machine.say(f"[LRT] {cell_a}|{cell_b} at X{point[0]:.3f} Y{point[1]:.3f} ±{sigma:.3f} "
                         f"(gap {gap:.2f}, {len(taps)} taps at z={z_press:.3f}"
                         + (f", {wrong} on the wrong side)" if wrong else ")"))
        return point, gap, sigma

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
        '''The docked tool: the X and Y edges, and contact z on the z cell -> {'x', 'y', 'z',
        'gaps', 'tip', 'sigma': {'x', 'y', 'z'}}, sigma how sure each is (mm).
        bed_z: {cell: BLTouch z} for z_cells(). prior: what is known of the
        tool already, {'tip': (x, y), 'z': contact z}, see locate() and window().
        locate() gives the tip to half a cell and where it touched; the edges are swept from
        there (z along the sheet's mesh), and each puts the tip exactly across its border;
        then contact z mid cell, where the tip is now known to be.'''
        cfg = self.cfg
        found = {}                  # hop -> {'shift', 'z', 'at'}: the tip, a contact z, and where
        self.depth = {}             # this tool's, found again
        self.surface = self.machine.mesh_profile(cfg['surface_mesh']) if cfg.get('surface_mesh') else None
        if cfg.get('surface_mesh') and self.surface is None:
            self.machine.say(f"[LRT] no {cfg['surface_mesh']} mesh: the taps take the sheet as flat")
        z_hop, z_row, z_col = cfg['z_cell']

        def over(hop, cell):
            '''-> (contact z, toolhead xy) over a cell's centre: the tip found on this array
            first, and the taps' depth there.'''
            if hop not in found:
                shift, z, at = self.locate(hop, next(v for c, v in bed_z.items() if c[0] == hop), prior)
                found[hop] = {'shift': shift, 'z': z, 'at': at}
                # The taps' depth on the z cell, or where it touched when that doesn't get there
                # (the tip half a cell off it yet): either may be a weak cell (BED_5's (2, 4) tops
                # out at ~220, never press_strength: the taps all went the whole press)
                z_at, xy = over(hop, self.z_cell_of(hop))
                self.depth[hop] = self.depth_on(hop, xy, z_at)
                if self.depth[hop] >= (self.press_cap or cfg['press']) - 1e-9:
                    self.depth[hop] = min(self.depth[hop], self.depth_on(hop, at, z))
            f = found[hop]
            xy = np.asarray(self.array(hop).center(*cell), float) - f['shift']
            return f['z'] + self.follow(xy, f['at']), xy

        if self.before_measure:
            self.before_measure()
        self.matrix(True)
        try:
            points, gaps, sigmas = {'x': [], 'y': []}, [], {'x': [], 'y': []}
            for axis, edges in (('x', cfg['x_edges']), ('y', cfg['y_edges'])):
                for edge in edges:
                    hop, cell_a, cell_b = edge
                    z_a, xy_a = over(hop, cell_a)
                    point, gap, sigma = self.find_edge(edge, z_a, found[hop]['shift'], at=xy_a)
                    points[axis].append(point[0 if axis == 'x' else 1])
                    gaps.append(gap)
                    sigmas[axis].append(sigma)
                    # The tip is on that border with the toolhead at `point`: its offset across
                    # the border, exactly, for what comes next
                    array = self.array(hop)
                    ca, cb = (np.asarray(array.center(*c), float) for c in (cell_a, cell_b))
                    u = (cb - ca) / np.linalg.norm(cb - ca)
                    s = found[hop]['shift']
                    found[hop]['shift'] = s + (np.dot((ca + cb) / 2 - point, u) - np.dot(s, u)) * u
                    self.machine.say(f"[LRT] {axis} edge {edge}: {point.round(3)} ±{sigma:.3f} gap={gap:.3f}")
            z_top, _ = over(z_hop, (z_row, z_col))
            z, sigma_z = self.contact_z(z_hop, z_row, z_col, bed_z[tuple(cfg['z_cell'])], found[z_hop]['shift'],
                                        z_top + cfg['back_off'], prior)
        finally:
            self.matrix(False)
            if self.after_measure:
                self.after_measure()        # it touched the sheet, even when it stopped
        mean = lambda v: float(np.sqrt(np.mean(np.square(v))) / np.sqrt(len(v)))
        return {
            'z': z,
            'x': float(np.mean(points['x'])),
            'y': float(np.mean(points['y'])),
            'gaps': gaps,
            'tip': [float(v) for v in found[z_hop]['shift']],
            'sigma': {'x': mean(sigmas['x']), 'y': mean(sigmas['y']), 'z': sigma_z},
        }

    def z_cell_of(self, hop):
        '''The cell the taps' depth is found on, on this array: the z cell, or its array's aim.'''
        h, row, col = self.cfg['z_cell']
        return (row, col) if h == hop else tuple(int(v) for v in self.arrays[hop]['aim'])

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
        if max(ref['sigma'].values()) > self.cfg.get('max_sigma', 0.15):
            self.machine.say(f"[LRT] the reference is unsure: ±{ref['sigma']}; every pen measured against it "
                             f"will be as unsure")
        self.machine.gcode_run(f"WRITE_TOOL_TAG DX=0 DY=0 DZ={tool_z:.3f} REFERENCE=1")
        ref['bed_z'] = [[*cell, z] for cell, z in bed_z.items()]
        return {'fsr_ref': ref}

    def probe_tool(self, profile):
        '''The docked tool against the reference -> (dx, dy, dz).
        The edges give where the tool was *sent* when it met them, so a tool
        tip that sits +0.5mm off meets them 0.5mm early: dx = tool - reference.
        Each is as sure as both measurements together; one less sure than `max_sigma`
        stops, the values in the message (better no tag than a wrong one).'''
        ref = profile['fsr_ref']
        bed_z = {tuple(c[:3]): c[3] for c in ref['bed_z']}
        self.machine.gcode_run("_CLEAR_OFFSETS")
        m = self.measure(bed_z)
        dx = round(m['x'] - ref['x'], 3)
        dy = round(m['y'] - ref['y'], 3)
        dz = round(m['z'] - bed_z[tuple(self.cfg['z_cell'])], 3)
        ref_sigma = ref.get('sigma', {})
        sigma = {k: float(np.hypot(m['sigma'][k], ref_sigma.get(k, 0.0))) for k in ('x', 'y', 'z')}
        said = (f"dx={dx} ±{sigma['x']:.3f} dy={dy} ±{sigma['y']:.3f} dz={dz} ±{sigma['z']:.3f} "
                f"gaps={[round(g, 3) for g in m['gaps']]}")
        if max(sigma.values()) > self.cfg.get('max_sigma', 0.15):
            raise FsrError(f"[LRT] too unsure to write the tag: {said}. Again, or WRITE_TOOL_TAG by hand")
        self.machine.say(f"[LRT] offsets {said}")
        return dx, dy, dz
