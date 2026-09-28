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
                 noise=8, alive_for=None, responds=True, spike=False, disconnect_after=None):
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
        self.rng = np.random.default_rng(7)
        self.lowest_z = 99.0
        self.dragged = False
        self.ran = []

    def tip_xy(self):
        return np.array(self.pos[:2]) + self.tip

    def press(self):
        if self.tool is None:
            return 0.0
        return bed_z(*self.tip_xy()) - (self.pos[2] - self.tool_length)

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

    def frame(self, array):
        pressed = None
        cell = array.cell_at(self.tip_xy())
        if cell and self.press() > 0:
            local = self.tip_xy() - array.origin
            u = np.dot(local, array.col_dir) / array.pitch % 1 * array.pitch
            v = np.dot(local, array.row_dir) / array.pitch % 1 * array.pitch
            margin = self.dead / 2
            if margin <= u <= array.pitch - margin and margin <= v <= array.pitch - margin:
                pressed = cell
        values = []
        for row in range(array.rows):
            for col in range(array.cols):
                s = abs(self.rng.normal(0, self.noise))
                if (row, col) == pressed and self.responds:
                    s = 1000 if self.spike else min(1000, self.press() * self.gain) + s
                values.append([row, col, int(s)])
        return values

    def probe_offsets(self):
        return PROBE_OFFSET

    def probe(self):
        x, y = self.pos[:2]
        z = bed_z(x + PROBE_OFFSET[0], y + PROBE_OFFSET[1]) + PROBE_OFFSET[2]
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
    # The edges sit between the cells: x = 108 + 2 * 2.5 between rows, y = 36 + 4 * 2.5 between cols.
    assert abs(ref['x'] - 113.0) < 0.03 and abs(ref['y'] - 46.0) < 0.03
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

def test_dead_sensor_lifts():
    profile = calibrated()
    fsr, bed, _ = setup(alive_for=1.0)
    bed.tool = 'T1'
    try:
        fsr.probe_tool(profile)
        assert False, 'should stop'
    except FsrError as e:
        assert 'no frames' in str(e)
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
    '''A few mm off in X (4 rows) and more in Y (8 cols): found, and measured.'''
    profile = calibrated()
    for tip in ((3.4, -5.0), (-3.2, 8.0), (5.5, 1.9), (-1.6, -0.9)):
        fsr, bed, _ = setup(tip=tip)
        bed.tool = 'T1'
        dx, dy, _ = fsr.probe_tool(profile)
        assert abs(dx + tip[0]) < 0.03 and abs(dy + tip[1]) < 0.03, (tip, dx, dy)
        assert not bed.dragged and bed.lowest_z >= floor_of(fsr, profile)

def test_off_the_array_stops_at_the_floor():
    profile = calibrated()
    # Misses the 4 rows; lands on a dead zone (this tip has no width to reach a cell)
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
    cfg['arrays'][0]['origin'] = (109.5, 35.2)     # we aim off, the cells are where they were
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


if __name__ == '__main__':
    run_tests(globals())
