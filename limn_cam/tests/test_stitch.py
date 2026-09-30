# Stitching: tiles cut from one scene, landed a little off, turned as the camera is
import numpy as np
import pytest
from PIL import Image, ImageFilter

from limn_cam import scan as sc
from limn_cam import stitch as st

PPM = 20.0                  # px/mm of the scene and the tiles


def scene(w_mm, h_mm, seed=4):
    rng = np.random.default_rng(seed)
    small = rng.random((int(h_mm * PPM / 6), int(w_mm * PPM / 6)))
    big = Image.fromarray((small * 255).astype(np.uint8)).resize((int(w_mm * PPM), int(h_mm * PPM)), Image.BICUBIC)
    return big.filter(ImageFilter.GaussianBlur(1.2))


def cut(big, x, y, fov, turn, x0=0.0, y1=None):
    '''The shot a camera over (x, y) would take of `big` (its top-left at x0, y1 mm), turned.'''
    fx, fy = fov
    left, top = (x - fx / 2 - x0) * PPM, (y1 - (y + fy / 2)) * PPM
    im = big.crop((int(round(left)), int(round(top)), int(round(left + fx * PPM)), int(round(top + fy * PPM))))
    return im.rotate(-turn, expand=True) if turn else im


def test_register_finds_where_the_tiles_landed(tmp_path):
    fov, turn = (15.0, 9.0), 180.0
    region = (10, 10, 45, 35)
    plan = sc.tiles(region, fov, 0.3, turn)
    big = scene(60, 50)
    rng = np.random.default_rng(1)
    off = rng.uniform(-0.3, 0.3, (len(plan), 2))
    off[0] = 0                                  # the first stays where it was sent
    files, tiles = {}, []
    for (r, c, x, y), (ex, ey) in zip(plan, off):
        name = f'r{r}c{c}.png'
        files[name] = cut(big, x + ex, y + ey, fov, turn, x0=0, y1=50)
        tiles.append({'file': name, 'row': r, 'col': c, 'x': x, 'y': y})
    pos, pairs = st.register(tiles, lambda f: files[f], fov, turn, ppm=PPM)
    assert all(p['used'] for p in pairs) and len(pairs) >= len(plan)
    got = np.array(pos) - np.array([(t['x'], t['y']) for t in tiles])
    assert np.abs(got - off).max() < 0.08, np.abs(got - off).max()
    # Stitched where registered: it matches the scene
    img, extent = st.compose(tiles, lambda f: files[f], fov, turn, PPM, pos)
    x0, y0, x1, y1 = extent
    ref = big.crop((int(round(x0 * PPM)), int(round((50 - y1) * PPM)), int(round(x1 * PPM)), int(round((50 - y0) * PPM))))
    a, b = np.asarray(img.convert('L'), float), np.asarray(ref.resize(img.size), float)
    assert np.abs(a - b)[20:-20, 20:-20].mean() < 12
    with pytest.raises(ValueError, match='megapixels'):
        st.compose(tiles, lambda f: files[f], fov, turn, 400, pos, max_mp=1)


def test_stitch_in_the_store(tmp_path):
    fov, turn = (15.0, 9.0), 180.0
    store = sc.ScanStore(tmp_path)
    sid = store.new({'kind': 'scan', 'fov': list(fov), 'turn': turn})
    big = scene(60, 50)
    import io
    for r, c, x, y in sc.tiles((10, 10, 40, 30), fov, 0.3, turn):
        buf = io.BytesIO()
        cut(big, x, y, fov, turn, y1=50).convert('RGB').save(buf, 'JPEG', quality=95)
        store.add(sid, f'r{r}c{c}.jpg', buf.getvalue(), {'row': r, 'col': c, 'x': x, 'y': y, 'z': 9.2})
    info = st.info(store, sid, 30)
    assert info['used'] == info['of'] > 0 and info['moved_max'] < 0.1 and info['native_ppm'] == pytest.approx(PPM, abs=0.5)
    assert info['width'] == pytest.approx((info['extent'][2] - info['extent'][0]) * 30, abs=2)
    path, got = st.stitch(store, sid, 30)
    assert Image.open(path).size == (got['width'], got['height'])


def test_a_camera_a_little_askew():
    assert st._axes((15, 9), -179.2) == (15, 9) and st._axes((15, 9), 90.4) == (9, 15)
    im = Image.new('RGB', (150, 90), 'white')
    assert st.upright(im, -179.2).size == (150, 90) and st.upright(im, 90).size == (90, 150)
