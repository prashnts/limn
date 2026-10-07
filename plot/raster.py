# Limn plot - a drawing's <image>s made into lines a pen can draw
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# An image is first separated into inks (job.RasterSpec.separate):
#
#   one   its darkness, in one colour (`colour`)
#   cmyk  cyan, magenta, yellow and black (black takes what the three share)
#   pens  the colours of the pens there are: each pixel unmixed into how much
#         of each ink, as inks multiply (absorbance: -log of the colour),
#         0..1 each, least squares
#
# Each ink is then sampled on its own grid, turned to its own angle (the
# screen angles of print: its dots and rows don't line up with the others'
# into a moire), the pixels averaged down to the grid. Up to `paper` it is
# the paper (no ink: a light background isn't speckled), the rest stretched
# to 0..1, then ** gamma. Then:
#
#   dither    Floyd-Steinberg on cells `pitch` apart (Pillow's); the inked
#             cells of a row joined into lines. Fine detail, many strokes.
#   lines     rows `pitch` apart, each drawn where the picture is darker than
#             its row's level (4 levels, ordered): long strokes, quick.
#   halftone  dots `cell` apart, every other row offset, each a spiral with its
#             turns `pitch` apart, as wide as the spot is dark.
#
# `pitch` and `cell` are mm as plotted (the drawing's scale is taken out).
# Left empty they follow the pen that draws the ink (its colour's layer):
# pitch its fill spacing, so black is solid; cell 6 of its lines, 0.5 to 3 mm.
# A fine pen (a 0.05 fineliner) would make millions of cells: the grid is
# coarsened to MAX_CELLS (MAX_DOTS for halftone), and the problems say so.
# A halftone's points go as its inked area / (pitch x chord), whatever the dot
# grid: past MAX_POINTS its dots' turns spread (lighter), said so too. With a
# fine pen `lines` is the quick one; dither becomes stippling (a touch a cell).
#
# The lines of each ink come out as one shape (svg.Shape, raster: never too
# small for its tool) stroked in the ink's colour: its layer draws it.
import math

import numpy as np
import shapely
from PIL import Image
from shapely.geometry import LineString, Polygon

from . import svg
from .geometry import lines_of
from .job import RasterSpec

LEVELS = (0, 2, 1, 3)       # the rows' thresholds in `lines`, in order (a 1-D Bayer matrix)
CMYK = (('#00ffff', 15), ('#ff00ff', 75), ('#ffff00', 0), ('#000000', 45))
ANGLES = (45, 15, 75, 0, 30, 60, 90, 105)
MAX_CELLS = 250_000         # dither: about 60 thousand strokes at most
MAX_ROWS_CELLS = 6_000_000  # lines: its strokes are whole runs of a row, few; only memory bounds it
MAX_DOTS = 25_000           # halftone: each dot a spiral of a few turns
MAX_POINTS = 500_000        # halftone: points of all its spirals (G-code lines), an ink; its turns spread past it


def _rgb(hexc):
    return np.array([int(hexc[i:i + 2], 16) for i in (1, 3, 5)], float) / 255


def inks(spec: RasterSpec, tools=None):
    '''[(colour, angle)]: the inks the image is separated into, on their screen angles.'''
    one = 45 if spec.mode == 'halftone' else 0
    if spec.separate == 'one':
        return [(spec.colour.lower(), one)]
    if spec.separate == 'cmyk':
        return list(CMYK)
    colours = []
    for t in (tools or {}).values():
        c = t.color.lower()
        if t.draws and (not spec.pens or t.id in spec.pens) and c not in colours and _rgb(c).min() < 0.95:
            colours.append(c)
    return [(c, ANGLES[i % len(ANGLES)]) for i, c in enumerate(colours)] or [('#000000', one)]


def keys(spec: RasterSpec, tools=None):
    '''The colour keys its lines are painted by: one layer for each ink.'''
    return [f'stroke {c}' for c, _ in inks(spec, tools)]


def drawn(obj, d):
    '''Whether the object's images are made into lines.'''
    return obj.raster.mode != 'skip' and bool(d.images)


def unmix(rgb, colours):
    '''How much of each ink makes each pixel: (h, w, n) 0..1. Inks multiply, so their
    absorbances (-log of the colour) add: least squares over the absorbances, kept 0..1
    (projected gradient), for each colour of the picture at 5 bits a channel.'''
    h, w, _ = rgb.shape
    q = (rgb >> 3).reshape(-1, 3).astype(np.int32)
    codes, inv = np.unique(q[:, 0] * 1024 + q[:, 1] * 32 + q[:, 2], return_inverse=True)
    cols = (np.stack([codes // 1024, codes // 32 % 32, codes % 32], axis=1) * 8 + 4) / 255
    A = -np.log(np.clip(cols, 0.02, 1))
    P = -np.log(np.clip(np.array([_rgb(c) for c in colours]), 0.02, 1))
    G, B = P @ P.T, A @ P.T
    step = 1 / max(np.linalg.eigvalsh(G).max(), 1e-6)
    c = np.zeros((len(codes), len(colours)))
    for _ in range(300):
        c = np.clip(c - (c @ G - B) * step, 0, 1)
    return c[inv.ravel()].reshape(h, w, len(colours)).astype(np.float32)


def planes(img, spec: RasterSpec, tools=None):
    '''{colour: (h, w) 0..1}: how much of each ink, before the paper and gamma.'''
    ink = inks(spec, tools)
    k = ('planes', spec.separate, tuple(c for c, _ in ink), spec.invert)
    if k in img.cache:
        return img.cache[k]
    rgb = 255 - img.rgb if spec.invert else img.rgb
    if spec.separate == 'one':
        out = {ink[0][0]: 1 - (rgb @ np.array([0.2126, 0.7152, 0.0722], np.float32)) / 255}
    elif spec.separate == 'cmyk':
        f = rgb.astype(np.float32) / 255
        black = 1 - f.max(axis=2)
        cmy = (1 - f - black[..., None]) / np.maximum(1 - black[..., None], 1e-6)
        out = {'#00ffff': cmy[..., 0], '#ff00ff': cmy[..., 1], '#ffff00': cmy[..., 2], '#000000': black}
    else:
        c = unmix(rgb, [c for c, _ in ink])
        out = {colour: c[..., i] for i, (colour, _) in enumerate(ink)}
    for x in [x for x in img.cache if isinstance(x, tuple) and x[0] == 'planes']:
        del img.cache[x]                        # one separation kept at a time: they are big
    img.cache[k] = out
    return out


def grid(img, plane, step, angle, most):
    '''`plane` sampled on a grid `step` mm apart, its rows along `angle` degrees ->
    (us, vs, t, world, step): t[v, u] NaN off the image, world(u, v) -> drawing mm.
    Coarser than `step` when it would take more than `most` cells.'''
    r = math.radians(angle)
    ca, sa = math.cos(r), math.sin(r)
    c = img.corners()
    U, V = c[:, 0] * ca + c[:, 1] * sa, -c[:, 0] * sa + c[:, 1] * ca
    a, b, cc, dd, e, f = img.matrix
    det = a * dd - b * cc
    h, w = plane.shape
    n = abs(det) * w * h / step ** 2            # cells on the picture (not its turned bounds)
    if n > most:
        step *= math.sqrt(n / most)
    us, vs = np.arange(U.min() + step / 2, U.max(), step), np.arange(V.min() + step / 2, V.max(), step)
    Ug, Vg = np.meshgrid(us, vs)
    X, Y = Ug * ca - Vg * sa, Ug * sa + Vg * ca
    px = math.sqrt(abs(det))                    # mm a pixel
    if step > 1.5 * px:                         # average the pixels a cell covers
        k = step / px
        plane = np.asarray(Image.fromarray(plane).resize((max(1, round(w / k)), max(1, round(h / k))), Image.BOX))
    sx, sy = plane.shape[1] / w, plane.shape[0] / h
    pu = (dd * (X - e) - cc * (Y - f)) / det * sx
    pv = (-b * (X - e) + a * (Y - f)) / det * sy
    inside = (pu >= 0) & (pu < plane.shape[1]) & (pv >= 0) & (pv < plane.shape[0])
    t = np.full(X.shape, np.nan, np.float32)
    t[inside] = plane[pv[inside].astype(int), pu[inside].astype(int)]
    return us, vs, t, (lambda u, v: (u * ca - v * sa, u * sa + v * ca)), step


def tone(d, spec):
    d = np.clip((np.clip(d, 0, 1) - spec.paper) / (1 - spec.paper), 0, 1)
    return d ** spec.gamma


def floyd(t):
    '''Floyd-Steinberg (Pillow's): which cells are inked (NaN: never).'''
    grey = np.clip((1 - np.nan_to_num(t)) * 255 + 0.5, 0, 255).astype(np.uint8)
    white = np.asarray(Image.fromarray(grey, 'L').convert('1', dither=Image.Dither.FLOYDSTEINBERG), bool)
    return ~white & ~np.isnan(t)


def runs(mask, us, v, step, world):
    '''The inked cells of a row as lines, centre to centre (one cell: a short dash).'''
    edges = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    out = []
    for i, j in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1) - 1):
        a, b = (us[i], us[j]) if j > i else (us[i] - step / 4, us[i] + step / 4)
        out.append(np.array([world(a, v), world(b, v)]))
    return out


def spiral(cx, cy, r, pitch, chord=0.1):
    '''A dot `r` across (radius), inked by a spiral from its middle with turns `pitch` apart,
    its points about `chord` apart (at least 12 a turn).'''
    if r <= pitch / 2:
        return np.array([[cx - pitch / 8, cy], [cx + pitch / 8, cy]])
    outer = r - pitch / 2                       # the line's centre: its ink reaches r
    turns = outer / pitch
    n = max(12, min(96, math.ceil(2 * math.pi * outer / chord)))       # points a turn
    t = np.linspace(0, turns + 1, int(n * (turns + 1)) + 2)    # out to the edge, then once round it
    rho = np.minimum(t * pitch, outer)
    return np.column_stack([cx + rho * np.cos(2 * math.pi * t), cy + rho * np.sin(2 * math.pi * t)])


def auto(spec: RasterSpec, pen):
    '''(pitch, cell) as plotted: the spec's, else from the pen that draws the ink.'''
    width = pen.width if pen is not None else 0.5
    spacing = pen.spacing if pen is not None else 0.45
    return spec.pitch or spacing, spec.cell or min(3.0, max(0.5, 6 * width))


def lines(img, spec: RasterSpec, scale=1.0, colour=None, angle=0, pen=None, tools=None, problems=None):
    '''One ink of the image as lines, drawing mm (y down, the drawing's scale not applied).'''
    colour = colour or spec.colour.lower()
    pitch, cell = auto(spec, pen)
    k = (spec.model_dump_json(exclude={'pens'}), scale, colour, angle, pitch, cell)
    if k in img.cache:
        out, note = img.cache[k]
        if note and problems is not None:
            problems.append(note)
        return out
    plane = planes(img, spec, tools)[colour]
    out, note = [], None
    if spec.mode in ('dither', 'lines'):
        us, vs, t, world, step = grid(img, plane, pitch / scale, angle, MAX_CELLS if spec.mode == 'dither' else MAX_ROWS_CELLS)
        t = tone(t, spec)
        if spec.mode == 'dither':
            ink = floyd(t)
        else:
            lv = np.array([(LEVELS[i % len(LEVELS)] + 0.5) / len(LEVELS) for i in range(len(vs))])[:, None]
            ink = np.nan_to_num(t) > lv
        for row, v in zip(ink, vs):
            out += runs(row, us, v, step, world)
        if step * scale > pitch * 1.01:
            note = (f'{spec.mode} in {colour}: {step * scale:.2f} mm cells instead of {pitch:.2f}, '
                    f'else too many strokes for the picture\'s size (lighter than it would be)')
    elif spec.mode == 'halftone':
        us, vs, t, world, step = grid(img, plane, cell / scale, angle, MAX_DOTS)
        t = np.nan_to_num(tone(t, spec))
        chord = max(0.1, pitch / 2)                 # mm as plotted between a spiral's points
        # its points: each dot pi r^2 / (pitch chord) (r = 0.6 step sqrt(t)), at least 12 a turn
        est = float(np.sum(2 * math.pi * (0.36 * step ** 2 * t) * scale ** 2)) / (pitch * chord)
        turns = pitch * max(1.0, est / MAX_POINTS)
        p = turns / scale
        for i, v in enumerate(vs):
            for j, u in enumerate(us):
                r = step * 0.6 * math.sqrt(t[i, j])         # pi (0.6 cell)^2 ~ the cell's area at full
                if r >= p / 4:
                    out.append(spiral(*world(u + (step / 2 if i % 2 else 0), v), r, p, chord / scale))
        frame = Polygon(img.corners())          # dots at the edge are cut by the picture's frame
        shapely.prepare(frame)
        out = [q for p in out for q in ([p] if frame.contains(LineString(p)) else lines_of(LineString(p) & frame))]
        if step * scale > cell * 1.01 or turns > pitch * 1.01:
            note = (f'halftone in {colour}: dots {step * scale:.2f} mm apart, their turns {turns:.2f} apart '
                    f'(asked {cell:.2f}, {pitch:.2f}), else too much to plot: lighter. Lines plot quickest with a fine pen')
    if note and problems is not None:
        problems.append(note)
    if len(img.cache) > 24:
        for x in [x for x in img.cache if isinstance(x, tuple) and x[0] != 'planes']:
            del img.cache[x]
    img.cache[k] = (out, note)
    return out


def raster_shapes(d, obj, tools=None, pen_of=None, problems=None):
    '''The drawing's images as shapes of lines, one for each ink, as obj.raster says (none
    when it skips them). pen_of(colour): the tool that draws that ink, None: not drawn.'''
    if not drawn(obj, d):
        return []
    spec, out = obj.raster, []
    for img in d.images:
        for colour, angle in inks(spec, tools):
            pen = pen_of(colour) if pen_of else None
            if pen_of and pen is None:
                continue                        # skipped or masked: no lines to make
            paths = lines(img, spec, obj.scale, colour, angle, pen, tools, problems)
            if paths:
                out.append(svg.Shape(img.index, img.id, colour, None, 0.01, False, False, 'nonzero',
                                     'round', 'round', paths, [False] * len(paths), raster=True))
    return out
