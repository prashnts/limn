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


class FsrBed:
    '''The plotter over BED_5: a docked tool whose tip sits `tip` off the
    toolhead, pressing on an FSR array with a dead zone between cells.'''

    def __init__(self, samples, dock, cfg, tip=(0.0, 0.0), tool_length=1.8, dead=0.4, gain=2000,
                 noise=8, alive_for=None, responds=True, spike=False, disconnect_after=None,
                 crosstalk=False, width=0.0, slope_y=0.0, mesh=True, row_crosstalk=0.0, wipes=(), ghost=None,
                 dead_lifts=0.0):
        self.samples = samples
        self.dock = dock
        self.arrays = [FsrArray(a['hop'], a['origin'], a['col_dir'], a['row_dir'], cfg['pitch'])
                       for a in cfg['arrays']]
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
        self.crosstalk = crosstalk              # as on BED_5: a press lifts its column's row 3 to ~530, row 0 a bit
        self.width = width                      # tip radius: near an edge it presses both cells, each less
        self.slope_y = slope_y                  # the sheet rises this much per mm in Y, on top of bed_z
        self.mesh = mesh                        # an lrt_fsr mesh of it, as LRT_MESH_CALIBRATE takes
        self.row_crosstalk = row_crosstalk      # a press lifts the rest of its row by this share of it
        self.dead_lifts = dead_lifts            # a press on row 3 (no series resistor) lifts its column's rows by this share
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
        x0, y0, x1, y1 = 111, 40, 118.5, 59
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

    def frame(self, array):
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
                    s += {3: 530, 0: 220}.get(row, 0)
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
    cfg = cfg or bed_cfg()
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
    assert abs(ref_dz - 1.0) < 0.1 and abs(dz - ref_dz - 0.4) < 0.03
    assert not bed.dragged and bed.lowest_z >= floor_of(fsr, profile)

def test_crosstalk_up_the_column():
    '''BED_5: a press lifts row 3 of its column to ~530 at once, before the pressed
    cell gets there. Measured all the same, far off too.'''
    fsr, bed, _ = setup(crosstalk=True)
    profile = fsr.calibrate()
    for tip in ((0.35, -0.2), (3.4, -5.0), (-1.6, -0.9)):
        fsr, bed, _ = setup(tip=tip, crosstalk=True)
        bed.tool = 'T1'
        dx, dy, _ = fsr.probe_tool(profile)
        assert abs(dx + tip[0]) < 0.03 and abs(dy + tip[1]) < 0.03, (tip, dx, dy)
        assert not bed.dragged and bed.lowest_z >= floor_of(fsr, profile)

def test_prior_brings_the_tip_down_on_the_aim():
    '''Without a prior this tip lands on the edge between rows 0 and 1 at the aim
    (a dead zone for a tip this fine); told where it is, it comes down mid cell.'''
    profile = calibrated()
    tip = (-1.25, 0.6)
    fsr, bed, _ = setup(tip=tip)
    bed.tool = 'T0'
    try:
        fsr.probe_tool(profile)
        assert False, 'lands on the dead zone'
    except FsrError as e:
        assert 'no contact' in str(e)
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
    fsr, bed, _ = setup(tip=(-4.5, 0.0))           # off the rows
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
    # On a corner of four cells each gets a few percent, only the crosstalk shows:
    # nothing to go by, so it stops and lifts. TIP= brings such a tool down mid cell.
    fsr, bed, _ = setup(tip=(1.25, 1.25), crosstalk=True, width=0.3)
    bed.tool = 'T3'
    try:
        fsr.probe_tool(profile)
        assert False, 'should stop'
    except FsrError:
        pass
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
    assert abs(depth - bed_cfg()['press']) < 1e-9 and press < 0.21 + 0.3 + 0.03, (press, depth)

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
    fsr, bed, dock = setup(wipes=[(1.0, 2.0, {(1, 3)}, 600)])
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
    '''A few mm off in X (rows 0-2) and more in Y (8 cols): found, and measured.'''
    profile = calibrated()
    for tip in ((3.4, -5.0), (-3.2, 8.0), (3.0, 1.9), (-1.6, -0.9)):
        fsr, bed, _ = setup(tip=tip)
        bed.tool = 'T1'
        dx, dy, _ = fsr.probe_tool(profile)
        assert abs(dx + tip[0]) < 0.03 and abs(dy + tip[1]) < 0.03, (tip, dx, dy)
        assert not bed.dragged and bed.lowest_z >= floor_of(fsr, profile)

def test_off_the_array_stops_at_the_floor():
    profile = calibrated()
    # Misses the rows; lands on a dead zone (this tip has no width to reach a cell)
    for tip in ((-4.5, 0.0), (0.0, 1.25)):
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


if __name__ == '__main__':
    run_tests(globals())

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

def test_a_weak_press_on_another_cell_stops_short_of_the_floor():
    '''A fineliner off by a cell pressed its neighbour too weakly to count as "sure",
    and LRT_FSR_Z went on down to the floor (2026-10-07). It stops 0.2mm on now.'''
    fsr, bed, _ = setup(cfg=copy.deepcopy(bed_cfg()), gain=700, tip=(2.5, 0))     # a row off: (2, 1) under it
    bed.tool = 'T1'
    presses, read = [], fsr.read
    fsr.read = lambda hop, limit=True: presses.append(bed.press()) or read(hop, limit)
    fsr.matrix(True)
    try:
        fsr.contact_z(1, 1, 1, bed_z(*fsr.array(1).center(1, 1)))
        assert False, 'it should stop'
    except FsrError as e:
        assert 'another cell' in str(e) or 'instead of' in str(e), e
    assert max(presses) < 0.21 + 0.2 + 0.15, max(presses)

def test_locate_doesnt_measure_towards_the_dead_row():
    '''BED_5's row 3 has no series resistor: pressed, it lifts its column's other rows,
    so row 2 seemed to go on responding over it, and locate put the tip 1.3mm too far in
    X (3.16 for ~1.85, 2026-10-07). It measures towards row 1 instead.'''
    fsr, bed, _ = setup(cfg=copy.deepcopy(bed_cfg()), tip=(1.85, 2.2), crosstalk=True, dead_lifts=0.6)
    bed.tool = 'T1'
    fsr.matrix(True)
    shift, _ = fsr.locate(1, bed_z(*fsr.array(1).point(1.5, 5.5)))
    assert abs(shift[0] - 1.85) < 0.3 and abs(shift[1] - 2.2) < 0.3, shift
