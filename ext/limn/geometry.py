# Limn - calibration math. Pure functions, no Klipper.
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
import math
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

def mark_points(marks):
    '''The corners of a bed's test marks, in the order they are used (mark i: point i to
    point i + 1). A grid row by row (`nx`, `ny`, `xrange`, `yrange`), or the sheet's
    (sheet_layout) marks.'''
    if 'xrange' in marks:
        return gen_mark_grid(**marks)
    return sheet_layout(marks)['points']

TICK_GAP = 0.8          # mm between the holder ticks: the last of five stays 0.8 clear of the next mark

def holder_ticks(at, n, arm, gap=TICK_GAP):
    '''n short ticks along X beside the └ at `at`, in the quarter no corner uses there (+X,
    -Y): the holder the pen came from (41: one ... 45: five).'''
    x, y = at
    return [[(round(x + arm / 2, 2), round(y - 1 - gap * k, 2)), (round(x + arm, 2), round(y - 1 - gap * k, 2))]
            for k in range(n)]


# The sheet (beds.py `marks` with `area`): every pen leaves its purge and its test mark on it.
#
#   y1 +---+---------------------------+      The purge: an L along the low X and low Y edges,
#      | | |  ┐   ┐   ┐   ┐   ┐   ┐     |      `purge` of the area. Each pen draws one line down
#      | | |  ┼ ┼ ┼ ┼ ┼ ┼ ┼ ┼ ┼ ┼ ┼     |      the Y band and one along the X band, the full
#      | | |  ┼   ┼   ┼   ┼   ┼   ┼     |      length and side by side with the other pens', and
#      |Y| |        the marks           |      a circle round the corner's centre: its ink
#      | | |                            |      flows before the mark, a long line shows the mesh
#      +---+----------------------------+      (thin or skipping where the paper is high or low),
#      | o |  ===== X lines =====       |      parallel lines and concentric circles show two
#   y0 +---+----------------------------+      pens' offsets apart.
#      x0                               x1
#
# Slots are used coarse first, then in between (fill_order): lines `pitch` apart, then halfway;
# marks on a `step` grid, then on the grid shifted by half a step both ways.

def fill_order(lo, hi, pitch):
    '''Positions from lo to hi, `pitch` apart first, then the ones halfway between them.'''
    n = int((hi - lo) / pitch + 1e-9)
    coarse = [lo + k * pitch for k in range(n + 1)]
    return [round(v, 3) for v in coarse + [a + pitch / 2 for a in coarse[:-1]]]

def purge_band(w, h, share):
    '''The width t of an L along two edges of a w x h area that takes `share` of it:
    t (w + h) - t^2 = share w h.'''
    s = w + h
    return (s - math.sqrt(s * s - 4 * share * w * h)) / 2

def sheet_layout(marks):
    '''Where everything goes on the sheet: {'points': the marks' corners in the order they are
    used, 'y_lines', 'x_lines': [(start, end)] one per pen, 'circles': [(centre, r)] one per
    pen, 'band': the purge's width}. marks: beds.py's, `area` ((x0, y0), (x1, y1)) the corners
    of the area a pen can draw in, its offsets anywhere up to TOOL_MAX_DXY.'''
    (x0, y0), (x1, y1) = marks['area']
    p = marks['purge']
    arm, step, gap, pitch = marks['arm'], marks['step'], p['gap'], p['pitch']
    t = purge_band(x1 - x0, y1 - y0, p['share'])
    # The purge: lines half a pitch in from the band's sides, circles round the corner's centre
    ys = (round(y0 + t + gap, 2), y1)
    xs = (round(x0 + t + gap, 2), x1)
    y_lines = [((x, ys[1]), (x, ys[0])) for x in fill_order(x0 + pitch / 2, x0 + t - pitch / 2, pitch)]
    x_lines = [((xs[0], y), (xs[1], y)) for y in fill_order(y0 + pitch / 2, y0 + t - pitch / 2, pitch)]
    c = (round(x0 + t / 2, 2), round(y0 + t / 2, 2))
    circles = [(c, r) for r in fill_order(p['r_min'], t / 2 - pitch / 2, p['ring_pitch'])]
    # The marks: down Y from the top-left corner as the IR Top camera sees it (high X, high Y),
    # columns towards -X. A mark's corner holds arms of `arm` all round and the holder ticks
    # (up to 5) under it: keep them on the area, clear of the purge.
    below = 1 + 4 * TICK_GAP
    lo_x, lo_y = xs[0] + arm, ys[0] + max(arm, below)
    hi_x, hi_y = x1 - arm, y1 - arm
    cols = int((hi_x - lo_x) / step + 1e-9) + 1
    rows = int((hi_y - lo_y) / step + 1e-9) + 1

    def grid(dx, dy, cols, rows):
        return [(round(hi_x - dx - c * step, 2), round(hi_y - dy - r * step, 2))
                for c in range(cols) for r in range(rows)]
    points = grid(0, 0, cols, rows) + grid(step / 2, step / 2, cols - 1, rows - 1)
    return {'points': points, 'y_lines': y_lines, 'x_lines': x_lines, 'circles': circles, 'band': round(t, 2)}

def circle_points(centre, r, seg=0.5):
    '''A closed circle as a polyline, from its +X point, anticlockwise, about `seg` mm a side.'''
    n = max(16, int(math.ceil(2 * math.pi * r / seg)))
    cx, cy = centre
    return [(round(cx + r * math.cos(2 * math.pi * k / n), 3), round(cy + r * math.sin(2 * math.pi * k / n), 3))
            for k in range(n + 1)]

def purge_strokes(layout, k):
    '''Pen k's purge on the sheet: its Y line, its circle, its X line (in that order: the
    corner between them). Past purge_slots, over the first pens' again, all three together.'''
    k %= purge_slots(layout)
    (a, b), (c, r), (d, e) = layout['y_lines'][k], layout['circles'][k], layout['x_lines'][k]
    return [[a, b], circle_points(c, r), [d, e]]

def purge_slots(layout):
    '''How many pens the purge has room for: the fewest of its three.'''
    return min(len(layout['y_lines']), len(layout['x_lines']), len(layout['circles']))

def wipe_slots(*, origin, size, nx, ny, **_):
    '''The wipe area's slots, in the order they are used: ((x0, y0), (x1, y1)) each, row by
    row along Y from its origin.'''
    (ox, oy), (w, h) = origin, size
    sw, sh = w / nx, h / ny
    return [((round(ox + i * sw, 2), round(oy + j * sh, 2)), (round(ox + (i + 1) * sw, 2), round(oy + (j + 1) * sh, 2)))
            for j in range(ny) for i in range(nx)]

def prime_strokes(slot, margin=1.0, turns=3):
    '''A pen primed in a slot of the wipe area: one zigzag across it, `turns` times there
    and back, inside `margin`.'''
    (x0, y0), (x1, y1) = slot
    x0, y0, x1, y1 = x0 + margin, y0 + margin, x1 - margin, y1 - margin
    n = 2 * turns
    return [[(round(x0 if k % 2 == 0 else x1, 2), round(y0 + (y1 - y0) * k / n, 2)) for k in range(n + 1)]]

def plus_strokes(slot, margin=1.0):
    '''A test mark in a slot of the wipe area: a + in its middle, as wide as it leaves.'''
    (x0, y0), (x1, y1) = slot
    cx, cy = round((x0 + x1) / 2, 2), round((y0 + y1) / 2, 2)
    arm = round(min(x1 - x0, y1 - y0) / 2 - margin, 2)
    return [[(cx - arm, cy), (cx + arm, cy)], [(cx, cy - arm), (cx, cy + arm)]]

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
