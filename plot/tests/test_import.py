# SVG import, colours, fills and occlusion
import numpy as np
import pytest
from shapely.geometry import LineString, Point, box

from plot import svg
from plot.geometry import fill, hatch, region, thin, inset
from plot.job import Group, Obj
from plot.slicer import default_groups, slice_object


def test_styles_units_and_text(write_svg):
    p = write_svg('''
        <style>.l1{stroke:#FFCD00;stroke-width:4;fill:none}</style>
        <g stroke-width="3" fill="none">
          <path class="l1" d="M10 50 H90"/>
          <path stroke="#bb4d98" stroke-opacity="0.5" d="M50 10 V90"/>
        </g>
        <circle cx="50" cy="50" r="5" fill="white" stroke="black" stroke-width="1"/>
        <text x="10" y="20" font-family="Futura" font-size="12">Hi</text>''', w=200, h=100)
    d = svg.load(p)
    assert d.size == pytest.approx((200, 100), abs=1e-3)
    yellow, purple, circle = d.shapes
    assert (yellow.stroke, yellow.width, yellow.stroke_opaque) == ('#ffcd00', pytest.approx(4), True)
    assert (purple.stroke, purple.width, purple.stroke_opaque) == ('#bb4d98', pytest.approx(3), False)
    assert (circle.fill, circle.stroke, circle.closed) == ('#ffffff', '#000000', [True])
    assert np.allclose(yellow.paths[0], [[10, 50], [90, 50]])
    assert set(d.groups()) == {'stroke #ffcd00', 'stroke #bb4d98', 'stroke #000000', 'fill #ffffff', 'fill #000000'}
    assert d.groups()['fill #000000']['texts'] == 1
    t, = d.texts
    assert (t.text, t.family, t.size) == ('Hi', 'Futura', 12)


def test_curves_within_tolerance(write_svg):
    d = svg.load(write_svg('<circle cx="50" cy="50" r="20" stroke="red" fill="none"/>'), tolerance=0.02)
    p = d.shapes[0].paths[0]
    r = np.hypot(*(p - 50).T)
    assert np.abs(r - 20).max() < 1e-3          # the vertices are on the circle (Béziers in svgelements),
    mid = (p[:-1] + p[1:]) / 2
    assert 20 - np.hypot(*(mid - 50).T).max() < 0.021   # the chords within tolerance of it


def test_default_groups_nearest_tool_and_white_mask(write_svg, tools):
    d = svg.load(write_svg('''
        <path d="M0 0 H10" stroke="#e00000" stroke-width="1"/>
        <path d="M0 5 H10" stroke="#10ee10" stroke-width="1"/>
        <rect x="0" y="0" width="5" height="5" fill="#fdfdfd"/>'''))
    g = default_groups(d, tools)
    assert g['stroke #e00000'].tool == 'T3'
    assert g['stroke #10ee10'].tool in ('T0', 'T1', 'T2')
    assert g['fill #fdfdfd'].mask


def test_fill_rules():
    outer = np.array([[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]], float)
    same = np.array([[3, 3], [7, 3], [7, 7], [3, 7], [3, 3]], float)
    assert region([outer, same], 'evenodd').area == pytest.approx(100 - 16)
    assert region([outer, same], 'nonzero').area == pytest.approx(100)          # both wound the same way
    assert region([outer, same[::-1]], 'nonzero').area == pytest.approx(100 - 16)


def test_fill_keeps_ink_inside():
    area = box(0, 0, 10, 5)
    paths = fill(area, width=0.5, spacing=0.4, pattern='hatch', angle=0)
    pts = np.vstack(paths)
    # The tool's centre stays half its width in: the ink's edge is the area's edge
    assert pts[:, 0].min() == pytest.approx(0.25) and pts[:, 0].max() == pytest.approx(9.75)
    assert pts[:, 1].min() == pytest.approx(0.25) and pts[:, 1].max() == pytest.approx(4.75)
    # One zigzag: the hatch lines are linked inside the area
    assert len(paths) == 2      # the border, and the hatch


def test_hatch_grid_and_spacing():
    lines = hatch(box(0, 0, 10, 10), 1.0, 0)
    ys = sorted(round(l[0][1], 6) for l in lines)
    assert ys == [float(k) for k in range(0, 11)]


def test_thin_parts_are_drawn_on_their_centre():
    river = LineString([(0, 0), (30, 0), (30, 20)]).buffer(0.2, cap_style='flat')    # 0.4 wide, pen 0.5
    assert inset(river, 0.25).is_empty
    paths = fill(river, 0.5, 0.4)
    pts = np.vstack(paths)
    assert river.buffer(1e-6).contains(Point(pts[0]))
    assert sum(np.hypot(*np.diff(p, axis=0).T).sum() for p in paths) > 45       # most of its 50mm


def test_crossing_lines_keep_their_colours(write_svg, tools):
    # Red under, then a 4mm yellow line over it: the red is cut where the yellow is
    p = write_svg('''
        <path d="M10 50 H90" stroke="#ff0000" stroke-width="0.5"/>
        <path d="M50 10 V90" stroke="#21ff06" stroke-width="4"/>''')
    groups = {'stroke #ff0000': Group(tool='T3'), 'stroke #21ff06': Group(tool='T0')}
    s = slice_object(Obj(id='d', svg=str(p), groups=groups), tools)
    red = sorted(s.paths['T3'], key=lambda a: a[:, 0].min())
    assert len(red) == 2
    assert red[0][:, 0].max() == pytest.approx(48) and red[1][:, 0].min() == pytest.approx(52)
    # The yellow is 4mm wide, drawn as its area, the pen's centre half its width in
    yx, w = np.vstack(s.paths['T0'])[:, 0], tools['T0'].width
    assert yx.min() == pytest.approx(48 + w / 2) and yx.max() == pytest.approx(52 - w / 2)
    # Without occlusion the red is one line
    s2 = slice_object(Obj(id='d', svg=str(p), groups=groups, occlude=False), tools)
    assert len(s2.paths['T3']) == 1


def test_masks_hide_and_see_through_doesnt(write_svg, tools):
    p = write_svg('''
        <path d="M10 50 H90" stroke="#ff0000" stroke-width="0.5"/>
        <circle cx="30" cy="50" r="5" fill="#ffffff"/>
        <path d="M70 10 V90" stroke="#0000ff" stroke-width="4" stroke-opacity="0.5"/>''')
    groups = {'stroke #ff0000': Group(tool='T3'), 'fill #ffffff': Group(mask=True),
              'stroke #0000ff': Group(tool='T4')}
    s = slice_object(Obj(id='d', svg=str(p), groups=groups), tools)
    assert len(s.paths['T3']) == 2         # cut by the white circle only
    assert 'T4' in s.paths
    # A colour that isn't drawn hides nothing
    groups['fill #ffffff'] = Group()
    assert len(slice_object(Obj(id='d', svg=str(p), groups=groups), tools).paths['T3']) == 1


def test_object_coordinates_are_y_up(write_svg, tools):
    p = write_svg('<path d="M0 0 L10 0" stroke="#ff0000" stroke-width="0.5"/>', w=20, h=30)
    s = slice_object(Obj(id='d', svg=str(p), groups={'stroke #ff0000': Group(tool='T3')}), tools)
    a, = s.paths['T3']
    assert a[:, 1].tolist() == pytest.approx([30, 30])         # the SVG's top is y = page height
    assert a[:, 2].tolist() == [0, 0]
