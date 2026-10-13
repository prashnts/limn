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
# A measurement too unsure (sigma over `max_sigma`) is written and said as rough;
# only borders a cell apart (a wrong cell) write no tag.
# A tool is compared with the reference tool (T4) on the same cells, so the
# array positions only need to be roughly right.
#
# The arrays run in matrix mode meanwhile: every cell every frame, so we also
# know they are alive. No frame for `alive` seconds, a press above
# `press_limit`, or no contact down to the floor: lift to park and stop.
import random
from collections import Counter

import numpy as np

from .geometry import FsrArray, mesh_z
from .samples import FSR, RTP, S_MATRIX
from .machine import JOG_SPEED, lifted_on_error


class FsrError(RuntimeError):
    pass


HIGH_AT_REST = 40      # a cell this far over the sheet's median at rest, untouched, is faulty (BED_5's col 3: 75-100)
BARS = '▁▂▃▄▅▆▇█'


def grid(strengths, rows=4, cols=8, full=60):
    '''The whole array on one line for the console: row 0 first, col 0 leftmost, each
    cell a bar of its strength over the strongest's (at least `full`, so the noise at
    rest stays flat); · nothing, x a cell not read (dead, faulty).'''
    top = max(max(strengths.values(), default=0), full)

    def bar(c):
        if c not in strengths:
            return 'x'
        v = strengths[c] / top
        return '·' if v < 1 / 16 else BARS[min(len(BARS) - 1, int(v * len(BARS)))]
    return '|'.join(''.join(bar((r, c)) for c in range(cols)) for r in range(rows))


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
    # cell, none of its side neighbours faulty (a diagonal one is ~1.8mm off the centre: a faulty (0, 5)
    # pushed the aim from (1, 4) to (2, 5), 2026-10-13). Pens off the sheet there: locate's reach.
    aim = list(spec['aim'])
    shift = result.get('shift')
    if shift is not None:
        pitch = cfg['pitch']
        dr = float(np.dot(shift, spec['row_dir'])) / pitch
        dc = float(np.dot(shift, spec['col_dir'])) / pitch
        land = (spec['aim'][0] + dr, spec['aim'][1] + dc)
        near = lambda c: [(c[0] + i, c[1] + j) for i, j in ((-1, 0), (1, 0), (0, -1), (0, 1))]
        # Inner cells only, never the outer rows and cols: a pen ~4mm off the reference (the Micron 01
        # Blue) would come down beside the sheet (the aim on (3, 3), 2026-10-13)
        rows = 1 + max(c[0] for c in cells)
        cols = 1 + max(c[1] for c in cells)
        inner = [c for c in cells if 0 < c[0] < rows - 1 and 0 < c[1] < cols - 1 and c not in faulty and c not in weak]
        ok = [c for c in inner if not any(n in faulty for n in near(c))] or inner
        if ok:
            target = min(ok, key=lambda c: np.hypot(c[0] + 0.5 - land[0], c[1] + 0.5 - land[1]))
            aim = [round(target[0] + 0.5 - dr, 2), round(target[1] + 0.5 - dc, 2)]
        else:
            warnings.append("no good inner cell to aim at: the config's aim stays")
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


def judge_taps(taps, cell_a, cell_b, lifted_rows, onset, lead, lifted_cols=(), sure=float('inf')):
    '''taps: {t: {cell: rise}} along an edge from a into b -> {t: (a, b, top)} for border(). Whether the
    tip is on a or b, not on a third cell, goes by a lifted row's cell less its lift: what it reads on
    the taps where the other cell, in its column, is the one pressed. Its lift (~40-65 with any press
    up its column) led a weak (1, 5) and (2, 5) on their border, 2.3mm away, and voted (3, 5)'s side:
    ±0.43 on (2, 5)|(3, 5), twice (2026-10-12). Its share of a + b stays as read: less its lift, the
    border moved 0.3-0.5mm and two runs went 0.2mm apart (as read: 0.03). A lifted column (col 0,
    along its row: (1, 0) 86-110 under presses on row 1, 2026-10-13) the same way. Nor is a cell
    lifted by a or b a third cell, under `sure`.'''
    def lifted_by(c, o):
        return c != o and ((c[0] in lifted_rows and o[0] not in lifted_rows and c[1] == o[1])
                           or (c[1] in lifted_cols and o[1] not in lifted_cols and c[0] == o[0]))
    lift = {}
    for c, o in ((cell_a, cell_b), (cell_b, cell_a)):
        if lifted_by(c, o):
            under = [s.get(c, 0.0) for s in taps.values() if s.get(o, 0.0) >= onset and s.get(o, 0.0) >= max(s.values())]
            lift[c] = float(np.median(under)) if under else 0.0
    out = {}
    for t, s in taps.items():
        a, b = s.get(cell_a, 0.0), s.get(cell_b, 0.0)
        own = [max(s.get(c, 0.0) - lift.get(c, 0.0), 0.0) for c in (cell_a, cell_b)]
        third = max((v for c, v in s.items() if c not in (cell_a, cell_b)
                     and (v >= sure or not (lifted_by(c, cell_a) or lifted_by(c, cell_b)))), default=0.0)
        out[t] = (a, b, max(a, b, third) if max(own) >= lead * max(own + [third]) else float('inf'))
    return out


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
        self.ref_above = None       # the reference's contact over the BLTouch z (probe_tool): locate's reach
        self.dz_trim = cfg.get('dz_trim', 0.0)  # mm off every dz written to a tag (DZ_TRIM=), see calibrate_reference
        self.rng = random.Random()  # which borders a measurement takes (pick_edges)
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
                                            'faulty_cells': [tuple(c) for c in judged['faulty']],
                                            'weak_cells': [tuple(c) for c in judged.get('weak', ())]}}

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

    def growth(self, strengths, before):
        '''The most any cell rose since `before`, over its own reading there: a press grows under
        the tip, a reading in the air stays. Only cells now over half of `early`: the rest is
        the sheet's noise, and 32 cells of it would always show some cell rising.'''
        floor = 0.5 * self.cfg.get('early', self.cfg['respond'])
        return max((v - before.get(c, 0.0) for c, v in strengths.items() if v >= floor), default=0.0)

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
        '''The strongest cells, and the whole array (grid()), for messages.'''
        cells = sorted(strengths, key=lambda c: -strengths[c])[:n]
        return ', '.join(f"{c}={strengths[c]:.0f}" for c in cells) + f" [{grid(strengths, full=self.cfg['respond'])}]"

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

    def lifted_by(self, hop, c, o):
        '''Whether cell c lifts with a press on cell o: c on a lifted row and o up its column (row 3,
        no series resistor: 30-65 with any press up it), or c on a lifted column and o along its row
        (col 0: (1, 0) read 86-110 under presses on row 1, and answered for (1, 3), (1, 7), 2026-10-13).'''
        spec = self.arrays[hop]
        rows, cols = spec.get('lifted_rows', ()), spec.get('lifted_cols', ())
        return c != o and ((c[0] in rows and o[0] not in rows and c[1] == o[1])
                           or (c[1] in cols and o[1] not in cols and c[0] == o[0]))

    def on_lifted(self, hop, c):
        spec = self.arrays[hop]
        return c[0] in spec.get('lifted_rows', ()) or c[1] in spec.get('lifted_cols', ())

    def unlifted(self, strengths, hop, level=None):
        '''The readings without the cells only lifted (see touched()).'''
        level_ = level or self.cfg['respond']
        return {c: s for c, s in strengths.items() if s >= self.cfg['sure']
                or not any(v >= level_ and self.lifted_by(hop, c, o) for o, v in strengths.items())}

    def touched(self, strengths, hop, level=None):
        '''The cells that respond (see responds()), strongest first. A cell in one of the array's
        crosstalk_rows only when no other row of its column responds, or when
        it is a real press: a press elsewhere in the column lifts it too.
        A cell on one of the array's lifted rows or columns under `sure` is no press at all while a cell
        it lifts with (lifted_by) reads `level`: it lifts with every press along it about as much as a fine
        tip's own cell, and, left in, row 3 outread (1, 4) under a Micron 005 and put the tip two rows
        out, beside the sheet (2026-10-12).'''
        strengths = self.unlifted(strengths, hop, level)
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
        Confirmed within `confirm` fine steps on: a press grows as it goes deeper (every ladder
        on BED_5, 2026-10-07), a reading in the air doesn't (a bent liner, 2026-09-30), and then
        it goes on down. The growth is each cell's over its own reading at the onset (growth()):
        not the strongest cell's. On 2026-10-11 (3, 1) led at first touch and stayed at 41-45
        while (1, 1), under the tip, grew 18, 24, 30: judged by the strongest, two of three
        contacts were taken for readings in the air and came out 0.12-0.18mm low. z is where it rose `early`, between the step before and the first over
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
            at_onset = strengths
            for _ in range(cfg.get('confirm', 5)):
                z -= cfg['fine_step']
                self.machine.move(z=z, speed=JOG_SPEED)
                strengths = self.read(hop)
                if self.growth(strengths, at_onset) >= 0.1 * cfg['respond']:
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
            # And `locate_reach` rows either way, at the same heights, once these have gone `reach_after`
            # past where the reference touched (ref_above) with no answer: a pen further off the
            # reference than the sheet is wide comes down beside it at the aim, but on it at one of
            # those (the sheet is above the panel beside it; a gentle touch beside it is fine, the user,
            # 2026-10-13). Not before: a far spot answering first (the sheet's slope, a dead row's
            # crosstalk) brought locate down off the aim (simulated). Rows only: 4 of them, 10mm,
            # against pens ~4.4mm off in X (the Blue); 8 cols leave room in Y.
            # Each as the aim and as its (1/4, 1/2) spot: not both on a border's dead zone
            reach = [p + k * array.pitch * np.asarray(array.row_dir, float)
                     for k in cfg.get('locate_reach', ()) for p in (spots[0], spots[2])]
            below = bed_z + self.ref_above - cfg.get('reach_after', 0.3) if self.ref_above is not None else None
            z, aim = self._descend_spots(hop, spots, z, cfg['step'], floor, reach if below is not None else (), below)
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
            cell, aim = self._find_cell(hop, aim, z_press, z_lift, strengths, touched[0])
            shift = np.asarray(array.center(*cell), float) - aim
            self.machine.move(z=cfg['z_park'])
            self.machine.wait_moves()
        self.machine.say(f"[LRT] tip at about {shift.round(2).tolist()} from the toolhead, on {cell} "
                         f"(cells {touched}), taps press {self.depth[hop]:.2f}mm")
        return shift, z, aim

    def _find_cell(self, hop, aim, z_press, z_lift, strengths, cell):
        '''The cell under the tip, from taps around where it first touched -> (that cell, the toolhead
        xy it is under: `aim`, or half a cell on from it).
        Locate's own tap names a cell, but a lifted line reads about as much as a fine tip's own cell
        (row 3 up its column: named (3, 4) for (1, 4) twice, 2026-10-12 and 10-13). So each cell the tip
        could be on (close to the strongest in locate's tap) says which cell must answer a tap `o` cells
        over: its own + o. Each tap's answer points back at the tip's cell; the cells it doesn't
        point at drop out. An answer no cell predicted names the tip's cell itself, the answer less
        the step (10-13: a row over from (3, 4), (0, 4) answered: the tip was on (1, 4)), and another
        tap has to agree. Done when one cell is left and a tap that put the tip on an inner cell (off
        the outer rows and cols) was answered there: an FSR under the tip, room on every side.
        Taps only where every cell still possible lands on a cell that is read, rather not on a lifted
        line, weak, or an outer cell; diagonal first (both axes at once); the rest at random, so
        other cells are pressed each time (wear: the cells pressed most went dead, 10-12).
        No such tap, or no answer that agrees: stop, nothing pressed beside the sheet.'''
        array, spec = self.array(hop), self.arrays[hop]
        unread = {tuple(c) for c in spec.get('faulty_cells', ())}
        weak = {tuple(c) for c in spec.get('weak_cells', ())}

        def on(c):
            return 0 <= c[0] < array.rows and 0 <= c[1] < array.cols

        def readable(c):
            return on(c) and c[0] not in spec.get('dead_rows', ()) and c[1] not in spec.get('faulty_cols', ()) \
                and c not in unread

        def inner(c):
            return 0 < c[0] < array.rows - 1 and 0 < c[1] < array.cols - 1

        def plus(c, o):
            return (c[0] + o[0], c[1] + o[1])

        lifted_rows, lifted_cols = spec.get('lifted_rows', ()), spec.get('lifted_cols', ())

        def lifts_say(reading):
            '''-> (rows, cols) the press is on, by the lifted lines alone: row 3 rises only with a press
            up its own column, col 0 only along its own row (2026-10-12/13). Together they point at one
            cell, even one that reads nothing (a weak one, a dead zone): (3, c) and (r, 0) -> (r, c).'''
            sure = self.cfg['sure']
            cols = {c[1] for c, v in reading.items() if c[0] in lifted_rows and c[1] not in lifted_cols and onset <= v < sure}
            rows = {c[0] for c, v in reading.items() if c[1] in lifted_cols and c[0] not in lifted_rows and onset <= v < sure}
            return rows, cols

        def narrow(cs, o, reading):
            '''The cells of cs the lifts in `reading` (a tap o over) agree with; all of them, when none do.'''
            rows, cols = lifts_say(reading)
            kept = {c for c in cs if (not rows or plus(c, o)[0] in rows) and (not cols or plus(c, o)[1] in cols)}
            return kept or cs

        onset = self.cfg.get('early', self.cfg['respond'])
        named = cell
        own = self.unlifted(strengths, hop, onset)
        cands = {c for c in own if readable(c) and self.responds(own, c, onset)} | {cell}
        # The rest of a lifted line the named cell is on (below: candidates when the cell is only its lift)
        mates = {c for c in ((r, cell[1]) for r in range(array.rows)) if cell[0] in spec.get('lifted_rows', ())} \
            | {c for c in ((cell[0], k) for k in range(array.cols)) if cell[1] in spec.get('lifted_cols', ())}
        offsets = [(dr, dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1) if (dr, dc) != (0, 0)]
        used, agreed, said, nudged = set(), False, [], 0
        # A first contact on a weak cell, a lifted line's lift, or under locate_strength: the tip is
        # likely on a border (10-13: the old aim brought it down on (1, 4)|(1, 5), (1, 5) nearly dead,
        # and only row 3's lift answered). Every tap whole cells over would put it on that border again.
        doubt = named in weak or strengths.get(named, 0.0) < 0.5 * self.cfg.get('locate_strength', self.cfg['respond']) \
            or (self.on_lifted(hop, named) and strengths.get(named, 0.0) < self.cfg['sure'])
        misses = 2 if doubt else 0
        if self.on_lifted(hop, named) and strengths.get(named, 0.0) < self.cfg['sure']:
            # Its lift, not the tip: the tip may be anywhere along that line. Taps along the line keep
            # every cell of it on the sheet, and the cell that answers says which row (or column)
            cands |= {m for m in mates if on(m)}
        cands = narrow(cands, (0, 0), strengths)
        start, start_aim, start_mates, first = set(cands), aim, set(mates), None
        for _ in range(self.cfg.get('locate_taps', 8)):
            if misses >= 2 and nudged < 2:
                # A quarter cell on, diagonally, towards the sheet's middle; no answer there either, a
                # quarter the other way from where it came down. Of three spots a quarter apart, at most
                # one is on a border's dead zone (~0.4mm): a tip on a border is a quarter inside a cell
                # after either. Each cell it could be on is now itself or its neighbour that way, and
                # the taps start over. An axis goes the other way, or not at all, where every cell it
                # could be on wouldn't stay on the sheet.
                sign = []
                for axis, n in ((0, array.rows), (1, array.cols)):
                    mid = 1 if np.mean([c[axis] for c in start]) + 0.5 < n / 2 else -1
                    ways = (mid, -mid) if first is None else (-first[axis],)
                    sign.append(next((d for d in ways if all(0 <= c[axis] + d < n for c in start)), 0))
                sign = first = tuple(sign)
                if nudged and not any(sign):
                    break
                grow = lambda cs: {plus(c, (i * sign[0], j * sign[1])) for c in cs for i in (0, 1) for j in (0, 1)}
                aim = start_aim + array.pitch / 4 * (sign[0] * array.row_dir + sign[1] * array.col_dir)
                cands, mates = {c for c in grow(start) if on(c)}, grow(start_mates)
                used, agreed, misses, nudged = set(), False, 0, nudged + 1
                said.append(f"a quarter cell {sign} from where it came down")
                self.machine.say(f"[LRT] {'first contact unsure' if doubt and nudged == 1 else 'no answer'} around "
                                 f"{named}: a quarter cell {sign} from where it came down, the tip on one of {sorted(cands)}")
            options = [o for o in offsets if o not in used and all(readable(plus(c, o)) for c in cands)]
            if not options:
                raise FsrError(f"[LRT] the tip is on one of {sorted(cands)} ({self.top(strengths)}), and no tap "
                               f"tells which without pressing beside the sheet: stopped before the edges"
                               + (f" ({'; '.join(said)})" if said else ""))
            o = min(options, key=lambda o: (sum(self.on_lifted(hop, plus(c, o)) or plus(c, o) in weak for c in cands),
                                            sum(not on(plus(m, o)) for m in mates),
                                            sum(not inner(plus(c, o)) for c in cands),
                                            0 in o, self.rng.random()))
            used.add(o)
            step = array.pitch * (o[0] * array.row_dir + o[1] * array.col_dir)
            there = self._press_until_answered(hop, aim + step, aim, z_press + self.depth[hop], z_lift,
                                               [plus(c, o) for c in cands])
            answered = [a for a in self.touched(there, hop, onset) if readable(a)]
            said.append(f"{o}: {self.top(there)}")
            if not answered:
                # Only lifts: where they cross is the cell pressed (it may read nothing itself)
                rows, cols = lifts_say(there)
                if len(rows) == 1 and len(cols) == 1:
                    answered = [(next(iter(rows)), next(iter(cols)))]
                    said[-1] += f" (the lifts: {answered[0]})"
                elif rows or cols:
                    kept = narrow(cands, o, there)
                    if kept != cands:
                        cands, agreed = kept, False
                        said[-1] += f" (the lifts: {sorted(rows) or '-'} {sorted(cols) or '-'})"
                        continue
            fit = {c for c in cands if plus(c, o) in answered}
            if not fit:
                # Or a predicted cell rose `early`, clearly over the others predicted, and at least half the
                # strongest: a patchy cell can read under its row's crosstalk and not lead (the old sheet,
                # row 0.35-0.95 of a press), but not under a cell nobody predicted at 6x it (simulated)
                own = self.unlifted(there, hop, onset)
                rose = {c: own.get(plus(c, o), 0.0) for c in cands}
                best = max(rose, key=rose.get)
                if rose[best] >= onset and rose[best] >= 0.5 * max(own.values(), default=0.0) \
                        and all(v < self.cfg['dominance'] * rose[best] for c, v in rose.items() if c != best):
                    fit = {best}
            if fit:
                cands, agreed = fit, True
            else:
                pointed = {c for c in ((a[0] - o[0], a[1] - o[1]) for a in answered) if on(c)}
                if not pointed:
                    misses += 1
                    continue
                self.machine.say(f"[LRT] a tap {o} over from {sorted(cands)} answered on {answered}: "
                                 f"the tip is on {sorted(pointed)}, to be confirmed")
                cands, agreed = pointed, False
                continue
            if len(cands) == 1 and agreed and inner(plus(next(iter(cands)), o)):
                found = next(iter(cands))
                if found != named or nudged:
                    self.machine.say(f"[LRT] not {named}: the taps around it say the tip is on {found} ({'; '.join(said)})")
                return found, aim
        raise FsrError(f"[LRT] the taps around {named} don't agree where the tip is ({'; '.join(said)}; "
                       f"still {sorted(cands)}): stopped before the edges")

    def _press_until_answered(self, hop, xy, at, z_contact, z_lift, cells):
        '''Down at `xy` from the contact z found at `at` (following the sheet) until one of `cells`
        reads `locate_strength`, the pen's cap at most, -> the readings there. Those cells, not the
        strongest: a lifted row's lift would stop it at once (0.02mm, simulated). A weak cell answers
        too, only deeper; a dead zone or nothing at the cap reads low.'''
        cfg = self.cfg
        dz = self.follow(xy, at)
        # A fine step short of the cap: the contact it goes from can be a fine step late
        most = (self.press_cap or cfg['press']) - cfg['fine_step']
        target = cfg.get('locate_strength') or cfg['respond']
        with lifted_on_error(self.machine, cfg['z_park']):
            self.machine.move(z=z_lift + max(dz, 0), speed=JOG_SPEED * 5)
            self.machine.move(float(xy[0]), float(xy[1]))
            depth = 0.0
            while True:
                self.machine.move(z=z_contact + dz - depth, speed=JOG_SPEED)
                strengths = self.read(hop)
                # one of `cells`, or any cell not on a lifted line: an answer nobody predicted counts too
                if depth >= most - 1e-9 or max((v for c, v in strengths.items()
                                                 if c in cells or not self.on_lifted(hop, c)), default=0.0) >= target:
                    break
                depth = round(min(depth + cfg['fine_step'], most), 3)
            self.machine.move(z=z_lift, speed=JOG_SPEED * 5)
        return strengths

    def _descend_spots(self, hop, points, z, step, floor, reach=(), below=None):
        '''Coarse steps down, at each of `points` by turns, lifted between: -> (z, the point
        where something presses). Like _descend(early=True), at several spots. `reach`: more
        points, by turns with them from `below` down.'''
        cfg = self.cfg
        lift = cfg['back_off']
        said = False
        while True:
            z -= step
            if z < floor:
                raise FsrError(f"[LRT] no contact down to z={floor:.2f}: is the tool over the array at hop {hop}?")
            far = list(reach) if below is not None and z <= below else []
            if far and not said:
                said = True
                self.machine.say(f"[LRT] nothing at the aim by z={z:.2f}, past where the reference touched: "
                                 f"{len(far)} spots a way off too, by turns")
            for p in list(points) + far:
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
            # The strongest: not a lifted row's lift (row 3 reads ~55 at once, the taps came out shallow)
            strength = strengths.get(tuple(cell), 0) if cell else \
                max((v for c, v in strengths.items() if not self.on_lifted(hop, c) or v >= cfg['sure']), default=0)
            if strength >= target:
                break
        return depth

    def depth_on(self, hop, xy, z, cell=None):
        '''press_depth() with the toolhead at xy, from its contact z there: on `cell`, or the
        strongest cell, whichever it is (the tip only known to half a cell).'''
        with lifted_on_error(self.machine, self.cfg['z_park']):
            self.machine.move(z=z + self.cfg['back_off'], speed=JOG_SPEED * 5)
            self.machine.move(float(xy[0]), float(xy[1]))
            self.machine.move(z=z, speed=JOG_SPEED)
            depth = self.press_depth(hop, cell, z)
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
            # measure()'s own tip: m['x'] / m['y'] average two different borders an axis (2026-10-12:
            # against the first edge's border alone, half a pitch off in X and 1.5 in Y, every press on a corner)
            shift = np.array(m['tip'], float)
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
                            other = max(((c, v) for c, v in live.items() if c != cell and c not in high
                                         and not self.lifted_by(hop, c, cell)),
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

    def find_edge(self, edge, z_contact, shift=(0, 0), at=None, unsure=(0.0, 0.0)):
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
        z_contact: contact z with the toolhead at `at` (default: over a's centre).
        unsure: (along the rows, along the cols) mm the tip may be from `shift`, kept clear of the
        sheet's end too: locate's is half a cell until an edge has put the tip across it.'''
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
            mu, mv = margin + unsure[1], margin + unsure[0]
            if not (mu <= u_ <= array.cols * array.pitch - mu and mv <= v_ <= array.rows * array.pitch - mv):
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
            judged = lambda: judge_taps(taps, cell_a, cell_b, spec.get('lifted_rows', ()), onset, cfg['dominance'],
                                        spec.get('lifted_cols', ()), cfg['sure'])

            for side in np.array([0.0, 0.4, -0.4, 0.8, -0.8]) * array.pitch:
                line, taps = (a + b) / 2 + side * across, {}

                def sweep(ts):
                    for t in ts:
                        t = round(float(t), 4)
                        p = line + t * u
                        if t in taps or abs(t) > reach + 1e-9 or not inside(p):
                            continue
                        s = self.tap(hop, p, z_press, z_lift, at)
                        taps[t] = s
                        if self.verbose:
                            self.machine.say(f"[LRT]   tap at X{p[0]:.3f} Y{p[1]:.3f} z={z_press:.3f}: "
                                             f"{cell_a}={s.get(cell_a, 0.0):.0f} {cell_b}={s.get(cell_b, 0.0):.0f} ({self.top(s)})")
                sweep(np.arange(-reach, reach + 1e-9, coarse))
                found = border(judged(), onset, cfg['dominance'])
                if found is not None:
                    sweep(np.arange(found[0] - span, found[0] + span + 1e-9, fine))
                    found = border(judged(), onset, cfg['dominance'])
                for _ in range(2 if found is not None else 0):    # each end's span halved, twice
                    sweep([sum(end) / 2 for end in found[4]])
                    found = border(judged(), onset, cfg['dominance']) or found
                if found is not None:
                    break
                answered = sum(a_ + b_ >= onset for a_, b_, _ in judged().values())
                self.machine.say(f"[LRT] no border from {cell_a} to {cell_b} {side:+.2f}mm across: "
                                 f"{answered} of {len(taps)} taps answered, again beside it")
                # Most taps unanswered: pressing too lightly, not beside the cells. Deeper on the next line,
                # the cap at most (locate's 0.06 barely reached (1, 2) from a contact on (3, 3): 0-4 of 29
                # taps answered on five lines, 2026-10-13 12:10)
                if answered < len(taps) / 2:
                    deeper = min(z_contact - z_press + 2 * cfg['fine_step'], (self.press_cap or cfg['press']) - cfg['fine_step'])
                    if deeper > z_contact - z_press + 1e-9:
                        z_press = z_contact - deeper
                        self.machine.say(f"[LRT] the taps press {deeper:.2f}mm now")
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
    def border_pairs(self, hop):
        '''Every border between two cells that are read, none weak or lifted -> {'x': [edge], 'y': [edge]}, an edge
        (hop, a, b): between rows (along X here) and between cols (along Y).'''
        array, spec = self.array(hop), self.arrays[hop]
        unread = {tuple(c) for c in spec.get('faulty_cells', ())} | {tuple(c) for c in spec.get('weak_cells', ())}
        # Nor on a lifted row or column: its lift votes on the border (row 3: (2, 5)|(3, 5) ±0.41, 2026-10-12)
        ok = lambda c: c[0] not in spec.get('dead_rows', ()) and c[1] not in spec.get('faulty_cols', ()) \
            and c not in unread and not self.on_lifted(hop, c)
        cells = [(r, c) for r in range(array.rows) for c in range(array.cols) if ok((r, c))]
        return {'x': [(hop, a, (a[0] + 1, a[1])) for a in cells if (a[0] + 1, a[1]) in cells],
                'y': [(hop, a, (a[0], a[1] + 1)) for a in cells if (a[0], a[1] + 1) in cells]}

    def pick_edges(self, hop, n, among=None):
        '''n borders an axis, at random -> (x edges, y edges) for measure(): every measurement
        presses other cells (wear, the cells pressed most went dead, 2026-10-12), and n borders
        average out one border's own error (the same border, the same pen: ~0.1mm from run to run;
        two borders 0.2mm apart where the pitch says 2.5). among: {'x', 'y': [edge]} to pick from
        (the reference's borders, for a pen), else every border read. The first of an axis is
        inside the sheet, both its cells off the outer rows and cols: before it the tip is known to
        half a cell, and its sweeps keep that far clear of the sheet's end (find_edge `unsure`).'''
        array = self.array(hop)
        pool = among or self.border_pairs(hop)
        picked = []
        for axis in ('x', 'y'):
            edges = [tuple((e[0], tuple(e[1]), tuple(e[2]))) for e in pool[axis]]
            inner = [e for e in edges if all(0 < c[0] < array.rows - 1 and 0 < c[1] < array.cols - 1 for c in e[1:])]
            if not edges:
                raise FsrError(f"[LRT] no {axis} border to measure on hop {hop}")
            first = self.rng.choice(inner or edges)
            rest = [e for e in edges if e != first]
            picked.append([first] + self.rng.sample(rest, min(n - 1, len(rest))))
        self.machine.say(f"[LRT] borders this time: x {[e[1:] for e in picked[0]]}, y {[e[1:] for e in picked[1]]}")
        return tuple(picked)

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

    def measure(self, bed_z, prior=None, edges=None):
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
            first (the taps press as deep as locate's until the tip is known, see below).'''
            if hop not in found:
                shift, z, at = self.locate(hop, next(v for c, v in bed_z.items() if c[0] == hop), prior)
                found[hop] = {'shift': shift, 'z': z, 'at': at, 'axes': set()}
            f = found[hop]
            xy = np.asarray(self.array(hop).center(*cell), float) - f['shift']
            return f['z'] + self.follow(xy, f['at']), xy

        # X, Y, X, Y: each edge after the first goes by the tip as the edges before found it (both
        # X edges on locate's Y missed their first lines, 2026-10-11)
        # edges: (x edges, y edges), a pick_edges(); the config's without (LRT_FSR_MEASURE, a survey)
        x_edges, y_edges = (list(e) for e in (edges or (cfg['x_edges'], cfg['y_edges'])))
        # The first of an axis on inner cells, as pick_edges() has it: until it, the tip is known to half
        # a cell, and the sweeps keep that far clear of the sheet's end (an outer cell's side is too short)
        def outer(e):
            a = self.array(e[0])
            return not all(0 < c[0] < a.rows - 1 and 0 < c[1] < a.cols - 1 for c in e[1:])
        x_edges, y_edges = sorted(x_edges, key=outer), sorted(y_edges, key=outer)
        per_edge = []
        order = [(axis, edges[i]) for i in range(max(len(x_edges), len(y_edges)))
                 for axis, edges in (('x', x_edges), ('y', y_edges)) if i < len(edges)]
        if self.before_measure:
            self.before_measure()
        self.matrix(True)
        try:
            points, gaps, sigmas, tips = {'x': [], 'y': []}, [], {'x': [], 'y': []}, {'x': [], 'y': []}
            for axis, edge in order:
                hop, cell_a, cell_b = edge
                z_a, xy_a = over(hop, cell_a)
                f = found[hop]
                # The taps' depth, once an X and a Y edge put the tip to ~0.01: this edge's own, on
                # the centres of its two cells, the weaker one's. Found on locate's estimate before,
                # half a cell out, it was often on a border's dead zone: every tap the whole 0.2, and
                # the cells pressed most went dead ((0, 2), (1, 1), (1, 2), 2026-10-12). Found on the
                # strongest cell (1, 6), 0.02: the weaker (2, 5)|(3, 5) had taps on the wrong side,
                # its sigma 0.37-0.57. Each from that cell's own contact estimate, as the taps go.
                if f['axes'] >= {'x', 'y'}:
                    z_b, xy_b = over(hop, cell_b)
                    self.depth[hop] = max(self.depth_on(hop, xy_a, z_a, cell_a),
                                          self.depth_on(hop, xy_b, z_b, cell_b))
                # Where no edge has put the tip yet, it is anywhere on locate's cell: half a cell either
                # way, clear of the sheet's end too (a Y sweep went 0.19mm past col 7's end, simulated)
                half = self.array(hop).pitch / 2
                unsure = (0.0 if 'x' in f['axes'] else half, 0.0 if 'y' in f['axes'] else half)
                point, gap, sigma = self.find_edge(edge, z_a, found[hop]['shift'], at=xy_a, unsure=unsure)
                points[axis].append(point[0 if axis == 'x' else 1])
                gaps.append(gap)
                sigmas[axis].append(sigma)
                # The tip is on that border with the toolhead at `point`: its offset across
                # the border, exactly, for what comes next
                array = self.array(hop)
                ca, cb = (np.asarray(array.center(*c), float) for c in (cell_a, cell_b))
                u = (cb - ca) / np.linalg.norm(cb - ca)
                tips[axis].append(float(np.dot((ca + cb) / 2 - point, u)))
                per_edge.append([axis, hop, list(cell_a), list(cell_b), float(point[0 if axis == 'x' else 1]), float(sigma)])
                f['shift'] = f['shift'] + (tips[axis][-1] - np.dot(f['shift'], u)) * u
                f['axes'].add(axis)
                self.machine.say(f"[LRT] {axis} edge {edge}: {point.round(3)} ±{sigma:.3f} gap={gap:.3f}, "
                                 f"the tip {tips[axis][-1]:.3f} across it")
            z_top, _ = over(z_hop, (z_row, z_col))
            z, sigma_z = self.contact_z(z_hop, z_row, z_col, bed_z[tuple(cfg['z_cell'])], found[z_hop]['shift'],
                                        z_top + cfg['back_off'], prior)
            # Contact over the BLTouch on every cell it probed, not the z cell alone: a tilted pen or
            # one patch of the sheet shows as their spread. A cell that doesn't answer is left out.
            above = {tuple(cfg['z_cell']): (z - bed_z[tuple(cfg['z_cell'])], sigma_z)}
            for cell in bed_z:
                if cell in above or cell[0] != z_hop:
                    continue
                c_top, _ = over(z_hop, cell[1:])
                try:
                    c_z, c_sigma = self.contact_z(z_hop, *cell[1:], bed_z[cell], found[z_hop]['shift'],
                                                  c_top + cfg['back_off'])
                except FsrError as e:
                    self.machine.say(f"[LRT] no contact z on {cell[1:]}, left out: {e}")
                    continue
                above[cell] = (c_z - bed_z[cell], c_sigma)
        finally:
            self.matrix(False)
            if self.after_measure:
                self.after_measure()        # it touched the sheet, even when it stopped
        def mean(axis):
            '''How sure the mean of an axis' edges is: each edge's own sigma, and with two or more
            how far apart the tip offsets they imply are (the same tip, different borders: the
            sheet's ripple, a cell's gain, a stray tap; what one edge's sigma can't see).'''
            v, t = sigmas[axis], tips[axis]
            spread = float(np.var(t, ddof=1)) if len(t) > 1 else 0.0
            return float(np.sqrt((np.mean(np.square(v)) + spread) / len(v)))
        v = [d for d, _ in above.values()]
        z_above = float(np.median(v))
        sigma_z = float(np.sqrt((np.mean([s ** 2 for _, s in above.values()])
                                 + (np.var(v, ddof=1) if len(v) > 1 else 0.0)) / len(v)))
        self.machine.say(f"[LRT] contact over the BLTouch: {z_above:.3f} ±{sigma_z:.3f}, cell by cell "
                         f"{ {c[1:]: round(d, 3) for c, (d, _) in above.items()} }")
        return {
            'z': z,
            'above': z_above,           # contact over the BLTouch z, the median of the cells': what dz is from
            'x': float(np.mean(points['x'])),
            'y': float(np.mean(points['y'])),
            'gaps': gaps,
            'tip': [float(v) for v in found[z_hop]['shift']],
            'sigma': {'x': mean('x'), 'y': mean('y'), 'z': sigma_z},
            'edge_tips': tips,
            'edges': per_edge,
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
        '''The reference tool on the carriage, bed_z just probed -> profile. Its tag's dz is the
        contact over the BLTouch z less `dz_trim`: contact is where the sheet starts to rise, and
        a pen put down at Z1 there only just touched the paper (nothing drawn, 2026-10-09). The
        trim takes every tag's dz down alike, the reference's and the pens' (probe_tool): each
        pen sits that much lower, all of them still the same against each other.'''
        hop = self.cfg['z_cell'][0]
        n = self.cfg.get('edges')
        ref = self.measure(bed_z, edges=self.pick_edges(hop, n[0]) if n else None)
        contact = ref['above']
        tool_z = round(contact - self.dz_trim, 3)
        self.machine.say(f"[LRT] the reference touches {contact:.3f} over the BLTouch z, dz={tool_z:.3f} "
                         f"with the trim of {self.dz_trim:.2f}")
        if max(ref['sigma'].values()) > self.cfg.get('max_sigma', 0.15):
            self.machine.say(f"[LRT] the reference is unsure: ±{ref['sigma']}; every pen measured against it "
                             f"will be as unsure")
        self.machine.gcode_run(f"WRITE_TOOL_TAG DX=0 DY=0 DZ={tool_z:.3f} REFERENCE=1")
        ref['bed_z'] = [[*cell, z] for cell, z in bed_z.items()]
        ref['dz_trim'] = self.dz_trim           # the tags' trim: LRT_MARK TRIM= goes from it
        return {'fsr_ref': ref}

    def probe_tool(self, profile):
        '''The docked tool against the reference -> (dx, dy, dz).
        The edges give where the tool was *sent* when it met them, so a tool
        tip that sits +0.5mm off meets them 0.5mm early: dx = tool - reference.
        Each is as sure as both measurements together; one less sure than `max_sigma`
        stops, the values in the message (better no tag than a wrong one).'''
        ref = profile['fsr_ref']
        self.ref_above = ref.get('above')
        bed_z = {tuple(c[:3]): c[3] for c in ref['bed_z']}
        self.machine.gcode_run("_CLEAR_OFFSETS")
        ref_sigma = ref.get('sigma', {})
        if ref.get('edges') and self.cfg.get('edges'):
            # Border by border against the reference's same border: what one border has of its own
            # (the sheet, a cell's gain) is in both and goes; the uncertainty is how far the borders
            # disagree on the offset, with each one's own sigma
            hop = self.cfg['z_cell'][0]
            theirs = {(a, tuple(ca), tuple(cb)): (point, sigma) for a, h, ca, cb, point, sigma in ref['edges']}
            among = {axis: [(h, tuple(ca), tuple(cb)) for a, h, ca, cb, _, _ in ref['edges'] if a == axis]
                     for axis in ('x', 'y')}
            m = self.measure(bed_z, edges=self.pick_edges(hop, self.cfg.get('edges', (4, 3))[1], among))
            off, sigma = {}, {}
            for axis in ('x', 'y'):
                mine = [(point - theirs[(axis, tuple(ca), tuple(cb))][0],
                         s ** 2 + theirs[(axis, tuple(ca), tuple(cb))][1] ** 2)
                        for a, h, ca, cb, point, s in m['edges'] if a == axis]
                d = np.array([v for v, _ in mine])
                spread = float(np.var(d, ddof=1)) if len(d) > 1 else 0.0
                off[axis] = float(np.mean(d))
                sigma[axis] = float(np.sqrt((np.mean([v for _, v in mine]) + spread) / len(d)))
                self.machine.say(f"[LRT] d{axis} border by border: {[round(float(v), 3) for v in d]}")
                # Borders half a cell or more apart: one of them is off by a cell (the wrong cell named,
                # a lifted row's vote), not noise. The only case worth no tag.
                if len(d) > 1 and np.ptp(d) >= self.array(hop).pitch / 2:
                    raise FsrError(f"[LRT] d{axis} borders {np.ptp(d):.2f}mm apart: one is a cell off, no tag")
            dx, dy = round(off['x'], 3), round(off['y'], 3)
            sigma['z'] = float(np.hypot(m['sigma']['z'], ref_sigma.get('z', 0.0)))
        else:                       # a reference from before its borders were kept: by the means
            m = self.measure(bed_z)
            dx = round(m['x'] - ref['x'], 3)
            dy = round(m['y'] - ref['y'], 3)
            sigma = {k: float(np.hypot(m['sigma'][k], ref_sigma.get(k, 0.0))) for k in ('x', 'y', 'z')}
        dz = round(m['above'] - self.dz_trim, 3)        # as the reference's
        said = (f"dx={dx} ±{sigma['x']:.3f} dy={dy} ±{sigma['y']:.3f} dz={dz} ±{sigma['z']:.3f} "
                f"gaps={[round(g, 3) for g in m['gaps']]}")
        # Unsure is still far better than no tag (a pen ~4mm off, refused at ±0.33, 2026-10-12): written,
        # and said as rough
        if max(sigma.values()) > self.cfg.get('max_sigma', 0.15):
            self.machine.say(f"[LRT] rough (over ±{self.cfg.get('max_sigma', 0.15)}), written all the same: {said}")
        self.machine.say(f"[LRT] offsets {said}")
        return dx, dy, dz
