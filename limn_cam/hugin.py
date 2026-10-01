# Limn cam - stitching a scan with Hugin's tools (cpfind, autooptimiser, nona, enblend)
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# The camera moves over a flat bed at one height: a mosaic, so every tile is
# placed by a translation (Hugin's TrX, TrY), not turned like a panorama's.
# Hugin measures them on the image plane at distance 1: an image `hfov`
# degrees wide is 2 tan(hfov/2) across, so `unit` mm of the bed are one, TrX
# runs along the image's x and TrY down it. A tile goes in as it was shot,
# turned by its roll (r = -turn: the camera sits upside down), and starts where
# the camera was sent. Then:
#   cpfind --prealigned       features matched only where tiles overlap
#   autooptimiser -n          TrX, TrY of every tile but the first, and the lens's barrel (b)
#   cpclean -w -s             points that still disagree left out, then optimised again
#   vig_optimize              the light's fall-off over a shot
#   nona, enblend             each tile drawn where it belongs; enblend lays a seam
#                             between tiles instead of fading one into the other (no ghosts)
# The tools must be there: apt install hugin-tools enblend. The work files go in
# the scan's folder (RAM on the Pi) and are removed; the project (hugin.pto)
# stays, to open in Hugin.
import math
import re
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np
from PIL import Image

from .image import box_blur, load
from .stitch import flat_field

HFOV = 10.0                 # degrees given to a tile: any small angle, it only sets the units
MAX_OFF = 1.5               # mm a tile may end up from where it was sent: further, the match is wrong
PAIR_OFF = 1.0              # mm a pair's offset may differ from the moves' (the carriage lands ~0.6 off at worst)
MAX_MP = 90                 # megapixels a stitch may take: the Pi's memory
TOOLS = ('pto_gen', 'pto_var', 'cpfind', 'autooptimiser', 'pano_modify', 'nona', 'enblend')


def missing():
    '''Hugin's tools that aren't installed.'''
    return [t for t in TOOLS if shutil.which(t) is None]


def unit_mm(fov, hfov=HFOV):
    '''mm of the bed in one of Hugin's units, for a shot fov[0] mm wide.'''
    return fov[0] / (2 * math.tan(math.radians(hfov) / 2))


def flatten(im, flat):
    '''The shot divided by the light's fall-off, as bright on the whole.'''
    if flat is None:
        return im.convert('RGB')
    f = np.asarray(Image.fromarray((flat * 255).astype(np.uint8)).resize(im.size, Image.BILINEAR), np.float32)
    f = f / np.median(f, axis=(0, 1))
    a = np.asarray(im.convert('RGB'), np.float32) / np.maximum(f, 0.2)
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def enhance(src, dst, r=40):
    '''A grey copy for finding features: divided by its own blur (the light's
    fall-off and the paper's tint go), the contrast stretched.'''
    a = load(Image.open(src))
    k = 4
    bg = np.kron(box_blur(a[::k, ::k], max(1, r // k)), np.ones((k, k)))[:a.shape[0], :a.shape[1]]
    h = a / np.maximum(bg, 1e-3)
    lo, hi = np.percentile(h, (1, 99))
    Image.fromarray((np.clip((h - lo) / max(hi - lo, 1e-6), 0, 1) * 255).astype(np.uint8)).save(dst, quality=92)


def _run(args, cwd, log):
    t = time.time()
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    log(f'{args[0]}: {time.time() - t:.1f}s')
    if r.returncode:
        raise RuntimeError(f'{args[0]} failed: {(r.stderr or r.stdout).strip()[-400:]}')
    return r.stdout + r.stderr


def images(pto):
    '''The `i` lines of a project, as {key: value} (strings), in order.'''
    out = []
    for line in Path(pto).read_text().splitlines():
        if line.startswith('i '):
            out.append({m.group(1): m.group(2) for m in re.finditer(r'\b([a-zA-Z]+)(".*?"|\S+)', line[2:])})
    return out


def pano(pto):
    '''The `p` line: {w, h, v, S (crop)}.'''
    for line in Path(pto).read_text().splitlines():
        if line.startswith('p '):
            return {m.group(1): m.group(2) for m in re.finditer(r'\b([a-zA-Z]+)(".*?"|\S+)', line[2:])}
    raise ValueError('no p line')


def clean(src, dst, tol=12.0, least=4):
    '''Matches that agree, kept: the tiles only slide, so the points of one pair
    are all about as far apart. Those more than `tol` px from their pair's median
    go, and pairs with fewer than `least` left go whole (halftone repeats: a match
    one dot off). -> (points kept, {(a, b): median offset (px, image a minus image b)}).'''
    lines = Path(src).read_text().splitlines()
    pairs = {}
    for i, line in enumerate(lines):
        if line.startswith('c '):
            kv = {m.group(1): float(m.group(2)) for m in re.finditer(r'\b([a-zA-Z]+)(-?[0-9.e+-]+)', line[2:])}
            pairs.setdefault((int(kv['n']), int(kv['N'])), []).append((i, kv['x'] - kv['X'], kv['y'] - kv['Y']))
    drop, kept = set(), {}
    for k, v in pairs.items():
        a = np.array([(x, y) for _, x, y in v])
        bad = np.linalg.norm(a - np.median(a, axis=0), axis=1) > tol
        if (~bad).sum() < least:
            bad[:] = True
        else:
            kept[k] = tuple(np.median(a[~bad], axis=0))
        drop |= {v[j][0] for j in np.flatnonzero(bad)}
    Path(dst).write_text('\n'.join(l for i, l in enumerate(lines) if i not in drop) + '\n')
    return sum(1 for l in lines if l.startswith('c ')) - len(drop), kept


def similarity(pairs, tiles, turn):
    '''The camera's real scale and turn, from how far apart the matches put each
    pair against how far apart the camera was sent (its moves are right, on the
    whole) -> (px per mm, turn degrees), medians over the pairs. A point P shows
    at ppm R (P - C) in a shot taken from C, R turning bed mm (x right, y up) into
    image px (y down): so a pair's offset is ppm R (Cb - Ca).'''
    t = math.radians(turn)
    ex, ey = complex(math.cos(t), math.sin(t)), complex(math.sin(t), -math.cos(t))
    z = []
    for (a, b), (mx, my) in pairs.items():
        dx, dy = tiles[b]['x'] - tiles[a]['x'], tiles[b]['y'] - tiles[a]['y']
        n = dx * ex + dy * ey
        if abs(n) > 1e-6:
            z.append(complex(mx, my) / n)
    if not z:
        return None, turn
    return float(np.median(np.abs(z))), turn + math.degrees(float(np.median(np.angle(z))))


def plausible(pairs, tiles, ppm, turn, off=PAIR_OFF):
    '''The pairs whose offset is within `off` mm of what the moves make it.'''
    t = math.radians(turn)
    ex, ey = complex(math.cos(t), math.sin(t)), complex(math.sin(t), -math.cos(t))
    out = {}
    for (a, b), (mx, my) in pairs.items():
        n = (tiles[b]['x'] - tiles[a]['x']) * ex + (tiles[b]['y'] - tiles[a]['y']) * ey
        if abs(complex(mx, my) - ppm * n) / ppm <= off:
            out[(a, b)] = (mx, my)
    return out


def keep_pairs(src, dst, pairs):
    '''The project with only the control points of these pairs -> how many.'''
    out, n = [], 0
    for line in Path(src).read_text().splitlines():
        if line.startswith('c '):
            kv = dict(re.findall(r'\b([nN])(\d+)', line))
            if (int(kv['n']), int(kv['N'])) not in pairs:
                continue
            n += 1
        out.append(line)
    Path(dst).write_text('\n'.join(out) + '\n')
    return n


def anchors(n, pairs):
    '''The tiles to keep where they were sent: the first of each group the pairs
    join (tile 0 for its own), and every tile in no pair.'''
    parent = list(range(n))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for a, b in pairs:
        parent[root(a)] = root(b)
    groups = {}
    for i in range(n):
        groups.setdefault(root(i), []).append(i)
    return sorted(min(g) for g in groups.values())


def control_points(pto):
    return sum(1 for line in Path(pto).read_text().splitlines() if line.startswith('c '))


def done(store, sid, ppm):
    '''The stitch at ppm and its info if it is made and fresh, else None.'''
    import json
    d = store.dir(sid)
    out, js = d / f'hugin-{ppm:g}.jpg', d / 'hugin.json'
    if out.exists() and js.exists() and out.stat().st_mtime >= (d / 'meta.json').stat().st_mtime:
        info = json.loads(js.read_text())
        if info.get('px_per_mm') == ppm:
            return out, info
    return None


def stitch(store, sid, ppm, log=print, keep_work=False):
    '''The scan `sid` stitched by Hugin at `ppm` px/mm, kept in its folder as
    hugin-<ppm>.jpg -> (path, info).'''
    if missing():
        raise RuntimeError(f'Hugin\'s tools are missing ({", ".join(missing())}): apt install hugin-tools enblend')
    d = store.dir(sid).resolve()           # pto_gen writes the images' paths whole
    meta = store.meta(sid)
    tiles = meta.get('tiles') or []
    if len(tiles) < 2:
        raise ValueError('Hugin needs two tiles or more')
    out = d / f'hugin-{ppm:g}.jpg'
    if done(store, sid, ppm):
        return done(store, sid, ppm)
    fov, turn = meta['fov'], meta.get('turn', 0.0)
    unit = unit_mm(fov)
    work = d / 'hugin-work'
    if work.exists():
        shutil.rmtree(work)
    work.mkdir()
    w = lambda name: f'hugin-work/{name}'
    run = lambda *a: _run(list(a), d, log)
    try:
        # The tiles where the camera was sent, the first one the origin
        x0, y0 = tiles[0]['x'], tiles[0]['y']
        run('pto_gen', '-o', w('0.pto'), '-p', '0', '-f', str(HFOV), *[t['file'] for t in tiles])
        sets = []
        for i, t in enumerate(tiles):
            sets += [f'r{i}={-turn:.4f}', f'TrX{i}={(t["x"] - x0) / unit:.6f}', f'TrY{i}={-(t["y"] - y0) / unit:.6f}']
        run('pto_var', '--set', ','.join(sets), '-o', w('1.pto'), w('0.pto'))
        run('pto_var', '--opt', 'TrX,TrY,!TrX0,!TrY0', '-o', w('2.pto'), w('1.pto'))
        # Features are found on copies with the light's fall-off divided out and the
        # contrast stretched (soft halftone print gives cpfind little otherwise),
        # the tiles themselves drawn
        text = (d / w('2.pto')).read_text()
        for t in tiles:
            enhance(d / t['file'], d / w('e-' + t['file']))
            text = text.replace(f'"{d / t["file"]}"', f'"{d / w("e-" + t["file"])}"')
        (d / w('2e.pto')).write_text(text)
        run('cpfind', '--prealigned', '--fullscale', '--sieve2size', '4', '-o', w('3e.pto'), w('2e.pto'))
        text = (d / w('3e.pto')).read_text()
        for t in tiles:
            text = text.replace(f'"{d / w("e-" + t["file"])}"', f'"{d / t["file"]}"')
        (d / w('3.pto')).write_text(text)
        found = control_points(d / w('3.pto'))
        if not found:
            raise RuntimeError('no features matched between the tiles: blank paper? a texture helps')
        kept, pairs = clean(d / w('3.pto'), d / w('4.pto'))
        if not kept:
            raise RuntimeError(f'none of the {found} matches agree: repeating texture (halftone)? blank paper?')
        # The real scale and turn, from all pairs at once; then each tile only slides
        size = Image.open(d / tiles[0]['file']).size
        cam_ppm, turn_seen = similarity(pairs, tiles, turn)
        if cam_ppm and len(pairs) >= 3:
            # Pairs that put their tiles further apart than the carriage can be off
            # matched something else (blank paper, a repeat): out, and measure again
            good = plausible(pairs, tiles, cam_ppm, turn_seen)
            if len(good) < len(pairs):
                log(f'{len(pairs) - len(good)} of {len(pairs)} pairs disagree with the moves: left out')
                kept = keep_pairs(d / w('4.pto'), d / w('4.pto'), good)
                pairs = good
                cam_ppm, turn_seen = similarity(pairs, tiles, turn)
        if cam_ppm and len(pairs) >= 3:
            unit = size[0] / cam_ppm / (2 * math.tan(math.radians(HFOV) / 2))
        else:
            cam_ppm, turn_seen = size[0] / fov[0], turn
        sets = []
        for i, t in enumerate(tiles):
            sets += [f'r{i}={-turn_seen:.4f}', f'TrX{i}={(t["x"] - x0) / unit:.6f}', f'TrY{i}={-(t["y"] - y0) / unit:.6f}']
        run('pto_var', '--set', ','.join(sets), '-o', w('5.pto'), w('4.pto'))
        # Each group of tiles the matches join keeps one where it was sent (else it
        # could go anywhere); a tile no match reaches stays where it was sent
        fixed = ','.join(f'!TrX{i},!TrY{i}' for i in anchors(len(tiles), pairs))
        run('pto_var', '--opt', f'TrX,TrY,{fixed}', '-o', w('5v.pto'), w('5.pto'))
        run('autooptimiser', '-n', '-o', w('5o.pto'), w('5v.pto'))
        run('pto_var', '--opt', f'TrX,TrY,{fixed},b', '-o', w('6.pto'), w('5o.pto'))
        report = run('autooptimiser', '-n', '-o', w('6o.pto'), w('6.pto'))
        b = float(images(d / w('6o.pto'))[0]['b'])
        if abs(b) > 0.1:                         # not a lens: too few points to tell; without it
            log(f'barrel {b:.3f} left out')
            report = run('autooptimiser', '-n', '-o', w('6o.pto'), w('5v.pto'))
        rms = re.findall(r'([0-9.]+) units', report)
        # Drawn from copies with the light's fall-off divided out (the tiles' median,
        # kept as bright as it is on the whole): Hugin's own vignetting fit, from
        # overlaps this small, came out patchy
        flat = flat_field([Image.open(d / t['file']) for t in tiles[:40]])
        text = (d / w('6o.pto')).read_text()
        for t in tiles:
            flatten(Image.open(d / t['file']), flat).save(d / w('f-' + t['file']), quality=95)
            text = text.replace(f'"{d / t["file"]}"', f'"{d / w("f-" + t["file"])}"')
        (d / w('7.pto')).write_text(text)
        # Where the tiles ended up, against where they were sent
        moved = []
        for t, im in zip(tiles, images(d / w('7.pto'))):
            mx, my = float(im['TrX']) * unit + x0, -float(im['TrY']) * unit + y0
            moved.append(math.hypot(mx - t['x'], my - t['y']))
        far = [t['file'] for t, m in zip(tiles, moved) if m > MAX_OFF]
        # The canvas: at fov AUTO first, then as many pixels as ppm wants
        run('pano_modify', '--projection=0', '--fov=AUTO', '--canvas=AUTO', '-o', w('8.pto'), w('7.pto'))
        p = pano(d / w('8.pto'))
        v = float(p['v'])
        width = round(ppm * unit * 2 * math.tan(math.radians(v) / 2))
        height = round(width * int(p['h']) / int(p['w']))
        if width * height > MAX_MP * 1e6:
            full = width * height / 1e6
            raise ValueError(f'{full:.0f} megapixels at {ppm:g} px/mm, more than {MAX_MP}: '
                             f'try {ppm * math.sqrt(MAX_MP / full):.0f} px/mm or less')
        run('pano_modify', f'--canvas={width}x{height}', '--crop=AUTO', '-o', 'hugin.pto', w('8.pto'))
        run('nona', '-m', 'TIFF_m', '-o', w('r'), 'hugin.pto')
        run('enblend', '-o', w('out.tif'), *sorted(str(p.relative_to(d)) for p in work.glob('r*.tif')))
        img = Image.open(d / w('out.tif'))
        img.convert('RGB').save(out, quality=94)
        # The project kept with the tiles, by their names: it opens next to them (here,
        # in the zip, on the NAS), drawn from the tiles as they were shot
        text = (d / 'hugin.pto').read_text()
        for t in tiles:
            text = text.replace(f'"{d / w("f-" + t["file"])}"', f'"{t["file"]}"')
        (d / 'hugin.pto').write_text(text)
        matched = {i for a, b_ in pairs for i in (a, b_)}
        info = {'tiles': len(tiles), 'points': found, 'kept': kept, 'pairs': len(pairs),
                'camera': {'px_per_mm': round(cam_ppm, 2), 'fov': [round(size[0] / cam_ppm, 3), round(size[1] / cam_ppm, 3)],
                           'turn': round(turn_seen, 2), 'fov_was': fov, 'turn_was': turn},
                'rms_px': round(float(rms[-1]), 3) if rms else None,
                'unmatched': [t['file'] for i, t in enumerate(tiles) if i not in matched],
                'moved_max': round(max(moved), 3), 'far': far, 'width': img.size[0], 'height': img.size[1],
                'px_per_mm': ppm, 'engine': 'hugin'}
        import json
        (d / 'hugin.json').write_text(json.dumps(info))
        return out, info
    finally:
        if not keep_work:
            shutil.rmtree(work, ignore_errors=True)
