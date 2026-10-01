# Limn cam - images as numpy arrays: ink between two shots, sampling
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Ink is what got darker between a shot before and one after, each divided by
# its own local brightness first: the light may change between the shots (and
# the paper's shading along with it), a pen line doesn't care.
from pathlib import Path

import numpy as np
from PIL import Image

DARK = 0.12                 # local brightness under which a pixel tells nothing


def load(src):
    '''A path, bytes, a PIL image or an array -> float gray 0..1, (h, w).'''
    if isinstance(src, np.ndarray):
        a = src.astype(float)
        if a.ndim == 3:
            a = a[..., :3] @ [0.299, 0.587, 0.114]
        return a / 255.0 if a.max() > 1.5 else a
    if isinstance(src, (bytes, bytearray)):
        import io
        src = Image.open(io.BytesIO(src))
    elif isinstance(src, (str, Path)):
        src = Image.open(src)
    return np.asarray(src.convert('L'), float) / 255.0


def box_blur(a, r):
    '''Mean over a (2r+1)^2 box, edges clamped (integral image).'''
    r = max(int(r), 1)
    p = np.pad(a, r + 1, mode='edge')
    s = p.cumsum(0).cumsum(1)
    k = 2 * r + 1
    out = s[k:, k:] - s[:-k, k:] - s[k:, :-k] + s[:-k, :-k]
    return out[:a.shape[0], :a.shape[1]] / (k * k)


def change(before, after, radius=12):
    '''How much darker `after` is than `before` (lighter: negative), as a fraction
    of the local brightness: ~0.1 for a fine line seen from afar.'''
    b, a = load(before), load(after)
    if b.shape != a.shape:
        raise ValueError(f'the shots differ in size: {b.shape} and {a.shape}')
    lb, la = box_blur(b, radius), box_blur(a, radius)
    c = b / np.maximum(lb, 1e-3) - a / np.maximum(la, 1e-3)
    c[np.minimum(lb, la) < DARK] = 0          # the lens's black ring, shadows: nothing to tell there
    return c


def ink(before, after, radius=12):
    '''change(), 0 where nothing got darker.'''
    return np.clip(change(before, after, radius), 0, None)


def noise(c):
    '''A robust sigma of a change() map: most of it is no change (0: too dark to tell).'''
    v = c[c != 0]
    if not v.size:
        return 1e-6
    return float(1.4826 * np.median(np.abs(v - np.median(v))) + 1e-6)


def sample(a, pts):
    '''Bilinear values of `a` at (x, y) pixel points, 0 outside.'''
    pts = np.atleast_2d(np.asarray(pts, float))
    h, w = a.shape
    x, y = pts[:, 0], pts[:, 1]
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = x - x0, y - y0
    out = np.zeros(len(pts))
    ok = (x0 >= 0) & (y0 >= 0) & (x0 < w - 1) & (y0 < h - 1)
    x0, y0, fx, fy = x0[ok], y0[ok], fx[ok], fy[ok]
    out[ok] = (a[y0, x0] * (1 - fx) * (1 - fy) + a[y0, x0 + 1] * fx * (1 - fy)
               + a[y0 + 1, x0] * (1 - fx) * fy + a[y0 + 1, x0 + 1] * fx * fy)
    return out


def paper(img, backend=None):
    '''Where the paper is: the largest bright and smooth region -> (x0, y0, x1, y1)
    pixels, None when nothing looks like it. The rest of a shot changes between
    two (lights, reflections, the machine), the paper only by the ink.'''
    from .backend import get
    a = load(img)
    m = box_blur(a, 8)
    sd = np.sqrt(np.maximum(box_blur(a * a, 8) - m * m, 0))
    top = np.percentile(m, 99.5)
    for level in (0.8, 0.75, 0.7):
        mask = (m > level * top) & (sd < 0.08)     # drawn lines are texture too: a full sheet still counts
        blobs = (backend or get()).components(mask, mask.astype(float))
        if not blobs:
            continue
        b = max(blobs, key=lambda b: b.area)
        x0, y0, x1, y1 = b.box
        if b.area > 0.01 * a.size and b.area > 0.5 * (x1 - x0 + 1) * (y1 - y0 + 1):    # a filled rectangle
            return b.box
    return None
