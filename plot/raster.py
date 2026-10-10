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
#   palette  the picture's own main colours (`colours` of them, median cut over
#         all the drawing's pictures, the paper-light ones left out): each pixel
#         goes to the nearest, as dark as it is next to that colour (the colour
#         itself solid). Each is a layer: give each a pen, any pen
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
# pitch its fill spacing, so black is solid; cell 4 of its lines, 0.5 to 2 mm
# (6, to 3 mm, made dots too big to read as tone: 2.4 mm for a 0.4 felt tip).
# With `palette` a colour drawn by a pen of another colour is as dark as the
# colour, not solid: a light grey drawn in blue is a quarter covered.
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


PAPER_LIGHT = 0.92          # palette: colours this light are the paper, not an ink


def _lum(rgb):
    return rgb @ np.array([0.2126, 0.7152, 0.0722], np.float32)


def palette(images, n, invert=False):
    '''The main colours of the pictures, '#rrggbb' darkest first: median cut over all of
    them together (so every picture has the same inks), the paper-light ones left out.'''
    if not images:
        return []
    k = ('palette', n, invert, tuple(id(im) for im in images))
    first = images[0].cache
    if k in first:
        return first[k]
    px = []
    for im in images:
        rgb = 255 - im.rgb if invert else im.rgb
        flat = rgb.reshape(-1, 3)
        step = max(1, len(flat) // 200_000)
        px.append(flat[::step])
    px = np.vstack(px).astype(np.uint8)
    q = Image.fromarray(px.reshape(1, -1, 3), 'RGB').quantize(colors=min(256, n + 4), method=Image.Quantize.MEDIANCUT)
    pal = np.array(q.getpalette()[:3 * (min(256, n + 4))], float).reshape(-1, 3)
    counts = np.bincount(np.asarray(q).ravel(), minlength=len(pal))
    keep = [(int(counts[i]), pal[i]) for i in range(len(pal)) if counts[i] and _lum(pal[i] / 255) < PAPER_LIGHT]
    keep.sort(key=lambda x: -x[0])
    out = []
    for _, c in keep:
        hexc = '#' + ''.join(f'{int(round(v)):02x}' for v in c)
        if hexc not in out:
            out.append(hexc)
        if len(out) == n:
            break
    out.sort(key=lambda c: float(_lum(_rgb(c))))
    first[k] = out
    for im in images[1:]:
        im.cache[('palette', n, invert)] = out
    first[('palette', n, invert)] = out
    return out


def inks(spec: RasterSpec, tools=None, images=None):
    '''[(colour, angle)]: the inks the image is separated into, on their screen angles.
    images: the drawing's pictures, for `palette` (their colours).'''
    one = 45 if spec.mode == 'halftone' else 0
    if spec.separate == 'one':
        return [(spec.colour.lower(), one)]
    if spec.separate == 'cmyk':
        return list(CMYK)
    if spec.separate == 'palette':
        cols = palette(images, spec.colours, spec.invert) if images else []
        return [(c, ANGLES[i % len(ANGLES)]) for i, c in enumerate(cols)] or [('#000000', one)]
    colours = []
    for t in (tools or {}).values():
        c = t.color.lower()
        if t.draws and (not spec.pens or t.id in spec.pens) and c not in colours and _rgb(c).min() < 0.95:
            colours.append(c)
    return [(c, ANGLES[i % len(ANGLES)]) for i, c in enumerate(colours)] or [('#000000', one)]


def keys(spec: RasterSpec, tools=None, images=None):
    '''The colour keys its lines are painted by: one layer for each ink.'''
    return [f'stroke {c}' for c, _ in inks(spec, tools, images)]


def spec_of(obj, img):
    '''How one of its images is drawn: its own settings (obj.images, by index), else the drawing's.'''
    return obj.images.get(str(img.index)) or obj.raster


def peers(obj, d, spec):
    '''The images whose inks `palette` takes together with this spec's: the ones of the same palette.'''
    return [im for im in d.images if (s := spec_of(obj, im)).mode != 'skip' and s.separate == 'palette'
            and (s.colours, s.invert) == (spec.colours, spec.invert)]


def object_keys(obj, d, tools=None):
    '''The colour keys of all its images' inks, each once: a layer each.'''
    out = []
    for img in d.images:
        spec = spec_of(obj, img)
        if spec.mode != 'skip':
            out += [k for k in keys(spec, tools, peers(obj, d, spec)) if k not in out]
    return out


def drawn(obj, d):
    '''Whether any of the object's images is made into lines.'''
    return any(spec_of(obj, im).mode != 'skip' for im in d.images)


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
    ink = inks(spec, tools, [img]) if spec.separate != 'palette' else \
        [(c, 0) for c in img.cache.get(('palette', spec.colours, spec.invert), [])]
    k = ('planes', spec.separate, tuple(c for c, _ in ink), spec.invert)
    if k in img.cache:
        return img.cache[k]
    rgb = 255 - img.rgb if spec.invert else img.rgb
    if spec.separate == 'one':
        out = {ink[0][0]: 1 - (rgb @ np.array([0.2126, 0.7152, 0.0722], np.float32)) / 255}
    elif spec.separate == 'palette':
        # each pixel to the nearest of the palette and the paper; as dark next to its colour
        cols = [c for c, _ in ink]
        ref = np.array([_rgb(c) for c in cols] + [[1.0, 1.0, 1.0]], np.float32)
        f = rgb.astype(np.float32) / 255
        near = np.argmin(((f[..., None, :] - ref[None, None]) ** 2).sum(axis=3), axis=2)
        dark = 1 - _lum(f)
        out = {c: np.where(near == i, np.clip(dark / max(1e-3, 1 - float(_lum(ref[i]))), 0, 1), 0).astype(np.float32)
               for i, c in enumerate(cols)}
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
    return spec.pitch or spacing, spec.cell or min(2.0, max(0.5, 4 * width))


def lines(img, spec: RasterSpec, scale=1.0, colour=None, angle=0, pen=None, tools=None, problems=None):
    '''One ink of the image as lines, drawing mm (y down, the drawing's scale not applied).'''
    colour = colour or spec.colour.lower()
    pitch, cell = auto(spec, pen)
    k = (spec.model_dump_json(exclude={'pens'}), scale, colour, angle, pitch, cell, pen.color if pen is not None else None)
    if k in img.cache:
        out, note = img.cache[k]
        if note and problems is not None:
            problems.append(note)
        return out
    plane = planes(img, spec, tools)[colour]
    if spec.separate == 'palette' and pen is not None:     # as dark as its colour, in the pen's ink
        plane = np.clip(plane * ((1 - float(_lum(_rgb(colour)))) / max(0.05, 1 - float(_lum(_rgb(pen.color))))), 0, 1)
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
                if r >= p * 0.35:                   # less: a dot the pen's width, far darker than asked
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
    '''The drawing's images as shapes of lines, one for each ink, as each image's spec says
    (spec_of; none for one it skips). pen_of(colour): the tool that draws that ink, None: not drawn.'''
    if not drawn(obj, d):
        return []
    out = []
    for img in d.images:
        spec = spec_of(obj, img)
        if spec.mode == 'skip':
            continue
        for colour, angle in inks(spec, tools, peers(obj, d, spec)):
            pen = pen_of(colour) if pen_of else None
            if pen_of and pen is None:
                continue                        # skipped or masked: no lines to make
            paths = lines(img, spec, obj.scale, colour, angle, pen, tools, problems)
            if paths:
                out.append(svg.Shape(img.index, img.id, colour, None, 0.01, False, False, 'nonzero',
                                     'round', 'round', paths, [False] * len(paths), raster=True))
    return out
