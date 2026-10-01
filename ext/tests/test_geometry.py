# uv run python ext/tests/test_geometry.py
import re
import os
import json
import random

import numpy as np

from fakes import run_tests
from limn import geometry
from limn.geometry import ProbeValue, FsrArray, mesh_z

PRINTER_CFG = os.path.join(os.path.dirname(__file__), '..', '..', 'klipper', 'printer.cfg')


def saved_profile():
    '''ref_samples and ref_z_panel as saved by the old extension.'''
    text = open(PRINTER_CFG).read()
    get = lambda key: json.loads(re.search(r'#\*# ' + key + r' = (.*)', text).group(1))
    return [ProbeValue(*p) for p in get('ref_samples')], [ProbeValue(*p) for p in get('ref_z_panel')]


def old_gen_bb_grid(*, nx=5, ny=5, xrange=(45, 106), yrange=(40, 70), deviation=0, z_park=9):
    # As it was in ext/limn.py
    xmin, xmax = xrange
    ymin, ymax = yrange
    coords = []
    stepx = (xmax - xmin) / (nx - 1)
    stepy = (ymax - ymin) / (ny - 1)
    for x in np.arange(xmin, xmax + 1, stepx):
        for y in np.arange(ymin, ymax + 1, stepy):
            x += random.uniform(-deviation, deviation)
            y += random.uniform(-deviation, deviation)
            x = np.round(x, 2).tolist()
            y = np.round(y, 2).tolist()
            coords.append((x, y, z_park))
    return coords


def test_grids_unchanged():
    for kw in ({'nx': 4, 'ny': 3, 'xrange': (30, 90), 'yrange': (42, 65)},
               {'nx': 4, 'ny': 4, 'xrange': (30, 90), 'yrange': (110, 160), 'z_park': 6}):
        assert geometry.gen_bb_grid(**kw) == old_gen_bb_grid(**kw)

def test_touch_transform_recovers_an_affine():
    params = (0.002, 0.00001, -3.2, -0.00002, 0.0014, 3.5)
    A, B, C, D, E, F = params
    raw = [(1722.0, 3160.0), (1184.0, 2211.0), (620.0, 3700.0)]
    data = [((A * x + B * y + C, D * x + E * y + F, 9), (x, y)) for x, y in raw]
    assert np.allclose(geometry.touch_transform(data), params)
    xy = geometry.apply_transform(params, raw)
    assert np.allclose(xy, [p[0][:2] for p in data])

def test_rtp_raw_axes():
    assert geometry.rtp_raw_xy([100, 200, 5]) == (200, 100)

def test_rtp_offsets_match_the_old_formula():
    ref_samples, ref_z_panel = saved_profile()
    rng = np.random.default_rng(1)
    tool = [ProbeValue(r.mx, r.my, r.mz, r.tx + 0.3 + rng.normal(0, 0.02), r.ty - 0.2, r.tz + 0.5)
            for r in ref_samples]
    # As it was in ext/limn.py cmd_PROBE_TOOL
    xydiff = np.round(np.median(np.array(tool) - np.array(ref_samples), axis=0), 3) * -1
    zdiff = np.round(np.median(np.array(tool) - np.array(ref_z_panel), axis=0), 3)
    dx, dy, dz = geometry.rtp_tool_offsets(tool, ref_samples, ref_z_panel)
    assert (dx, dy, dz) == (xydiff[3], xydiff[4], zdiff[5])
    assert abs(dx + 0.3) < 0.02 and abs(dy - 0.2) < 1e-9

def test_rtp_reference_z():
    ref_samples, ref_z_panel = saved_profile()
    old = np.round(np.median(np.array(ref_samples) - np.array(ref_z_panel), axis=0), 3)[5]
    assert geometry.rtp_reference_z(ref_samples, ref_z_panel) == old

def test_spread():
    assert geometry.spread([]) == float('inf')
    assert geometry.spread([(1, 1), (1, 1)]) == 0

def test_fsr_array_along_x():
    a = FsrArray(1, origin=(100, 50), col_dir=(1, 0), row_dir=(0, 1))
    assert np.allclose(a.center(0, 0), (101.25, 51.25))
    assert np.allclose(a.center(1, 3), (108.75, 53.75))
    assert a.cell_at((108.9, 53.1)) == (1, 3)
    assert a.cell_at((99, 50)) is None

def test_fsr_array_along_y():
    a = FsrArray(2, origin=(108, 36), col_dir=(0, 1), row_dir=(1, 0))
    assert np.allclose(a.center(1, 3), (111.75, 44.75))
    assert a.cell_at((111.75, 44.75)) == (1, 3)
    assert a.cell_at((111.75, 57)) is None      # 8 cells of 2.5 along y end at 56


def test_mesh_z():
    # bed_mesh keeps its probed points row by row along y
    profile = {'mesh_params': {'min_x': 0, 'max_x': 10, 'min_y': 0, 'max_y': 20, 'x_count': 3, 'y_count': 2},
               'points': [[0.0, 1.0, 2.0], [2.0, 3.0, 4.0]]}      # z = 0.2x + 0.1y
    for x, y in ((0, 0), (10, 20), (2.5, 5), (7.5, 15), (5, 10)):
        assert abs(mesh_z(profile, x, y) - (0.2 * x + 0.1 * y)) < 1e-9, (x, y)
    assert mesh_z(profile, -5, 30) == mesh_z(profile, 0, 20)        # clamped to the mesh


if __name__ == '__main__':
    run_tests(globals())
