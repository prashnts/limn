# uv run python ext/tests/test_marks.py
# The bed's placement, its meshes and the test marks, over Klipper restarts.
from fakes import run_tests
from test_klipper import FakeGcmd, make, make_with_holder, raises
from limn.placement import placement_key, mesh_fingerprint, stale_meshes, next_mark
from limn.geometry import gen_mark_grid, mark_strokes
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
        points = gen_mark_grid(**bed['marks'])
        for a, b in zip(points, points[1:]):
            assert marks.problems(mark_strokes(a, b, bed['marks']['arm']), (5, 5, 1.0),
                                  ((x0, y0), (x0 + w, y0 + h))) == [], name


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
        printer.objects.update({'bed_mesh': self.bed_mesh, 'toolhead': self.toolhead, 'probe': object()})
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
            self.bed_mesh.profiles[params['PROFILE']] = profile(x0, y0, x1, y1, z=-2 - len(self.meshed) / 100)
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
        return [s for s in self.gcode.scripts if s.endswith('ACT1')]

    def restart(self, **kwargs):
        '''Klipper again, with what survives: the saved variables and the meshes.'''
        ext, printer = make()
        return Plotter(ext, printer, svv=self.svv, bed_mesh=self.bed_mesh, bed=self.bed, **kwargs)


def plotter(carried=42, **kwargs):
    ext, printer = make()
    return Plotter(ext, printer, svv={'currently_docked_tool': carried}, **kwargs)


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
    assert p.said('Next test mark: 4 of 17')
    p.bed = reply(placed=5)
    p.run('LRT_MARKS')
    assert p.said('Next test mark: 1 of 17')

def test_mark_travels_high_and_away_from_the_holders():
    p = plotter(carried=42)
    p.run('LRT_PROBE_TOOL')
    (x0, y0, z0), (x1, y1, z1), (x2, y2, z2) = p.toolhead.moves[-3:]
    assert z0 == z1 == z2 == 9                              # up, over the beds
    assert (x1, y1) == (24.0, 3.0) and (x2, y2) == (24.0, 120.0)    # X first, away from the reader
    assert p.gcode.scripts.index('_APPLY_OFFSETS MESH=lrt_paper') < p.gcode.scripts.index('G1 Z1 ACT1')

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

def test_paper_full():
    p = plotter(carried=42)
    p.svv['lrt_marks'] = {'placement': 'BED_3@dock:9f2c01aa:1', 'next': 17}
    p.run('LRT_PROBE_TOOL')
    assert p.pen_downs() == [] and p.said('paper is full')
    p.run('LRT_MARKS', RESET=1)
    p.run('LRT_PROBE_TOOL')
    assert len(p.pen_downs()) == 2 and p.svv['lrt_marks']['next'] == 1


def test_fsr_bltouch_z_puts_the_tool_away():
    p = plotter(carried=42)

    class Fsr:
        def bltouch_z(self, cell):
            assert not p.svv['currently_docked_tool'], 'BLTouch probing with a tool on'
            return 4.2

    assert p.ext._fsr_bed_z(FakeGcmd(p.gcode, {}), Fsr(), (1, 1, 3)) == 4.2
    assert p.gcode.scripts[:2] == ['UNDOCK', 'DOCK T=42'] and p.undocked == [42] and p.docked == [42]

def test_the_sheet_is_wiped_between_pens():
    p = plotter(carried=42, bed=reply('BED_5'))
    gcmd = FakeGcmd(p.gcode, {})

    class Fsr:
        wiped = 0
        before_measure = after_measure = None

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


if __name__ == '__main__':
    run_tests(globals())
