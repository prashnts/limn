# The Z axis's play from a photo: tails that drag until the pen rises enough
import numpy as np

from limn_cam import play as pm
from limn_cam.tests.test_ladder import camera, shoot

TEST = pm.PlayTest(pen='T3', press=0.3, spots=[(12, 70), (12, 90)], rises=[0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5])


def drawn(test, lets_go):
    '''What the tests leave when the pen lets go at a rise of lets_go[spot]: the pressed
    strokes, the tails under that, and the crosses.'''
    out = []
    for s, r, a, m, e in test.tests():
        out.append((a, m, 0.55))
        if r < lets_go[s]:
            out.append((m, e, 0.45))
    h = test.cross / 2
    for cx, cy in test.anchors():
        out += [((cx - h, cy), (cx + h, cy), 0.55), ((cx, cy - h), (cx, cy + h), 0.55)]
    return out


def test_play_from_a_photo():
    h = camera(px=3.1)
    before = shoot(h, [], size=(700, 900))
    after = shoot(h, drawn(TEST, {0: 0.5, 1: 1.25}), size=(700, 900), light=1.1, seed=5)
    res = pm.analyze(before, after, TEST, roi=None)
    assert res.anchor_error < 1.5 and not res.notes, res.notes
    assert [s.rise for s in res.spots] == [0.5, 1.25]
    assert [s.per_press for s in res.spots] == [round(0.5 / 0.3, 2), round(1.25 / 0.3, 2)]


def test_play_saved_for_plot(tmp_path):
    from plot.profile import Play
    res = pm.Result([pm.Spot(12, 70, 0.5, 1.67, 1.0, []), pm.Spot(12, 90, None, None, 1.0, [])], 0.3, [], 3, 0.2)
    path = tmp_path / 'play.toml'
    assert pm.save(res, path, TEST) == [[12, 70, 1.67]]
    import tomllib
    p = Play(**tomllib.loads(path.read_text()))
    assert p.spots == [(12, 70, 1.67)] and abs(p.extra((12, 70), 0.3) - 0.5) < 0.01


def test_play_gcode_is_plot_safe():
    from plot.profile import load_machine
    m = load_machine(overrides={'bed_id': 'BED_5'})
    text, problems = pm.gcode(TEST, m)
    assert problems == []
    lines = text.splitlines()
    tails = [l for l in lines if l.startswith('G1 Z') and float(l.split()[1][1:]) > TEST.z_touch - TEST.press + 1e-6]
    assert len(tails) == len(TEST.tests())              # each test rises to its trial height before its tail
