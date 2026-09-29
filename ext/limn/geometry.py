# Limn - calibration math. Pure functions, no Klipper.
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
from collections import namedtuple

import numpy as np

# A probed point: m = where the machine was sent, t = what was measured there
# (RTP reading or probe position), tz = the z of the trigger.
ProbeValue = namedtuple('PV', ['mx', 'my', 'mz', 'tx', 'ty', 'tz'])
TX, TY, TZ = (ProbeValue._fields.index(f) for f in ('tx', 'ty', 'tz'))


def gen_bb_grid(*, nx=5, ny=5, xrange=(45, 106), yrange=(40, 70), z_park=9):
    '''nx * ny points covering the ranges, column by column.'''
    xmin, xmax = xrange
    ymin, ymax = yrange
    stepx = (xmax - xmin) / (nx - 1)
    stepy = (ymax - ymin) / (ny - 1)
    return [(np.round(x, 2).tolist(), np.round(y, 2).tolist(), z_park)
            for x in np.arange(xmin, xmax + 1, stepx)
            for y in np.arange(ymin, ymax + 1, stepy)]

def gen_mark_grid(*, nx, ny, xrange, yrange, **_):
    '''Centres of the test marks' + on the paper, row by row.'''
    return [(round(float(x), 2), round(float(y), 2))
            for y in np.linspace(*yrange, ny) for x in np.linspace(*xrange, nx)]

def mark_strokes(at, to, arm):
    '''One test mark, two strokes through their corner: └ at `at`, which with the
    previous tool's ┐ there makes a +, and ┐ at `to`, for the next tool.'''
    (x0, y0), (x1, y1) = at, to
    return [[(x0 + arm, y0), (x0, y0), (x0, y0 + arm)],
            [(x1 - arm, y1), (x1, y1), (x1, y1 - arm)]]


# RTP
def rtp_raw_xy(values):
    '''The panel's raw [x, y, z] in the plotter's axis order: the panel is
    mounted turned, its y runs along the plotter's x.'''
    return values[1], values[0]

def touch_transform(data):
    '''Raw panel -> plotter coordinates from three points (Atmel AVR341).
    data: [((plotter x, y, ..), (raw x, raw y)), ...] -> (A, B, C, D, E, F)'''
    (Xd1, Yd1), (Xd2, Yd2), (Xd3, Yd3) = [(p[0][0], p[0][1]) for p in data[:3]]
    (Xt1, Yt1), (Xt2, Yt2), (Xt3, Yt3) = [(p[1][0], p[1][1]) for p in data[:3]]

    div = (Xt1 * (Yt2 - Yt3)) + (Xt2 * (Yt3 - Yt1)) + (Xt3 * (Yt1 - Yt2))
    A = ((Xd1 * (Yt2 - Yt3)) + (Xd2 * (Yt3 - Yt1)) + (Xd3 * (Yt1 - Yt2))) / div
    B = ((A * (Xt3 - Xt2)) + Xd2 - Xd3) / (Yt2 - Yt3)
    C = Xd3 - (A * Xt3) - (B * Yt3)

    D = ((Yd1 * (Yt2 - Yt3)) + (Yd2 * (Yt3 - Yt1)) + (Yd3 * (Yt1 - Yt2))) / div
    E = ((D * (Xt3 - Xt2)) + Yd2 - Yd3) / (Yt2 - Yt3)
    F = Yd3 - (D * Xt3) - (E * Yt3)
    return (A, B, C, D, E, F)

def apply_transform(params, raw):
    '''raw: N x 2 panel readings -> N x 2 plotter coordinates.'''
    A, B, C, D, E, F = params
    raw = np.asarray(raw, dtype=float).reshape(-1, 2)
    x, y = raw[:, 0], raw[:, 1]
    return np.stack((A * x + B * y + C, D * x + E * y + F), axis=1)

def spread(xy):
    '''Mean of the x and y standard deviation of some readings.'''
    xy = np.asarray(xy, dtype=float).reshape(-1, 2)
    if len(xy) == 0:
        return float('inf')
    return float(np.mean(np.std(xy, axis=0)))

def rtp_reference_z(ref_samples, ref_z_panel):
    '''Reference tool z: its touch z over the BLTouch z, median of the grid.'''
    diff = np.array(ref_samples, dtype=float) - np.array(ref_z_panel, dtype=float)
    return float(np.round(np.median(diff, axis=0), 3)[TZ])

def rtp_tool_offsets(samples, ref_samples, ref_z_panel):
    '''A tool against the reference grid -> (dx, dy, dz).
    XY: where the panel saw this tool vs the reference tool at the same
    commanded points, negated so the offset moves the tool onto the reference.
    Z: the tool's touch z over the BLTouch z.'''
    samples = np.array(samples, dtype=float)
    xy = np.round(np.median(samples - np.array(ref_samples, dtype=float), axis=0), 3) * -1
    z = np.round(np.median(samples - np.array(ref_z_panel, dtype=float), axis=0), 3)
    return float(xy[TX]), float(xy[TY]), float(z[TZ])


def mesh_z(profile, x, y):
    '''z of a Klipper bed mesh profile (its `points` and `mesh_params`, as in
    bed_mesh's status) at (x, y): bilinear between the probed points, clamped
    to the mesh.'''
    p = profile['mesh_params']
    z = np.asarray(profile['points'], dtype=float)         # rows along y
    fx = np.clip((x - p['min_x']) / (p['max_x'] - p['min_x']), 0, 1) * (p['x_count'] - 1)
    fy = np.clip((y - p['min_y']) / (p['max_y'] - p['min_y']), 0, 1) * (p['y_count'] - 1)
    i, j = min(int(fx), p['x_count'] - 2), min(int(fy), p['y_count'] - 2)
    u, v = fx - i, fy - j
    return float((1 - v) * ((1 - u) * z[j, i] + u * z[j, i + 1]) + v * ((1 - u) * z[j + 1, i] + u * z[j + 1, i + 1]))


# FSR
class FsrArray:
    '''One 4 x 8 FSR array on the bed. `origin` is the outer corner of cell
    (row 0, col 0) in plotter coordinates; `col_dir` / `row_dir` are the
    plotter directions of increasing col / row, eg. (1, 0) and (0, 1).'''

    def __init__(self, hop, origin, col_dir, row_dir, pitch=2.5, rows=4, cols=8):
        self.hop = hop
        self.origin = np.array(origin, dtype=float)
        self.col_dir = np.array(col_dir, dtype=float)
        self.row_dir = np.array(row_dir, dtype=float)
        self.pitch = pitch
        self.rows = rows
        self.cols = cols

    def point(self, row, col):
        '''Plotter point at fractional (row, col) from the origin, in cells.'''
        return self.origin + self.pitch * (col * self.col_dir + row * self.row_dir)

    def center(self, row, col):
        return self.point(row + 0.5, col + 0.5)

    def cell_at(self, xy):
        '''(row, col) under a plotter point, or None outside the array.'''
        local = np.array(xy, dtype=float) - self.origin
        col = int(np.floor(np.dot(local, self.col_dir) / self.pitch))
        row = int(np.floor(np.dot(local, self.row_dir) / self.pitch))
        if 0 <= row < self.rows and 0 <= col < self.cols:
            return row, col
        return None
