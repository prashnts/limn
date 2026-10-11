# Limn plot - colours no pen has: screens, and pens side by side
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Inks next to each other mix in the eye, not on the paper: from a little way off a
# patch reflects the average of what its inks and its bare paper reflect, each by the
# share of the patch it covers (linear light). So:
#
# - screen (a tool's or a colour's `tone`): one pen, its lines spaced so the share it
#   covers makes the colour's lightness: a grey in the black pen is lines with paper
#   between, not black.
# - mix (a colour's layer `mix`): the shares of all the pens (and the paper) whose average
#   is nearest the colour, solved over the simplex. One set of lines over the area, a pen
#   width and its bleed apart (inks side by side never touch: ink.py has nothing to cut),
#   each line given to a pen in proportion: a green C, Y, C, Y; darker, some K lines;
#   lighter, some left as paper. Which line goes to which pen is fixed by the line's
#   number on a grid that doesn't move (the golden ratio spreads them evenly), so two
#   shapes of a colour line up.
#
# The plot takes the light pens first and the dark last (emit), so yellow goes before it
# can pick up a darker ink, and the black fineliner comes last.
import math

import numpy as np
from shapely import affinity
from shapely.geometry import MultiLineString

from .geometry import lines_of

SCREEN_MIN = 0.03   # a share under this of the area isn't drawn: the paper
GOLDEN = (math.sqrt(5) - 1) / 2


def linear(hexc):
    '''sRGB '#rrggbb' -> linear light, 0..1 each.'''
    c = np.array([int(hexc[i:i + 2], 16) for i in (1, 3, 5)], float) / 255
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def luminance(hexc):
    return float(linear(hexc) @ (0.2126, 0.7152, 0.0722))


def coverage(colour, pen):
    '''The share of the area a pen of colour `pen` inks to look as light as `colour` (0..1).'''
    dark = 1 - luminance(pen)
    return float(np.clip((1 - luminance(colour)) / max(dark, 1e-3), 0, 1))


def _simplex(v):
    '''v projected onto the probability simplex.'''
    u = np.sort(v)[::-1]
    css = np.cumsum(u) - 1
    k = np.nonzero(u * np.arange(1, len(v) + 1) > css)[0][-1]
    return np.maximum(v - css[k] / (k + 1), 0)


def shares(colour, pens, chroma=0.02):
    '''{pen id: share of the area it inks} whose average with the paper is nearest `colour`
    (linear RGB, least squares). Each pen's share costs `chroma` times how colourful it is:
    where grey and black make a colour as well, the colour pens stay out of it (a grey isn't
    a little of everything). pens: {id: '#rrggbb'}. -> (shares, the paper's, the error 0..1).'''
    ids = list(pens)
    if not ids:
        return {}, 1.0, 1.0
    V = np.vstack([linear(pens[i]) for i in ids] + [np.ones(3)])      # the paper last
    t = linear(colour)
    G = V @ V.T + 1e-4 * np.eye(len(V))
    b = V @ t - chroma * (V.max(axis=1) - V.min(axis=1))
    w = np.full(len(V), 1 / len(V))
    step = 1 / np.linalg.eigvalsh(G).max()
    for _ in range(400):
        w = _simplex(w - step * (G @ w - b))
    err = float(np.linalg.norm(w @ V - t) / math.sqrt(3))
    return {i: float(x) for i, x in zip(ids, w[:-1]) if x >= SCREEN_MIN}, float(w[-1]), err


def rows(area, spacing, angle):
    '''Lines `spacing` apart at `angle` over `area`, each with its number on a grid that
    doesn't depend on the area: [(k, (n, 2))].'''
    if area is None or area.is_empty:
        return []
    r = affinity.rotate(area, -angle, origin=(0, 0))
    x0, y0, x1, y1 = r.bounds
    out = []
    for k in range(math.ceil(y0 / spacing), math.floor(y1 / spacing) + 1):
        cut = r.intersection(MultiLineString([[(x0 - 1, k * spacing), (x1 + 1, k * spacing)]]))
        out += [(k, p) for p in lines_of(affinity.rotate(cut, angle, origin=(0, 0)))]
    return out


def side_by_side(area, share, tools, angle=45):
    '''The area's lines, each to a pen: {pen id: paths}, and the lines' spacing.
    share: {pen id: share of the area}, as shares() gives.'''
    use = {i: s for i, s in share.items() if i in tools and s > 0}
    if not use:
        return {}, 0.0
    spacing = max(tools[i].width + tools[i].bleed for i in use) + 0.005     # (a hair: ink.guard's d is <=)
    # a line of pen i inks w_i / spacing of its strip: that many more of its lines for a thin pen
    n = {i: s * spacing / tools[i].width for i, s in use.items()}
    total = sum(n.values())
    if total > 1:
        n = {i: v / total for i, v in n.items()}
    order = sorted(n)                       # a fixed order: the same colour, the same lines
    edges = np.cumsum([n[i] for i in order])
    out = {}
    for k, p in rows(area, spacing, angle):
        u = (k * GOLDEN) % 1.0
        j = int(np.searchsorted(edges, u, side='right'))
        if j < len(order):                  # past the last: the paper's line
            out.setdefault(order[j], []).append(p)
    return out, spacing
