# Limn cam - plane to image: homographies
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# The paper is a plane: a homography takes its mm (machine X, Y) to image
# pixels, whatever the camera. Fitted from four points or more (normalised DLT).
import numpy as np


def _normalise(pts):
    pts = np.asarray(pts, float)
    c = pts.mean(axis=0)
    s = np.sqrt(2) / max(np.linalg.norm(pts - c, axis=1).mean(), 1e-12)
    return np.array([[s, 0, -s * c[0]], [0, s, -s * c[1]], [0, 0, 1]])


class Homography:
    def __init__(self, m):
        self.m = np.asarray(m, float) / m[2][2]

    @classmethod
    def fit(cls, src, dst):
        '''src -> dst, from 4 or more point pairs (least squares beyond 4).'''
        src, dst = np.asarray(src, float), np.asarray(dst, float)
        if len(src) < 4 or len(src) != len(dst):
            raise ValueError('a homography needs 4 point pairs or more')
        ts, td = _normalise(src), _normalise(dst)
        s = (ts @ np.column_stack([src, np.ones(len(src))]).T).T
        d = (td @ np.column_stack([dst, np.ones(len(dst))]).T).T
        rows = []
        for (x, y, _), (u, v, _) in zip(s, d):
            rows.append([-x, -y, -1, 0, 0, 0, u * x, u * y, u])
            rows.append([0, 0, 0, -x, -y, -1, v * x, v * y, v])
        _, _, vt = np.linalg.svd(np.asarray(rows))
        h = vt[-1].reshape(3, 3)
        return cls(np.linalg.inv(td) @ h @ ts)

    def __call__(self, pts):
        pts = np.asarray(pts, float)
        one = pts.ndim == 1
        p = np.atleast_2d(pts)
        q = (self.m @ np.column_stack([p, np.ones(len(p))]).T).T
        out = q[:, :2] / q[:, 2:3]
        return out[0] if one else out

    def inverse(self):
        return Homography(np.linalg.inv(self.m))

    def scale(self, at):
        '''Pixels per mm around `at` (mm), the mean of both axes.'''
        a = self([at, (at[0] + 1, at[1]), (at[0], at[1] + 1)])
        return float((np.linalg.norm(a[1] - a[0]) + np.linalg.norm(a[2] - a[0])) / 2)

    def orientation(self, at):
        '''+1 when it keeps the handedness around `at`, -1 when it mirrors.'''
        a = self([at, (at[0] + 1, at[1]), (at[0], at[1] + 1)])
        u, v = a[1] - a[0], a[2] - a[0]
        return 1 if u[0] * v[1] - u[1] * v[0] > 0 else -1

    def error(self, src, dst):
        return np.linalg.norm(self(src) - np.asarray(dst, float), axis=1)

    def to_list(self):
        return self.m.tolist()
