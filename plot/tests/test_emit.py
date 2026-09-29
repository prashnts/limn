# G-code: travels, z limits, placement, tools and the preview
import numpy as np
import pytest

from plot.emit import plot
from plot.job import Group, Placement, SurfaceSpec
from plot.preview import DRAW, TRAVEL, parse, render_svg, stats
from plot.profile import load_machine, load_tools
from plot.slicer import Cache
from plot.tools import REGISTRY, Tool

RED = {'stroke #ff0000': Group(tool='T3')}


def moves(gcode, cmd=None):
    out = []
    for line in gcode.splitlines():
        w = line.split()
        if w and w[0] in ('G0', 'G1') and (cmd is None or w[0] == cmd):
            out.append((w[0], {k[0]: float(k[1:]) for k in w[1:]}))
    return out


def zs(gcode, cmd):
    return [p['Z'] for c, p in moves(gcode, cmd) if 'Z' in p]


def test_structure_and_heights(write_svg, job_of):
    # Two short strokes 5mm apart, and a third 60mm away
    p = write_svg('''
        <path d="M10 10 H20 M25 10 H35 M95 10 H96" stroke="#ff0000" stroke-width="0.5" fill="none"/>''')
    r, _ = plot(job_of(p, groups=RED))
    g = r.gcode
    lines = [l for l in g.splitlines() if l and not l.startswith(';')]
    assert lines[:5] == ['LAZY_HOME', 'PLOT_START EXT=3', '_CLEAR_OFFSETS HOME=1', 'T3', '_APPLY_OFFSETS HOME=1']
    assert lines[-1] == 'PLOT_END'
    m, pen = load_machine(), load_tools()['T3']
    assert set(zs(g, 'G1')) == {pen.z_down}          # pen down, the old ACT1
    travel = zs(g, 'G0')
    assert pen.z_down + pen.hop in travel            # the short hop
    assert m.z_travel in travel                      # the long travel
    assert max(travel) <= m.z_max
    assert not r.problems
    assert r.stats['tools']['T3']['strokes'] == 3
    assert r.stats['draw_mm'] == pytest.approx(21, abs=1e-3)


def test_travel_goes_up_before_and_down_after(write_svg, job_of):
    p = write_svg('<path d="M10 10 H20 M80 10 H90" stroke="#ff0000" stroke-width="0.5" fill="none"/>')
    g = plot(job_of(p, groups=RED))[0].gcode
    seq = moves(g)
    # Every XY travel happens at or above the travel height it needs: no XY move at pen height
    z = None
    for cmd, pr in seq:
        if 'Z' in pr and not ('X' in pr or 'Y' in pr):
            z = pr['Z']
        elif cmd == 'G0':
            assert z is None or z >= load_tools()['T3'].lift()


def test_z_limits_are_configurable(write_svg, job_of):
    p = write_svg('<path d="M10 10 H20 M80 10 H90" stroke="#ff0000" stroke-width="0.5" fill="none"/>')
    job = job_of(p, groups=RED)
    job.machine_overrides = {'z_travel': 4, 'z_max': 4.5}
    r, _ = plot(job)
    assert max(zs(r.gcode, 'G0')) == 4
    assert not r.problems
    # A pen that needs more than the limits allow is clamped, and it's a problem
    job.machine_overrides = {'z_max': 1.5}           # under the pen's hop
    r, _ = plot(job)
    assert max(zs(r.gcode, 'G0') + zs(r.gcode, 'G1')) <= 1.5
    assert any('z_max' in p or 'limits' in p for p in r.problems)
    job.machine_overrides = {'z_min': 1.5}
    r, _ = plot(job)
    assert min(zs(r.gcode, 'G1')) == 1.5
    assert any('limits' in p for p in r.problems)


def test_zones(write_svg, job_of, tmp_path):
    p = write_svg('<path d="M0 100 H1 M60 100 H61" stroke="#ff0000" stroke-width="0.5" fill="none"/>')
    job = job_of(p, x=20, y=100, groups=RED)
    # A clip in the way: the travel over it goes clearance above its top
    job.machine_overrides = {'zones': [{'name': 'clip', 'rect': [40, 95, 45, 105], 'z': 5.5}]}
    g = plot(job)[0].gcode
    assert 6.5 in zs(g, 'G0')
    job.machine_overrides = {'zones': [{'name': 'clip', 'rect': [40, 95, 45, 105], 'z': 6.5}]}
    assert any('over z_max' in p for p in plot(job)[0].problems)
    job.machine_overrides = {'zones': [{'name': 'holders', 'rect': [40, 95, 45, 105]}]}
    assert any('crosses holders' in p for p in plot(job)[0].problems)


def test_draw_area(write_svg, job_of):
    p = write_svg('<path d="M0 100 H50" stroke="#ff0000" stroke-width="0.5" fill="none"/>')
    r, _ = plot(job_of(p, x=80, y=100, groups=RED))
    assert any('outside the draw area' in p for p in r.problems)


def test_moving_doesnt_slice_again(write_svg, job_of):
    p = write_svg('<path d="M10 10 H20 V30" stroke="#ff0000" stroke-width="0.5" fill="none"/>')
    job = job_of(p, x=10, y=40, groups=RED)
    cache = Cache()
    a, _ = plot(job, cache)
    job.objects[0].placement = Placement(x=30, y=50, rotate=90)
    b, _ = plot(job, cache)
    assert cache.slices == 1
    sa, sb = parse(a.gcode), parse(b.gcode)
    da, db = sa.segs[sa.kind == DRAW], sb.segs[sb.kind == DRAW]
    assert len(da) == len(db) == 2
    assert np.hypot(*(da[:, 3:5] - da[:, :2]).T).sum() == pytest.approx(np.hypot(*(db[:, 3:5] - db[:, :2]).T).sum())
    # Anything but the placement slices again
    job.objects[0].groups = {'stroke #ff0000': Group(tool='T4')}
    plot(job, cache)
    assert cache.slices == 2


def test_rotation_is_about_the_origin():
    pl = Placement(x=10, y=20, rotate=90)
    assert pl.apply([[1, 0, 0]])[0].tolist() == pytest.approx([10, 21, 0])
    assert pl.local(pl.apply([[3, 4, 0]]))[0].tolist() == pytest.approx([3, 4, 0])


def test_tool_kinds(write_svg, job_of, tmp_path):
    (tmp_path / 'kinds').mkdir()
    (tmp_path / 'kinds' / 'marker.py').write_text('''
from plot.tools import Pen, kind

@kind('test-marker')
class Marker(Pen):
    press: float = 0.2

    def down(self, ctx, z):
        return z + self.z_down - self.press
''')
    (tmp_path / 'tools.toml').write_text('''
plugins = ["kinds/marker.py"]
[T0]
kind = "pencil"
width = 0.3
wear = 100
[T1]
kind = "laser"
focus = 4
power = 99
[T2]
kind = "brush"
width = 1
reload_every = 30
well = [100, 20]
well_z = 0.5
dips = 1
[T3]
kind = "test-marker"
press = 0.3
''')
    body = '<path d="M10 10 H50" stroke="{}" stroke-width="0.2" fill="none"/>'
    p = write_svg(''.join(body.format(c).replace('M10 10', f'M10 {10 + 10 * i}')
                          for i, c in enumerate(['#000000', '#ff6a00', '#0000ff', '#00ff00'])))
    groups = {'stroke #000000': Group(tool='T0'), 'stroke #ff6a00': Group(tool='T1'),
              'stroke #0000ff': Group(tool='T2'), 'stroke #00ff00': Group(tool='T3')}
    job = job_of(p, groups=groups)
    job.tools = str(tmp_path / 'tools.toml')
    assert load_tools(job.tools)['T3'].__class__.__name__ == 'Marker'
    g = plot(job)[0].gcode
    blocks = dict(zip(['T0', 'T1', 'T2', 'T3'], g.split('\n; --- ')[1:]))
    # pencil: lower as it draws
    z0 = zs(blocks['T0'], 'G1')
    assert z0[0] == 1 and z0[-1] < 1
    # laser: at its focus, on while drawing
    assert 'M3 S99' in blocks['T1'] and 'M5' in blocks['T1']
    assert set(zs(blocks['T1'], 'G1')) <= {4.0}
    sim = parse(g)
    # brush: 40mm with a dip every 30: to the well twice
    well = [pr for c, pr in moves(blocks['T2'], 'G0') if pr.get('X') == 100 and pr.get('Y') == 20]
    assert len(well) == 2 and 0.5 in zs(blocks['T2'], 'G1')
    # the hand-written kind
    assert zs(blocks['T3'], 'G1') and all(z == pytest.approx(0.7) for z in zs(blocks['T3'], 'G1'))


def test_unknown_kind():
    from plot.tools import resolve
    with pytest.raises(ValueError, match='no tool kind'):
        resolve('crayon')


def test_heightmap_object(write_svg, job_of, tmp_path):
    # A bump 3mm high under the middle of a 40mm line: the pen follows it,
    # and the travels go over it
    z = np.zeros((11, 41))
    z[:, 18:23] = 3.0
    np.save(tmp_path / 'bump.npy', z)
    p = write_svg('<path d="M0 50 H40 M0 45 H40" stroke="#ff0000" stroke-width="0.5" fill="none"/>', w=40, h=100)
    job = job_of(p, x=20, y=40, groups=RED,
                 surface=SurfaceSpec(kind='heightmap', path='bump.npy', origin=(0, 45), pitch=1))
    r, _ = plot(job)
    down = zs(r.gcode, 'G1')
    assert min(down) == 1 and max(down) == pytest.approx(4)
    sim = parse(r.gcode)
    trav = sim.segs[(sim.kind == TRAVEL) & (np.abs(sim.segs[:, 0] - sim.segs[:, 3]) > 1)]
    for s in trav:
        if 38 <= min(s[0], s[3]) <= 43 or min(s[0], s[3]) < 40 < max(s[0], s[3]):
            assert s[2] >= 4        # over the bump, clear of it


def test_preview_of_prusa_gcode(machine):
    # What PrusaSlicer wrote with the ACT substitutions (slicer/config.ini)
    g = '''
T0 ; change extruder
G1 Z10 ACT3 X10 Y10 ; move to first layer point
G1 Z0 ACT1 ; unretract
G1 X20 Y10 E1.2
G3 X30 Y20 I0 J10 E1
G1 Z5 ACT2 ; retract
G1 X50 Y50
G1 Z0 ACT1
G1 X60 Y50 E1
'''
    sim = parse(g)
    assert not sim.ours and sim.tools == ['T0']
    drawn = sim.segs[sim.kind == DRAW]
    assert drawn[:, 2].max() == 1 and np.all(drawn[:, 5] == 1)       # ACT1 is Z1
    st = stats(sim, machine)
    arc = np.pi / 2 * 10
    assert st['draw_mm'] == pytest.approx(10 + arc + 10, rel=1e-2)
    # The travel at ACT2 (Z3) isn't drawn
    assert st['tool_changes'] == 1


def test_render_has_bed_art_and_tools(write_svg, job_of, machine, tools):
    p = write_svg('<path d="M10 10 H20" stroke="#ff0000" stroke-width="0.5" fill="none"/>')
    g = plot(job_of(p, groups=RED))[0].gcode
    out = render_svg(parse(g), machine, tools)
    assert 'data:image/svg+xml;base64,' in out
    assert 'stroke="#fb0207" stroke-width="0.5"' in out


def test_order_improves_and_keeps_every_path():
    from plot.order import improve, join, length, order
    rng = np.random.default_rng(1)
    paths = [np.array([p, p + rng.normal(0, 1, 2)]) for p in rng.uniform(0, 100, (300, 2))]

    def travel(ps):
        pos, t = np.zeros(2), 0.0
        for p in ps:
            t += np.hypot(*(p[0] - pos))
            pos = p[-1]
        return t
    g = order(paths)
    im = improve(g, (0, 0), 2.0)
    assert travel(im) < travel(g)
    assert len(im) == len(paths) and length(im) == pytest.approx(length(paths))
    ends = lambda ps: sorted(tuple(np.round(np.sort(p[[0, -1]], axis=0).ravel(), 9)) for p in ps)
    assert ends(im) == ends(paths)          # the same paths, some the other way round


def test_link_small_gaps_only():
    from plot.order import join
    a, b, c = (np.array([[0, 0, 0], [10, 0, 0]], float), np.array([[10.2, 0, 0], [20, 0, 0]], float),
               np.array([[21, 0, 0], [30, 0, 0]], float))
    out = join([a, b, c], link=0.25)
    assert len(out) == 2 and out[0][-1, 0] == 20        # down across 0.2, up for 1


def test_z_moves_in_a_row_are_one():
    from plot.gcode import Writer
    g = Writer()
    g.at(0, 0, 1)
    g.rapid(z=1.8, f=300)
    g.rapid(z=2.5, f=300)
    g.rapid(x=20, f=7800)
    g.rapid(z=1.8, f=300)
    g.rapid(z=1, f=300)         # down and up again: nothing
    assert g.lines == ['G0 Z2.5 F300', 'G0 X20 F7800', 'G0 Z1 F300']


def test_reach_keeps_tool_offsets_inside_the_axes(write_svg, job_of):
    # BED_5's paper starts at X0; a tool with dx -2.54 can't draw at X2 (Klipper: out of range)
    from plot.profile import load_machine
    m = load_machine(overrides={'bed_id': 'BED_5'})
    assert m.draw_area[0] == m.travel_area[0] + m.tool_max_dxy
    p = write_svg('<path d="M0 100 H20" stroke="#ff0000" stroke-width="0.5" fill="none"/>')
    job = job_of(p, x=2, y=100, groups=RED)
    job.machine_overrides = {'bed_id': 'BED_5'}
    r, _ = plot(job)
    assert any('travel limits' in p for p in r.problems)
    assert any('outside the draw area' in p for p in r.problems)
    job.objects[0].placement = Placement(x=6, y=100)
    assert not plot(job)[0].problems
