# Limn plot - cutting a shape's outline into pieces, to draw each with its own tool
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# A cut is where along one of the shape's paths (its index k) the outline is
# cut, as a fraction t of that path's length: the drawing's units don't matter,
# nor its scale. The pieces between the cuts are painted apart (job.ShapePaint
# segments), each by a key "k@t", t where it starts: a new cut elsewhere leaves
# a piece's key, and so its tool, as it was. A closed path needs two cuts to
# come apart; one only opens it there. The fill isn't cut.
import numpy as np

ROUND = 4           # a fraction's digits: 1e-4 of the path


def key(k, t):
    return f'{k}@{t:.{ROUND}f}'


def _arc(pts):
    return np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])


def _between(pts, cum, s0, s1):
    '''The polyline from arc length s0 to s1 (s0 < s1 <= its length).'''
    def at(s):
        i = min(max(int(np.searchsorted(cum, s, side='right')) - 1, 0), len(pts) - 2)
        d = cum[i + 1] - cum[i]
        return pts[i] + (pts[i + 1] - pts[i]) * ((s - cum[i]) / d if d > 0 else 0)
    inner = pts[(cum > s0) & (cum < s1)]
    return np.vstack([at(s0), inner, at(s1)])


def pieces(path, closed, ts):
    '''The path cut at the fractions ts -> [(start fraction, (n, 2) points)].
    Without a cut: the path whole (closed: round, back to its start).'''
    pts = np.vstack([path, path[:1]]) if closed else np.asarray(path, float)
    cum = _arc(pts)
    length = cum[-1]
    ts = sorted({round(float(t), ROUND) for t in ts if 0 <= t < 1 and (closed or t > 0)})
    if length <= 0 or not ts:
        return [(0.0, pts)]
    if not closed:
        bounds = [0.0] + ts + [1.0]
        return [(a, _between(pts, cum, a * length, b * length)) for a, b in zip(bounds, bounds[1:]) if b > a]
    out = []
    for a, b in zip(ts, ts[1:] + [ts[0] + 1]):
        if b <= 1:
            out.append((a, _between(pts, cum, a * length, b * length)))
        else:                                   # round past the start
            first = _between(pts, cum, a * length, length) if a < 1 else pts[-1:]
            out.append((a, np.vstack([first, _between(pts, cum, 0, (b - 1) * length)[1:]])))
    return out


def nearest(paths, closed, p):
    '''Where on the paths point p is nearest -> (k, t, distance).'''
    best = (None, 0.0, np.inf)
    p = np.asarray(p, float)
    for k, (path, c) in enumerate(zip(paths, closed)):
        pts = np.vstack([path, path[:1]]) if c else np.asarray(path, float)
        if len(pts) < 2:
            continue
        a, b = pts[:-1], pts[1:]
        ab = b - a
        L2 = (ab ** 2).sum(axis=1)
        u = np.clip(((p - a) * ab).sum(axis=1) / np.where(L2 > 0, L2, 1), 0, 1)
        q = a + ab * u[:, None]
        d = np.linalg.norm(q - p, axis=1)
        i = int(np.argmin(d))
        if d[i] < best[2]:
            cum = _arc(pts)
            best = (k, float((cum[i] + u[i] * np.sqrt(L2[i])) / cum[-1]) if cum[-1] > 0 else 0.0, float(d[i]))
    return best


def point(path, closed, t):
    '''The point at fraction t along the path.'''
    pts = np.vstack([path, path[:1]]) if closed else np.asarray(path, float)
    cum = _arc(pts)
    return _between(pts, cum, 0, max(t * cum[-1], 1e-12))[-1] if cum[-1] > 0 else pts[0]
