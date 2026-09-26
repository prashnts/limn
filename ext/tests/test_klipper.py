# uv run python ext/tests/test_klipper.py
# The Klipper side, with stand-ins for Klipper's objects.
import os
import re

from fakes import FakeReactor, run_tests
import limn
from limn.samples import FSR, S_MATRIX

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
        return int(self.values.get(key, default))


class FakeGcode:
    def __init__(self):
        self.commands = {}
        self.said = []

    def register_command(self, name, handler, desc=None):
        self.commands[name] = handler

    def respond_info(self, msg):
        self.said.append(msg)


class FakeConfigfile:
    def __init__(self):
        self.saved = {}

    def set(self, section, key, value):
        self.saved[(section, key)] = value


class FakePrinter:
    def __init__(self):
        self.reactor = FakeReactor()
        self.objects = {'gcode': FakeGcode(), 'configfile': FakeConfigfile()}
        self.events = {}

    def get_reactor(self):
        return self.reactor

    def lookup_object(self, name):
        return self.objects[name]

    def register_event_handler(self, event, handler):
        self.events[event] = handler


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


if __name__ == '__main__':
    run_tests(globals())
