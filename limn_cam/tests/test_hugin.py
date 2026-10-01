# Stitching with Hugin (limn_cam/hugin.py), on a scan made up from one picture
import io

import numpy as np
import pytest
from PIL import Image, ImageDraw

from limn_cam import hugin
from limn_cam.scan import ScanStore

pytestmark = pytest.mark.skipif(bool(hugin.missing()), reason='no Hugin tools here')

PPM = 20.0          # px per mm the made-up camera really has
SIZE = (400, 240)   # a shot, px: 20 x 12 mm


def bed(w=1400, h=900, seed=3):
    '''Something with texture all over: blobs, lines, letters.'''
    rng = np.random.default_rng(seed)
    im = Image.new('RGB', (w, h), 'white')
    dr = ImageDraw.Draw(im)
    for _ in range(900):
        x, y, r = rng.integers(0, w), rng.integers(0, h), rng.integers(3, 14)
        dr.ellipse((x - r, y - r, x + r, y + r), fill=tuple(int(v) for v in rng.integers(0, 200, 3)))
    for _ in range(120):
        dr.line(tuple(int(v) for v in rng.integers(0, max(w, h), 4)), fill=(20, 20, 20), width=2)
    return im


def make_scan(tmp_path, off=(0.3, -0.2), cols=3, rows=2, step=(14.0, 8.0), fov_said=(21.0, 12.6)):
    '''Tiles cut from bed() where a camera turned -179.2 degrees saw them; the tile
    (1, 1) really `off` mm from where it was sent. The meta says fov_said: a
    calibration 5% off.'''
    big = bed()
    store = ScanStore(tmp_path)
    sid = store.new({'kind': 'scan', 'fov': list(fov_said), 'turn': -179.2})
    for r in range(rows):
        for c in range(cols):
            x, y = 15 + c * step[0], 15 + r * step[1]          # mm, y up
            tx, ty = (x + off[0], y + off[1]) if (r, c) == (1, 1) else (x, y)
            u, v = tx * PPM, big.height - ty * PPM           # image px of the shot's middle
            box = (u - SIZE[0] / 2 - 20, v - SIZE[1] / 2 - 20, u + SIZE[0] / 2 + 20, v + SIZE[1] / 2 + 20)
            tile = big.crop(tuple(int(round(b)) for b in box)).rotate(179.2, resample=Image.BICUBIC)     # upright() turns it back
            tile = tile.crop((20, 20, 20 + SIZE[0], 20 + SIZE[1]))
            buf = io.BytesIO()
            tile.save(buf, 'JPEG', quality=95)
            store.add(sid, f'r{r:02d}c{c:02d}.jpg', buf.getvalue(), {'row': r, 'col': c, 'x': x, 'y': y, 'z': 9.2})
    return store, sid


def test_hugin_finds_the_tiles_and_the_camera(tmp_path):
    store, sid = make_scan(tmp_path)
    path, info = hugin.stitch(store, sid, 10, log=lambda m: None)
    assert path.exists() and info['unmatched'] == []
    assert info['rms_px'] < 1.0
    assert info['camera']['px_per_mm'] == pytest.approx(PPM, rel=0.02)         # not the 19.05 the meta says
    assert info['camera']['turn'] == pytest.approx(-179.2, abs=0.3)
    assert info['moved_max'] == pytest.approx(np.hypot(0.3, 0.2), abs=0.1)   # the tile that landed off
    w, h = Image.open(path).size
    assert w == pytest.approx((2 * 14 + 20) * 10, rel=0.05) and h == pytest.approx((8 + 12) * 10, rel=0.08)
    # The project stays, by the tiles' names
    pto = (store.dir(sid) / 'hugin.pto').read_text()
    assert 'n"r00c00.jpg"' in pto and 'hugin-work' not in pto
    assert not (store.dir(sid) / 'hugin-work').exists()
    assert hugin.done(store, sid, 10)[1] == info


def test_matches_that_disagree_are_left_out(tmp_path):
    lines = ['p f0 w100 h100 v10', 'i w10 h10 n"a"', 'i w10 h10 n"b"']
    good = [f'c n0 N1 x{100 + i} y{50 + i} X{i} Y{i} t0' for i in range(6)]           # all 100, 50 apart
    bad = ['c n0 N1 x900 y50 X0 Y0 t0']                                              # one dot off: 900
    few = [f'c n0 N2 x{i} y0 X{i * 50} Y0 t0' for i in range(3)]                       # 3 that disagree
    (tmp_path / 'a.pto').write_text('\n'.join(lines + good + bad + few) + '\n')
    kept, pairs = hugin.clean(tmp_path / 'a.pto', tmp_path / 'b.pto')
    assert kept == 6 and list(pairs) == [(0, 1)] and pairs[(0, 1)] == pytest.approx((100, 50))
    assert hugin.anchors(4, pairs) == [0, 2, 3]         # 0 for {0, 1}; 2 and 3 on their own
