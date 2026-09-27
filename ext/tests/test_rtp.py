# uv run python ext/tests/test_rtp.py
import numpy as np

from fakes import FakeDock, ProbeResult, run_tests
from limn.beds import BEDS
from limn.rtp import Rtp
from limn.samples import Samples, Sample, RTP, S_SAMPLE

PROBE_OFFSET = (-34.34, 25.0, 0.8)
# Plotter -> raw panel reading, the inverse of what calibration has to find.
TO_RAW = np.array([[500.0, 3.0], [-2.0, 730.0]])
RAW_ZERO = np.array([1600.0, -2500.0])


def bed_z(x, y):
    return 0.01 * x + 0.005 * y     # not level


class Plotter:
    '''Enough of a plotter for the RTP routines: moves, BLTouch, a docked
    tool whose tip sits `tip` off the toolhead, and the panel under it.'''

    def __init__(self, samples, tool_length=6.0, tip=(0.0, 0.0), noise=0.02, panel_works=True):
        self.samples = samples
        self.pos = [0.0, 0.0, 9.0]
        self.t = 0.0
        self.tool = None
        self.tool_length = tool_length
        self.tip = np.array(tip)
        self.noise = noise
        self.panel_works = panel_works
        self.rng = np.random.default_rng(3)
        self.ran = []

    def move(self, x=None, y=None, z=None, speed=None):
        for i, v in enumerate((x, y, z)):
            if v is not None:
                self.pos[i] = float(v)

    def wait_moves(self):
        pass

    def now(self):
        return self.t

    def pause(self, seconds):
        self.t += seconds

    def probe_offsets(self):
        return PROBE_OFFSET

    def gcode_run(self, script):
        self.ran.append(script)
        if script == 'T4':
            self.tool = 'T4'
        if script == 'UNDOCK':
            self.tool = None

    def say(self, msg):
        pass

    def probe(self):
        x, y = self.pos[:2]
        if self.tool is None:
            px, py = x + PROBE_OFFSET[0], y + PROBE_OFFSET[1]
            z = bed_z(px, py) + PROBE_OFFSET[2]
        else:
            tip = np.array([x, y]) + self.tip
            z = bed_z(*tip) + self.tool_length
            if self.panel_works:
                for _ in range(6):
                    self.t += 0.03
                    raw = TO_RAW @ (tip + self.rng.normal(0, self.noise, 2)) + RAW_ZERO
                    # The panel sends its own axes: [y, x] in plotter order.
                    self.samples.add(Sample(self.t, 1, RTP, S_SAMPLE, [raw[1], raw[0], 30000]))
        return ProbeResult(x, y, z, x, y, z)


def setup(**kw):
    samples = Samples()
    plotter = Plotter(samples, **kw)
    dock = FakeDock()
    return Rtp(plotter, dock, samples, BEDS['BED_3']['rtp']), plotter, dock


def test_calibrate_keeps_the_sequence():
    rtp, plotter, dock = setup()
    profile = rtp.calibrate()
    macros = [s.split()[0] for s in plotter.ran]
    assert macros[:3] == ['UNDOCK', 'G28', '_CLEAR_OFFSETS']
    assert 'BED_MESH_CALIBRATE' not in macros         # LRT_CALIBRATE meshes the bed before
    assert macros.index('T4') < macros.index('WRITE_TOOL_TAG')
    assert plotter.ran[-1].startswith('WRITE_TOOL_TAG DX=0 DY=0 DZ=')
    assert len(profile['ref_samples']) == len(profile['ref_z_panel']) == 12
    # The reference tool is seen where it was sent.
    for r in profile['ref_samples']:
        assert abs(r.tx - r.mx) < 0.1 and abs(r.ty - r.my) < 0.1
    assert dock.sent.count('arm(rtp)') == dock.sent.count('disarm()') > 0

def test_tool_offsets():
    rtp, plotter, _ = setup()
    profile = rtp.calibrate()
    tool, plotter, _ = setup(tip=(0.4, -0.25), tool_length=6.3)
    plotter.tool = 'T1'
    dx, dy, dz = tool.probe_tool(profile)
    # The offset moves the tool back onto the reference: minus where its tip sits.
    assert abs(dx + 0.4) < 0.03 and abs(dy - 0.25) < 0.03
    ref_dz = float(np.median([r.tz - p.tz for r, p in zip(profile['ref_samples'], profile['ref_z_panel'])]))
    assert abs(dz - ref_dz - 0.3) < 0.01

def test_gives_up_on_a_silent_panel():
    rtp, plotter, _ = setup()
    profile = rtp.calibrate()
    silent, plotter, _ = setup(panel_works=False)
    plotter.tool = 'T4'
    try:
        silent.probe_points([(50, 50, 9)], profile['touch_params'], 3)
        assert False, 'should give up'
    except RuntimeError as e:
        assert 'after 9 probes' in str(e)


if __name__ == '__main__':
    run_tests(globals())
