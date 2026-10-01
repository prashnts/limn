# uv run pytest limn_cam/tests
import json

import numpy as np
import pytest

from limn_cam import backend as backends
from limn_cam import ladder as lad
from limn_cam.geometry import Homography
from limn_cam.image import ink, sample


def camera(angle=172, px=2.9, skew=0.0006):
    '''Paper mm -> pixels: turned, scaled, a little perspective (like the overhead one, upside down).'''
    c, s = np.cos(np.radians(angle)), np.sin(np.radians(angle))
    m = np.array([[px * c, -px * s, 520], [px * s, px * c, 610], [skew, -skew / 2, 1]])
    return Homography(m)


def shoot(h, strokes, size=(600, 900), light=1.0, seed=1, width=0.35):
    '''A gray shot of paper with these ink strokes [(a, b, darkness)], lit unevenly.'''
    rng = np.random.default_rng(seed)
    hh, ww = size
    y, x = np.mgrid[0:hh, 0:ww]
    img = light * (0.85 - 0.25 * ((x - ww / 2) ** 2 + (y - hh / 2) ** 2) / (ww * ww))
    inv = h.inverse()
    mm = inv(np.column_stack([x.ravel(), y.ravel()])).reshape(hh, ww, 2)
    for a, b, dark in strokes:
        a, b = np.asarray(a, float), np.asarray(b, float)
        u = b - a
        t = np.clip(((mm - a) @ u) / (u @ u), 0, 1)
        dist = np.linalg.norm(mm - (a + t[..., None] * u), axis=2)
        img = img * (1 - dark * np.clip(1.0 - dist / width, 0, 1))
    img = img + rng.normal(0, 0.008, img.shape)
    return np.clip(img * 255, 0, 255).astype(np.uint8)


def drawn(ld, touch, solid):
    '''The strokes a ladder leaves when each pen touches at touch[pen], a whole line from solid[pen].'''
    out = []
    for pen, z, a, b in ld.strokes():
        if z <= solid[pen]:
            out.append((a, b, 0.55))
        elif z <= touch[pen]:
            mid = np.add(a, b) / 2                  # half a line: the start of the stroke only
            out.append((a, mid, 0.3))
    first = ld.pens[0]
    if ld.zs[-1] <= touch[first]:
        h = ld.cross / 2
        for cx, cy in ld.anchors():
            out += [((cx - h, cy), (cx + h, cy), 0.55), ((cx, cy - h), (cx, cy + h), 0.55)]
    return out


LADDER = lad.Ladder(pens=['T0', 'T1'], z_top=2.4, z_bottom=1.0, z_step=0.1, origin=(12, 67), pitch=2.5, length=4.0)


@pytest.mark.parametrize('name', ['numpy', 'opencv'])
def test_touch_heights_from_a_photo(name):
    if name == 'opencv':
        pytest.importorskip('cv2')                      # an extra: uv sync --extra cam
    h = camera()
    before = shoot(h, [((30, 100), (60, 110), 0.5)])                        # older ink stays out of it
    touch, solid = {'T0': 2.0, 'T1': 1.5}, {'T0': 1.9, 'T1': 1.4}
    after = shoot(h, [((30, 100), (60, 110), 0.5)] + drawn(LADDER, touch, solid), light=1.15, seed=2)
    res = lad.analyze(before, after, LADDER, backends.get(name))
    assert res.anchor_error < 1.5
    assert res.pens['T0'].touch_z == 2.0 and res.pens['T1'].touch_z == 1.5
    assert res.pens['T0'].solid_z == 1.9 and res.pens['T1'].solid_z == 1.4
    assert not res.notes, res.notes
    fit = Homography(res.homography)
    assert np.abs(fit(LADDER.anchors()) - h(LADDER.anchors())).max() < 1.5
    json.dumps(res.to_dict())


def test_a_pen_that_never_draws_is_told():
    h = camera()
    before = shoot(h, [])
    after = shoot(h, drawn(LADDER, {'T0': 1.6, 'T1': 0.5}, {'T0': 1.5, 'T1': 0.4}), seed=3)
    res = lad.analyze(before, after, LADDER)
    assert res.pens['T1'].touch_z is None and any('T1 did not draw' in n for n in res.notes)
    assert res.pens['T0'].touch_z == 1.6


def test_no_crosses_no_fit():
    h = camera()
    blank = shoot(h, [])
    with pytest.raises(ValueError, match='marks found'):
        lad.analyze(blank, shoot(h, [], seed=4), LADDER)


def test_suggested_dz():
    res = lad.Result({'T0': lad.PenResult('T0', 2.0, 1.9), 'T1': lad.PenResult('T1', None, None)}, [], 3, 0.5, 0.03)
    tags = {'41': {'dz': 0.75}, '42': {'dz': 1.45}}
    s = lad.suggest(res, tags, (41, 42), z_touch=1.15)
    assert s['T0'] == {'holder': 41, 'dz': 0.75, 'touch_z': 2.0, 'new_dz': 1.6} and s['T1'] is None


def test_ladder_gcode_is_plot_safe():
    from plot.profile import load_machine
    m = load_machine(overrides={'bed_id': 'BED_5'})
    text, problems = lad.gcode(LADDER, m)
    assert problems == []
    lines = text.splitlines()
    assert lines.count('T0') == 1 and lines.count('T1') == 1 and lines[-1] == 'PLOT_END'
    downs = [float(l.split()[1][1:]) for l in lines if l.startswith('G1 Z')]
    assert downs.count(1.0) == len(LADDER.pens) + 10         # the lowest stroke of each pen, and 10 cross arms
    hop = LADDER.z_top + LADDER.hop
    # Every stroke comes down from the same hop (the Z axis has play)
    z = None
    for l in lines:
        w = l.split()
        if l.startswith('G1 Z'):
            assert z == hop, l
        if w and w[0] in ('G0', 'G1'):
            z = next((float(v[1:]) for v in w[1:] if v[0] == 'Z'), z)
    far = lad.Ladder(pens=['T0'], origin=(80, 150))
    assert 'off the paper' in lad.gcode(far, m)[1][0]


def test_homography_round_trip():
    h = camera()
    src = np.array([[0, 0], [50, 0], [50, 30], [0, 30], [20, 10]], float)
    fit = Homography.fit(src, h(src))
    assert np.allclose(fit(src), h(src), atol=1e-6)
    assert np.allclose(fit.inverse()(fit(src)), src, atol=1e-6)


def test_markers_with_opencv():
    cv2 = pytest.importorskip('cv2')
    tag = cv2.aruco.generateImageMarker(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), 7, 120)
    img = np.full((300, 400), 255, np.uint8)
    img[90:210, 140:260] = tag
    found = backends.get('opencv').markers(img)
    assert [m.id for m in found] == [7] and abs(found[0].size - 120) < 3
    with pytest.raises(NotImplementedError):
        backends.get('numpy').markers(img)
