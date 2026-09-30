# Limn cam - stitching a scan's tiles into one picture
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Every tile knows where the camera was sent (meta.json), and the camera's
# `fov` and `turn`. Stood upright (image x along +X, its y down along -Y), the
# tiles would join where they were sent, but the carriage lands a little off
# (the belts, the Z play, the tether). So each pair of neighbours is compared
# where they overlap (phase correlation): how far the second sits from where it
# should, against the first. A least squares over every pair puts each tile
# where they agree (the first stays), pairs that disagree too much or match too
# weakly left out. Then they are drawn at the resolution asked for, each seam
# a cross-fade over the overlap.
import json
import math

import numpy as np
from PIL import Image

from .image import load

REGISTER_PPM = 25.0         # px/mm the overlaps are compared at: quick, and good to ~0.05mm
MAX_OFF = 1.5               # mm: a pair further off than this doesn't count
MIN_PEAK = 0.04             # a weaker match doesn't count
MAX_MP = 90                 # megapixels a stitch may take: the Pi's memory


def _axes(fov, turn):
    '''The shot's mm along X and Y once upright: swapped for an odd quarter turn
    (by the nearest one: a camera 0.8 degree askew is still upside down, not sideways).'''
    return tuple(fov[::-1]) if round(turn / 90) % 2 else tuple(fov)


def upright(im, turn):
    '''The tile turned so its x runs along +X (PIL turns counter-clockwise): quarter
    turns exactly, what is left over (the camera mounted a little askew, eg. -179.2)
    about the middle, the size kept.'''
    k = round(turn / 90) % 4
    if k:
        im = im.transpose([None, Image.Transpose.ROTATE_90, Image.Transpose.ROTATE_180, Image.Transpose.ROTATE_270][k])
    rest = turn - round(turn / 90) * 90
    if abs(rest) > 0.05:
        im = im.rotate(rest, resample=Image.BICUBIC, expand=False)
    return im


def flat_field(images, size=(96, 54)):
    '''How the light falls off across a shot (vignetting), from many shots of
    different things: their median, smoothed, 1 at its brightest -> (h, w, 3), or None.'''
    if len(images) < 4:
        return None
    small = np.stack([np.asarray(im.convert('RGB').resize(size, Image.BILINEAR), np.float32) for im in images])
    med = np.median(small, axis=0)
    from .image import box_blur
    med = np.stack([box_blur(med[..., c], 6) for c in range(3)], axis=-1)
    return med / max(med.max(), 1e-3)


def flatten(im, flat):
    '''The shot divided by the light's fall-off.'''
    if flat is None:
        return im
    f = np.asarray(Image.fromarray((flat * 255).astype(np.uint8)).resize(im.size, Image.BILINEAR), np.float32) / 255
    a = np.asarray(im.convert('RGB'), np.float32) / np.maximum(f, 0.2)
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def _corr(a, b):
    '''b's content moved from a's -> (dx, dy, peak): pixels, and how clear the match is.'''
    win = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1]))
    fa, fb = np.fft.fft2((a - a.mean()) * win), np.fft.fft2((b - b.mean()) * win)
    x = fb * np.conj(fa)
    r = np.fft.ifft2(x / (np.abs(x) + 1e-9)).real
    iy, ix = np.unravel_index(np.argmax(r), r.shape)
    h, w = r.shape

    def sub(c, m, n):
        if not 0 < c < n - 1:
            return 0.0
        d = m[c - 1] - 2 * m[c] + m[c + 1]
        return 0.5 * (m[c - 1] - m[c + 1]) / d if d else 0.0
    dx, dy = ix + sub(ix, r[iy, :], w), iy + sub(iy, r[:, ix], h)
    return (dx - w if dx > w / 2 else dx), (dy - h if dy > h / 2 else dy), float(r[iy, ix])


def _neighbours(tiles):
    at = {(t['row'], t['col']): i for i, t in enumerate(tiles) if 'row' in t}
    for (r, c), i in at.items():
        for nb in ((r, c + 1), (r + 1, c)):
            if nb in at:
                yield i, at[nb]


def register(tiles, load_image, fov, turn, ppm=REGISTER_PPM):
    '''Where each tile really is -> ([(x, y) mm], [pair]). tiles: meta.json's,
    load_image(file) -> PIL image. pair: {a, b, off (mm), peak, used}.'''
    fx, fy = _axes(fov, turn)
    size = (max(8, round(fx * ppm)), max(8, round(fy * ppm)))
    imgs = {}

    def gray(i):
        if i not in imgs:
            imgs[i] = load(upright(load_image(tiles[i]['file']), turn).resize(size))
        return imgs[i]

    pairs, eqs = [], []
    for a, b in _neighbours(tiles):
        ta, tb = tiles[a], tiles[b]
        # The overlap, mm, where they were sent
        x0 = max(ta['x'], tb['x']) - fx / 2
        x1 = min(ta['x'], tb['x']) + fx / 2
        y0 = max(ta['y'], tb['y']) - fy / 2
        y1 = min(ta['y'], tb['y']) + fy / 2
        if x1 - x0 < 1 or y1 - y0 < 1:
            continue

        def crop(t, img):
            u0, u1 = (x0 - (t['x'] - fx / 2)) * ppm, (x1 - (t['x'] - fx / 2)) * ppm
            v0, v1 = ((t['y'] + fy / 2) - y1) * ppm, ((t['y'] + fy / 2) - y0) * ppm
            return img[int(round(v0)):int(round(v1)), int(round(u0)):int(round(u1))]
        ca, cb = crop(ta, gray(a)), crop(tb, gray(b))
        h, w = min(ca.shape[0], cb.shape[0]), min(ca.shape[1], cb.shape[1])
        if h < 8 or w < 8:
            continue
        dx, dy, peak = _corr(ca[:h, :w], cb[:h, :w])
        off = (-dx / ppm, dy / ppm)         # b's content moved (dx, dy): b was (-dx, +dy)/ppm off, x, y
        used = peak >= MIN_PEAK and math.hypot(*off) <= MAX_OFF
        pairs.append({'a': a, 'b': b, 'off': [round(off[0], 3), round(off[1], 3)], 'peak': round(peak, 3), 'used': used})
        if used:
            eqs.append((a, b, off, peak))
    n = len(tiles)
    err = np.zeros((n, 2))
    if eqs:
        # e_b - e_a = off, weighted by the match; e_0 = 0
        A = np.zeros((len(eqs) + 1, n))
        B = np.zeros((len(eqs) + 1, 2))
        for k, (a, b, off, peak) in enumerate(eqs):
            A[k, a], A[k, b] = -peak, peak
            B[k] = np.array(off) * peak
        A[-1, 0] = 1.0
        err = np.linalg.lstsq(A, B, rcond=None)[0]
        # Tiles no pair reached keep where they were sent
        seen = {0} | {a for a, *_ in eqs} | {b for _, b, *_ in eqs}
        for i in range(n):
            if i not in seen:
                err[i] = 0
    return [(t['x'] + float(e[0]), t['y'] + float(e[1])) for t, e in zip(tiles, err)], pairs


def _feather(w, h, ramps):
    '''An L mask, 255 inside, falling to 0 over `ramps` px at each edge (left, top, right, bottom).'''
    m = np.ones((h, w), np.float32)
    left, top, right, bottom = ramps
    if left:
        m[:, :left] *= np.linspace(0, 1, left, endpoint=False)[None, :]
    if right:
        m[:, w - right:] *= np.linspace(1, 0, right, endpoint=False)[None, :]
    if top:
        m[:top, :] *= np.linspace(0, 1, top, endpoint=False)[:, None]
    if bottom:
        m[h - bottom:, :] *= np.linspace(1, 0, bottom, endpoint=False)[:, None]
    return Image.fromarray((m * 255).astype(np.uint8), 'L')


def size_at(tiles, fov, turn, ppm, positions=None):
    fx, fy = _axes(fov, turn)
    pos = positions or [(t['x'], t['y']) for t in tiles]
    xs, ys = [p[0] for p in pos], [p[1] for p in pos]
    return (int(round((max(xs) - min(xs) + fx) * ppm)), int(round((max(ys) - min(ys) + fy) * ppm)))


def compose(tiles, load_image, fov, turn, ppm, positions=None, max_mp=MAX_MP, flat=None):
    '''The tiles as one picture at `ppm` px/mm, where `positions` put them (default:
    where they were sent), each seam faded over its overlap -> (image, (x0, y0, x1, y1) mm).'''
    fx, fy = _axes(fov, turn)
    pos = positions or [(t['x'], t['y']) for t in tiles]
    W, H = size_at(tiles, fov, turn, ppm, pos)
    if W * H > max_mp * 1e6:
        full = W * H / 1e6
        raise ValueError(f'{full:.0f} megapixels at {ppm:g} px/mm, more than {max_mp}: '
                         f'try {ppm * math.sqrt(max_mp / full):.0f} px/mm or less')
    x0 = min(p[0] for p in pos) - fx / 2
    y1 = max(p[1] for p in pos) + fy / 2
    canvas = Image.new('RGB', (W, H), 'black')
    tw, th = max(1, int(round(fx * ppm))), max(1, int(round(fy * ppm)))
    placed = []                             # mm boxes already drawn
    for t, (x, y) in zip(tiles, pos):
        box = (x - fx / 2, y - fy / 2, x + fx / 2, y + fy / 2)
        # Fade in over whatever of the neighbours is already there, on each side
        ramps = [0, 0, 0, 0]                 # left (-X), top (+Y), right (+X), bottom (-Y), px
        for b in placed:
            ox = min(box[2], b[2]) - max(box[0], b[0])
            oy = min(box[3], b[3]) - max(box[1], b[1])
            if ox <= 0 or oy <= 0:
                continue
            if b[0] < box[0] and ox < fx * 0.9:
                ramps[0] = max(ramps[0], int(ox * ppm))
            if b[2] > box[2] and ox < fx * 0.9:
                ramps[2] = max(ramps[2], int(ox * ppm))
            if b[3] > box[3] and oy < fy * 0.9:
                ramps[1] = max(ramps[1], int(oy * ppm))
            if b[1] < box[1] and oy < fy * 0.9:
                ramps[3] = max(ramps[3], int(oy * ppm))
        im = upright(flatten(load_image(t['file']).convert('RGB'), flat), turn).resize((tw, th), Image.LANCZOS)
        left = int(round((box[0] - x0) * ppm))
        top = int(round((y1 - box[3]) * ppm))
        canvas.paste(im, (left, top), _feather(tw, th, ramps))
        placed.append(box)
    return canvas, (x0, y1 - H / ppm, x0 + W / ppm, y1)


def info(store, sid, ppm=None):
    '''Where the scan's tiles really are (registered, kept in stitch.json) and, with
    `ppm`, how big a stitch would be -> {used, of, moved_max, extent, width, height, mp}.'''
    d = store.dir(sid)
    meta = store.meta(sid)
    tiles = meta.get('tiles') or []
    if not tiles:
        raise KeyError('no tiles yet')
    fov, turn = meta['fov'], meta.get('turn', 0.0)
    got = _registered(d, tiles, fov, turn)
    fx, fy = _axes(fov, turn)
    xs, ys = [p[0] for p in got['positions']], [p[1] for p in got['positions']]
    out = {k: got[k] for k in ('used', 'of', 'moved_max')}
    out['extent'] = [min(xs) - fx / 2, min(ys) - fy / 2, max(xs) + fx / 2, max(ys) + fy / 2]
    out['native_ppm'] = round(max(Image.open(d / tiles[0]['file']).size) / max(fov), 1)
    if ppm:
        w, h = size_at(tiles, fov, turn, ppm, got['positions'])
        out.update(width=w, height=h, mp=round(w * h / 1e6, 1), px_per_mm=ppm, too_big=w * h > MAX_MP * 1e6)
    return out


def _registered(d, tiles, fov, turn, refine=True):
    info_path = d / 'stitch.json'
    if info_path.exists() and info_path.stat().st_mtime >= (d / 'meta.json').stat().st_mtime:
        return json.loads(info_path.read_text())
    load_image = lambda f: Image.open(d / f)
    if refine and len(tiles) > 1:
        positions, pairs = register(tiles, load_image, fov, turn)
    else:
        positions, pairs = [(t['x'], t['y']) for t in tiles], []
    used = [p for p in pairs if p['used']]
    got = {'positions': positions, 'pairs': pairs, 'used': len(used), 'of': len(pairs),
           'moved_max': round(max((math.hypot(px - t['x'], py - t['y']) for t, (px, py) in zip(tiles, positions)),
                                  default=0.0), 3)}
    info_path.write_text(json.dumps(got))
    return got


def stitch(store, sid, ppm, refine=True):
    '''The scan `sid` stitched at `ppm` px/mm, kept in its folder -> (path, info).'''
    d = store.dir(sid)
    meta = store.meta(sid)
    tiles = meta.get('tiles') or []
    if not tiles:
        raise KeyError('no tiles yet')
    out = d / f'stitch-{ppm:g}.jpg'
    info_path = d / 'stitch.json'
    fresh = lambda p: p.exists() and p.stat().st_mtime >= (d / 'meta.json').stat().st_mtime
    load_image = lambda f: Image.open(d / f)
    fov, turn = meta['fov'], meta.get('turn', 0.0)
    if fresh(info_path):
        info = json.loads(info_path.read_text())
    else:
        if refine and len(tiles) > 1:
            positions, pairs = register(tiles, load_image, fov, turn)
        else:
            positions, pairs = [(t['x'], t['y']) for t in tiles], []
        used = [p for p in pairs if p['used']]
        info = {'positions': positions, 'pairs': pairs, 'used': len(used), 'of': len(pairs),
                'moved_max': round(max((math.hypot(px - t['x'], py - t['y']) for t, (px, py) in zip(tiles, positions)),
                                       default=0.0), 3)}
        info_path.write_text(json.dumps(info))
    if not fresh(out):
        flat = flat_field([load_image(t['file']) for t in tiles[:40]])
        img, extent = compose(tiles, load_image, fov, turn, ppm, info['positions'], flat=flat)
        img.save(out, quality=92)
    w, h = Image.open(out).size
    return out, {**{k: info[k] for k in ('used', 'of', 'moved_max')}, 'width': w, 'height': h, 'px_per_mm': ppm}
