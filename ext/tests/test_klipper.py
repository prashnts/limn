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
    def __init__(self):
        self.commands = {}
        self.said = []
        self.scripts = []

    def register_command(self, name, handler, desc=None):
        self.commands[name] = handler

    def respond_info(self, msg):
        self.said.append(msg)

    def run_script_from_command(self, script):
        self.scripts.append(script)

    def create_gcode_command(self, command, commandline, params):
        return FakeGcmd(self, params)

    def run(self, name, **params):
        self.commands[name](FakeGcmd(self, params))


class FakeSaveVariables:
    def __init__(self):
        self.allVariables = {}

    def cmd_SAVE_VARIABLE(self, gcmd):
        self.allVariables[gcmd.get('VARIABLE')] = ast.literal_eval(gcmd.get('VALUE'))


class FakeToolhead:
    def __init__(self):
        self.waits = 0

    def wait_moves(self):
        self.waits += 1


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

    def lookup_object(self, name):
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


def make_with_holder(low=(15, 14, 13, 12, 11), pages=None, carried=0):
    ext, printer = make()
    mcp, nfc = FakeMCP23017(low), FakePN532(pages)
    ext._attach_holder(ToolHolder(printer.reactor, FakeBus(mcp, nfc), parse_pins('15:41, 14:42, 13:45, 12:43, 11:44'),
                                  say=printer.objects['gcode'].respond_info))
    svv = printer.objects['save_variables'].allVariables
    svv['currently_docked_tool'] = carried
    return ext, printer, mcp, nfc, printer.objects['gcode'], svv

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
    assert ext.get_status(0)['tag'] == {'ok': False, 'error': 'no tag'}

def test_tag_write():
    ext, printer, _, nfc, gcode, svv = make_with_holder(pages=tag_pages())
    raises(lambda: gcode.run('TOOL_TAG_WRITE'))
    gcode.run('TOOL_TAG_WRITE', DX=2.5, NAME='Brush pen')
    assert svv['tool_offset_x'] == 2.5 and svv['tool_offset_z'] == 0.05 and svv['tool_name'] == 'Brush pen'
    nfc.pages = None
    assert 'write failed' in raises(lambda: gcode.run('TOOL_TAG_WRITE', DZ=1))


if __name__ == '__main__':
    run_tests(globals())
