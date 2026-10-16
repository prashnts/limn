# uv run python ext/tests/test_marks.py
# The bed's placement, its meshes and the test marks, over Klipper restarts.
import collections
from fakes import run_tests
from test_klipper import FakeGcmd, FakeProbe, make, make_with_holder, raises
from limn.placement import placement_key, mesh_fingerprint, stale_meshes, next_mark, mesh_move_z
from limn.geometry import (gen_mark_grid, mark_points, mark_strokes, holder_ticks, wipe_slots, prime_strokes, plus_strokes,
                           sheet_layout, purge_strokes, purge_slots, fill_order)
from limn.beds import TOOL_MAX_DXY
import numpy as np
from limn.beds import BEDS
from limn import marks

BED_3_SPEC = ['BED_3', 10000, 28000, 36000]


def reply(name='BED_3', boot='9f2c01aa', placed=1, powered=True):
    return [name, BED_3_SPEC if name == 'BED_3' else None,
            {'boot': boot, 'placed': placed, 'powered': powered}]


def profile(x0, y0, x1, y1, z=-2.0):
    return {'points': [[z, z + 0.1234567], [z + 0.2, z]],
            'mesh_params': {'min_x': x0, 'max_x': x1, 'min_y': y0, 'max_y': y1, 'x_count': 2, 'y_count': 2}}


# Pure parts
def test_placement_key():
    assert placement_key(reply(), 'live:1') == 'BED_3@dock:9f2c01aa:1'
    assert placement_key(reply(placed=2), 'live:1') != placement_key(reply(), 'live:1')
    assert placement_key(reply(boot='00000001'), 'live:1') != placement_key(reply(), 'live:1')
    assert placement_key(reply(powered=False), 'live:1') is None          # not confirmed yet
    assert placement_key(reply('NONE', powered=False), 'live:1') == 'NONE@dock:9f2c01aa:1'
    assert placement_key(['BED_3', BED_3_SPEC], 'live:1') == 'BED_3@live:1'     # older Dock firmware

def test_fingerprint_survives_save_config():
    p = profile(5, 100, 114.97999999999999, 175)
    saved = {'points': [[float('%.6f' % v) for v in row] for row in p['points']],
             'mesh_params': dict(p['mesh_params'])}
    assert mesh_fingerprint(p) == mesh_fingerprint(saved)
    assert mesh_fingerprint(profile(5, 100, 115, 175, z=-1.9)) != mesh_fingerprint(p)
    assert mesh_fingerprint(None) is None

def test_stale_meshes():
    profiles = {'lrt_paper': profile(5, 100, 115, 175)}
    record = {'placement': 'k', 'profiles': {'lrt_paper': mesh_fingerprint(profiles['lrt_paper'])}}
    assert stale_meshes(record, 'k', profiles, ['lrt_paper']) == []
    assert stale_meshes(record, 'other', profiles, ['lrt_paper'])
    assert stale_meshes(record, None, profiles, ['lrt_paper'])
    assert stale_meshes(None, 'k', profiles, ['lrt_paper'])
    assert 'no lrt_panel' in stale_meshes(record, 'k', profiles, ['lrt_paper', 'lrt_panel'])[0]
    older = {'lrt_paper': profile(5, 100, 115, 175, z=-1.5)}
    assert 'SAVE_CONFIG' in stale_meshes(record, 'k', older, ['lrt_paper'])[0]

def test_next_mark():
    assert next_mark({'placement': 'k', 'next': 4}, 'k') == 4
    assert next_mark({'placement': 'k', 'next': 4}, 'k2') == 0
    assert next_mark({'placement': 'k', 'next': 4}, None) == 0
    assert next_mark(None, 'k') == 0

def test_marks_make_a_cross_with_the_previous_one():
    points = gen_mark_grid(**BEDS['BED_3']['marks'])
    assert len(points) == 18 and points[0] == (20.0, 120.0) and points[1] == (36.0, 120.0)
    first, second = mark_strokes(points[0], points[1], 4), mark_strokes(points[1], points[2], 4)
    closing, opening = first[1], second[0]
    assert closing[1] == opening[1] == points[1]            # both corners at the same point
    arms = {(p[0] - points[1][0], p[1] - points[1][1]) for p in (closing[0], closing[2], opening[0], opening[2])}
    assert arms == {(-4, 0), (0, -4), (4, 0), (0, 4)}       # together: a +

def test_mark_problems():
    strokes = mark_strokes((20, 120), (36, 120), 4)
    paper = ((5, 100), (115, 175))
    assert marks.problems(strokes, (0.3, -0.2, 1.0), paper) == []
    assert 'dx=9' in marks.problems(strokes, (9, 0, 1.0), paper)[0]
    assert 'dz=4' in marks.problems(strokes, (0, 0, 4), paper)[0]
    assert 'off the paper' in marks.problems(strokes, (0, 0, 1.0), ((25, 100), (115, 175)))[0]
    assert 'past X' in marks.problems(mark_strokes((100, 120), (114, 120), 4), (0, 0, 1.0), paper)[0]
    for name, bed in BEDS.items():                          # each bed's marks fit its paper mesh
        paper_mesh = next(m for m in bed['meshes'] if m['profile'] == 'lrt_paper')
        (x0, y0), (w, h) = paper_mesh['origin'], paper_mesh['size']
        points = mark_points(bed['marks'])
        for a, b in zip(points, points[1:]):
            assert marks.problems(mark_strokes(a, b, bed['marks']['arm']), (5, 5, 1.0),
                                  ((x0, y0), (x0 + w, y0 + h))) == [], name


# The sheet: the purge and the marks (BED_5)
SHEET = BEDS['BED_5']['marks']


def dots(strokes, step=0.1):
    '''Points every `step` mm along the strokes.'''
    out = []
    for s in strokes:
        for (ax, ay), (bx, by) in zip(s, s[1:]):
            n = max(1, int(np.hypot(bx - ax, by - ay) / step))
            out += [(ax + (bx - ax) * k / n, ay + (by - ay) * k / n) for k in range(n + 1)]
    return np.array(out)


def apart(a, b):
    return float(np.min(np.hypot(a[:, None, 0] - b[None, :, 0], a[:, None, 1] - b[None, :, 1])))


def footprint(at, arm):
    '''All a point can hold: the └ drawn there, the ┐ the pen before left there, five ticks.'''
    x, y = at
    return [[(x + arm, y), (x, y), (x, y + arm)], [(x - arm, y), (x, y), (x, y - arm)]] + holder_ticks(at, 5, arm)


def test_fill_order_coarse_then_between():
    assert fill_order(0, 3, 1) == [0, 1, 2, 3, 0.5, 1.5, 2.5]

def test_sheet_uses_the_whole_area_and_stays_on_the_mesh():
    L = sheet_layout(SHEET)
    assert len(L['points']) - 1 >= 120 and purge_slots(L) >= 20
    paper = next(m for m in BEDS['BED_5']['meshes'] if m['profile'] == 'lrt_paper')
    (mx, my), (w, h) = paper['origin'], paper['size']
    assert SHEET['area'] == ((mx + TOOL_MAX_DXY, my + TOOL_MAX_DXY), (mx + w - TOOL_MAX_DXY, my + h - TOOL_MAX_DXY))
    everything = [st for k in range(purge_slots(L)) for st in purge_strokes(L, k)] \
        + [st for p in L['points'] for st in footprint(p, SHEET['arm'])]
    for d in ((5, 5), (-5, -5), (5, -5), (-5, 5)):          # any offsets a tag may have
        assert marks.problems(everything, (*d, 1.0), ((mx, my), (mx + w, my + h))) == [], d
    xs = [x for st in everything for x, _ in st]
    ys = [y for st in everything for _, y in st]
    (x0, y0), (x1, y1) = SHEET['area']
    assert min(xs) - x0 < 1 and x1 - max(xs) < 1 and min(ys) - y0 < 1 and y1 - max(ys) < 1     # edge to edge
    # The purge is a quarter of it
    t = L['band']
    assert abs(t * (x1 - x0) + t * (y1 - y0) - t * t - 0.25 * (x1 - x0) * (y1 - y0)) < 1

def test_sheet_marks_and_purge_keep_apart():
    L, arm = sheet_layout(SHEET), SHEET['arm']
    prints = [dots(footprint(p, arm)) for p in L['points']]
    for i, a in enumerate(prints):                          # every mark, the in-between ones too
        near = [j for j, q in enumerate(L['points']) if j != i and abs(q[0] - L['points'][i][0]) <= 10
                and abs(q[1] - L['points'][i][1]) <= 10]
        for j in near:
            assert apart(a, prints[j]) >= 0.75, (L['points'][i], L['points'][j])
    purge = dots([st for k in range(purge_slots(L)) for st in purge_strokes(L, k)], step=0.5)
    every_mark = np.concatenate(prints)
    assert apart(purge, every_mark) >= SHEET['purge']['gap'] - 0.01
    lines = [dots([a]) for a in L['y_lines']] + [dots([a]) for a in L['x_lines']]
    rings = dots([purge_strokes(L, k)[1] for k in range(len(L['circles']))], step=0.3)
    assert min(apart(rings, ln) for ln in lines) >= 0.5     # the circles stay in their corner

def test_purge_lines_line_up_pen_after_pen():
    L = sheet_layout(SHEET)
    ys = [purge_strokes(L, k)[0] for k in range(purge_slots(L))]
    assert len({(a[1], b[1]) for a, b in ys}) == 1         # same start and end: side by side
    x = [a[0] for a, _ in ys]
    assert x[1] - x[0] == SHEET['purge']['pitch'] and len(set(x)) == len(x)
    ring = purge_strokes(L, 0)[1]
    assert ring[0] == ring[-1]                              # a closed circle
    assert purge_strokes(L, purge_slots(L)) == purge_strokes(L, 0)     # full: over the first again

def test_sheet_status_and_plan():
    st = marks.sheet_status(SHEET, None)
    n, k = len(mark_points(SHEET)) - 1, purge_slots(sheet_layout(SHEET))
    assert st == {'marks': [0, n], 'purge': [0, k], 'full': []}
    assert marks.sheet_status(SHEET, {'next': 3, 'purge': k})['full'] == ['purge']
    strokes, after, said = marks.plan(SHEET, {'next': 3, 'purge': 4}, 45)
    assert after == {'next': 4, 'purge': 5} and said.startswith('purge 5, mark 4')
    assert len(strokes) == 3 + 2 + 5                        # Y line, circle, X line; └ ┐; five ticks
    strokes, after, _ = marks.plan(SHEET, {'next': n, 'purge': k}, 41)     # full: on it goes
    assert after == {'next': n + 1, 'purge': k + 1}
    assert strokes[3:5] == mark_strokes(mark_points(SHEET)[0], mark_points(SHEET)[1], SHEET['arm'])


# In Klipper
class FakeBedMesh:
    def __init__(self):
        self.profiles = {}

    def get_status(self, eventtime):
        return {'profiles': self.profiles}


class FakeToolhead:
    def __init__(self):
        self.pos = [135.0, 3.0, 7.0, 0.0]
        self.moves = []
        self.waits = 0

    def manual_move(self, coord, speed):
        self.pos[:3] = [p if c is None else c for p, c in zip(self.pos, coord)]
        self.moves.append(tuple(self.pos[:3]))

    def get_position(self):
        return list(self.pos)

    def get_last_move_time(self):
        return 0.0

    def wait_moves(self):
        self.waits += 1


class FakeRoutine:
    def __init__(self, plotter, offsets):
        self.plotter = plotter
        self.offsets = offsets

    def calibrate(self):
        self.plotter.steps.append('calibrate')
        return {}

    def probe_bed_z(self):
        assert not self.plotter.svv.get('currently_docked_tool'), 'BLTouch probing with a tool on'
        self.plotter.steps.append('bed_z')
        return [[30.0, 42.0, 9, 0, 0, 4.5]]

    def bed_z_update(self, profile, bed_z):
        return {'ref_z_panel': bed_z}

    def calibrate_reference(self, bed_z):
        self.plotter.steps.append(('reference', self.plotter.svv.get('currently_docked_tool')))
        return {'ref_z_panel': bed_z, 'touch_params': [1, 0, 0, 0, 1, 0]}

    def probe_tool(self, profile):
        return self.offsets


class Plotter:
    '''The macros the extension runs, as far as it cares: BED_MESH_CALIBRATE
    (undocks first), DOCK, WRITE_TOOL_TAG.'''

    def __init__(self, ext, printer, svv=None, bed_mesh=None, bed=None, offsets=(0.3, -0.2, 1.1),
                 reference_tag=False):
        self.ext, self.printer = ext, printer
        self.gcode = printer.objects['gcode']
        self.svv = printer.objects['save_variables'].allVariables
        if svv is not None:
            self.svv.update(svv)
        self.bed_mesh = bed_mesh or FakeBedMesh()
        self.bed = bed or reply()
        self.toolhead = FakeToolhead()
        printer.objects.update({'bed_mesh': self.bed_mesh, 'toolhead': self.toolhead, 'probe': FakeProbe()})
        self.gcode.on_script = self.on_script
        ext.dock.request = lambda cmd, kind, timeout=3: list(self.bed)
        ext._routine = lambda gcmd, bed: FakeRoutine(self, offsets)
        self.reference_tag = reference_tag      # the tag of the tool in holder 45
        self.meshed, self.docked, self.undocked, self.steps = [], [], [], []

    def on_script(self, script):
        name, *words = script.split()
        params = dict(w.split('=', 1) for w in words if '=' in w)
        if name == 'BED_MESH_CALIBRATE':
            if self.svv.get('currently_docked_tool'):
                self.undocked.append(self.svv['currently_docked_tool'])
                self.svv['currently_docked_tool'] = 0
            x0, y0 = map(float, params.get('mesh_min', '0,35').split(','))
            x1, y1 = map(float, params.get('mesh_max', '110,174').split(','))
            p = profile(x0, y0, x1, y1, z=-2 - len(self.meshed) / 100)
            p['mesh_params'] = collections.OrderedDict(p['mesh_params'])      # as bed_mesh keeps them
            self.bed_mesh.profiles[params['PROFILE']] = p
            self.meshed.append(params['PROFILE'])
        elif name == 'DOCK':
            tool = int(params['T'])
            self.svv['currently_docked_tool'] = tool
            self.docked.append(tool)
            self.ext.tag = {'ok': True, 'name': f'pen {tool}', 'reference': tool == 45 and self.reference_tag}
        elif name == 'UNDOCK':
            if self.svv.get('currently_docked_tool'):
                self.undocked.append(self.svv['currently_docked_tool'])
                self.svv['currently_docked_tool'] = 0
        elif name == 'WRITE_TOOL_TAG':
            for axis in 'XYZ':
                self.svv['tool_offset_' + axis.lower()] = float(params['D' + axis])

    def run(self, name, **params):
        self.gcode.run(name, **params)

    def said(self, text):
        return any(text in s for s in self.gcode.said)

    def pen_downs(self):
        return [s for s in self.gcode.scripts if s == f'G1 Z{marks.PEN_Z}']

    def restart(self, **kwargs):
        '''Klipper again, with what survives: the saved variables and the meshes.'''
        ext, printer = make()
        return Plotter(ext, printer, svv=self.svv, bed_mesh=self.bed_mesh, bed=self.bed, **kwargs)


def plotter(carried=42, **kwargs):
    ext, printer = make()
    return Plotter(ext, printer, svv={'currently_docked_tool': carried}, **kwargs)


def test_a_bed_meshed_before_is_meshed_again_3mm_over_its_highest_point():
    p = plotter(carried=0)
    p.run('LRT_MESH_CALIBRATE')
    meshes = [s for s in p.gcode.scripts if s.startswith('BED_MESH_CALIBRATE')]
    assert not any('HORIZONTAL_MOVE_Z' in s for s in meshes)        # nothing to go by yet
    assert p.svv['lrt_mesh_tops']['BED_3'] == {'lrt_paper': -1.8, 'lrt_panel': -1.81}
    p.run('LRT_MESH_CALIBRATE')
    meshes = [s for s in p.gcode.scripts if s.startswith('BED_MESH_CALIBRATE')][2:]
    assert meshes[0].endswith('HORIZONTAL_MOVE_Z=2.00')               # -1.8 + z_offset 0.8 + 3
    assert meshes[1].endswith('HORIZONTAL_MOVE_Z=1.99')


def test_mesh_calibrate_remembers_the_placement():
    p = plotter(carried=0)
    p.run('LRT_MESH_CALIBRATE')
    assert p.meshed == ['lrt_paper', 'lrt_panel']
    assert p.svv['lrt_meshes']['placement'] == 'BED_3@dock:9f2c01aa:1'
    p.run('LRT_MESH_CALIBRATE', IF_STALE=1)
    assert p.meshed == ['lrt_paper', 'lrt_panel'] and p.said('not meshing')
    p = p.restart()                                         # after SAVE_CONFIG: the same meshes
    p.run('LRT_MESH_CALIBRATE', IF_STALE=1)
    assert p.meshed == []

def test_mesh_calibrate_again_once_the_bed_moved():
    p = plotter(carried=0)
    p.run('LRT_MESH_CALIBRATE')
    p.ext.dock.handle_line('!LRT>>bed_removed>>["NONE", null]>>')
    assert p.ext.placement is None and p.said('bed was removed')
    p.bed = reply(placed=3)                                 # put back: the Dock counted it
    p = p.restart()
    p.run('LRT_MESH_CALIBRATE', IF_STALE=1)
    assert p.meshed == ['lrt_paper', 'lrt_panel'] and p.said('placed after the last meshes')

def test_restart_without_save_config_meshes_again():
    p = plotter(carried=0)
    p.run('LRT_MESH_CALIBRATE')
    p.bed_mesh.profiles['lrt_paper'] = profile(5, 110, 115, 174, z=-1.8)      # the older, saved one
    p = p.restart()
    p.run('LRT_MESH_CALIBRATE', IF_STALE=1)
    assert p.meshed == ['lrt_paper', 'lrt_panel'] and p.said('SAVE_CONFIG')

def test_older_dock_firmware_is_only_trusted_until_a_restart():
    p = plotter(carried=0, bed=['BED_3', BED_3_SPEC])
    p.run('LRT_MESH_CALIBRATE')
    p.run('LRT_MESH_CALIBRATE', IF_STALE=1)
    assert p.meshed == ['lrt_paper', 'lrt_panel']
    p = p.restart()
    p.run('LRT_MESH_CALIBRATE', IF_STALE=1)
    assert p.meshed == ['lrt_paper', 'lrt_panel']

def test_no_bed_meshes_the_whole_bed():
    p = plotter(carried=0, bed=reply('NONE', powered=False))
    p.run('LRT_MESH_CALIBRATE')
    assert p.meshed == ['default'] and 'BED_MESH_CALIBRATE PROFILE=default' in p.gcode.scripts
    p = plotter(carried=0, bed=reply('BED_1'))
    assert 'no meshes known for bed BED_1' in raises(lambda: p.run('LRT_MESH_CALIBRATE'))
    p = plotter(carried=0, bed=reply(powered=False))
    assert 'just been placed' in raises(lambda: p.run('LRT_MESH_CALIBRATE'))
    assert p.meshed == []

def test_empty_holders_are_normal_with_a_carried_tool():
    ext, printer, *_ = make_with_holder(low=(12,), carried=42)             # only 43 home, 42 on
    p = Plotter(ext, printer)
    p.run('LRT_PROBE_TOOL')
    assert p.meshed == ['lrt_paper', 'lrt_panel'] and p.undocked[0] == 42 and p.docked == [42]
    assert p.said('holder 45 is empty') and len(p.pen_downs()) == 2

def test_several_empty_holders_and_nothing_saved_leave_it_to_undock():
    ext, printer, *_ = make_with_holder(low=(12,), carried=0)
    p = Plotter(ext, printer)
    p.run('LRT_MESH_CALIBRATE')
    assert p.meshed == ['lrt_paper', 'lrt_panel'] and p.undocked == [] and not p.said('taking')

def test_probe_tool_puts_a_docked_tool_away_to_mesh():
    ext, printer, *_ = make_with_holder(low=(15, 13, 12, 11), carried=42)  # DOCK T=42
    p = Plotter(ext, printer)
    p.run('LRT_PROBE_TOOL')
    assert p.meshed == ['lrt_paper', 'lrt_panel'] and p.undocked[0] == 42 and p.docked[-1] == 42
    assert len(p.pen_downs()) == 2

def test_probe_tool_takes_the_only_empty_holder_as_the_carried_tool():
    ext, printer, *_ = make_with_holder(low=(15, 13, 12, 11), carried=0, key_open=False)   # 42 on, not saved (DOCK_RESET)
    p = Plotter(ext, printer)
    p.run('LRT_PROBE_TOOL')
    assert p.said('taking 42 as the one on the carriage')
    assert p.meshed == ['lrt_paper', 'lrt_panel'] and p.undocked[0] == 42 and p.docked[-1] == 42

def test_an_open_key_carries_nothing_whatever_the_holders_say():
    # Seen on the printer: holder 45 read empty with its pen put away, the key open.
    # The guess undocked 45 onto an empty carriage and its holder check stopped it.
    ext, printer, *_ = make_with_holder(low=(15, 14, 12, 11), carried=0, key_open=True)
    p = Plotter(ext, printer, bed=reply('BED_5'))
    p.run('LRT_MESH_CALIBRATE')
    assert p.meshed and p.undocked == [] and not p.said('taking')
    assert 'no tool on the carriage' in raises(lambda: p.run('LRT_FSR_Z'))


# The bed moved: its z again, and with the reference tool its points too
def test_moved_bed_with_the_reference_tool_calibrates_again():
    ext, printer, *_ = make_with_holder(low=(15, 13, 12, 11), carried=42)
    p = Plotter(ext, printer, reference_tag=True)
    p.run('LRT_PROBE_TOOL')
    assert p.steps == ['bed_z', ('reference', 45)]
    assert p.docked == [45, 42] and p.undocked == [42, 45]    # 42 away, 45 in and out, 42 back
    assert p.ext.profile['touch_params'] == [1, 0, 0, 0, 1, 0]
    assert p.said('Calibrated again with the reference tool 45')

def test_moved_bed_without_the_reference_tag_only_takes_the_z():
    ext, printer, *_ = make_with_holder(low=(15, 13, 12, 11), carried=42)
    p = Plotter(ext, printer, reference_tag=False)
    touch_params = p.ext.profile['touch_params']
    p.run('LRT_PROBE_TOOL')
    assert p.steps == ['bed_z'] and p.docked == [45, 42]      # looked at 45's tag, put it back
    assert p.ext.profile['ref_z_panel'] == [[30.0, 42.0, 9, 0, 0, 4.5]]
    assert p.ext.profile['touch_params'] == touch_params and len(p.ext.profile['ref_samples']) == 12
    assert p.said("isn't the reference's") and p.said('New bed z only')

def test_moved_bed_with_holder_45_empty_only_takes_the_z():
    ext, printer, *_ = make_with_holder(low=(15, 14, 12, 11), carried=45)  # 45 on the carriage
    p = Plotter(ext, printer, reference_tag=True)
    p.run('LRT_PROBE_TOOL')                                 # the fake holder still reads it empty
    assert p.steps == ['bed_z'] and p.docked == [45] and p.said('holder 45 is empty')

def test_no_holders_only_takes_the_z():
    p = plotter(carried=42)
    p.run('LRT_PROBE_TOOL')
    assert p.steps == ['bed_z'] and p.docked == [42] and p.said('no tool holders')

def test_mesh_calibrate_alone_takes_the_z_too():
    p = plotter(carried=0)
    p.run('LRT_MESH_CALIBRATE')
    assert p.steps == ['bed_z']
    p.steps = []
    p.run('LRT_PROBE_TOOL')                                 # fresh now: nothing again
    assert p.steps == [] and p.meshed == ['lrt_paper', 'lrt_panel']

def test_calibrate_does_not_take_the_z_twice():
    p = plotter(carried=0)
    p.run('LRT_CALIBRATE')
    assert p.steps == ['calibrate']

def test_probe_tool_meshes_a_moved_bed_first_and_takes_the_tool_back():
    p = plotter(carried=42)
    p.run('LRT_PROBE_TOOL')
    assert p.meshed == ['lrt_paper', 'lrt_panel'] and p.undocked == [42] and p.docked == [42]
    assert len(p.pen_downs()) == 2                          # └ and ┐
    p.meshed = []
    p.run('LRT_PROBE_TOOL')
    assert p.meshed == [] and len(p.pen_downs()) == 4

def test_marks_carry_on_after_a_restart_until_the_bed_moves():
    p = plotter(carried=42)
    p.run('LRT_PROBE_TOOL')
    p.run('LRT_PROBE_TOOL')
    assert p.svv['lrt_marks'] == {'placement': 'BED_3@dock:9f2c01aa:1', 'next': 2}
    p = p.restart()
    p.run('LRT_PROBE_TOOL')
    points = gen_mark_grid(**BEDS['BED_3']['marks'])
    x, y = points[2]
    assert f'G1 X{x + 4} Y{y}' in p.gcode.scripts          # └ at the third point: where the last ┐ is
    assert p.svv['lrt_marks']['next'] == 3
    p.run('LRT_MARKS')
    assert p.said('BED_3: 3 of 17 marks')
    p.bed = reply(placed=5)
    p.run('LRT_MARKS')
    assert p.said('BED_3: 0 of 17 marks')

def test_mark_travels_high_and_away_from_the_holders():
    p = plotter(carried=42)
    p.run('LRT_PROBE_TOOL')
    (x0, y0, z0), (x1, y1, z1), (x2, y2, z2) = p.toolhead.moves[-3:]
    assert z0 == z1 == z2 == 9                              # up, over the beds
    assert (x1, y1) == (24.0, 3.0) and (x2, y2) == (24.0, 120.0)    # X first, away from the reader
    assert p.gcode.scripts.index('_APPLY_OFFSETS MESH=lrt_paper') < p.gcode.scripts.index('G1 Z1.0')

def test_mark_pen_is_high_off_the_paper():
    '''Z moves only over the mark, and up to Z7 before anything leaves the paper.'''
    p = plotter(carried=42)
    p.run('LRT_PROBE_TOOL')
    s = p.gcode.scripts
    a, b = s.index('_APPLY_OFFSETS MESH=lrt_paper'), len(s) - 1 - s[::-1].index('_CLEAR_OFFSETS')
    mark = s[a + 1:b]
    assert not any('ACT' in x for x in s)
    assert mark[0] == f'G1 F{marks.DRAW_FEED}' and mark[1].startswith('G1 X')    # across at Z7 (_APPLY_OFFSETS)
    assert mark[-1] == 'G1 Z7.0' and mark[-2] == 'G1 Z2.5'
    zs = [float(x.split('Z')[1]) for x in mark if x.startswith('G1 Z')]
    assert set(zs) == {1.0, 2.5, 7.0}

def test_no_mark_when_unsafe():
    p = plotter(carried=42, offsets=(0.2, 0.1, 5.0))
    p.run('LRT_PROBE_TOOL')
    assert p.pen_downs() == [] and p.said('dz=5.0') and 'lrt_marks' not in p.svv
    p = plotter(carried=42)
    p.run('LRT_MESH_CALIBRATE')
    p.run('LRT_MARKS')
    p.ext._ensure_meshes = lambda gcmd: None                # the bed moves while the tool is probed
    p.bed = reply(placed=2)
    p.run('LRT_PROBE_TOOL')
    assert p.pen_downs() == [] and p.said('placed after the last meshes')

def test_paper_full_draws_on_and_says_so():
    '''The user knows: a full sheet doesn't stop a pen, it goes over the first slots and the
    status (the plot UI, the LEDs) says the sheet is full.'''
    p = plotter(carried=42)
    p.svv['lrt_marks'] = {'placement': 'BED_3@dock:9f2c01aa:1', 'next': 17}
    p.ext._read_bed_id(FakeGcmd(p.gcode, {}))
    assert p.ext.get_status(0)['sheet']['full'] == ['marks']
    p.run('LRT_PROBE_TOOL')
    assert len(p.pen_downs()) == 2 and p.said('The sheet is full (marks)') and p.svv['lrt_marks']['next'] == 18
    x, y = gen_mark_grid(**BEDS['BED_3']['marks'])[0]
    assert f'G1 X{x + 4} Y{y}' in p.gcode.scripts          # over the first mark again
    p.run('LRT_MARKS', RESET=1)
    assert p.ext.get_status(0)['sheet']['full'] == []
    p.run('LRT_PROBE_TOOL')
    assert len(p.pen_downs()) == 4 and p.svv['lrt_marks']['next'] == 1


def test_a_pen_purges_then_marks_on_bed_5():
    p = plotter(carried=45, bed=reply('BED_5'))
    p.run('LRT_MESH_CALIBRATE')
    p.svv['currently_docked_tool'] = 45                     # (meshing put it away)
    p.run('LRT_MARK')
    L = sheet_layout(SHEET)
    s = p.gcode.scripts
    a = s.index('_APPLY_OFFSETS MESH=lrt_paper')
    (x, y0), (_, y1) = L['y_lines'][0]
    assert s[a + 2:a + 5] == [f'G1 X{x} Y{y0}', 'G1 Z1.0', f'G1 X{x} Y{y1}']     # the long line first
    assert len(p.pen_downs()) == 3 + 2 + 5 and p.said('Drawn: purge 1, mark 1')
    assert p.ext.get_status(0)['sheet'] == {'bed': 'BED_5', 'marks': [1, len(L['points']) - 1],
                                            'purge': [1, purge_slots(L)], 'full': []}
    p.svv['lrt_marks']['purge'] = purge_slots(L)            # the purge is full: on it goes, said
    p.run('LRT_MARK')
    assert len(p.pen_downs()) == 20 and p.said('The sheet is full (purge)')
    assert p.ext.get_status(0)['sheet']['full'] == ['purge']


def test_fsr_bltouch_z_puts_the_tool_away():
    p = plotter(carried=42)

    class Fsr:
        def bltouch_z(self, cell):
            assert not p.svv['currently_docked_tool'], 'BLTouch probing with a tool on'
            return 4.2

    assert p.ext._fsr_bed_z(FakeGcmd(p.gcode, {}), Fsr(), (1, 1, 3)) == 4.2
    assert p.gcode.scripts[:2] == ['UNDOCK', 'DOCK T=42'] and p.undocked == [42] and p.docked == [42]

def test_an_inked_sheet_is_wiped_before_the_bltouch_probes_it():
    p = plotter(carried=42, bed=reply('BED_5'))
    p.ext._read_bed_id(FakeGcmd(p.gcode, {}))

    class Fsr:
        wiped = 0

        def wait_clean(self):
            self.wiped += 1

        def bltouch_z(self, cell):
            return 4.2

    fsr = Fsr()
    p.ext._fsr_bed_z(FakeGcmd(p.gcode, {}), fsr, (1, 1, 6))
    assert fsr.wiped == 0                           # nothing touched the sheet yet
    p.ext._fsr_last = 42
    p.ext._fsr_bed_z(FakeGcmd(p.gcode, {'CLEAN': 0}), fsr, (1, 1, 6))
    assert fsr.wiped == 0 and p.ext._fsr_last == 42
    p.ext._fsr_bed_z(FakeGcmd(p.gcode, {}), fsr, (1, 1, 6))
    assert fsr.wiped == 1 and p.ext._fsr_last is None and p.said('left ink on the FSR sheet')
    # Meshing the sheet (lrt_fsr) too
    wipes = []
    p.ext._wipe_sheet = lambda gcmd, bed, routine=None: wipes.append(bed['sensor'])
    p.ext._fsr_last = 42
    p.run('LRT_MESH_CALIBRATE')
    assert wipes == ['fsr'] and 'lrt_fsr' in p.meshed

def test_the_sheet_is_wiped_between_pens():
    p = plotter(carried=42, bed=reply('BED_5'))
    gcmd = FakeGcmd(p.gcode, {})

    class Fsr:
        wiped = 0
        before_measure = after_measure = None
        cfg, press_cap = {'press': 0.3}, None

        def wait_clean(self):
            self.wiped += 1

        def measure(self):
            self.before_measure()
            self.after_measure()

    fsr = Fsr()
    p.ext._fsr_hooks(gcmd, fsr)
    fsr.measure()                                   # nothing known of the sheet: no wait
    fsr.measure()                                   # the same pen again: no wait
    assert fsr.wiped == 0
    p.svv['currently_docked_tool'] = 43
    fsr.measure()                                   # another pen: wipe first
    assert fsr.wiped == 1 and p.said('last had tool 42, now 43')
    assert fsr.press_cap == 0.2 and p.said('at most 0.20mm past contact (the FSR\'s, its tag names no pen)')
    p.ext._tags()['44'] = {'pen': 'stb-88'}
    p.svv['currently_docked_tool'] = 44
    fsr.measure()                                   # a Stabilo may press 0.3: the FSR's 0.2
    assert fsr.press_cap == 0.2 and p.said('at most 0.20mm past contact (the FSR\'s)')
    p.ext._tags()['44'] = {'pen': 'mic-01'}
    fsr.measure()                                   # a Micron 01 (press 0.1 plotting, 0.25 at most): 0.2 too
    assert fsr.press_cap == 0.2
    p.ext._fsr_hooks(FakeGcmd(p.gcode, {'PRESS': '0.3'}), fsr)
    fsr.measure()                                   # PRESS=: deeper, on purpose
    assert fsr.press_cap == 0.3
    p.ext._fsr_hooks(gcmd, fsr)
    fsr.wiped = 1
    p.svv['currently_docked_tool'] = 44
    p.ext._fsr_hooks(FakeGcmd(p.gcode, {'CLEAN': 0}), fsr)
    fsr.measure()                                   # CLEAN=0
    assert fsr.wiped == 1
    p.svv['currently_docked_tool'] = 45
    p.ext.dock.handle_line('!LRT>>bed_removed>>["NONE", null]>>')
    p.ext._fsr_hooks(gcmd, fsr)
    fsr.measure()                                   # the bed was off the plotter
    assert fsr.wiped == 1

def test_fsr_jogs_need_a_tool_on_the_carriage():
    ext, printer, *_ = make_with_holder(low=(13,), carried=0)              # only 45 home, nothing on
    p = Plotter(ext, printer, bed=reply('BED_5'))
    for name in ('LRT_FSR_Z', 'LRT_FSR_EDGE', 'LRT_FSR_MEASURE'):
        assert 'no tool on the carriage' in raises(lambda: p.run(name))
    assert p.toolhead.moves == [] and 'UNDOCK' not in p.gcode.scripts

def test_fsr_bltouch_z_puts_away_a_tool_not_saved_as_carried():
    # Over the array the BLTouch puts the carriage in the lane of holder 41: a pen
    # on it that the variables missed (DOCK_RESET) would run into the holders.
    ext, printer, *_ = make_with_holder(low=(15, 13, 12, 11), carried=0, key_open=False)   # 42 on, not saved
    p = Plotter(ext, printer)

    class Fsr:
        def bltouch_z(self, cell):
            assert not p.svv['currently_docked_tool'], 'BLTouch probing with a tool on'
            return 4.2

    assert p.ext._fsr_bed_z(FakeGcmd(p.gcode, {}), Fsr(), (1, 1, 3)) == 4.2
    assert p.said('taking 42 as the one on the carriage') and p.undocked == [42] and p.docked == [42]


def test_a_calibration_keeps_over_a_restart_without_save_config():
    p = plotter(carried=0, bed=reply('BED_5'))
    ref = {'x': 114.0, 'y': 52.5, 'z': 3.44, 'gaps': [1.0, 0.04], 'tip': [1.5, 1.6], 'bed_z': [[1, 1, 1, 2.72]]}
    p.ext._save_profile({'fsr_ref': ref})
    assert p.svv['lrt_profile']['version'] and p.ext.calibrated('fsr')
    p = p.restart()                                         # no SAVE_CONFIG: the config has none
    assert not p.ext.calibrated('fsr')
    p.ext._load_saved_profile()                             # klippy:connect
    assert p.ext.calibrated('fsr') and p.ext.profile['fsr_ref'] == ref
    p.svv['lrt_profile'] = {**p.svv['lrt_profile'], 'version': 'v0'}     # another format: not taken
    p = p.restart()
    p.ext._load_saved_profile()
    assert not p.ext.calibrated('fsr')

def test_meshes_come_back_after_a_restart_without_save_config():
    p = plotter(carried=0)
    p.run('LRT_MESH_CALIBRATE')
    taken = dict(p.bed_mesh.profiles)
    p.bed_mesh.profiles.clear()
    p.bed_mesh.profiles['lrt_paper'] = profile(5, 110, 115, 174, z=-1.8)      # an older, SAVE_CONFIG'd one
    p = p.restart()
    p.ext._restore_meshes()                                 # klippy:connect
    assert p.bed_mesh.profiles == taken
    p.run('LRT_MESH_CALIBRATE', IF_STALE=1)
    assert p.meshed == [] and p.said('not meshing')

def test_calibrate_uses_the_meshes_of_the_bed_as_it_sits():
    p = plotter(carried=0)
    p.run('LRT_CALIBRATE')
    assert p.meshed == ['lrt_paper', 'lrt_panel']
    p.meshed.clear()
    p.run('LRT_CALIBRATE')                                  # the same bed: no new meshes
    assert p.meshed == [] and p.said('using them')
    p.run('LRT_CALIBRATE', MESH=1)
    assert p.meshed == ['lrt_paper', 'lrt_panel']

def test_a_saved_survey_is_gone_by_until_cleared():
    from limn.beds import BEDS
    p = plotter(carried=45, bed=reply('BED_5'))
    judged = {'faulty': [[0, 3], [1, 3], [2, 3]], 'weak': [[2, 4]], 'noise': 3.0, 'early': 35,
              'median': 500.0, 'warnings': [], 'shift': [2.0, 2.13], 'aim': [1.77, 6.28]}
    p.svv['lrt_fsr_survey'] = {'BED_5': {'date': '2026-10-07 21:00', 'placement': None, 'hops': {'1': judged}}}
    from limn.fsr import Fsr
    gcmd = FakeGcmd(p.gcode, {})
    p.run('LRT_READ_BED_ID')
    fsr = Fsr(None, None, None, BEDS['BED_5']['fsr'])
    p.ext._apply_survey(gcmd, fsr)
    assert fsr.cfg['early'] == 35 and fsr.arrays[1]['aim'] == (1.77, 6.28)
    assert [tuple(c) for c in fsr.arrays[1]['faulty_cells']] == [(0, 3), (1, 3), (2, 3)]
    assert p.said('going by the survey of 2026-10-07 21:00')
    assert BEDS['BED_5']['fsr']['arrays'][0]['aim'] == (1.5, 5.5)          # the config stays as it is
    fsr = Fsr(None, None, None, BEDS['BED_5']['fsr'])
    p.ext._apply_survey(FakeGcmd(p.gcode, {'SURVEY': 0}), fsr)
    assert fsr.cfg.get('early') == BEDS['BED_5']['fsr']['early'] and 'faulty_cells' not in fsr.arrays[1]
    p.run('LRT_FSR_SURVEY', CLEAR=1)
    assert 'BED_5' not in p.svv['lrt_fsr_survey'] and p.said('dropped for BED_5')


# The wipe area: primes and the test marks of pens probed mid-plot, off the paper
WIPE_ON = {**BEDS['BED_5']['wipe'], 'enabled': True}


def wiping(carried=42, **kwargs):
    '''A plotter on BED_5 with its wipe area switched on, meshed, the FSR calibrated.'''
    p = plotter(carried=carried, bed=reply('BED_5'), **kwargs)
    BEDS['BED_5']['wipe'] = WIPE_ON
    p.ext.profile['fsr_ref'] = {'bed_z': []}
    p.run('LRT_MESH_CALIBRATE')
    p.svv['currently_docked_tool'] = carried
    return p


def unwipe():
    BEDS['BED_5']['wipe'] = {**WIPE_ON, 'enabled': False}


def test_wipe_slots_and_strokes_stay_inside():
    w = BEDS['BED_5']['wipe']
    slots = wipe_slots(**w)
    assert len(slots) == w['nx'] * w['ny'] and slots[0][0] == tuple(w['origin'])
    assert slots[1][0][0] > slots[0][0][0] and slots[1][0][1] == slots[0][0][1]    # across X first, then along Y
    rect = (tuple(w['origin']), (w['origin'][0] + w['size'][0], w['origin'][1] + w['size'][1]))
    mesh = ((0, 30), (93, 160))
    for slot in slots:
        for strokes in (prime_strokes(slot), plus_strokes(slot)):
            assert marks.wipe_problems(strokes, (-2, 1, 1.0), rect, mesh) == []
    assert 'past X' in marks.wipe_problems(prime_strokes(slots[-1]), (4.9, 0, 1.0), rect, mesh)[0]
    assert 'off the wipe area' in marks.wipe_problems([[(50, 50), (60, 50)]], (0, 0, 1.0), rect, mesh)[0]
    assert 'no lrt_paper' in marks.wipe_problems(prime_strokes(slots[0]), (0, 0, 1.0), rect, None)[0]


def test_wipe_is_off_until_measured():
    assert BEDS['BED_5']['wipe']['enabled'] is False
    p = plotter(carried=42, bed=reply('BED_5'))
    p.run('TOOL_PRIME')
    assert p.said('switched off') and p.pen_downs() == []


def test_primes_fill_the_wipe_area_then_ask_for_a_fresh_pad():
    p = wiping()
    try:
        n = len(wipe_slots(**WIPE_ON))
        for _ in range(n):
            p.run('TOOL_PRIME')
        assert p.svv['lrt_wipe']['next'] == n and p.said('the wipe area is full now')
        downs = len(p.pen_downs())
        p.run('TOOL_PRIME')
        assert len(p.pen_downs()) == downs and p.said('LRT_WIPE RESET=1')
        assert p.ext.get_status(0)['wipe']['full']
        p.run('LRT_WIPE', RESET=1)
        p.run('TOOL_PRIME')
        assert p.svv['lrt_wipe']['next'] == 1 and not p.ext.get_status(0)['wipe']['full']
        p.bed = reply('BED_5', placed=4)                    # the bed moved: a fresh start, as the marks
        p.run('LRT_WIPE')
        assert p.said('Next slot: 1 of')
    finally:
        unwipe()


def test_prepare_probes_a_pen_without_offsets_and_marks_in_the_wipe_area():
    p = wiping()
    try:
        p.ext.tag = {'ok': True, 'name': 'new pen', 'dx': 0.0, 'dy': 0.0, 'dz': 0.0, 'reference': False}
        marks_before = p.svv.get('lrt_marks')
        p.run('TOOL_PREPARE', CALIBRATE='auto', PRIME=1)
        assert p.said('its tag has no offsets') and any(s.startswith('WRITE_TOOL_TAG DX=0.3') for s in p.gcode.scripts)
        assert p.svv['lrt_wipe']['next'] == 2                # its test mark, then its prime
        assert p.svv.get('lrt_marks') == marks_before        # nothing on the paper: it has the plot
        # A pen with offsets: only primed
        p.ext.tag = {'ok': True, 'name': 'old pen', 'dx': -1.0, 'dy': 0.2, 'dz': 1.1, 'reference': False}
        n = sum(s.startswith('WRITE_TOOL_TAG') for s in p.gcode.scripts)
        p.run('TOOL_PREPARE', CALIBRATE='auto', PRIME=1)
        assert sum(s.startswith('WRITE_TOOL_TAG') for s in p.gcode.scripts) == n and p.svv['lrt_wipe']['next'] == 3
    finally:
        unwipe()


def test_prepare_pauses_when_a_new_pen_cannot_be_measured():
    p = plotter(carried=42, bed=reply('BED_5'))             # not calibrated
    p.ext.tag = {'ok': True, 'name': 'new pen', 'dx': 0.0, 'dy': 0.0, 'dz': 0.0, 'reference': False}
    p.run('TOOL_PREPARE', CALIBRATE='auto', PRIME=0)
    assert p.said("isn't calibrated") and p.gcode.scripts[-1] == 'PAUSE'
    assert not any(s.startswith('WRITE_TOOL_TAG') for s in p.gcode.scripts)


if __name__ == '__main__':
    run_tests(globals())


def test_bed_5_marks_run_down_the_paper_from_its_top_left():
    '''BED_5: two columns along Y from (84, 152), by the dock (high X) and the paper's far end (high Y),
    10mm apart; each mark is still a └ and a ┐ that the next pen's └ makes a + with, and with the
    holder ticks and a pen 5mm off every stroke is on the paper mesh.'''
    m = BEDS['BED_5']['marks']
    points = mark_points(m)
    assert points[0] == (84, 152) and points[1] == (84, 142) and points[11] == (84, 42) and points[12] == (70, 152)
    assert len(points) == 24
    paper_mesh = next(x for x in BEDS['BED_5']['meshes'] if x['profile'] == 'lrt_paper')
    (x0, y0), (w, h) = paper_mesh['origin'], paper_mesh['size']
    for a, b in zip(points, points[1:]):
        strokes = mark_strokes(a, b, m['arm']) + holder_ticks(a, 5, m['arm'])
        for off in ((5, 5, 1.0), (-5, -5, 1.0), (5, -5, 1.0), (-5, 5, 1.0)):
            assert marks.problems(strokes, off, ((x0, y0), (x0 + w, y0 + h))) == [], (a, b, off)


def test_holder_ticks_keep_clear_of_the_crosses():
    '''The ticks go in the quarter of the └'s corner no stroke uses (+X, -Y), and stop short of the next
    point's └ (its +Y arm) 10mm on.'''
    ticks = holder_ticks((84, 152), 5, 3)
    assert len(ticks) == 5
    for (xa, ya), (xb, yb) in ticks:
        assert ya == yb and 84 < xa < xb <= 87 and 152 - 6 < ya < 152
    assert min(p[1] for t in ticks for p in t) > 142 + 3


def test_lrt_mark_draws_the_next_mark_at_a_trim():
    '''LRT_MARK: the carried pen draws the next test mark now. TRIM= goes from the trim the tags were
    written with (the calibration's): a trim 0.1 more is the pen 0.1 lower than Z1. Z= as is; not
    both; out of 0.3 .. 2.0 refused. Each one moves the slot on, its ticks the holder (45: five).'''
    p = plotter(carried=45, bed=reply('BED_5'))
    p.ext.profile['fsr_ref'] = {'bed_z': [], 'dz_trim': 0.3}
    p.run('LRT_MESH_CALIBRATE')
    p.svv['currently_docked_tool'] = 45
    p.run('LRT_MARK')
    assert p.gcode.scripts.count('G1 Z1.0') == 2 + 5 and p.svv['lrt_marks']['next'] == 1
    p.run('LRT_MARK', TRIM=0.4)
    assert p.gcode.scripts.count('G1 Z0.9') == 7 and p.svv['lrt_marks']['next'] == 2 and p.said('a trim of 0.40')
    p.run('LRT_MARK', Z=1.15)
    assert p.gcode.scripts.count('G1 Z1.15') == 7 and p.svv['lrt_marks']['next'] == 3
    assert 'not both' in raises(lambda: p.run('LRT_MARK', TRIM=0.4, Z=1.0))
    assert 'out of 0.3' in raises(lambda: p.run('LRT_MARK', Z=0.1))
    assert p.svv['lrt_marks']['next'] == 3
    p = plotter(carried=42)                                                 # BED_3, an RTP bed: no trim
    assert 'Z= instead' in raises(lambda: p.run('LRT_MARK', TRIM=0.4))


def test_mesh_travel_goes_by_the_last_mesh_of_the_bed():
    # 2026-10-13's lrt_paper: highest point -1.016, the BLTouch's z_offset 0.8
    assert mesh_move_z(-1.016, 0.8, 5.5) == 2.78
    # the FSR sits higher: never over horizontal_move_z
    assert mesh_move_z(1.95, 0.8, 5.5) == 5.5
    # no mesh of this bed yet
    assert mesh_move_z(None, 0.8, 5.5) == 5.5
