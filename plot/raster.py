# Limn plot - a drawing's <image>s made into lines a pen can draw
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# An image is sampled on a grid square to the page (job.RasterSpec), its
# pixels averaged down to the grid first. Darkness: 0 white (or transparent)
# to 1 black, inverted on request; up to `paper` is the paper (no ink, so a
# light background isn't speckled), the rest stretched to 0..1, then ** gamma.
# Then, in the spec's colour:
#
#   dither    Floyd-Steinberg on cells `pitch` apart; the dark cells of a row
#             joined into lines. Fine detail, many short strokes.
#   lines     rows `pitch` apart, each drawn where the picture is darker than
#             its row's level (4 levels, ordered): long strokes, quick to plot.
#   halftone  dots `cell` apart (every other row offset), each a spiral with
#             its turns `pitch` apart, as wide as the spot is dark.
#
# `pitch` and `cell` are mm as plotted: the drawing's scale is taken out. The
# lines come out as one shape per image (svg.Shape, raster: never too small
# for its tool), stroked in the spec's colour: its colour's layer draws it.
import math

import numpy as np
from PIL import Image

from . import svg
from .job import RasterSpec

LEVELS = (0, 2, 1, 3)       # the rows' thresholds in `lines`, in order (a 1-D Bayer matrix)


def key(spec: RasterSpec):
    '''The colour key the lines are painted by.'''
    return f'stroke {spec.colour.lower()}'


def drawn(obj, d):
    '''Whether the object's images are made into lines.'''
    return obj.raster.mode != 'skip' and bool(d.images)


def sample(img, step):
    '''Darkness on a grid `step` mm apart over the image -> (xs, ys, d), d NaN off the image.'''
    c = img.corners()
    (x0, y0), (x1, y1) = c.min(axis=0), c.max(axis=0)
    xs, ys = np.arange(x0 + step / 2, x1, step), np.arange(y0 + step / 2, y1, step)
    a, b, cc, dd, e, f = img.matrix
    det = a * dd - b * cc
    dark = img.dark
    h, w = dark.shape
    px = math.sqrt(abs(det))                    # mm a pixel
    if step > 1.5 * px:                         # average the pixels a cell covers
        k = step / px
        dark = np.asarray(Image.fromarray(dark).resize((max(1, round(w / k)), max(1, round(h / k))), Image.BOX))
    sx, sy = dark.shape[1] / w, dark.shape[0] / h
    X, Y = np.meshgrid(xs, ys)
    u = (dd * (X - e) - cc * (Y - f)) / det * sx
    v = (-b * (X - e) + a * (Y - f)) / det * sy
    inside = (u >= 0) & (u < dark.shape[1]) & (v >= 0) & (v < dark.shape[0])
    out = np.full(X.shape, np.nan, np.float32)
    out[inside] = dark[v[inside].astype(int), u[inside].astype(int)]
    return xs, ys, out


def tone(d, spec):
    d = np.clip(d, 0, 1)
    if spec.invert:
        d = 1 - d
    d = np.clip((d - spec.paper) / (1 - spec.paper), 0, 1)
    return d ** spec.gamma


def floyd(d):
    '''Floyd-Steinberg, serpentine: which cells are inked (NaN: never).'''
    g = np.nan_to_num(d).astype(np.float64)
    h, w = g.shape
    out = np.zeros((h, w), bool)
    for y in range(h):
        s = 1 if y % 2 == 0 else -1
        row, nxt = g[y], g[y + 1] if y + 1 < h else None
        for x in (range(w) if s == 1 else range(w - 1, -1, -1)):
            new = row[x] >= 0.5
            out[y, x] = new
            err = row[x] - new
            if 0 <= x + s < w:
                row[x + s] += err * 7 / 16
            if nxt is not None:
                if 0 <= x - s < w:
                    nxt[x - s] += err * 3 / 16
                nxt[x] += err * 5 / 16
                if 0 <= x + s < w:
                    nxt[x + s] += err / 16
    return out & ~np.isnan(d)


def runs(mask, xs, y, step):
    '''The inked cells of a row as lines, centre to centre (one cell: a short dash).'''
    edges = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    out = []
    for i, j in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1) - 1):
        a, b = (xs[i], xs[j]) if j > i else (xs[i] - step / 4, xs[i] + step / 4)
        out.append(np.array([[a, y], [b, y]]))
    return out


def spiral(cx, cy, r, pitch):
    '''A dot `r` across (radius), inked by a spiral from its middle with turns `pitch` apart.'''
    if r <= pitch / 2:
        return np.array([[cx - pitch / 8, cy], [cx + pitch / 8, cy]])
    outer = r - pitch / 2                       # the line's centre: its ink reaches r
    turns = outer / pitch
    n = max(16, int(2 * math.pi * outer / (pitch / 3)))
    t = np.linspace(0, turns + 1, int(n * (turns + 1)) + 2)    # out to the edge, then once round it
    rho = np.minimum(t * pitch, outer)
    return np.column_stack([cx + rho * np.cos(2 * math.pi * t), cy + rho * np.sin(2 * math.pi * t)])


def lines(img, spec: RasterSpec, scale=1.0):
    '''The image as lines, drawing mm (y down, the drawing's scale not applied).'''
    k = (spec.model_dump_json(), scale)
    if k in img.cache:
        return img.cache[k]
    pitch = spec.pitch / scale
    out = []
    if spec.mode in ('dither', 'lines'):
        xs, ys, d = sample(img, pitch)
        t = tone(d, spec)
        if spec.mode == 'dither':
            ink = floyd(t)
        else:
            lv = np.array([(LEVELS[i % len(LEVELS)] + 0.5) / len(LEVELS) for i in range(len(ys))])[:, None]
            ink = np.nan_to_num(t) > lv
        for row, y in zip(ink, ys):
            out += runs(row, xs, y, pitch)
    elif spec.mode == 'halftone':
        cell = spec.cell / scale
        xs, ys, d = sample(img, cell)
        t = np.nan_to_num(tone(d, spec))
        for i, y in enumerate(ys):
            for j, x in enumerate(xs):
                r = cell * 0.6 * math.sqrt(t[i, j])         # pi (0.6 cell)^2 ~ the cell's area at black
                if r >= pitch / 4:
                    out.append(spiral(x + (cell / 2 if i % 2 else 0), y, r, pitch))
    if len(img.cache) > 8:
        img.cache.clear()
    img.cache[k] = out
    return out


def raster_shapes(d, obj):
    '''The drawing's images as shapes of lines, as obj.raster says (none when it skips them).'''
    if not drawn(obj, d):
        return []
    spec = obj.raster
    out = []
    for img in d.images:
        paths = lines(img, spec, obj.scale)
        if paths:
            out.append(svg.Shape(img.index, img.id, spec.colour.lower(), None, 0.01, False, False, 'nonzero',
                                 'round', 'round', paths, [False] * len(paths), raster=True))
    return out
