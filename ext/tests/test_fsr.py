# uv run python ext/tests/test_fsr.py
import copy

import numpy as np

from fakes import FakeDock, ProbeResult, run_tests
from limn.beds import BEDS
from limn.fsr import Fsr, FsrError
from limn.geometry import FsrArray
from limn.samples import Samples, Sample, FSR, S_MATRIX

PROBE_OFFSET = (-34.34, 25.0, 0.8)
FRAME = 0.03    # s between FSR frames


def bed_z(x, y):
    return 0.01 * x + 0.005 * y     # not level


def bed_cfg():
    return copy.deepcopy(BEDS['BED_5']['fsr'])


def old_cfg():
    '''BED_5's config for the sheet it had until 2026-10-07 (a glue void: cols 3 and 4 faulty,
    the aim moved off them), the one the bed5 model (FsrBed.frame_bed5) is measured from.'''
    cfg = bed_cfg()
    cfg['arrays'][0].update(faulty_cols=(3, 4), aim=(1.5, 6.3), dead_rows=(3,))
    return cfg


class FsrBed:
    '''The plotter over BED_5: a docked tool whose tip sits `tip` off the
    toolhead, pressing on an FSR array with a dead zone between cells.'''

    def __init__(self, samples, dock, cfg, tip=(0.0, 0.0), tool_length=1.8, dead=0.4, gain=2000,
                 noise=8, alive_for=None, responds=True, spike=False, disconnect_after=None,
                 crosstalk=False, width=0.0, slope_y=0.0, mesh=True, row_crosstalk=0.0, wipes=(), ghost=None,
                 dead_lifts=0.0, bed5=False, fresh=False, shift=(0.0, 0.0), dead_cols=(), preload=None, hover=None,
                 patchy=0.0):
        self.samples = samples
        self.dock = dock
        # shift: the sheet sits that far from where the config has it (a swap)
        self.arrays = [FsrArray(a['hop'], np.asarray(a['origin'], float) + np.asarray(shift, float),
                                a['col_dir'], a['row_dir'], cfg['pitch']) for a in cfg['arrays']]
        self.dead_cols = set(dead_cols)         # columns whose line doesn't answer (a ribbon off)
        self.preload = preload or {}            # {cell: level} at rest, nothing on it (the new sheet's (3, 0): 80-130)
        self.hover = hover or {}                # {row: level} with the tool over the sheet (its row 3: 30-50)
        self.pos = [0.0, 0.0, cfg['z_park']]
        self.t = 0.0
        self.tool = None
        self.tip = np.array(tip)
        self.tool_length = tool_length
        self.dead = dead
        self.gain = gain
        self.noise = noise
        self.alive_for = alive_for              # frames stop after this many seconds
        self.responds = responds
        self.spike = spike
        self.disconnect_after = disconnect_after
        self.crosstalk = crosstalk              # as on BED_5: a press lifts its column's other rows (measured, see frame)
        self.width = width                      # tip radius: near an edge it presses both cells, each less
        self.slope_y = slope_y                  # the sheet rises this much per mm in Y, on top of bed_z
        self.mesh = mesh                        # an lrt_fsr mesh of it, as LRT_MESH_CALIBRATE takes
        self.row_crosstalk = row_crosstalk      # a press lifts the rest of its row by this share of it
        self.dead_lifts = dead_lifts            # a press on row 3 (no series resistor) lifts its column's rows by this share
        self.bed5 = bed5                        # BED_5 with a Stabilo as measured on the plotter, 2026-10-07: see frame_bed5
        self.fresh = fresh                      # bed5's physics, but a sheet without the old one's faults
        self.patchy = patchy                    # bed5: a pressed cell reads up to this share more or less, by where
        self.max_press = 0.0                    # the deepest press past first touch seen
        self.wipes = wipes                      # (from s, to s, cells, strength): a hand on the sheet
        self.ghost = ghost                      # (from, to mm over contact, cell, strength): a reading in the air
        self.rng = np.random.default_rng(7)
        self.lowest_z = 99.0
        self.dragged = False
        self.ran = []

    def tip_xy(self):
        return np.array(self.pos[:2]) + self.tip

    def sheet(self, x, y):
        return bed_z(x, y) + self.slope_y * (y - 50)

    def press(self):
        if self.tool is None:
            return 0.0
        return self.sheet(*self.tip_xy()) - (self.pos[2] - self.tool_length)

    def mesh_profile(self, name):
        '''The sheet probed on a 4 x 5 grid over the array (beds.py lrt_fsr), with the
        BLTouch's offset, the way bed_mesh keeps it.'''
        if not self.mesh:
            return None
        x0, y0, x1, y1 = 111, 40, 118.5, 57
        return {'mesh_params': {'min_x': x0, 'max_x': x1, 'min_y': y0, 'max_y': y1, 'x_count': 4, 'y_count': 5},
                'points': [[self.sheet(x, y) - 2.0 for x in np.linspace(x0, x1, 4)] for y in np.linspace(y0, y1, 5)]}

    def move(self, x=None, y=None, z=None, speed=None):
        if (x is not None or y is not None) and self.press() > 0:
            self.dragged = True
        for i, v in enumerate((x, y, z)):
            if v is not None:
                self.pos[i] = float(v)
        if self.tool is not None:
            self.lowest_z = min(self.lowest_z, self.pos[2])

    def wait_moves(self):
        pass

    def now(self):
        return self.t

    def pause(self, seconds):
        end = self.t + seconds
        while self.t < end:
            self.t = round(self.t + FRAME, 6)
            if self.disconnect_after is not None and self.t > self.disconnect_after:
                raise ConnectionError("Dock went away")
            if self.alive_for is not None and self.t > self.alive_for:
                continue
            for array in self.arrays:
                if array.hop in self.dock.matrix:
                    self.samples.add(Sample(self.t, array.hop, FSR, S_MATRIX, self.frame(array)))

    def shares(self, array):
        '''{cell: share of the press}: 1 inside a cell's active area, less for a
        cell whose area is within `width` of the tip, none in the dead zone.'''
        if self.press() <= 0 or not self.responds:
            return {}
        local = self.tip_xy() - array.origin
        u, v = np.dot(local, array.col_dir), np.dot(local, array.row_dir)
        margin, out = self.dead / 2, {}
        for row in range(array.rows):
            for col in range(array.cols):
                du = max(col * array.pitch + margin - u, 0, u - (col + 1) * array.pitch + margin)
                dv = max(row * array.pitch + margin - v, 0, v - (row + 1) * array.pitch + margin)
                d = np.hypot(du, dv)
                if d == 0 or d < self.width:
                    out[(row, col)] = 1.0 if d == 0 else 1 - d / self.width
        return out

    # BED_5 as measured with the Stabilo, 2026-10-07 (~/limn-shot/fsr-2026-10-07-manual.jsonl):
    # (1, 1) read 112, 201, 319, 461, 523, 573 at 0.01 .. 0.13mm past first touch, then less;
    # its column's row 0 0.94 of it at first touch, ~0.4 from 0.07mm on, row 2 0.8 -> 0.37,
    # row 3 (dead) ~1; (2, 4) never over ~230; a 0.2mm step in X: 545 / 625; column 3 ~75 at rest.
    WEAK = {(2, 4): 0.38}
    COLUMN = {0: (0.40, 0.55), 2: (0.37, 0.45), 3: (0.95, 0.0)}     # share of the pressed cell: base + extra at first touch
    # The new sheet (2026-10-07): rows 0-2 ~0.15 of the pressed cell up its column, row 3 ~0.35
    FRESH_COLUMN = {3: (0.35, 0.1)}
    FRESH_OTHER = (0.15, 0.1)
    ROW = (0.35, 0.6)                                               # along its row, the same way

    def frame_bed5(self, array):
        p = self.press()
        self.max_press = max(self.max_press, p)
        shares = self.shares(array)
        curve = 600 * (1 - np.exp(-p / 0.05)) if p > 0 else 0.0
        first = 1 / (1 + (max(p, 0) / 0.035) ** 4)                 # 1 at first touch, ~0 from 0.07mm
        ripple = 1 + 0.07 * np.cos(2 * np.pi * self.tip_xy()[0] / 0.4)
        # Patchier, as one scan of the real sheet was: (1, 1) read 485, 208, 427, 632, 322, 784
        # 0.2mm apart at one z (2026-10-07, fsr-2026-10-07-manual.jsonl #1); its crosstalk not
        x, y = self.tip_xy()
        patch = 1 + self.patchy * np.sin(2 * np.pi * x / 0.8 + 1.3) * np.sin(2 * np.pi * y / 0.9 + 0.4)
        weak = {} if self.fresh else self.WEAK
        pressed = {c: curve * s * weak.get(c, 1.0) * ripple for c, s in shares.items() if c[1] not in self.dead_cols}
        values = []
        for row in range(array.rows):
            for col in range(array.cols):
                # Its baseline drifts by tens, slowly and cell by cell, as the real one does
                drift = 15 * (1 + np.sin(self.t / 40 + 1.7 * row + 2.9 * col))
                s = abs(self.rng.normal(0, 4)) + drift + (75 if col == 3 and not self.fresh else 0)
                s += self.preload.get((row, col), 0) * (1 + 0.25 * np.sin(self.t / 7))
                s += self.hover.get(row, 0) if self.tool is not None else 0
                if (row, col) in pressed:
                    s += pressed[(row, col)] * patch
                else:
                    column = max((v for (r_, c), v in pressed.items() if c == col), default=0)
                    base, extra = (self.FRESH_COLUMN.get(row, self.FRESH_OTHER) if self.fresh
                                   else self.COLUMN.get(row, (0.4, 0.5)))
                    # Along the row too (a Micron's press lifted its row by 0.73 of it, 2026-09-29):
                    # strong at first touch, as up the column
                    along = max((v for (r_, c), v in pressed.items() if r_ == row), default=0)
                    s += max(column * (base + extra * first), along * (self.ROW[0] + self.ROW[1] * first))
                values.append([row, col, int(min(s, 1000))])
        return values

    def frame(self, array):
        if self.bed5:
            return self.frame_bed5(array)
        shares = self.shares(array)
        columns = {c for _, c in shares}
        pressed = min(880, self.press() * self.gain)
        rows = {r: max(v for (rr, _), v in shares.items() if rr == r) for r, _ in shares}
        values = []
        for row in range(array.rows):
            for col in range(array.cols):
                s = abs(self.rng.normal(0, self.noise))
                if (row, col) in shares:
                    s = 1000 if self.spike else min(880, self.press() * self.gain) * shares[(row, col)] + s
                elif self.dead_lifts and (3, col) in shares:
                    s += self.dead_lifts * pressed * shares[(3, col)]
                elif self.crosstalk and col in columns:
                    # Up the column, as measured (2026-10-07): row 3 ~0.95 of the pressed cell,
                    # row 0 0.94 of it at first touch falling to ~0.4 by 0.07mm, row 2 0.8 -> 0.37
                    first = 1 / (1 + (max(self.press(), 0) / 0.035) ** 4)
                    column = max(min(880, self.press() * self.gain) * v for (r_, c), v in shares.items() if c == col)
                    base, extra = {3: (0.95, 0.0), 0: (0.40, 0.55)}.get(row, (0.37, 0.45))
                    s += column * (base + extra * first)
                elif row in rows:
                    s += self.row_crosstalk * pressed * rows[row]
                if self.ghost and self.tool is not None and (row, col) == self.ghost[2] \
                        and self.ghost[0] <= -self.press() <= self.ghost[1]:
                    s = max(s, self.ghost[3])
                for t0, t1, cells, strength in self.wipes:
                    if t0 <= self.t < t1 and (row, col) in cells:
                        s = strength
                values.append([row, col, int(s)])
        return values

    def probe_offsets(self):
        return PROBE_OFFSET

    def probe(self):
        x, y = self.pos[:2]
        z = self.sheet(x + PROBE_OFFSET[0], y + PROBE_OFFSET[1]) + PROBE_OFFSET[2]
        return ProbeResult(x, y, z, x, y, z)

    def gcode_run(self, script):
        self.ran.append(script)
        if script == 'T4':
            self.tool = 'T4'
        if script == 'UNDOCK':
            self.tool = None

    def say(self, msg):
        pass


def setup(cfg=None, **kw):
    cfg = cfg or (old_cfg() if kw.get('bed5') else bed_cfg())
    samples, dock = Samples(), FakeDock()
    bed = FsrBed(samples, dock, cfg, **kw)
    return Fsr(bed, dock, samples, cfg), bed, dock

def floor_of(fsr, profile):
    cfg = fsr.cfg
    return min(c[3] for c in profile['fsr_ref']['bed_z']) + cfg['tool_z'][0]

def calibrated():
    fsr, bed, dock = setup()
    return fsr.calibrate()


def test_calibrate():
    fsr, bed, dock = setup()
    profile = fsr.calibrate()
    ref = profile['fsr_ref']
    assert [s.split()[0] for s in bed.ran[:3]] == ['UNDOCK', 'G28', '_CLEAR_OFFSETS']
    assert bed.ran[-1].startswith('WRITE_TOOL_TAG DX=0 DY=0 DZ=')
    # The edges sit between the cells: x = 111 + 2 * 2.5 between rows, y = 59.6 - 2 * 2.5 between cols 1 and 2.
    assert abs(ref['x'] - 116.0) < 0.03 and abs(ref['y'] - 54.6) < 0.03
    assert all(0.3 < g < 0.5 for g in ref['gaps'])
    assert all(v < 0.05 for v in ref['sigma'].values()), ref['sigma']
    assert not bed.dragged
    assert bed.pos[2] == fsr.cfg['z_park']
    assert not dock.matrix, 'matrix mode left on'

def test_tool_offsets():
    profile = calibrated()
    fsr, bed, _ = setup(tip=(0.35, -0.2), tool_length=2.2)
    bed.tool = 'T1'
    dx, dy, dz = fsr.probe_tool(profile)
    assert abs(dx + 0.35) < 0.03 and abs(dy - 0.2) < 0.03
    ref_fsr, ref_bed, _ = setup()
    ref_bed.tool = 'T4'
    _, _, ref_dz = ref_fsr.probe_tool(profile)
    assert abs(ref_dz + ref_fsr.dz_trim - 1.0) < 0.1 and abs(dz - ref_dz - 0.4) < 0.03     # contact ~1.0 over the BLTouch
    assert not bed.dragged and bed.lowest_z >= floor_of(fsr, profile)

def test_crosstalk_up_the_column():
    '''BED_5: a press lifts row 3 of its column to ~530 at once, before the pressed
    cell gets there. Measured all the same, far off too.'''
    fsr, bed, _ = setup(crosstalk=True)
    profile = fsr.calibrate()
    for tip in ((0.35, -0.2), (3.4, -3.5), (-1.6, -0.9)):
        fsr, bed, _ = setup(tip=tip, crosstalk=True)
        bed.tool = 'T1'
        dx, dy, _ = fsr.probe_tool(profile)
        assert abs(dx + tip[0]) < 0.03 and abs(dy + tip[1]) < 0.03, (tip, dx, dy)
        assert not bed.dragged and bed.lowest_z >= floor_of(fsr, profile)

def test_prior_brings_the_tip_down_on_the_aim():
    '''Without a prior this tip lands on the edge between rows 0 and 1 at the aim
    (a dead zone for a tip this fine): the first descent's second spot, half a cell
    over, finds it (it went to the floor before). Told where it is, it comes down mid cell.'''
    profile = calibrated()
    tip = (-1.25, 0.6)
    fsr, bed, _ = setup(tip=tip)
    bed.tool = 'T0'
    dx, dy, _ = fsr.probe_tool(profile)
    assert abs(dx - 1.25) < 0.03 and abs(dy + 0.6) < 0.03, (dx, dy)
    fsr, bed, _ = setup(tip=tip)
    bed.tool = 'T0'
    bed_z = {tuple(c[:3]): c[3] for c in profile['fsr_ref']['bed_z']}
    m = fsr.measure(bed_z, {'tip': (-1.2, 0.7), 'z': None})
    assert abs(m['x'] - profile['fsr_ref']['x'] - 1.25) < 0.03 and abs(m['y'] - profile['fsr_ref']['y'] + 0.6) < 0.03
    assert abs(m['tip'][0] - tip[0]) < 0.5 and abs(m['tip'][1] - tip[1]) < 0.5

def test_prior_z_keeps_a_miss_short():
    '''Told where contact is expected, a miss goes only prior_margin below it.'''
    profile = calibrated()
    bed_z = {tuple(c[:3]): c[3] for c in profile['fsr_ref']['bed_z']}
    fsr, bed, _ = setup(tip=(-6.0, 0.0))           # off the rows, from the second spot too
    bed.tool = 'T0'
    expected = bed_z[(1, 1, 1)] + 1.0                # where this tool's contact would be
    try:
        fsr.measure(bed_z, {'tip': None, 'z': expected})
        assert False, 'should stop'
    except FsrError as e:
        assert 'no contact' in str(e)
    assert bed.lowest_z >= expected - fsr.cfg['prior_margin'] - 1e-9
    assert bed.pos[2] == fsr.cfg['z_park']

def test_tip_on_an_edge_with_crosstalk():
    '''Seen with a 0.05 fineliner: its tip on the edge between rows 1 and 2 at the
    aim, each row a third of a press, and row 0's crosstalk as strong. That is no
    edge between rows 0 and 1.'''
    fsr, bed, _ = setup(crosstalk=True, width=0.3)
    profile = fsr.calibrate()
    for tip in ((1.25, 0.0), (1.25, 0.6), (-1.25, -0.4)):   # on the 1|2 edge, the 0|1 edge
        fsr, bed, _ = setup(tip=tip, crosstalk=True, width=0.3)
        bed.tool = 'T3'
        dx, dy, _ = fsr.probe_tool(profile)
        assert abs(dx + tip[0]) < 0.05 and abs(dy + tip[1]) < 0.05, (tip, dx, dy)
    # On a corner of four cells each gets a few percent, only the crosstalk shows; the
    # first descent's second spot, half a cell over, comes down on a cell and measures it
    fsr, bed, _ = setup(tip=(1.25, 1.25), crosstalk=True, width=0.3)
    bed.tool = 'T3'
    dx, dy, _ = fsr.probe_tool(profile)
    assert abs(dx + 1.25) < 0.05 and abs(dy + 1.25) < 0.05, (dx, dy)
    assert bed.pos[2] == fsr.cfg['z_park'] and not bed.dragged

def test_taps_follow_the_sheet():
    '''Seen with a fine Micron: the sheet drops ~0.05mm per mm towards -Y, and a
    tip that needs its whole press to register lost it over the 5mm searches.
    With the lrt_fsr mesh the taps keep the press.'''
    fine = dict(gain=700, slope_y=0.05)       # 150 needs 0.21mm of the 0.3mm press
    fsr, bed, _ = setup(**fine)
    profile = fsr.calibrate()
    for tip in ((0.35, -0.2), (-1.0, 2.2)):
        fsr, bed, _ = setup(tip=tip, **fine)
        bed.tool = 'T0'
        dx, dy, _ = fsr.probe_tool(profile)
        assert abs(dx + tip[0]) < 0.03 and abs(dy + tip[1]) < 0.03, (tip, dx, dy)
    # Each tap keeps the press: at the far end of a 5mm search towards -Y as
    # much as where the contact was found. Flat, a quarter mm of it would be gone.
    fsr, bed, _ = setup(**fine)
    fsr.surface = bed.mesh_profile('lrt_fsr')
    bed.tool = 'T0'
    at = np.array([114.75, 50.85])
    z_press = bed.sheet(*at) + bed.tool_length - 0.3
    depth = []
    fsr.read = lambda hop: depth.append(bed.press()) or {}
    for xy in (at, at - (0, 2.5), at - (0, 5)):
        fsr.tap(1, xy, z_press, z_press + 1.3, at)
    assert all(abs(d - 0.3) < 0.01 for d in depth), depth
    fsr.surface, depth[:] = None, []
    fsr.tap(1, at - (0, 5), z_press, z_press + 1.3, at)
    assert depth[0] < 0.1, depth

def test_taps_press_only_as_deep_as_needed():
    '''A Stabilo read ~460 at 0.05mm past contact and ~670 at 0.3mm, and 0.3mm taps
    left marks (2026-09-29): a felt tip presses until press_strength, a fine
    tip as deep as it needs, never more than `press` past contact.'''
    def deepest(cfg=None, **kw):
        cfg = cfg or bed_cfg()
        fsr, bed, _ = setup(cfg=copy.deepcopy(cfg), **kw)
        profile = fsr.calibrate()
        fsr, bed, _ = setup(cfg=copy.deepcopy(cfg), tip=(0.35, -0.2), **kw)
        bed.tool = 'T1'
        presses, read = [], fsr.read
        fsr.read = lambda hop, limit=True: presses.append(bed.press()) or read(hop, limit)
        dx, dy, _ = fsr.probe_tool(profile)
        assert abs(dx + 0.35) < 0.03 and abs(dy - 0.2) < 0.03, (kw, dx, dy)
        assert not bed.dragged
        return max(presses), fsr.depth[1]
    felt = dict(gain=9000)                      # 150 at 0.017mm, 450 at 0.05mm
    press, depth = deepest(**felt)
    assert depth <= 0.06 and press < 0.13, (press, depth)
    old = {**bed_cfg(), 'press_strength': None, 'step': 0.2, 'sure': 700}
    old_press, _ = deepest(old, **felt)
    assert old_press > 0.3 and press < old_press / 2.5, (press, old_press)
    fine = dict(gain=700)                       # 150 at 0.21mm: 450 never within 0.3 past it
    press, depth = deepest(**fine)
    # contact is a fine step late at most, and ~0.01 for its rise over the air (the noise in it)
    assert abs(depth - bed_cfg()['press']) < 1e-9 and press < 0.21 + 0.3 + 0.04, (press, depth)

def test_crosstalk_along_the_row():
    '''A Micron pressing (1,5) at 355 lifted (1,3) to 259 (0.73 of it). Here 0.8:
    it must not count as responding, or the search "finds" the tip there.'''
    fsr, bed, _ = setup(row_crosstalk=0.8)
    profile = fsr.calibrate()
    for tip in ((0.35, -0.2), (0.9, 1.6)):
        fsr, bed, _ = setup(tip=tip, row_crosstalk=0.8)
        bed.tool = 'T1'
        dx, dy, _ = fsr.probe_tool(profile)
        assert abs(dx + tip[0]) < 0.03 and abs(dy + tip[1]) < 0.03, (tip, dx, dy)
    # The Micron's case: its tip told (it would land on a dead zone otherwise)
    bed_z = {tuple(c[:3]): c[3] for c in profile['fsr_ref']['bed_z']}
    fsr, bed, _ = setup(tip=(-1.3, 0.95), row_crosstalk=0.8)
    bed.tool = 'T0'
    m = fsr.measure(bed_z, {'tip': (-1.2, 1.1), 'z': None})
    assert abs(m['x'] - profile['fsr_ref']['x'] - 1.3) < 0.03 and abs(m['y'] - profile['fsr_ref']['y'] + 0.95) < 0.03

def test_waits_for_the_sheet_to_be_wiped():
    '''A cloth over the sheet: presses on several cells, hard, then nothing.'''
    wipe = (5.0, 7.0, {(0, 1), (1, 2), (2, 4), (1, 6)}, 1000)
    fsr, bed, dock = setup(wipes=[wipe])
    bed.tool = 'T1'
    fsr.wait_clean()
    clean = fsr.cfg['clean']
    assert tuple(bed.pos[:2]) == clean['park'] and bed.pos[2] == fsr.cfg['z_park']
    assert 7.0 + clean['quiet'] <= bed.t < 7.0 + clean['quiet'] + 1.0, bed.t
    assert bed.ran == ['_BUZZ_WARN', '_BUZZ_DOOP'] and not dock.matrix

def test_a_brush_on_one_cell_is_no_wipe():
    fsr, bed, dock = setup(wipes=[(1.0, 2.0, {(1, 2)}, 600)])
    fsr.cfg = {**fsr.cfg, 'clean': {**fsr.cfg['clean'], 'timeout': 20}}
    bed.tool = 'T1'
    try:
        fsr.wait_clean()
        assert False, 'should give up'
    except FsrError as e:
        assert "wasn't wiped" in str(e) and '1 of 3' in str(e), e
    assert not dock.matrix

def test_dead_sensor_lifts():
    profile = calibrated()
    fsr, bed, _ = setup(alive_for=1.0)
    bed.tool = 'T1'
    try:
        fsr.probe_tool(profile)
        assert False, 'should stop'
    except FsrError as e:
        assert 'no frames' in str(e) and 'hop 1 FSR state 43' in str(e), e
    assert bed.pos[2] == fsr.cfg['z_park']

def test_no_frames_says_what_was_heard():
    fsr, bed, _ = setup(alive_for=0.0)          # nothing at all
    bed.tool = 'T1'
    try:
        fsr.measure({(1, 1, 1): 1.0})
        assert False, 'should stop'
    except FsrError as e:
        assert 'nothing from any node' in str(e), e
    fsr, bed, _ = setup(alive_for=0.0)          # only touch samples: old firmware
    bed.samples.add(Sample(0.0, 1, FSR, 42, [[1, 3, 400]]))
    try:
        fsr.measure({(1, 1, 1): 1.0})
        assert False, 'should stop'
    except FsrError as e:
        assert 'hop 1 FSR state 42 x1' in str(e) and 'mcu.py update' in str(e), e
    assert bed.pos[2] == fsr.cfg['z_park']

def test_no_contact_stops_at_the_floor():
    profile = calibrated()
    fsr, bed, _ = setup(responds=False)
    bed.tool = 'T1'
    try:
        fsr.probe_tool(profile)
        assert False, 'should stop'
    except FsrError as e:
        assert 'no contact' in str(e)
    assert bed.lowest_z >= floor_of(fsr, profile) - 1e-9
    assert bed.pos[2] == fsr.cfg['z_park']

def test_pressing_too_hard_lifts():
    profile = calibrated()
    fsr, bed, _ = setup(spike=True)
    bed.tool = 'T1'
    try:
        fsr.probe_tool(profile)
        assert False, 'should stop'
    except FsrError as e:
        assert 'too hard' in str(e)
    assert bed.pos[2] == fsr.cfg['z_park']

def test_dock_disconnect_lifts():
    profile = calibrated()
    fsr, bed, _ = setup(disconnect_after=3.0)
    bed.tool = 'T1'
    try:
        fsr.probe_tool(profile)
        assert False, 'should stop'
    except ConnectionError:
        pass
    assert bed.pos[2] == fsr.cfg['z_park']

def test_tools_far_off():
    '''A few mm off in X (rows 0-2) and more in Y (8 cols, -4.25..+15.75 from the aim): found, and
    measured. Not where the tip lands on the faulty columns 3 and 4 (~+3.3..+8.3 in Y): never read.'''
    profile = calibrated()
    for tip in ((3.4, -3.5), (-2.0, 1.0), (3.0, 1.9), (-1.6, -0.9)):
        fsr, bed, _ = setup(tip=tip)
        bed.tool = 'T1'
        dx, dy, _ = fsr.probe_tool(profile)
        assert abs(dx + tip[0]) < 0.03 and abs(dy + tip[1]) < 0.03, (tip, dx, dy)
        assert not bed.dragged and bed.lowest_z >= floor_of(fsr, profile)

def test_off_the_array_stops_at_the_floor():
    profile = calibrated()
    # Misses the rows, from both spots of the first descent
    for tip in ((-6.0, 0.0), (-6.0, 1.25)):
        fsr, bed, _ = setup(tip=tip)
        bed.tool = 'T1'
        try:
            fsr.probe_tool(profile)
            assert False, 'should stop'
        except FsrError as e:
            assert 'no contact' in str(e) and 'over the array' in str(e)
        assert bed.lowest_z >= floor_of(fsr, profile) - 1e-9
        assert bed.pos[2] == fsr.cfg['z_park']

def test_array_origin_only_roughly_right():
    profile = calibrated()
    cfg = bed_cfg()
    fsr, bed, _ = setup(cfg=cfg, tip=(0.35, -0.2))
    cfg['arrays'][0]['origin'] = (112.5, 58.8)     # we aim off, the cells are where they were
    fsr.arrays = {a['hop']: a for a in cfg['arrays']}
    bed.tool = 'T1'
    dx, dy, _ = fsr.probe_tool(profile)
    assert abs(dx + 0.35) < 0.03 and abs(dy - 0.2) < 0.03

def test_unmeasured_array_is_refused():
    cfg = bed_cfg()
    cfg['arrays'][0]['origin'] = None
    fsr, bed, _ = setup()
    fsr.cfg = cfg
    fsr.arrays = {a['hop']: a for a in cfg['arrays']}
    try:
        fsr.array(1)
        assert False
    except FsrError as e:
        assert 'not set' in str(e)


def test_a_reading_in_the_air_is_a_false_start():
    """Seen with a bent 0.05 liner, 2026-09-30: a cell read over `respond` with the
    tip still in the air, and pressed in from there nothing did. It goes on down."""
    profile = calibrated()
    for ghost in ((0.7, 0.95, (0, 4), 170), (0.3, 0.6, (2, 0), 160)):
        fsr, bed, _ = setup(tip=(0.35, -0.2), ghost=ghost)
        bed.tool = 'T1'
        dx, dy, dz = fsr.probe_tool(profile)
        assert abs(dx + 0.35) < 0.03 and abs(dy - 0.2) < 0.03, (ghost, dx, dy)
        assert not bed.dragged


def test_taps_never_deeper_than_the_pen_presses_plotting():
    '''A fine tip never reaches press_strength: it went the whole `press` (0.3mm) on
    every tap, deeper than it ever presses plotting. press_cap: its own press.'''
    fsr, bed, _ = setup(cfg=copy.deepcopy(bed_cfg()), gain=700)
    profile = fsr.calibrate()
    fsr, bed, _ = setup(cfg=copy.deepcopy(bed_cfg()), gain=700, tip=(0.35, -0.2))
    bed.tool = 'T1'
    fsr.press_cap = 0.1
    dx, dy, _ = fsr.probe_tool(profile)
    assert abs(fsr.depth[1] - 0.1) < 1e-9 and abs(dx + 0.35) < 0.03 and abs(dy - 0.2) < 0.03

def test_a_press_on_another_cell_is_a_contact_too():
    '''A fineliner off by a cell pressed its neighbour, and LRT_FSR_Z went on down to the floor
    (2026-10-07), then stopped "another cell responds". The tip touched the sheet all the same:
    its contact is measured, a little less sure, never pressed in more than the confirmation.'''
    fsr, bed, _ = setup(cfg=copy.deepcopy(bed_cfg()), gain=700, tip=(2.5, 0))     # a row off: (2, 1) under it
    bed.tool = 'T1'
    presses, read = [], fsr.read
    fsr.read = lambda hop, limit=True: presses.append(bed.press()) or read(hop, limit)
    fsr.matrix(True)
    x, y = fsr.array(1).center(1, 1)
    z, sigma = fsr.contact_z(1, 1, 1, bed_z(x, y))
    touch = bed.sheet(x + 2.5, y) + bed.tool_length          # where it touches, under the tip
    onset = fsr.cfg['early'] / 700                            # where it rises `early`: 60 at 0.086mm
    assert abs(z - (touch - onset)) < 0.03, (z, touch)
    assert sigma >= fsr.cfg['off_cell'] and sigma < 0.05, sigma
    assert max(presses) < onset + 0.02 * (fsr.cfg['confirm'] + 1) + 0.01, max(presses)

def test_the_border_from_real_taps():
    '''A sweep along X over column 1 of the new sheet, a tap every 0.5mm, as recorded on the plotter
    (2026-10-07, ~/limn-shot/fsr-2026-10-07-manual.jsonl #30, the strongest six cells of each tap).
    Its readings: (1, 1) 383-525 over its row with the column's other rows 60-160 and (1, 0) up to 488
    at times (that sheet's leak); rows 0-1 lift row 3 over row 2. The three borders come out a pitch
    apart, no tap on the wrong side.'''
    from limn.fsr import border
    taps = [(110.5, {}), (111.0, {}), (111.5, {}), (112.0, {'3,1': 65, '1,1': 51, '2,1': 49, '0,1': 46}),
            (112.5, {'0,1': 423, '0,0': 181, '1,1': 100, '3,1': 83, '2,1': 71}),
            (113.0, {'0,1': 506, '0,0': 349, '1,1': 103, '3,1': 99, '2,1': 68}),
            (113.5, {'0,0': 626, '0,1': 207, '1,1': 58, '1,0': 53, '3,1': 49}),
            (114.0, {'0,1': 280, '0,0': 277, '1,1': 82, '3,1': 75, '2,1': 57}),
            (114.5, {'1,1': 480, '1,0': 155, '2,1': 110, '3,1': 106, '0,1': 101}),
            (115.0, {'1,1': 483, '1,0': 331, '3,1': 164, '2,1': 126, '0,1': 109}),
            (115.5, {'1,1': 383, '1,0': 136, '3,1': 108, '2,1': 105, '0,1': 96}),
            (116.0, {'1,1': 525, '1,0': 488, '3,1': 155, '2,1': 132, '0,1': 106}),
            (116.5, {'1,1': 525, '1,0': 460, '2,1': 97, '0,1': 90, '3,1': 80}),
            (117.0, {'2,1': 501, '1,1': 299, '2,0': 129, '3,1': 121, '0,1': 92, '1,0': 65}),
            (117.5, {'2,1': 387, '3,1': 228, '1,1': 106, '0,1': 69, '2,0': 59}),
            (118.0, {'2,1': 621, '3,1': 230, '2,0': 189, '1,1': 117, '0,1': 66, '1,2': 32}),
            (118.5, {'2,0': 616, '2,1': 513, '3,1': 162, '1,1': 106, '0,1': 67, '1,0': 49}),
            (119.0, {'2,1': 626, '3,1': 281, '2,0': 278, '1,1': 117, '0,1': 76}),
            (119.5, {'3,1': 464, '2,1': 85, '0,1': 74, '1,1': 63, '0,2': 24}),
            (120.0, {'3,1': 510, '2,1': 105, '1,1': 69, '0,1': 66, '0,2': 28}),
            (120.5, {'3,1': 531, '2,1': 101, '1,1': 69, '0,1': 65}),
            (121.0, {'3,1': 529, '2,1': 100, '1,1': 79, '0,1': 73}),
            (121.5, {'3,0': 441, '2,0': 35, '0,0': 23, '1,0': 22})]
    found = []
    for a, b in (('0,1', '1,1'), ('1,1', '2,1'), ('2,1', '3,1')):
        t0, gap, sigma, wrong, _ = border({x: (s.get(a, 0), s.get(b, 0), max(s.values(), default=0)) for x, s in taps}, 150)
        assert sigma < 0.15 and wrong == 0, (a, b, sigma, wrong)
        found.append(t0)
    assert np.allclose(np.diff(found), 2.5, atol=0.05), found
    # The old rule (a cell 'responds' over 150 and 0.9 of the strongest) on the same taps: with (1, 0)'s
    # leak at 488 next to (1, 1)'s 525 one tap more and the search would have turned there
    assert 460 / 525 < 0.9 < 488 / 525

def test_a_tip_a_cell_off_from_locate_is_measured():
    '''locate put the Stabilo's tip at Y 3.87 for 2.13 (2026-10-07), and LRT_CALIBRATE stopped. The
    sweeps reach two cells' width: 2mm off, the borders are found all the same.'''
    profile = calibrated()
    fsr, bed, _ = setup(tip=(0.35, -0.2))
    bed.tool = 'T1'
    locate = fsr.locate
    def off(*a, **k):
        shift, z, at = locate(*a, **k)
        return shift + np.array([0.0, 2.0]), z, at          # 2mm off in Y: lands a column over
    fsr.locate = off
    dx, dy, _ = fsr.probe_tool(profile)
    assert abs(dx + 0.35) < 0.03 and abs(dy - 0.2) < 0.03, (dx, dy)

def test_a_tap_that_can_go_either_way_is_said_so():
    '''Taps on the wrong side of a border (a sheet's leak, a twitch): the border is still where most
    of them say, and the sigma grows with how far off they were, so an unsure pen gets no tag.'''
    from limn.fsr import border
    clean = {round(t, 2): ((400.0, 100.0, 400.0) if t < 0 else (100.0, 400.0, 400.0)) for t in np.arange(-2.5, 2.51, 0.25)}
    t0, _, sigma, wrong, _ = border(clean, 150)
    assert abs(t0) < 0.15 and wrong == 0 and sigma < 0.1, (t0, sigma)
    stray = {**clean, -1.5: (100.0, 400.0, 400.0)}
    t1, _, sigma1, wrong1, _ = border(stray, 150)
    assert abs(t1 - t0) < 1e-9 and wrong1 == 1 and sigma1 > 0.3, (t1, sigma1)
    assert border({t: (400.0, 380.0, 400.0) for t in clean}, 150) is None       # never a border: all one side

def test_locate_doesnt_measure_towards_the_dead_row():
    '''BED_5's row 3 has no series resistor: pressed, it lifts its column's other rows,
    so row 2 seemed to go on responding over it, and locate put the tip 1.3mm too far in
    X (3.16 for ~1.85, 2026-10-07). It goes by the cell the tip is on: half a cell at most.'''
    fsr, bed, _ = setup(cfg=copy.deepcopy(bed_cfg()), tip=(1.85, 2.2), crosstalk=True, dead_lifts=0.6)
    bed.tool = 'T1'
    fsr.matrix(True)
    shift, _, _ = fsr.locate(1, bed_z(*fsr.array(1).point(1.5, 5.5)))
    assert abs(shift[0] - 1.85) < 1.25 and abs(shift[1] - 2.2) < 1.25, shift      # its cell: half a cell

def test_a_faulty_column_is_never_read():
    '''The old BED_5 sheet's column 3 lit up while the rest of its row was pressed: it read 469 with
    the pen on (1,1) and stopped LRT_CALIBRATE ("responds instead of", 2026-10-07).'''
    cfg = old_cfg()
    fsr, bed, _ = setup(cfg=cfg, row_crosstalk=0.9)
    bed.tool = 'T1'
    fsr.matrix(True)
    s = fsr.read(1)
    assert all(c[1] != 3 for c in s) and all(c[0] != 3 for c in s)
    assert 3 in cfg['arrays'][0]['faulty_cols']

def test_bed5_as_measured_never_presses_past_the_taps():
    '''BED_5 with a Stabilo as measured on the plotter (bed5=True, see FsrBed.frame_bed5):
    the column's rows nearly as strong as the pressed cell at first touch, a weak cell
    (2, 4) where locate first lands for this machine's pens, a ripple across the cells.
    Every tip is measured to a few hundredths, and nothing presses more than 0.1mm past
    first touch: the taps did, at the weak cell 0.17 (2026-10-07).'''
    fsr, bed, _ = setup(bed5=True)
    profile = fsr.calibrate()
    assert bed.max_press <= 0.1, bed.max_press
    for tip in ((2.0, 2.13), (2.6, 3.0), (-0.8, 1.2), (-1.25, 0.6), (1.25, 1.25)):
        fsr, bed, _ = setup(tip=tip, bed5=True)
        bed.tool = 'T1'
        fsr.press_cap = 0.1
        dx, dy, _ = fsr.probe_tool(profile)
        assert abs(dx + tip[0]) < 0.02 and abs(dy + tip[1]) < 0.02, (tip, dx, dy)
        assert bed.max_press <= 0.1, (tip, bed.max_press)
        assert not bed.dragged

def test_a_survey_finds_this_sheets_faults_and_a_healthy_one_none():
    '''LRT_FSR_SURVEY, every cell pressed by a felt tip: BED_5 as measured has its column 3
    high at rest and a weak (2, 4); a healthy sheet nothing. Never 0.1mm past first touch.'''
    from limn.fsr import judge_survey
    for kw, faulty, weak in ((dict(bed5=True), [(0, 3), (1, 3), (2, 3)], [(2, 4)]), (dict(gain=9000), [], [])):
        cfg = old_cfg() if kw.get('bed5') else bed_cfg()
        fsr, bed, _ = setup(cfg=cfg, tip=(2.0, 2.13), **kw)
        bed.tool = 'T4'
        result = fsr.survey(1, {c: bed_z(*fsr.array(1).center(*c[1:])) for c in fsr.z_cells()})
        judged = judge_survey(result, cfg, 1)
        assert judged['faulty'] == faulty and judged['weak'] == weak, judged
        assert np.allclose(result['shift'], (2.0, 2.13), atol=0.03), result['shift']
        assert getattr(bed, 'max_press', 0) <= 0.105 and not bed.dragged
        assert 30 <= judged['early'] <= 60 and not judged['warnings']
        # The aim brings the reference tip down mid cell on a good one, its neighbours not faulty
        lands = np.array(judged['aim']) + np.array([2.0 / 2.5, -2.13 / 2.5])     # cols run towards -Y
        cell = tuple(int(v) for v in lands)
        assert cell not in faulty and cell not in weak and all(abs(v % 1 - 0.5) < 0.25 for v in lands), lands

def test_after_a_swap_the_survey_takes_the_place_of_the_config():
    '''A new sheet with a fault the config doesn't know (the old sheet's column 3, but no
    faulty_cols): surveyed, its faulty cells aren't read and a pen is measured right. Its row 3
    stays dead (it rose with every press of its column, 0.95 of it: the survey's own first
    measurement, on (1, 1), can't work with that row read).'''
    from limn.fsr import judge_survey
    cfg = old_cfg()
    cfg['arrays'][0]['faulty_cols'] = ()
    cfg['arrays'][0]['aim'] = (1.5, 5.5)
    fsr, bed, _ = setup(cfg=copy.deepcopy(cfg), tip=(0.0, 0.0), bed5=True)
    bed.tool = 'T4'
    judged = judge_survey(fsr.survey(1, {c: bed_z(*fsr.array(1).center(*c[1:])) for c in fsr.z_cells()}), cfg, 1)
    assert judged['faulty'] == [(0, 3), (1, 3), (2, 3)]
    ref, _, _ = setup(cfg=copy.deepcopy(cfg), bed5=True)
    ref.apply_survey(1, judged)
    profile = ref.calibrate()
    for tip in ((2.0, 2.13), (1.0, 0.5)):
        fsr, bed, _ = setup(cfg=copy.deepcopy(cfg), tip=tip, bed5=True)
        fsr.apply_survey(1, judged)
        bed.tool = 'T1'
        fsr.press_cap = 0.1
        dx, dy, _ = fsr.probe_tool(profile)
        assert abs(dx + tip[0]) < 0.02 and abs(dy + tip[1]) < 0.02, (tip, dx, dy)
        assert bed.max_press <= 0.1, bed.max_press
        assert all(c[1] != 3 for c in fsr.read(1))

def test_a_fresh_sheet_with_the_config_as_it_is():
    '''After the swap (2026-10-07): BED_5's config knows no faulty column, its aim mid array.
    A fresh sheet with the measured physics (crosstalk, drift, ripple) but no faults: the
    survey finds none, and the reference and the pens are measured right, never pressed
    past 0.1mm.'''
    from limn.fsr import judge_survey
    cfg = bed_cfg()
    assert not cfg['arrays'][0]['faulty_cols'] and cfg['arrays'][0]['aim'] == (1.5, 5.5)
    fsr, bed, _ = setup(cfg=copy.deepcopy(cfg), bed5=True, fresh=True)
    bed.tool = 'T4'
    judged = judge_survey(fsr.survey(1, {c: bed_z(*fsr.array(1).center(*c[1:])) for c in fsr.z_cells()}), cfg, 1)
    assert judged['faulty'] == [] and judged['weak'] == [] and not judged['warnings'], judged
    assert bed.max_press <= 0.105
    ref, bed, _ = setup(cfg=copy.deepcopy(cfg), bed5=True, fresh=True)
    ref.apply_survey(1, judged)
    profile = ref.calibrate()
    assert bed.max_press <= 0.1
    for tip in ((2.0, 2.13), (2.4, 0.3), (1.0, -1.5), (-1.0, 3.0)):
        fsr, bed, _ = setup(cfg=copy.deepcopy(cfg), tip=tip, bed5=True, fresh=True)
        fsr.apply_survey(1, judged)
        bed.tool = 'T1'
        fsr.press_cap = 0.1
        dx, dy, _ = fsr.probe_tool(profile)
        assert abs(dx + tip[0]) < 0.02 and abs(dy + tip[1]) < 0.02, (tip, dx, dy)
        assert bed.max_press <= 0.1, (tip, bed.max_press)

def test_a_map_finds_where_the_sheet_sits_and_what_doesnt_answer():
    '''LRT_FSR_MAP on a fresh sheet that sits 1mm +X, 0.15mm +Y from the config (as the new
    one did, 2026-10-07) with its columns 4-7 dead (a ribbon off): the fitted origin is where
    it sits, the pitch 2.5, and those columns are silent.'''
    from limn import fsr_map
    cfg = bed_cfg()
    fsr, bed, _ = setup(cfg=copy.deepcopy(cfg), tip=(2.0, 2.13), bed5=True, fresh=True, shift=(1.0, 0.15),
                        dead_cols=(4, 5, 6, 7))
    bed.tool = 'T4'
    fsr.matrix(True)
    points = fsr.map_sheet(1, bed_z(*fsr.array(1).center(1, 1)), step=1.25, margin=1.0, tip=(2.0, 2.13))
    result = fsr_map.analyse(points, cfg['arrays'][0], cfg['pitch'], cfg['respond'])
    origin = np.array(cfg['arrays'][0]['origin']) + (1.0, 0.15)
    assert np.allclose(result['origin'], origin, atol=0.45), (result['origin'], origin)       # the coarse fit
    refined, borders = fsr.refine_origin(1, points, result['origin'], tip=(2.0, 2.13))
    assert np.allclose(refined, origin, atol=0.1) and len(borders) >= 2, (refined, origin, borders)
    assert abs(result['pitch'] - 2.5) < 0.1 and result['far'] == []
    assert {(r, c) for r in range(4) for c in (4, 5, 6, 7)} <= set(result['silent'])
    assert not {(r, c) for r in range(4) for c in range(4)} & set(result['silent']), result['silent']
    # A spot that never answers (the margin round the cells, a dead cell) goes 0.06 under where
    # the last touch and the mesh put the sheet: up to ~0.12 past touch where the mesh is off
    assert bed.max_press <= 0.125 and not bed.dragged, bed.max_press
    picture = fsr_map.svg(points, result, cfg['arrays'][0], cfg['pitch'], cfg['respond'])
    assert picture.startswith('<svg') and picture.count('<rect') > len(points)

def test_a_preloaded_cell_and_a_row_that_hears_the_head_arent_a_touch():
    '''The new sheet (2026-10-07): (3, 0) rests at 80-130, row 3 reads 30-50 with the pen
    over the sheet. Absolute, LRT_FSR_MAP 'touched' 4mm up. Every descent rises from its own
    baseline in the air: the map and a measurement come out right, never pressed in.'''
    from limn import fsr_map
    cfg = bed_cfg()
    kw = dict(bed5=True, fresh=True, preload={(3, 0): 100}, hover={3: 40})
    fsr, bed, _ = setup(cfg=copy.deepcopy(cfg), tip=(2.0, 2.13), **kw)
    bed.tool = 'T4'
    fsr.matrix(True)
    points = fsr.map_sheet(1, bed_z(*fsr.array(1).center(1, 1)), tip=(2.0, 2.13))
    result = fsr_map.analyse(points, cfg['arrays'][0], cfg['pitch'], cfg['respond'])
    assert np.allclose(result['origin'], cfg['arrays'][0]['origin'], atol=0.45) and result['answered'] > 100, result
    refined, _ = fsr.refine_origin(1, points, result['origin'], tip=(2.0, 2.13))
    assert np.allclose(refined, cfg['arrays'][0]['origin'], atol=0.1), refined
    assert bed.max_press <= 0.125
    ref, bed, _ = setup(cfg=copy.deepcopy(cfg), **kw)
    profile = ref.calibrate()
    fsr, bed, _ = setup(cfg=copy.deepcopy(cfg), tip=(2.0, 2.13), **kw)
    bed.tool = 'T1'
    fsr.press_cap = 0.1
    dx, dy, _ = fsr.probe_tool(profile)
    assert abs(dx + 2.0) < 0.02 and abs(dy + 2.13) < 0.02 and bed.max_press <= 0.1, (dx, dy, bed.max_press)

def test_a_patchy_sheet_is_measured_or_refused_never_wrong():
    '''The real sheet is patchier than a cell's ripple: a cell read 208 to 784 across a mm at one z, and
    the crosstalk beat it at its weak spots (2026-10-07). A pressed cell here reads half again more or less
    by where the tip is. The binary searches of the cells' thresholds stopped on 1 to 6 pens of 12 at this
    (2026-10-09, "responds at its neighbour's centre", "responds, not (1, 1)"); the sweeps measure them.'''
    cfg = bed_cfg()
    ref, bed, _ = setup(cfg=copy.deepcopy(cfg), bed5=True, fresh=True, patchy=0.5)
    profile = ref.calibrate()
    for tip in ((2.0, 2.13), (-0.34, 0.85), (1.96, 1.38), (-2.1, -1.7)):
        fsr, bed, _ = setup(cfg=copy.deepcopy(cfg), tip=tip, bed5=True, fresh=True, patchy=0.5)
        bed.tool = 'T1'
        fsr.press_cap = 0.1
        dx, dy, _ = fsr.probe_tool(profile)
        assert abs(dx + tip[0]) < 0.02 and abs(dy + tip[1]) < 0.02, (tip, dx, dy)
        # press_cap past contact; contact (60 over the air) is ~0.011 past first touch where a cell reads half
        assert bed.max_press <= 0.1 + 0.012 and not bed.dragged, (tip, bed.max_press)


def test_dz_trim_takes_every_tag_down_alike():
    '''The reference at Z1 on its measured dz only just touched the paper (2026-10-09): `dz_trim` comes
    off the reference's dz and every pen's alike, so they stay the same against each other.'''
    cfg = {**bed_cfg(), 'dz_trim': 0.0}
    fsr, bed, _ = setup(cfg=copy.deepcopy(cfg))
    profile = fsr.calibrate()
    plain = float(bed.ran[-1].split('DZ=')[1].split()[0])
    fsr, bed, _ = setup(cfg=copy.deepcopy(cfg))
    fsr.dz_trim = 0.15
    fsr.calibrate()
    assert abs(float(bed.ran[-1].split('DZ=')[1].split()[0]) - (plain - 0.15)) < 0.02, bed.ran[-1]
    dzs = []
    for trim in (0.0, 0.15):
        fsr, bed, _ = setup(cfg=copy.deepcopy(cfg), tip=(0.35, -0.2), tool_length=2.2)
        bed.tool = 'T1'
        fsr.dz_trim = trim
        dzs.append(fsr.probe_tool(profile)[2])
    assert abs(dzs[0] - dzs[1] - 0.15) < 0.02, dzs


if __name__ == '__main__':
    run_tests(globals())
