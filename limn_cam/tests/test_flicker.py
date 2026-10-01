# A light that flickers: its bands found, and left out by the brightest of a few frames
import io

import numpy as np
import pytest
from PIL import Image

from limn_cam import flicker
from limn_cam import scan as sc

from .test_scan import FakeMoonraker, camera, machine, run

H, W, PERIOD = 480, 640, 40


def paper(seed=0):
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:H, 0:W]
    a = 200 - 30 * ((x - W / 2) ** 2 + (y - H / 2) ** 2) / (W * W / 4)          # light falling off
    a[100:140, 200:440] = 40                                                    # some ink
    return np.clip(a + rng.normal(0, 1.0, a.shape), 0, 255)


def shot(a, phase=None, depth=40, seed=0):
    '''a, its rows darker in bands every PERIOD rows (3 rows thin) at `phase`.'''
    a = a.copy()
    if phase is not None:
        rows = (np.arange(H) + phase) % PERIOD < 3
        a[rows] -= depth
    buf = io.BytesIO()
    Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).convert('RGB').save(buf, 'JPEG', quality=95)
    return buf.getvalue()


def test_bands_are_found_and_plain_shots_left_alone():
    p = paper()
    b = flicker.bands(shot(p, 7))
    assert flicker.found(b) and b['period'] == pytest.approx(PERIOD, rel=0.1) or b['period'] == pytest.approx(PERIOD / 2, rel=0.1)
    assert not flicker.found(flicker.bands(shot(p)))


def test_the_brightest_of_three_frames_leaves_them_out():
    p = paper()
    out = flicker.merged([shot(p, ph) for ph in (3, 17, 31)])
    assert not flicker.found(flicker.bands(out))
    assert np.abs(np.asarray(Image.open(io.BytesIO(out)).convert('L'), float) - p).mean() < 3


class Flickering(FakeMoonraker):
    '''The camera under a light that flickers: each frame banded somewhere else.'''

    def __init__(self):
        super().__init__()
        self.frames, self.p = 0, paper()

    def snapshot(self, camera):
        self.frames += 1
        return shot(self.p, (self.frames * 13) % PERIOD)


def test_a_scan_under_a_flickering_light(tmp_path):
    mr, store = Flickering(), sc.ScanStore(tmp_path)
    st = run(sc.Job('scan', mr, camera(), machine(), store, sc.Settings(region=(20, 60, 40, 70))), 'scan')
    tiles = store.meta(st['scan'])['tiles']
    assert st['error'] is None and mr.frames == 3 * len(tiles)
    assert all(t['flicker']['frames'] == 3 and t['flicker']['after'] < flicker.MIN_RIPPLE for t in tiles)
    assert st['flicker']['shots'] == len(tiles)
    # Off: one frame a tile, bands and all
    mr2 = Flickering()
    st = run(sc.Job('scan', mr2, camera(), machine(), sc.ScanStore(tmp_path / 'b'),
                    sc.Settings(region=(20, 60, 40, 70), flicker='off')), 'scan')
    assert mr2.frames == len(tiles) and st.get('flicker') is None
