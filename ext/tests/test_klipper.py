# uv run python ext/tests/test_klipper.py
# The Klipper side, with stand-ins for Klipper's objects.
import os
import re

import ast

from fakes import FakeReactor, FakeBus, FakeMCP23017, FakePN532, run_tests
import limn
from limn.samples import FSR, S_MATRIX
from limn.tool_holder import ToolHolder, parse_pins
from test_tool_holder import tag_pages

PRINTER_CFG = os.path.join(os.path.dirname(__file__), '..', '..', 'klipper', 'printer.cfg')


class FakeConfig:
    '''The [limn] section, with the values SAVE_CONFIG wrote into printer.cfg.'''

    def __init__(self, printer):
        self.printer = printer
        text = open(PRINTER_CFG).read()
        section = text[text.index('#*# [limn]'):]
        self.values = dict(re.findall(r'#\*# (\w+) = (.*)', section))
        self.values['serial'] = '/dev/null'

    def get_name(self):
        return 'limn'

    def get_printer(self):
        return self.printer

    def get(self, key, default=None):
        return self.values.get(key, default)

    def getint(self, key, default=None):
        value = self.values.get(key, default)
        return None if value is None else int(value)


class GcodeError(Exception):
    pass


class FakeGcmd:
    def __init__(self, gcode, params):
        self.gcode = gcode
        self.params = {k: str(v) for k, v in params.items()}

    def get(self, key, default=KeyError):
        if key in self.params:
            return self.params[key]
        if default is KeyError:
            raise self.error(f"missing {key}")
        return default

    def get_int(self, key, default=KeyError):
        value = self.get(key, default)
        return None if value is None else int(value)

    def get_float(self, key, default=KeyError):
        value = self.get(key, default)
        return None if value is None else float(value)

    def respond_info(self, msg):
        self.gcode.respond_info(msg)

    def error(self, msg):
        return GcodeError(msg)


class FakeGcode:
    error = GcodeError

    def __init__(self):
        self.commands = {}
        self.said = []
        self.scripts = []
        self.on_script = None

    def register_command(self, name, handler, desc=None):
        self.commands[name] = handler

    def respond_info(self, msg):
        self.said.append(msg)

    def run_script_from_command(self, script):
        self.scripts.append(script)
        if self.on_script:
            self.on_script(script)

    def create_gcode_command(self, command, commandline, params):
        return FakeGcmd(self, params)

    def run(self, name, **params):
        self.commands[name](FakeGcmd(self, params))


class FakeSaveVariables:
    def __init__(self):
        self.allVariables = {}

    def cmd_SAVE_VARIABLE(self, gcmd):
        self.allVariables[gcmd.get('VARIABLE')] = ast.literal_eval(gcmd.get('VALUE'))


class FakeLedEffect:
    '''led_effect: `history` is every STATE it was set to, None for a stop.'''

    def __init__(self):
        self.enabled = False
        self.history = []

    def cmd_SET_LED_EFFECT(self, gcmd):
        if gcmd.get_int('STOP', 0):
            self.enabled = False
            self.history.append(None)
        else:
            self.enabled = True
            self.history.append(gcmd.get('STATE', None))

    @property
    def state(self):
        return self.history[-1] if self.enabled and self.history else None


LED_NAMES = ['ui_traffic_red', 'ui_traffic_yellow', 'ui_traffic_green', 'ui_tag', 'ui_alert'] \
    + [f'{kind}_{t}' for kind in ('holder', 'ui_tool') for t in (41, 42, 43, 44, 45)]


class FakeMacro:
    '''gcode_macro: only the variables it declares can be set.'''

    def __init__(self, **variables):
        self.variables = variables
        self.sets = 0

    def cmd_SET_GCODE_VARIABLE(self, gcmd):
        key = gcmd.get('VARIABLE')
        if key not in self.variables:
            raise gcmd.error(f"Unknown gcode_macro variable '{key}'")
        self.variables = {**self.variables, key: ast.literal_eval(gcmd.get('VALUE'))}
        self.sets += 1


class FakeToolhead:
    def __init__(self):
        self.waits = 0
        self.moves = []

    def wait_moves(self):
        self.waits += 1

    def manual_move(self, coord, speed):
        self.moves.append((coord, speed))


class FakeConfigfile:
    def __init__(self):
        self.saved = {}

    def set(self, section, key, value):
        self.saved[(section, key)] = value


class FakePrinter:
    def __init__(self):
        self.reactor = FakeReactor()
        self.objects = {'gcode': FakeGcode(), 'configfile': FakeConfigfile(),
                        'save_variables': FakeSaveVariables(), 'toolhead': FakeToolhead()}
        self.events = {}
        self.sent = []

    def get_reactor(self):
        return self.reactor

    def lookup_object(self, name, default=KeyError):
        if name not in self.objects and default is not KeyError:
            return default
        return self.objects[name]

    def register_event_handler(self, event, handler):
        self.events[event] = handler

    def send_event(self, event, *args):
        self.sent.append((event,) + args)


def make():
    printer = FakePrinter()
    return limn.load_config(FakeConfig(printer)), printer


def test_commands_registered():
    ext, printer = make()
    names = set(printer.objects['gcode'].commands)
    for name in ('LRT_CONNECT', 'LRT_DISCONNECT', 'LRT_READ_BED_ID', 'LRT_MESH_CALIBRATE',
                 'LRT_CALIBRATE', 'LRT_PROBE_TOOL', 'LRT_CHAIN', 'LRT_DEBUG', 'LRT_FSR_Z', 'LRT_FSR_EDGE'):
        assert name in names, name

def test_saved_profile_loads():
    ext, _ = make()
    assert ext.calibrated('rtp') and not ext.calibrated('fsr')
    assert len(ext.profile['ref_samples']) == 12
    assert ext.profile['ref_samples'][0].mx == 30.0
    assert len(ext.profile['touch_params']) == 6

def test_save_profile():
    ext, printer = make()
    ext._save_profile({'fsr_ref': {'x': 70.0, 'y': 46.0, 'z': 3.1, 'gaps': [], 'bed_z': []}})
    saved = printer.objects['configfile'].saved
    assert saved[('limn', 'version')] == limn.LRT_CONF_VERSION
    assert '"x": 70.0' in saved[('limn', 'fsr_ref')]
    assert ext.calibrated('fsr')

def test_dock_lines_reach_the_samples():
    ext, printer = make()
    ext.dock.handle_line('!LRT>>data>>{"hop": 2, "kind": 4, "state": 43, "values": [[0, 0, 12]]}>>')
    ext.dock.handle_line('!LRT>>read_bed_id>>["BED_5", ["BED_5", 22000, 43000, 47500]]>>')
    assert ext.samples.latest(2, FSR).state == S_MATRIX
    assert ext.bed == 'BED_5'
    assert ext.get_status(0)['bed'] == 'BED_5'


def test_moves_reach_klipper_as_plain_floats():
    # A numpy float in the toolhead's position breaks Klipper's status JSON (webhooks).
    import numpy as np
    from limn.machine import Machine
    _, printer = make()
    printer.objects['probe'] = object()
    toolhead = printer.objects['toolhead']
    machine = Machine(printer, None)
    machine.move(*(np.array([111.75, 44.75]) - np.array([-34.34, 25.0])))
    machine.move(z=np.float64(4.2), speed=np.float64(2))
    for coord, speed in toolhead.moves:
        assert all(v is None or type(v) is float for v in coord) and type(speed) is float, (coord, speed)
    assert toolhead.moves[0][0][2] is None and toolhead.moves[1][0][:2] == [None, None]


def make_with_holder(low=(15, 14, 13, 12, 11), pages=None, carried=0):
    ext, printer = make()
    mcp, nfc = FakeMCP23017(low), FakePN532(pages)
    ext._attach_holder(ToolHolder(printer.reactor, FakeBus(mcp, nfc), parse_pins('15:41, 14:42, 13:45, 12:43, 11:44'),
                                  say=printer.objects['gcode'].respond_info))
    ext.tool_macros = limn.parse_macros(limn.HOLDER_MACROS)
    svv = printer.objects['save_variables'].allVariables
    svv['currently_docked_tool'] = carried
    return ext, printer, mcp, nfc, printer.objects['gcode'], svv

def make_with_leds(**kwargs):
    ext, printer, mcp, nfc, gcode, svv = make_with_holder(**kwargs)
    leds = {name: FakeLedEffect() for name in LED_NAMES}
    printer.objects.update({'led_effect ' + name: effect for name, effect in leds.items()})
    printer.objects.update({f'gcode_macro T{i}': FakeMacro(color='', active=False) for i in range(4)})
    printer.objects['gcode_macro T4'] = FakeMacro()     # without the variables
    printer.events['klippy:connect']()
    wait(printer, 1)                                    # the holders settle while Klipper starts
    printer.events['klippy:ready']()
    wait(printer, 0.5)
    return ext, printer, mcp, gcode, svv, leds

def lit(leds):
    return {name: e.state for name, e in leds.items() if e.state}

def wait(printer, seconds):
    printer.reactor.pause(printer.reactor.t + seconds)

def raises(fn):
    try:
        fn()
    except GcodeError as e:
        return str(e)
    assert False, 'should raise'

def test_tool_holder_commands_registered():
    ext, printer = make()
    assert ext.holder is None
    for name in ('TOOL_HOLDERS', 'TOOL_HOLDER_CHECK', 'TOOL_TAG_READ', 'TOOL_TAG_WRITE'):
        assert name in printer.objects['gcode'].commands, name
    assert ext.get_status(0)['tool_holder']['enabled'] is False

def test_holder_check_without_holder_passes():
    ext, printer = make()
    printer.objects['gcode'].run('TOOL_HOLDER_CHECK', T=41, EXPECT='empty')
    assert 'not checking' in printer.objects['gcode'].said[-1]

def test_holder_check():
    ext, printer, mcp, _, gcode, _ = make_with_holder(low=(15,))
    gcode.run('TOOL_HOLDER_CHECK', T=41, EXPECT='occupied')
    assert 'occupied' in raises(lambda: gcode.run('TOOL_HOLDER_CHECK', T=41, EXPECT='empty'))
    assert 'no holder' in raises(lambda: gcode.run('TOOL_HOLDER_CHECK', T=40, EXPECT='empty'))
    assert printer.objects['toolhead'].waits >= 1
    mcp.fail = True
    assert "can't read" in raises(lambda: gcode.run('TOOL_HOLDER_CHECK', T=41, EXPECT='occupied'))

def test_dock_cycle_is_expected():
    ext, printer, mcp, _, gcode, svv = make_with_holder()
    printer.events['klippy:connect']()
    wait(printer, 1)
    gcode.run('TOOL_HOLDER_CHECK', T=42, EXPECT='occupied', ARM=1)
    mcp.low.discard(14)                                 # the carriage takes 42
    gcode.run('TOOL_HOLDER_CHECK', T=42, EXPECT='empty')
    wait(printer, 1)
    assert gcode.said[-1] == "[Tool holder] 42: tool removed (expected)"
    assert printer.sent[-1][-1] == set()
    assert ext.get_status(0)['tool_holder']['occupied'] == [41, 43, 44, 45]

def test_manual_return_clears_carried_tool():
    ext, printer, mcp, _, gcode, svv = make_with_holder(low=(15, 13, 12, 11), carried=42)
    svv['tool_offset_x'] = 0.3
    printer.events['klippy:connect']()
    wait(printer, 1)
    assert svv['currently_docked_tool'] == 42
    mcp.low.add(14)                                     # 42 put back by hand
    wait(printer, 1)
    assert "42: tool returned (manual)" in gcode.said[-2]
    assert svv['currently_docked_tool'] == 0 and svv['tool_offset_x'] == 0 and svv['tool_name'] == ''
    assert ext.get_status(0)['tool_holder']['last_manual']['added'] == [42]

def test_startup_finds_carried_tool_in_its_holder():
    ext, printer, mcp, _, gcode, svv = make_with_holder(carried=45)
    printer.events['klippy:connect']()
    wait(printer, 1)
    assert svv['currently_docked_tool'] == 0

def test_tag_read_saves_offsets():
    ext, printer, _, _, gcode, svv = make_with_holder(pages=tag_pages())
    gcode.run('TOOL_TAG_READ')
    assert gcode.scripts == ['_RFID_HOME']
    assert (svv['tool_offset_x'], svv['tool_offset_y'], svv['tool_offset_z']) == (1.25, -0.5, 0.05)
    assert svv['tool_name'] == 'Fineliner' and ext.get_status(0)['tag']['ok']

def test_tag_read_without_tag():
    ext, printer, _, _, gcode, svv = make_with_holder(pages=None)
    gcode.run('TOOL_TAG_READ', MOVE=0)
    assert gcode.scripts == [] and 'tool_offset_x' not in svv
    assert ext.get_status(0)['tag'] == {'ok': False, 'error': 'no tag', 'tries': 1}

def test_tag_write():
    ext, printer, _, nfc, gcode, svv = make_with_holder(pages=tag_pages())
    raises(lambda: gcode.run('TOOL_TAG_WRITE'))
    gcode.run('TOOL_TAG_WRITE', DX=2.5, NAME='Brush pen')
    assert svv['tool_offset_x'] == 2.5 and svv['tool_offset_z'] == 0.05 and svv['tool_name'] == 'Brush pen'
    nfc.pages = None
    assert 'write failed' in raises(lambda: gcode.run('TOOL_TAG_WRITE', DZ=1))


def test_leds_at_startup():
    ext, printer, mcp, gcode, svv, leds = make_with_leds(low=(15, 14, 13, 12), carried=44)
    assert lit(leds) == {'holder_41': 'occupied', 'holder_42': 'occupied', 'holder_43': 'occupied',
                         'holder_45': 'occupied', 'holder_44': 'carried', 'ui_tool_44': 'untagged',
                         'ui_alert': 'ok'}

def test_leds_drawn_when_holders_settled_during_startup():
    ext, printer, mcp, nfc, gcode, svv = make_with_holder()
    holder_41 = FakeLedEffect()
    printer.objects['led_effect holder_41'] = holder_41
    printer.events['klippy:connect']()
    wait(printer, 1)                                    # settled before klippy:ready: not drawn yet
    assert holder_41.state is None
    printer.events['klippy:ready']()
    wait(printer, 0.1)
    assert holder_41.state == 'occupied'

def test_leds_follow_a_dock():
    ext, printer, mcp, gcode, svv, leds = make_with_leds()
    gcode.run('TOOL_HOLDER_CHECK', T=42, EXPECT='occupied', ARM=1)
    wait(printer, 0.1)
    assert leds['holder_42'].state == 'occupied' and leds['ui_traffic_red'].state == 'on'
    gcode.run('TOOL_CHANGE_PHASE', PHASE='engage')
    wait(printer, 0.1)
    assert leds['ui_traffic_yellow'].state == 'on'
    assert leds['ui_traffic_red'].state is None
    mcp.low.discard(14)
    gcode.run('TOOL_CHANGE_PHASE', PHASE='leave')
    gcode.run('TOOL_HOLDER_CHECK', T=42, EXPECT='empty')
    svv['currently_docked_tool'] = 42                   # the macro's SAVE_VARIABLE, before the redraw
    wait(printer, 0.5)
    assert leds['holder_42'].state == 'carried' and leds['ui_traffic_green'].state == 'on'
    assert leds['ui_tool_42'].state == 'untagged'
    assert leds['holder_42'].history.count('carried') == 1          # no redraw without a change
    wait(printer, 4)
    assert leds['ui_traffic_green'].state is None

def test_leds_on_failed_check_and_manual_change():
    ext, printer, mcp, gcode, svv, leds = make_with_leds()
    raises(lambda: gcode.run('TOOL_HOLDER_CHECK', T=43, EXPECT='empty', ARM=1))
    wait(printer, 0.1)
    assert leds['holder_43'].state == 'error' and leds['ui_alert'].state == 'error_new'
    wait(printer, 3)
    assert leds['ui_alert'].state == 'error'
    gcode.run('TOOL_CHANGE_PHASE', PHASE='idle')
    mcp.low.discard(11)                                 # 44 lifted by hand
    wait(printer, 1)
    assert leds['holder_43'].state == 'occupied'
    assert leds['holder_44'].state == 'missing' and leds['ui_alert'].state == 'attention_fast'
    wait(printer, 5)
    assert leds['ui_alert'].state == 'warn'

def test_leds_heal_and_missing_effects():
    ext, printer, mcp, gcode, svv, leds = make_with_leds()
    leds['holder_41'].enabled = False                   # STOP_LED_EFFECTS from elsewhere
    del printer.objects['led_effect ui_alert']
    gcode.run('TOOL_LEDS')
    assert leds['holder_41'].state == 'occupied'
    assert 'holder_41=occupied' in gcode.said[-1]


def test_fluidd_tool_buttons():
    ext, printer, mcp, gcode, svv, leds = make_with_leds(low=(15, 13, 12, 11), carried=42)
    buttons = {i: printer.objects[f'gcode_macro T{i}'].variables for i in range(4)}
    assert buttons[0] == {'color': '4CAF50', 'active': False}
    assert buttons[1] == {'color': '', 'active': True}             # carried: no dot, highlighted
    assert printer.objects['gcode_macro T4'].variables == {}
    mcp.low.discard(12)                                 # 43 lifted by hand
    wait(printer, 5)
    assert printer.objects['gcode_macro T2'].variables['color'] == ''
    sets = printer.objects['gcode_macro T0'].sets
    gcode.run('TOOL_LEDS')
    assert printer.objects['gcode_macro T0'].sets == sets                   # only changes are set


def flaky_reader(nfc, gcode, nudges):
    '''The reader only reaches the tag after `nudges` nudges.'''
    pages, nfc.pages = nfc.pages, None
    def on_script(script):
        if script.startswith('_RFID_NUDGE') and sum(s.startswith('_RFID_NUDGE') for s in gcode.scripts) >= nudges:
            nfc.pages = pages
    gcode.on_script = on_script

def test_tag_read_nudges_the_reader():
    ext, printer, _, nfc, gcode, svv = make_with_holder(pages=tag_pages())
    flaky_reader(nfc, gcode, 1)
    gcode.run('TOOL_TAG_READ')
    assert gcode.scripts == ['_RFID_HOME', '_RFID_NUDGE ATTEMPT=1 T=0']
    assert svv['tool_name'] == 'Fineliner' and ext.tag['tries'] == 2
    assert "[Tag] no tag, nudging the reader (2/3)" in gcode.said

def test_tag_read_gives_up():
    ext, printer, _, nfc, gcode, svv = make_with_holder(pages=tag_pages())
    flaky_reader(nfc, gcode, 5)
    gcode.run('TOOL_TAG_READ')
    assert gcode.scripts == ['_RFID_HOME', '_RFID_NUDGE ATTEMPT=1 T=0', '_RFID_NUDGE ATTEMPT=2 T=0']
    assert ext.tag == {'ok': False, 'error': 'no tag', 'tries': 3} and 'tool_name' not in svv
    assert gcode.said[-1] == "[Tag] read failed after 3 tries: no tag"

def test_tag_without_moving_does_not_retry():
    ext, printer, _, nfc, gcode, svv = make_with_holder(pages=tag_pages())
    flaky_reader(nfc, gcode, 1)
    gcode.run('TOOL_TAG_READ', MOVE=0)
    assert gcode.scripts == [] and ext.tag['tries'] == 1

def test_tag_write_nudges_the_reader():
    ext, printer, _, nfc, gcode, svv = make_with_holder(pages=tag_pages())
    flaky_reader(nfc, gcode, 2)
    gcode.run('TOOL_TAG_WRITE', DZ=0.4)
    assert gcode.scripts[-1] == '_RFID_NUDGE ATTEMPT=2 T=0' and svv['tool_offset_z'] == 0.4
    ext.tag_retries = 0
    flaky_reader(nfc, gcode, 9)
    assert 'after 1 tries' in raises(lambda: gcode.run('TOOL_TAG_WRITE', DZ=0.5))


def test_nudge_reenters_the_carried_tools_holder():
    ext, printer, mcp, nfc, gcode, svv = make_with_holder(low=(15, 13, 12, 11), pages=tag_pages(), carried=42)
    printer.events['klippy:connect']()
    wait(printer, 1)
    flaky_reader(nfc, gcode, 1)
    inner = gcode.on_script
    def on_script(script):
        if script.startswith('_RFID_NUDGE'):
            mcp.low.add(14)                             # the carried 42 in its holder for a moment
            wait(printer, 0.6)
            mcp.low.discard(14)
            wait(printer, 0.2)                          # out again, the switch not settled yet
        inner(script)
    gcode.on_script = on_script
    gcode.run('TOOL_TAG_READ')
    assert gcode.scripts[-1] == '_RFID_NUDGE ATTEMPT=1 T=42'
    wait(printer, 1)
    assert svv['currently_docked_tool'] == 42 and ext.tag['ok']
    assert not any('manual' in line for line in gcode.said)
    assert ext.holder.expected == {} and ext.holder.occupied == {41, 43, 44, 45}

def test_nudge_without_reentering():
    ext, printer, mcp, nfc, gcode, svv = make_with_holder(pages=tag_pages(), carried=42)   # 42 reads as home
    flaky_reader(nfc, gcode, 1)
    gcode.run('TOOL_TAG_READ')
    assert gcode.scripts[-1] == '_RFID_NUDGE ATTEMPT=1 T=0'


if __name__ == '__main__':
    run_tests(globals())
