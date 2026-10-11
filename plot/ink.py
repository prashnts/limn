# Limn plot - ink on paper: what runs together
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Ink always bleeds. A spot the pen goes over again soaks the paper, and enough
# passes tear it; another ink touching it runs into it. The SVG doesn't care: a
# scatter plot of a thousand translucent dots, 0.5 mm each and 0.2 mm apart, is a
# thousand tiny circles each filled, the pen over the same spot a hundred times.
#
# The slicer gives each shape's stroke or fill as a Unit, in paint order, and:
# - merge (a tool's `dense`): small shapes of one tool (under MERGE of its widths
#   across) whose inks touch are one area, filled once: the dots of a scatter become
#   the band they make. Off ('exact', the default), every shape is followed as it is.
# - guard (a tool's `overdraw`): what is painted on top wins. From the top down, a
#   unit's lines are cut where they would go over ink already there: another tool's
#   kept its `bleed` clear (ink to ink, the pens' widths counted), its own where
#   they run within its fill spacing for more than CROSS spacings (lines that only
#   cross keep their crossing; a line along another, or a dot in one, goes).
#   Ends give way first, whoever is on top: a line whose end runs into another
#   tool's ink is shortened (a tick stops short of its label), rather than what
#   it runs into cut through (the label loses a piece of a letter).
#   'warn' only says so, 'draw' doesn't look.
# - check: the G-code as written, read back. How many layers of ink each spot gets,
#   averaged over a disc a pen's width across: a line 0.64, two crossing 1.27, a fill
#   at 15% overlap 1.18. Over DENSE is too much ink; any spot of two tools' inks
#   (bar light under dark, `layers`) is inks running together.
from dataclasses import dataclass, field

import numpy as np
import shapely
from shapely.geometry import MultiLineString, box
from shapely.ops import unary_union

from .geometry import fill

MERGE = 4       # dense 'merge': shapes under this many tool widths across are merged with those they touch
CROSS = 3       # its own ink on top: a stretch within its spacing longer than this many spacings is cut
DENSE = 1.6     # check: more layers of ink than this, averaged over a disc a pen's width across
SPOT = 2        # .. over more than this many pen widths squared, is a spot that soaks
BIG = 2000      # guard: a unit of more points than this is grown only near what it is checked against


@dataclass
class Unit:
    key: tuple                      # paint order: (shape index, 0 fill / 1 stroke)
    tool: str
    paths: list                     # (n, 2), object mm
    shapes: set = field(default_factory=set)
    ink: object = None              # the area its ink covers: small ones may merge
    how: tuple = None               # how its area is filled again: pattern, spacing, angle, border
    small: tuple | None = None      # (paths, ink) to tell whether it is too small, after merging
    merged: int = 1                 # shapes in it


def across(paths):
    pts = [p for p in paths if len(p)]
    if not pts:
        return 0.0
    a = np.vstack(pts)[:, :2]
    return float(np.ptp(a, axis=0).max())


def refill(area, width, how):
    '''Fill an area as a unit's `how` says: (pattern, spacing, angle, border).'''
    pattern, spacing, angle, border = how
    return fill(area, width, spacing, pattern, angle, border)


def merge(units, tools):
    '''Small units of one tool (and one way of filling) whose inks touch, merged: their
    areas filled once. -> (units in paint order, {tool: (shapes, areas they became)}).'''
    out, groups = [], {}
    for u in units:
        t = tools.get(u.tool)
        if (t is not None and getattr(t, 'dense', 'exact') == 'merge' and u.ink is not None
                and not u.ink.is_empty and u.how is not None and across(u.paths) < MERGE * t.width):
            groups.setdefault((u.tool, u.how), []).append(u)
        else:
            out.append(u)
    stats = {}
    for (tid, how), us in groups.items():
        t = tools[tid]
        inks = [u.ink for u in us]
        tree = shapely.STRtree(inks)
        parent = list(range(len(us)))

        def root(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        # touching: within the gap the paper closes anyway (its bleed, a fifth of the line at least)
        a, b = tree.query(inks, predicate='dwithin', distance=max(t.bleed, t.width / 5))
        for i, j in zip(a.tolist(), b.tolist()):
            if i != j:
                parent[root(i)] = root(j)
        clusters = {}
        for i in range(len(us)):
            clusters.setdefault(root(i), []).append(us[i])
        n = 0
        for cl in clusters.values():
            if len(cl) == 1:
                out.append(cl[0])
                continue
            area = unary_union([u.ink for u in cl])
            paths = refill(area, t.width, how)
            shapes = set().union(*(u.shapes for u in cl))
            out.append(Unit(max(u.key for u in cl), tid, paths, shapes, area, how,
                            (paths, area), sum(u.merged for u in cl)))
            n += 1
        merged = sum(len(cl) for cl in clusters.values() if len(cl) > 1)
        if merged:
            s, k = stats.get(tid, (0, 0))
            stats[tid] = (s + merged, k + n)
    out.sort(key=lambda u: u.key)
    return out, stats


def _densify(p, step):
    '''p with points every `step` at most along it, the original vertices kept (flagged).'''
    seg = np.diff(p[:, :2], axis=0)
    n = np.maximum(1, np.ceil(np.hypot(*seg.T) / step)).astype(int)
    f = (np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n)) / np.repeat(n, n)
    i = np.repeat(np.arange(len(seg)), n)
    q = np.vstack([p[i, :2] + seg[i] * f[:, None], p[-1:, :2]])
    orig = np.append(f == 0, True)
    return q, orig


def _runs(mask):
    '''(start, end) of each run of True in mask, end exclusive.'''
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


def cut_over(paths, same, other, long, step, min_piece):
    '''paths less where they run over ink: anywhere in `other` (another tool's, grown by the
    gap to it), along more than `long` in `same` (its own), or all of a path in `same`.
    -> (paths kept, mm cut, a point cut).'''
    if same is not None:
        shapely.prepare(same)
    if other is not None:
        shapely.prepare(other)
    out, removed, where = [], 0.0, None
    for p in paths:
        if len(p) < 2:
            out.append(p)
            continue
        q, orig = _densify(p, step)
        s = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(q, axis=0).T))])
        drop = np.zeros(len(q), bool)
        if other is not None:
            drop |= shapely.contains_xy(other, q[:, 0], q[:, 1])
        if same is not None:
            inside = shapely.contains_xy(same, q[:, 0], q[:, 1])
            for a, b in _runs(inside):
                if s[b - 1] - s[a] > long or (a == 0 and b == len(q)):
                    drop[a:b] = True
        if not drop.any():
            out.append(p)
            continue
        removed += float(np.sum(np.diff(s)[drop[1:] | drop[:-1]]))
        if where is None:
            where = q[np.argmax(drop)]
        zones = [z for z in (same, other) if z is not None]
        for a, b in _runs(~drop):
            keep = orig[a:b].copy()
            keep[0] = keep[-1] = True
            piece = q[a:b][keep]
            # the ends cut: on the edge of the ink, not on the last point sampled before it
            if a > 0:
                piece = np.vstack([_edge(q[a], q[a - 1], zones), piece])
            if b < len(q):
                piece = np.vstack([piece, _edge(q[b - 1], q[b], zones)])
            if len(piece) < 2 or np.hypot(*np.diff(piece, axis=0).T).sum() < min_piece:
                continue                # a crumb left between cuts: a dot next to other ink
            out.append(piece)
    return out, removed, where


def _edge(out_pt, in_pt, zones, n=12):
    '''Where the segment from out_pt (clear) to in_pt (in one of the zones) goes in.'''
    lo, hi = 0.0, 1.0
    for _ in range(n):
        m = (lo + hi) / 2
        x, y = out_pt + (in_pt - out_pt) * m
        if any(shapely.contains_xy(z, x, y) for z in zones):
            hi = m
        else:
            lo = m
    return out_pt + (in_pt - out_pt) * lo


def trim_ends(paths, zone, limit, step):
    '''Open paths whose ends are in `zone`, shortened out of it when that is under `limit`
    (a path all in it, that short, goes). -> (paths, mm trimmed, a point trimmed).'''
    shapely.prepare(zone)
    out, removed, where = [], 0.0, None
    for p in paths:
        if len(p) < 2 or np.allclose(p[0, :2], p[-1, :2]):
            out.append(p)
            continue
        q, orig = _densify(p, step)
        inside = shapely.contains_xy(zone, q[:, 0], q[:, 1])
        if not (inside[0] or inside[-1]):
            out.append(p)
            continue
        s = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(q, axis=0).T))])
        if inside.all():
            if s[-1] <= limit:
                removed += s[-1]
                where = q[0] if where is None else where
            else:
                out.append(p)
            continue
        a, b = 0, len(q)
        if inside[0]:
            a = int(np.argmin(inside))                      # the first point out
            if s[a] > limit:
                a = 0
        if inside[-1]:
            b = len(q) - int(np.argmin(inside[::-1]))       # past the last point out
            if s[-1] - s[b - 1] > limit:
                b = len(q)
        if (a, b) == (0, len(q)):
            out.append(p)
            continue
        removed += s[a] + s[-1] - s[b - 1]
        where = (q[0] if a else q[-1]) if where is None else where
        keep = orig[a:b].copy()
        keep[0] = keep[-1] = True
        piece = q[a:b][keep]
        if a:
            piece = np.vstack([_edge(q[a], q[a - 1], [zone]), piece])
        if b < len(q):
            piece = np.vstack([piece, _edge(q[b - 1], q[b], [zone])])
        out.append(piece)
    return out, removed, where


def guard(units, tools, under=None):
    '''Top wins: from the unit painted last down, each one's lines are cut where they would
    go over ink drawn on top of it (see the top). under(lower tool, upper tool): whether the
    lower ink is drawn whole under the upper (light under dark).
    -> (units, {(tool, tool on top): [mm cut, a point]}, shapes cut).'''
    lines = [MultiLineString([p for p in u.paths if len(p) >= 2]) if u.paths else None for u in units]
    idx = [i for i, g in enumerate(lines) if g is not None and not g.is_empty]
    if not idx:
        return units, {}, set()
    tree = shapely.STRtree([lines[i] for i in idx])
    ids = list(idx)                 # the tree's
    reach = max(t.width + t.bleed for t in tools.values()) + 0.01
    widest = max(t.width for t in tools.values())
    stats, cut_shapes = {}, set()
    out = list(units)

    def mode_of(t):
        return getattr(t, 'overdraw', 'cut') if t is not None else 'draw'

    grown = {}

    def ink_of(j, geom, d, box):
        '''Unit j's lines (geom) grown by d: its ink and the gap to it. Small units whole, once;
        a big one (a picture's thousands of lines) only near `box`, buffering all of it is slow.'''
        if len(shapely.get_coordinates(geom)) > BIG:
            near = shapely.clip_by_rect(geom, box[0] - d, box[1] - d, box[2] + d, box[3] + d)
            return None if near.is_empty else near.buffer(d, quad_segs=4)
        k = (j, id(geom), round(d, 6))
        if k not in grown:
            grown[k] = (geom, geom.buffer(d, quad_segs=4))      # geom kept: its id stays its own
        return grown[k][1]

    def near(i):
        x0, y0, x1, y1 = lines[i].bounds
        return (ids[k] for k in tree.query(box(x0 - reach, y0 - reach, x1 + reach, y1 + reach)))

    def tell(u, other, removed, where):
        st = stats.setdefault((u.tool, other), [0.0, where])
        st[0] += removed
        cut_shapes.update(u.shapes)

    # Ends first: against every other tool's ink, above or below (but what goes under it), one
    # after another from the top, against what is left: a tick gone, the label it ran into is clear
    for i in sorted(idx, reverse=True):
        u, t = units[i], tools.get(units[i].tool)
        if mode_of(t) == 'draw':
            continue
        zone, near_tools = [], []
        for j in near(i):
            v, vt = units[j], tools.get(units[j].tool)
            if j == i or vt is None or v.tool == u.tool or lines[j] is None:
                continue
            if under is not None and (under(t, vt) if j > i else under(vt, t)):
                continue
            g = ink_of(j, lines[j], (t.width + vt.width) / 2 + t.bleed, lines[i].bounds)
            if g is not None and g.intersects(lines[i]):
                zone.append(g)
                near_tools.append(v.tool)
        if not zone:
            continue
        z = unary_union(zone)
        paths, removed, where = trim_ends(u.paths, z, 2 * ((t.width + widest) / 2 + t.bleed), t.spacing / 4)
        if removed:
            top = next((tid for tid, g in zip(near_tools, zone) if g.covers(shapely.Point(where))), near_tools[0])
            tell(u, top, removed, where)
            if mode_of(t) == 'cut':
                out[i] = Unit(u.key, u.tool, paths, u.shapes, u.ink, u.how, u.small, u.merged)
                ls = MultiLineString([p for p in paths if len(p) >= 2]) if paths else None
                lines[i] = ls if ls is not None and not ls.is_empty else None
    idx = [i for i in idx if lines[i] is not None and not lines[i].is_empty]
    final = list(lines)
    for i in sorted(idx, reverse=True):
        u, t = out[i], tools.get(units[i].tool)
        mode = mode_of(t)
        if mode == 'draw':
            continue
        same, other, tops = [], [], {}
        for j in near(i):
            if j <= i or final[j] is None or final[j].is_empty:
                continue
            v, vt = units[j], tools.get(units[j].tool)
            if vt is None or (under is not None and under(t, vt)):
                continue
            d = t.spacing if v.tool == u.tool else (t.width + vt.width) / 2 + t.bleed
            g = ink_of(j, final[j], d, lines[i].bounds)
            if g is not None and g.intersects(lines[i]):
                (same if v.tool == u.tool else other).append(g)
                tops.setdefault(v.tool, []).append(g)
        if not same and not other:
            continue
        sz, oz = unary_union(same) if same else None, unary_union(other) if other else None
        paths, removed, where = cut_over(u.paths, sz, oz, CROSS * t.spacing, t.spacing / 4, t.width)
        if not removed:
            continue
        # who it was cut for: the top tool whose ink is at the first point cut, else the nearest
        top = next((tid for tid, gs in tops.items() if any(g.covers(shapely.Point(where)) for g in gs)),
                   next(iter(tops)))
        tell(u, top, removed, where)
        if mode == 'cut':
            out[i] = Unit(u.key, u.tool, paths, u.shapes, u.ink, u.how, u.small, u.merged)
            final[i] = MultiLineString([p for p in paths if len(p) >= 2]) if paths else None
    return out, stats, cut_shapes


# The check, on what is drawn (G-code read back)

def _resample(p, step):
    seg = np.diff(p[:, :2], axis=0)
    ln = np.hypot(*seg.T)
    n = np.maximum(1, np.ceil(ln / step)).astype(int)
    i = np.repeat(np.arange(len(seg)), n)
    f = (np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n) + 0.5) / np.repeat(n, n)
    return p[i, :2] + seg[i] * f[:, None], np.repeat(ln / n, n)


def _disc(shape, r_px):
    k = np.zeros(shape)
    r = max(1, int(round(r_px)))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    m = xx * xx + yy * yy <= r * r
    k[yy[m] % shape[0], xx[m] % shape[1]] = 1
    return k, int(m.sum())


def _spots(mask, px, min_area, block=4):
    '''Spots of mask over min_area mm²: [(area, (i, j) of a pixel in it)], biggest first.
    Spots are told apart on blocks of block × block pixels (touching blocks: one spot).'''
    if not mask.any():
        return []
    h, w = -(-mask.shape[0] // block), -(-mask.shape[1] // block)
    m = np.zeros((h * block, w * block), bool)
    m[:mask.shape[0], :mask.shape[1]] = mask
    cnt = m.reshape(h, block, w, block).sum(axis=(1, 3))
    lab = np.zeros(cnt.shape, np.int32)
    out = []
    for y, x in zip(*np.nonzero(cnt)):
        if lab[y, x]:
            continue
        lab[y, x] = len(out) + 1
        stack, total = [(y, x)], 0
        while stack:
            cy, cx = stack.pop()
            total += cnt[cy, cx]
            for ny in (cy - 1, cy, cy + 1):
                for nx in (cx - 1, cx, cx + 1):
                    if 0 <= ny < h and 0 <= nx < w and cnt[ny, nx] and not lab[ny, nx]:
                        lab[ny, nx] = lab[y, x]
                        stack.append((ny, nx))
        out.append((float(total) * px * px, (int(y) * block + block // 2, int(x) * block + block // 2)))
    return sorted((s for s in out if s[0] >= min_area), reverse=True)


MAX_PX = 1_500_000      # the grid's pixels at most: a bigger plot is checked coarser


def check(runs, tools, under=None):
    '''What is drawn: runs [(tool id, (n, 2+) points)], bed mm (a dot: a path that goes
    nowhere, inked as a dab half the pen's width long). -> (problems, report): spots of
    too much ink of one tool, spots where two tools' inks meet.'''
    runs = [(t, np.asarray(p)[:, :2]) for t, p in runs if t in tools and len(p)]
    if not runs:
        return [], {}
    widths = [tools[t].width for t, _ in runs]
    pad = max(widths) * 2
    allp = np.vstack([p for _, p in runs])
    x0, y0 = allp.min(axis=0) - pad
    x1, y1 = allp.max(axis=0) + pad
    px = max(min(widths) / 3, ((x1 - x0) * (y1 - y0) / MAX_PX) ** 0.5)
    nx, ny = int((x1 - x0) / px) + 1, int((y1 - y0) / px) + 1
    samples = {}
    for tid, p in runs:
        q, ln = _resample(p, px / 4) if len(p) >= 2 else (p[:1], np.zeros(1))
        if ln.sum() < tools[tid].width / 2:
            q, ln = p[:1], np.array([tools[tid].width / 2])
        samples.setdefault(tid, []).append((q, ln))
    dens = {}
    for tid, ss in samples.items():         # length of line in each pixel
        q, ln = np.vstack([a for a, _ in ss]), np.concatenate([b for _, b in ss])
        ix = np.clip(((q[:, 0] - x0) / px).astype(int), 0, nx - 1)
        iy = np.clip(((q[:, 1] - y0) / px).astype(int), 0, ny - 1)
        dens[tid] = np.bincount(iy * nx + ix, ln, minlength=nx * ny)
    problems, report, inked = [], {'dense': {}, 'touch': {}}, {}
    at = lambda ij: (round(float(x0 + (ij[1] + 0.5) * px), 1), round(float(y0 + (ij[0] + 0.5) * px), 1))
    kernels = {}

    def disc(r):
        if r not in kernels:
            k, cnt = _disc((ny, nx), r / px)
            kernels[r] = np.fft.rfft2(k), cnt
        return kernels[r]
    for tid, d in dens.items():
        t = tools[tid]
        f = np.fft.rfft2(d.reshape(ny, nx))
        k, cnt = disc(t.width)
        load = np.fft.irfft2(f * k, s=(ny, nx)) * t.width / (cnt * px * px)   # layers of ink, over a disc a width across
        k, _ = disc(t.width / 2)
        inked[tid] = np.fft.irfft2(f * k, s=(ny, nx)) > px / 8               # its ink, out to half its width
        spots = _spots(load > DENSE, px, SPOT * t.width ** 2)
        if spots:
            area = sum(a for a, _ in spots)
            report['dense'][tid] = {'area': round(area, 2), 'spots': len(spots), 'max': round(float(load.max()), 1),
                                    'at': at(spots[0][1])}
            problems.append(f'ink: {tid} puts over {DENSE:g} layers of ink on {area:.1f} mm² ({len(spots)} spot'
                            f'{"s" if len(spots) > 1 else ""}, up to {load.max():.0f}; the biggest at '
                            f'{at(spots[0][1])}): the paper soaks and tears there')
    ids = list(inked)
    for a in range(len(ids)):
        for b in range(a + 1, len(ids)):
            ta, tb = tools[ids[a]], tools[ids[b]]
            if under is not None and (under(ta, tb) or under(tb, ta)):
                continue
            both = inked[ids[a]] & inked[ids[b]]
            spots = _spots(both, px, (min(ta.width, tb.width) / 2) ** 2)
            if spots:
                area = sum(s for s, _ in spots)
                report['touch'][f'{ids[a]}+{ids[b]}'] = {'area': round(area, 3), 'spots': len(spots),
                                                         'at': at(spots[0][1])}
                problems.append(f'ink: {ids[a]} and {ids[b]} run together on {area:.2f} mm² ({len(spots)} spot'
                                f'{"s" if len(spots) > 1 else ""}, the biggest at {at(spots[0][1])})')
    return problems, report
