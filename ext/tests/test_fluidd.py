# klipper/limn_macros.cfg: the extension's commands as macros, for Fluidd (ext/limn/fluidd.py)
import configparser
import os

import fakes  # noqa: F401  (puts ext/ on the path)
from limn import fluidd

CFG = os.path.join(os.path.dirname(__file__), '..', '..', 'klipper', 'limn_macros.cfg')


def test_the_macros_file_is_up_to_date():
    assert open(CFG).read() == fluidd.render(), 'python ext/limn/fluidd.py > klipper/limn_macros.cfg'


def test_every_command_is_a_macro_that_runs_it():
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(CFG)
    names = [n for n, _, _ in fluidd.commands()]
    assert 'DOCK_MANUAL' in names and 'TOOL_SWAP' in names and len(names) == len(set(names))
    for n in names:
        sec = cfg[f'gcode_macro {n}']
        assert sec['rename_existing'] == '_LIMN_' + n
        assert sec['gcode'].strip().endswith(f'_LIMN_{n} {{rawparams}}')


def test_the_parameters_are_the_ones_the_command_reads():
    params = {n: dict(p) for n, _, p in fluidd.commands()}
    assert params['TOOL_SWAP'] == {'T': None, 'PEN': '', 'COLOR': '', 'NAME': '', 'CALIBRATE': 0}
    assert params['TOOL_HOLDER_CHECK'] == {'T': None, 'EXPECT': None, 'ARM': 0}
    assert params['LRT_FSR_MAP']['STEP'] == 1.25 and params['LRT_FSR_MAP']['REFINE'] == 1
    assert 'MOVE' in params['TOOL_TAG_READ']                      # read by a helper it hands gcmd to
    assert params['DOCK_CLEAR'] == {}
