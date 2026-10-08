# Limn plot - the order paths are drawn in
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Nearest next: from where the tool is, the closest end of any path left,
# drawn from that end. Then 2-opt (improve): reversing a run of paths, each
# drawn the other way round, while that shortens the travels, for as long as
# the time budget allows. Closed paths start at their vertex nearest the tool.
# Many paths (a dithered picture: tens of thousands of dashes) look for the
# nearest end in a grid of buckets around the tool instead of all of them.
import math
import time
from collections import defaultdict

import numpy as np

GRID = 2000         # more paths than this: the nearest end from a grid of buckets


def _closed(p):
    if len(p) <= 3:
        return False
    (x0, y0), (x1, y1) = p[0, :2].tolist(), p[-1, :2].tolist()      # np.allclose, without its cost
    return abs(x0 - x1) <= 1e-8 + 1e-5 * abs(x1) and abs(y0 - y1) <= 1e-8 + 1e-5 * abs(y1)


def _rotate(p, pos):
    k = int(np.argmin(np.hypot(*(p[:-1, :2] - pos).T)))
    return p if k == 0 else np.vstack([p[k:-1], p[:k], p[k:k + 1]])


def order(paths, start=(0, 0)):
    paths = [np.asarray(p, float) for p in paths if len(p)]
    n = len(paths)
    if not n:
        return []
    starts = np.array([p[0, :2] for p in paths])
    ends = np.array([p[-1, :2] for p in paths])
    closed = [_closed(p) for p in paths]
    alive = np.ones(n, bool)
    pos = np.asarray(start[:2], float)
    out = []
    nearest = _grid(starts, ends, alive) if n > GRID else None
    for _ in range(n):
        if nearest is not None:
            i, rev = nearest(pos)
            p = paths[i][::-1] if rev else paths[i]
            if closed[i]:
                p = _rotate(p, pos)
            alive[i] = False
            out.append(p)
            pos = p[-1, :2]
            continue
        ds = np.hypot(*(starts - pos).T)
        de = np.hypot(*(ends - pos).T)
        ds[~alive] = np.inf
        de[~alive] = np.inf
        i = int(np.argmin(np.minimum(ds, de)))
        p = paths[i][::-1] if de[i] < ds[i] else paths[i]
        if closed[i]:
            p = _rotate(p, pos)
        alive[i] = False
        out.append(p)
        pos = p[-1, :2]
    return out


def _grid(starts, ends, alive):
    '''nearest(pos) -> (path, from its end): the nearest end of a path still alive, from
    buckets about one path apart, looking in rings around pos until no ring can be nearer.'''
    n = len(starts)
    pts = np.vstack([starts, ends])
    lo = pts.min(axis=0)
    span = max(float(np.ptp(pts, axis=0).max()), 1e-6)
    h = span / math.sqrt(n)
    cells = np.floor((pts - lo) / h).astype(int)
    hi = cells.max(axis=0)
    grid = defaultdict(list)
    for k, (cx, cy) in enumerate(cells.tolist()):
        grid[(cx, cy)].append(k)

    def ring(cx, cy, r):
        if r == 0:
            yield cx, cy
            return
        for x in range(cx - r, cx + r + 1):
            yield x, cy - r
            yield x, cy + r
        for y in range(cy - r + 1, cy + r):
            yield cx - r, y
            yield cx + r, y

    def nearest(pos):
        cx, cy = (int(math.floor(v)) for v in (pos - lo) / h)
        far = max(abs(cx), abs(cy), abs(cx - hi[0]), abs(cy - hi[1])) + 1
        best, bk = math.inf, -1
        for r in range(far + 1):
            for c in ring(cx, cy, r):
                ks = grid.get(c)
                if not ks:
                    continue
                live = [k for k in ks if alive[k % n]]
                if len(live) < len(ks):
                    grid[c] = live              # the dead go as they are met
                for k in live:
                    d = math.hypot(pts[k, 0] - pos[0], pts[k, 1] - pos[1])
                    if d < best:
                        best, bk = d, k
            if bk >= 0 and best <= r * h:       # nothing in a further ring can be nearer
                break
        return bk % n, bk >= n
    return nearest


def improve(paths, start=(0, 0), budget=1.0):
    '''2-opt on an order of paths: shorter travels, within `budget` seconds.'''
    n = len(paths)
    if n < 3 or budget <= 0:
        return paths
    paths = list(paths)
    S = np.array([p[0, :2] for p in paths])
    E = np.array([p[-1, :2] for p in paths])
    flip = np.zeros(n, bool)
    home = np.asarray(start[:2], float)
    dist = lambda a, b: np.hypot(*(a - b).T)
    deadline = time.monotonic() + budget
    better = True
    while better and time.monotonic() < deadline:
        better = False
        for i in range(-1, n - 2):
            # Reverse positions i+1..j: edges (i, i+1) and (j, j+1) become (i, j) and (i+1, j+1)
            a = home if i < 0 else E[i]
            js = np.arange(i + 2, n)
            old = dist(a, S[i + 1]) + np.append(dist(E[js[:-1]], S[js[:-1] + 1]), 0.0)
            new = dist(a, E[js]) + np.append(dist(S[i + 1], S[js[:-1] + 1]), 0.0)
            gain = old - new
            k = int(np.argmax(gain))
            if gain[k] > 1e-6:
                j = js[k]
                seg = slice(i + 1, j + 1)
                S[seg], E[seg] = E[seg][::-1].copy(), S[seg][::-1].copy()
                flip[seg] = ~flip[seg][::-1]
                paths[seg] = paths[seg][::-1]
                better = True
            if time.monotonic() > deadline:
                break
    out, pos = [], home
    for p, f in zip(paths, flip):
        p = p[::-1] if f else p
        if _closed(p):
            p = _rotate(p, pos)
        out.append(p)
        pos = p[-1, :2]
    return out


def join(paths, tol=0.01, link=0.0):
    '''Merge paths that start where the one before ends; within `link`, the tool stays
    down across the gap (too small to see: the ink closes it anyway).'''
    out = []
    for p in paths:
        if out:
            gap = np.abs(out[-1][-1] - p[0])
            if np.all(gap <= tol):
                out[-1] = np.vstack([out[-1], p[1:]])
                continue
            if link and np.hypot(*gap[:2]) <= link and gap[2:].max(initial=0) <= tol:
                out[-1] = np.vstack([out[-1], p])
                continue
        out.append(p)
    return out


def length(paths):
    return float(sum(np.hypot(*np.diff(p[:, :2], axis=0).T).sum() for p in paths))
