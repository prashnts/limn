# Limn cam - a light that flickers: finding its bands in a shot, and taking them out
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# The camera reads its rows one after the other (a rolling shutter). An LED
# that is dimmed by PWM, or run from a cheap driver, goes dark for a moment
# many times a second: the rows read then come out darker, in bands across the
# shot, a fixed number of rows apart. The brighter the scene, the shorter the
# exposure and the deeper and thinner the bands. Stitching can't take them out:
# they are in every tile, and two overlapping tiles have them in other places.
#
# The bands move from frame to frame (the light isn't in step with the camera),
# and they only ever darken. So a few frames of the same spot, the brightest of
# them at each pixel, leave them out. found() says whether a shot has bands;
# merged() takes the brightest of several. Measured on the U20CAM under the new
# light (2026-10-01): bands every 137 rows, 1.2 grey levels (11.7 on bright
# paper) -> 0.44 with 3 frames; shots under the camera's own light: 0.3-0.5. The real fix is at the light: full power, DC, or an exposure a
# whole number of its periods long.
import io

import numpy as np
from PIL import Image

MIN_RIPPLE = 0.8        # grey levels a row is off its neighbours, the median over the columns: less is noise
MIN_PEAK = 5.0          # how far the strongest period stands out of the rest


def _grey(img):
    if isinstance(img, (bytes, bytearray)):
        img = Image.open(io.BytesIO(img))
    return np.asarray(img.convert('L'), np.float32) if isinstance(img, Image.Image) else np.asarray(img, np.float32)


def rows(img, window=41, step=4):
    '''How much darker or brighter each row is than the rows around it, in grey
    levels: per column against its own neighbourhood, then the median over the
    columns. A band crosses every column; the picture's own edges only some.'''
    g = _grey(img)[:, ::step]
    lg = np.log(g + 1)
    k = min(window, len(g) // 2 * 2 - 1)
    c = np.cumsum(np.pad(lg, ((k // 2 + 1, k // 2), (0, 0)), mode='edge'), axis=0)
    local = (c[k:] - c[:-k]) / k
    return np.median(lg - local, axis=1) * float(np.median(g))


def bands(img, lo=12, hi=600):
    '''How banded a shot is -> {ripple: grey levels, period: rows, peak: how clear}.'''
    r = rows(img)
    r = r[len(r) // 20:-len(r) // 20 or None]          # the edges' trend is poor
    n = len(r)
    f = np.abs(np.fft.rfft((r - r.mean()) * np.hanning(n)))
    k0, k1 = max(2, n // hi), min(len(f) - 1, n // lo)
    if k1 <= k0 + 2:
        return {'ripple': 0.0, 'period': None, 'peak': 0.0}
    k = k0 + int(np.argmax(f[k0:k1]))
    return {'ripple': round(float(r.std()), 2), 'period': round(n / k, 1),
            'peak': round(float(f[k] / max(np.median(f[k0:k1]), 1e-9)), 1)}


def found(b):
    return b['ripple'] >= MIN_RIPPLE and b['peak'] >= MIN_PEAK


def merged(jpegs, quality=95):
    '''The brightest of several frames of one spot, at each pixel -> jpeg bytes.'''
    frames = [np.asarray(Image.open(io.BytesIO(j)).convert('RGB')) for j in jpegs]
    out = io.BytesIO()
    Image.fromarray(np.max(frames, axis=0)).save(out, 'JPEG', quality=quality)
    return out.getvalue()
