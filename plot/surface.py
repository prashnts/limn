# Limn plot - what an object is drawn on
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# A surface takes the flat drawing (object mm, y up) onto itself: drape()
# gives each point the height of the surface under it, and adds points so the
# tool follows it between them. max_along() is what travels over it clear.
# Surfaces move with their object: sliced paths keep their z when placed.
#
# Flat: paper. Heightmap: a grid of heights, the drawing projected straight
# down onto a flat-ish object. A UV surface (a mesh and its unwrap, the
# drawing in texture space) goes here with the same two methods.
import math
from pathlib import Path

import numpy as np
from shapely.geometry import box


class Flat:
    max_z = 0.0
    footprint = None

    def drape(self, pts):
        pts = np.asarray(pts, float)
        return np.column_stack([pts[:, :2], np.zeros(len(pts))])

    def max_along(self, a, b):
        return 0.0


class Heightmap:
    def __init__(self, z, origin=(0, 0), pitch=1.0):
        self.z = np.asarray(z, float)      # rows along y, from origin[1]
        self.origin = np.asarray(origin, float)
        self.pitch = float(pitch)
        ny, nx = self.z.shape
        self.max_z = float(self.z.max())
        self.footprint = box(*self.origin, *(self.origin + ((nx - 1) * pitch, (ny - 1) * pitch)))

    @classmethod
    def load(cls, path, origin=(0, 0), pitch=1.0):
        path = Path(path)
        z = np.load(path) if path.suffix == '.npy' else np.loadtxt(path, delimiter=',')
        return cls(z, origin, pitch)

    def height(self, xy):
        xy = np.atleast_2d(np.asarray(xy, float))[:, :2]
        g = (xy - self.origin) / self.pitch
        ny, nx = self.z.shape
        inside = (g[:, 0] >= 0) & (g[:, 1] >= 0) & (g[:, 0] <= nx - 1) & (g[:, 1] <= ny - 1)
        gx = np.clip(g[:, 0], 0, nx - 1)
        gy = np.clip(g[:, 1], 0, ny - 1)
        x0 = np.minimum(gx.astype(int), nx - 2) if nx > 1 else np.zeros(len(gx), int)
        y0 = np.minimum(gy.astype(int), ny - 2) if ny > 1 else np.zeros(len(gy), int)
        fx, fy = gx - x0, gy - y0
        x1, y1 = np.minimum(x0 + 1, nx - 1), np.minimum(y0 + 1, ny - 1)
        z = (self.z[y0, x0] * (1 - fx) * (1 - fy) + self.z[y0, x1] * fx * (1 - fy)
             + self.z[y1, x0] * (1 - fx) * fy + self.z[y1, x1] * fx * fy)
        return np.where(inside, z, 0.0)

    def _densify(self, pts):
        step = self.pitch / 2
        out = [pts[:1]]
        for a, b in zip(pts[:-1], pts[1:]):
            n = max(1, math.ceil(math.dist(a, b) / step))
            t = np.linspace(0, 1, n + 1)[1:, None]
            out.append(a + (b - a) * t)
        return np.vstack(out)

    def drape(self, pts):
        pts = self._densify(np.asarray(pts, float)[:, :2])
        return np.column_stack([pts, self.height(pts)])

    def max_along(self, a, b):
        return float(self.height(self._densify(np.array([a[:2], b[:2]], float))).max())


def make(spec, root=Path('.')):
    if spec is None or spec.kind == 'flat':
        return Flat()
    if spec.kind == 'heightmap':
        return Heightmap.load(root / spec.path, spec.origin, spec.pitch)
    raise ValueError(f'no surface kind {spec.kind!r}')
