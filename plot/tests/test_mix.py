# Colours no pen has: a pen's lines screened to a colour's lightness, and colours
# mixed from the pens side by side (mix.py)
import numpy as np
import pytest
from shapely.geometry import box

from plot.ink import guard, Unit
from plot.job import Group, Obj
from plot.mix import coverage, luminance, shares, side_by_side
from plot.slicer import slice_object


@pytest.fixture
def cmyk(tools):
    '''Five pens: C, M, Y and grey Stabilos, and a black fineliner.'''
    pen = tools['T0']
    return {tid: pen.model_copy(update={'id': tid, 'color': c, 'width': w, 'bleed': 0.1})
            for tid, c, w in (('T0', '#00a0e0', 0.4), ('T1', '#e0007a', 0.4), ('T2', '#ffe000', 0.4),
                              ('T3', '#909090', 0.4), ('T4', '#101010', 0.1))}


def test_coverage_is_by_light_not_by_the_number():
    assert coverage('#ffffff', '#000000') == 0
    assert coverage('#000000', '#000000') == 1
    # sRGB 50% grey reflects ~21%: the black pen inks ~79% of it
    assert coverage('#808080', '#000000') == pytest.approx(1 - luminance('#808080'), abs=1e-6) == pytest.approx(0.78, abs=0.01)


def test_shares_mix_a_colour_from_the_pens_and_the_paper(cmyk):
    pens = {k: t.color for k, t in cmyk.items()}
    green, paper, err = shares('#60b040', pens)
    assert green.get('T0', 0) > 0.05 and green.get('T2', 0) > 0.1 and green.get('T1', 0) < 0.05
    assert err < 0.167                               # side by side gets only near a strong green: but nearer than any pen
    grey, paper, _ = shares('#c8c8c8', pens)
    assert set(grey) <= {'T3', 'T4'} and paper > 0.3        # a light grey: grey (and black) lines, paper between
    _, paper, _ = shares('#ffffff', pens)
    assert paper > 0.95


def test_side_by_side_lines_never_touch_and_keep_the_shares(cmyk):
    area = box(0, 0, 30, 30)
    lines, spacing = side_by_side(area, {'T0': 0.4, 'T2': 0.4}, cmyk, angle=45)
    assert set(lines) == {'T0', 'T2'} and spacing >= 0.5
    length = {k: sum(np.hypot(*np.diff(p, axis=0).T).sum() for p in ps) for k, ps in lines.items()}
    # inked share = length * width / area: 0.4 each asked, a slot each line (spacing 0.505)
    for k in lines:
        assert length[k] * 0.4 / area.area == pytest.approx(0.4, abs=0.05)
    units = [Unit((0, 0), k, ps) for k, ps in sorted(lines.items())]
    _, cut, _ = guard(units, cmyk)
    assert not cut                                  # side by side: nothing for the guard to cut


def test_a_grey_in_the_black_pen_is_screened_not_solid(write_svg, cmyk):
    p = write_svg('<rect x="10" y="10" width="20" height="20" fill="#bbbbbb"/>')
    g = {'fill #bbbbbb': Group(tool='T4')}
    solid = slice_object(Obj(id='d', svg=str(p), groups=g), cmyk).paths['T4']
    screen = slice_object(Obj(id='d', svg=str(p), groups={'fill #bbbbbb': Group(tool='T4', tone='screen')}),
                          cmyk).paths['T4']
    ink = lambda ps: sum(np.hypot(*np.diff(a[:, :2], axis=0).T).sum() for a in ps) * 0.1 / 400
    assert ink(solid) > 0.9
    assert ink(screen) == pytest.approx(coverage('#bbbbbb', '#101010'), abs=0.08)
    # the tool's own setting does as much
    tone = {**cmyk, 'T4': cmyk['T4'].model_copy(update={'tone': 'screen'})}
    assert len(slice_object(Obj(id='d', svg=str(p), groups=g), tone).paths['T4']) == len(screen)


def test_a_colour_mixed_from_the_pens(write_svg, cmyk):
    p = write_svg('''
        <rect x="10" y="10" width="20" height="20" fill="#60b040" stroke="#202020" stroke-width="0.3"/>''')
    g = {'fill #60b040': Group(mix=True), 'stroke #202020': Group(mix=True)}
    s = slice_object(Obj(id='d', svg=str(p), groups=g), cmyk)
    assert {'T0', 'T2'} <= set(s.paths)             # cyan and yellow lines in the green
    assert 'T4' in s.paths                          # its outline: the pen nearest its colour
    assert any('#60b040 mixed side by side' in q for q in s.problems)
    assert not any('would go over' in q for q in s.problems if 'T4' not in q)


def test_two_pens_of_one_ink_mix_as_one(write_svg, cmyk):
    p = write_svg('<rect x="10" y="10" width="20" height="20" fill="#404040"/>')
    two = {**cmyk, 'T5': cmyk['T4'].model_copy(update={'id': 'T5'})}
    s = slice_object(Obj(id='d', svg=str(p), groups={'fill #404040': Group(mix=True)}), two)
    assert 'T4' in s.paths and 'T5' not in s.paths
