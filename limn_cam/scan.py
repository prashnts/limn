# Limn cam - scanning a region with a camera tool: focus by height, tiles, a mosaic
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# The camera tool (plot/tools.py, Camera) works in the machine's own Z: once
# it is picked up, the tag offsets and the mesh are cleared. It moves sideways
# only at its `clear_z` or higher (clear of the bed's raised parts; home is Z8)
# and goes down only over the spot it shoots, never under its `z_min`. It is
# focused by height: at `focus_z` what lies there is sharpest, and one shot
# takes `fov` mm. A region is covered by tiles `overlap` apart, in rows that
# snake back and forth (a tethered camera moves as little as it can), each shot
# still for `settle` s. Every z comes from above: the Z axis has play.
#
# Scans live in a folder each (ScanStore): the tiles, meta.json with where each
# was taken, a mosaic and thumbnails made when asked for. Only the newest `keep`.
import io
import json
import math
import shutil
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
from PIL import Image

from .image import load


def sharpness(img, width=480):
    '''How sharp a shot is: the variance of its Laplacian, over the middle 80%,
    at `width` px across (noise matters less, and it's quick).'''
    a = load(img)
    step = max(1, a.shape[1] // width)
    a = a[::step, ::step]
    h, w = a.shape
    a = a[h // 10:h - h // 10, w // 10:w - w // 10]
    lap = 4 * a[1:-1, 1:-1] - a[:-2, 1:-1] - a[2:, 1:-1] - a[1:-1, :-2] - a[1:-1, 2:]
    return float(lap.var() * 1e4)


def shift(a, b, width=640):
    '''How far `b`'s picture has moved from `a`'s, pixels at full size (phase
    correlation, sub-pixel by a parabola) -> (dx, dy). Up to half a frame.'''
    ga, gb = load(a), load(b)
    step = max(1, ga.shape[1] // width)
    ga, gb = ga[::step, ::step], gb[::step, ::step]
    win = np.outer(np.hanning(ga.shape[0]), np.hanning(ga.shape[1]))
    fa, fb = np.fft.fft2((ga - ga.mean()) * win), np.fft.fft2((gb - gb.mean()) * win)
    r = np.fft.ifft2(fb * np.conj(fa) / (np.abs(fb * np.conj(fa)) + 1e-9)).real
    iy, ix = np.unravel_index(np.argmax(r), r.shape)
    h, w = r.shape

    def sub(c, m, n):
        if not 0 < c < n - 1:
            return 0.0
        d = m[c - 1] - 2 * m[c] + m[c + 1]
        return 0.5 * (m[c - 1] - m[c + 1]) / d if d else 0.0
    dx = ix + sub(ix, r[iy, :], w)
    dy = iy + sub(iy, r[:, ix], h)
    dx = dx - w if dx > w / 2 else dx
    dy = dy - h if dy > h / 2 else dy
    return dx * step, dy * step


def calibrate(size, moved_x, moved_y, step):
    '''One shot's size and turn from the picture's shift for a move of `step` mm
    along X (moved_x, px) and along Y (moved_y). size: the image (w, h) px.
    -> {px_per_mm, fov: (w, h) mm, turn: degrees, mirrored}'''
    sx, sy = np.array(moved_x) / step, np.array(moved_y) / step      # px per mm of move
    ppm = (np.linalg.norm(sx) + np.linalg.norm(sy)) / 2
    # The scene moves the other way: the camera going +X moves it -sx in the image
    turn = math.degrees(math.atan2(-sx[1], -sx[0]))
    # From above, +X right and +Y up the image (image y runs down): the cross is < 0. More: mirrored
    mirrored = bool(np.cross(-sx, -sy) > 0)
    return {'px_per_mm': round(float(ppm), 2), 'fov': (round(size[0] / ppm, 2), round(size[1] / ppm, 2)),
            'turn': round(turn, 1), 'mirrored': mirrored,
            'skew': round(float(abs(np.dot(sx, sy)) / (np.linalg.norm(sx) * np.linalg.norm(sy))), 3)}


def footprint(fov, turn):
    '''mm the shot covers along X and Y, the image turned `turn` degrees.'''
    w, h = fov
    c, s = abs(math.cos(math.radians(turn))), abs(math.sin(math.radians(turn)))
    return w * c + h * s, w * s + h * c


def tiles(region, fov, overlap=0.2, turn=0.0):
    '''Shot centres covering `region` (x0, y0, x1, y1 mm), `overlap` of a shot shared
    with the next, rows along X that snake -> [(row, col, x, y)].'''
    x0, y0, x1, y1 = region
    fx, fy = footprint(fov, turn)

    def centres(a, b, f):
        span = b - a
        if span <= f:
            return [(a + b) / 2]
        n = math.ceil((span - f) / (f * (1 - overlap))) + 1
        return list(np.linspace(a + f / 2, b - f / 2, n))
    xs, ys = centres(x0, x1, fx), centres(y0, y1, fy)
    out = []
    for r, y in enumerate(ys):
        row = list(enumerate(xs))
        for c, x in (row if r % 2 == 0 else row[::-1]):
            out.append((r, c, round(float(x), 3), round(float(y), 3)))
    return out


@dataclass
class Settings:
    '''The Scan tab's, kept in the workspace (scan.json).'''
    tool: str = ''                                  # the camera tool: T0 ..
    region: tuple[float, float, float, float] | None = None
    z: float | None = None                          # None: the camera's focus_z
    overlap: float = 0.2
    refocus: float = 0.0                            # mm up and down around z at each tile, 0: none
    refocus_step: float = 0.1
    settle: float | None = None                     # None: the camera's
    sweep: tuple[float, float, float] | None = None # the focus sweep: from, to, step; None: clear_z down 2.5
    low: bool = False                               # stay at the shooting z between tiles (flat regions only)

    def to_dict(self):
        return asdict(self)


class ScanStore:
    def __init__(self, root, keep=30):
        self.root = Path(root)
        self.keep = keep

    def new(self, meta):
        self.root.mkdir(parents=True, exist_ok=True)
        sid = time.strftime('%Y%m%d-%H%M%S')
        d = self.root / sid
        n = 1
        while d.exists():
            n += 1
            d = self.root / f'{sid}-{n}'
        d.mkdir()
        (d / 'meta.json').write_text(json.dumps({**meta, 'id': d.name, 'tiles': []}, indent=1))
        self.prune()
        return d.name

    def dir(self, sid):
        d = self.root / sid
        if '/' in sid or '..' in sid or not (d / 'meta.json').exists():
            raise KeyError(sid)
        return d

    def meta(self, sid):
        return json.loads((self.dir(sid) / 'meta.json').read_text())

    def add(self, sid, name, jpeg, info):
        d = self.dir(sid)
        (d / name).write_bytes(jpeg)
        meta = self.meta(sid)
        meta['tiles'].append({'file': name, **info})
        (d / 'meta.json').write_text(json.dumps(meta, indent=1))

    def update(self, sid, **fields):
        meta = {**self.meta(sid), **fields}
        (self.dir(sid) / 'meta.json').write_text(json.dumps(meta, indent=1))

    def list(self):
        if not self.root.exists():
            return []
        out = []
        for d in sorted(self.root.iterdir(), reverse=True):
            try:
                m = self.meta(d.name)
            except (KeyError, ValueError):
                continue
            out.append({k: m.get(k) for k in ('id', 'kind', 'region', 'z', 'camera', 'started', 'done', 'error')}
                       | {'count': len(m.get('tiles', []))})
        return out

    def delete(self, sid):
        shutil.rmtree(self.dir(sid))

    def prune(self):
        scans = sorted((d for d in self.root.iterdir() if (d / 'meta.json').exists()), reverse=True)
        for d in scans[self.keep:]:
            shutil.rmtree(d, ignore_errors=True)

    def file(self, sid, name):
        p = self.dir(sid) / name
        if '/' in name or '..' in name or not p.exists():
            raise KeyError(name)
        return p

    def thumb(self, sid, name, width=320):
        '''A smaller copy of a shot, kept. name `latest`: the newest shot.'''
        d = self.dir(sid)
        if name == 'latest':
            shots = self.meta(sid).get('tiles') or []
            if not shots:
                raise KeyError('no shot yet')
            name = shots[-1]['file']
        t = d / f'thumb-{width}-{name}'
        if not t.exists():
            im = Image.open(self.file(sid, name))
            im.thumbnail((width, width * 4))
            im.convert('RGB').save(t, quality=85)
        return t

    def mosaic(self, sid, px_per_mm=12.0):
        '''The tiles placed where they were taken, one image (no blending: the later
        tile on top). Made once, kept.'''
        d = self.dir(sid)
        meta = self.meta(sid)
        out = d / f'mosaic-{px_per_mm:g}.jpg'
        if out.exists() and out.stat().st_mtime >= (d / 'meta.json').stat().st_mtime:
            return out
        tiles_ = meta.get('tiles', [])
        if not tiles_:
            raise KeyError('no tiles yet')
        fov, turn = meta['fov'], meta.get('turn', 0.0)
        fx, fy = footprint(fov, turn)
        xs = [t['x'] for t in tiles_]
        ys = [t['y'] for t in tiles_]
        x0, y0 = min(xs) - fx / 2, min(ys) - fy / 2
        W = int(round((max(xs) - min(xs) + fx) * px_per_mm))
        H = int(round((max(ys) - min(ys) + fy) * px_per_mm))
        canvas = Image.new('RGB', (max(W, 1), max(H, 1)), 'black')
        for t in tiles_:
            im = Image.open(d / t['file']).convert('RGB')
            if turn:
                im = im.rotate(-turn, expand=True)
            im = im.resize((max(1, int(round(fx * px_per_mm))), max(1, int(round(fy * px_per_mm)))))
            # image y down, machine y up: the row for y is counted from the top
            left = int(round((t['x'] - fx / 2 - x0) * px_per_mm))
            top = int(round((y0 + (max(ys) - min(ys) + fy) - (t['y'] + fy / 2)) * px_per_mm))
            canvas.paste(im, (left, top))
        canvas.save(out, quality=90)
        return out


class Job:
    '''One thing the camera does on the plotter, in the background: `state` says how
    it goes, stop() asks it to stop between shots.'''

    def __init__(self, what, mr, camera, machine, store, settings):
        self.mr = mr
        self.camera = camera            # plot.tools.Camera, from the tags
        self.machine = machine
        self.store = store
        self.s = settings
        self.state = {'what': what, 'done': False, 'error': None, 'i': 0, 'n': 0,
                      'started': time.time(), 'scan': None, 'result': None}
        self._stop = False
        self._thread = None
        self.z = None                   # where the camera is, once known
        self.xy = None

    def start(self, fn):
        def run():
            try:
                fn()
            except Exception as e:
                self.state['error'] = str(e)
            finally:
                if self.z is not None and self.z < self.clear():
                    try:                            # never left low over the bed
                        self.mr.gcode(f'G90\nG1 Z{self.clear():.3f} F300\nM400', timeout=60)
                        self.z = self.clear()
                    except Exception:
                        pass
                self.state['done'], self.state['ended'] = True, time.time()
                if self.state['scan']:
                    try:
                        self.store.update(self.state['scan'], done=True, error=self.state['error'])
                    except KeyError:
                        pass
        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop = True

    def _check(self):
        if self._stop:
            raise RuntimeError('stopped')

    # On the plotter
    def carry(self):
        '''The camera on the carriage, in the machine's own Z (no offsets, no mesh),
        at clear_z.'''
        holder = self.camera.holder
        carried = int(self.mr.query(save_variables='variables')['save_variables']['variables']
                      .get('currently_docked_tool', 0) or 0)
        clear = self.clear()
        if carried != holder:
            self.mr.gcode(f'LAZY_HOME\n_CLEAR_OFFSETS HOME=1\n{self.camera.call}\n_CLEAR_OFFSETS\n'
                          f'G90\nG1 Z{clear:.3f} F300\nM400', timeout=600)
        else:
            st = self.mr.query(gcode_move='homing_origin', bed_mesh='profile_name')
            if any(abs(v) > 1e-6 for v in st['gcode_move']['homing_origin'][:3]) \
                    or (st.get('bed_mesh') or {}).get('profile_name'):
                self.mr.gcode('_CLEAR_OFFSETS', timeout=300)
            self.mr.gcode(f'G90\nG1 Z{clear:.3f} F300\nM400', timeout=120)
        self.z = clear

    def z_limits(self):
        return self.camera.z_limits(self.machine)

    def clear(self):
        lo, hi = self.z_limits()
        return min(max(self.camera.clear_z, lo), hi)

    def sweep(self):
        '''The focus sweep's z, high to low, within the camera's limits.'''
        lo, hi = self.z_limits()
        a, b, step = self.s.sweep or (self.clear() - 2.5, self.clear(), 0.25)
        a, b = max(min(a, b), lo), min(max(a, b), hi)
        return sorted(np.arange(a, b + step / 2, step), reverse=True)

    def goto(self, x, y, z, lift=True):
        '''There, still. Sideways only at clear_z or higher (or, not `lift`, at the
        height it is at: stepping down in place, or `low` between tiles); down
        onto z from above (the play); then settle.'''
        lo, hi = self.z_limits()
        z = min(max(z, lo), hi)
        settle = self.s.settle if self.s.settle is not None else self.camera.settle
        lines = ['G90']
        there = self.xy is not None and abs(self.xy[0] - x) < 1e-6 and abs(self.xy[1] - y) < 1e-6
        if lift and not there:
            lines.append(f'G1 Z{max(self.clear(), z):.3f} F300')
        if not there:
            lines.append(f'G1 X{x:.3f} Y{y:.3f} F4000')
        if not lift and self.z is not None and z > self.z:
            lines.append(f'G1 Z{z + 0.3:.3f} F300')             # up: overshoot, then down onto it
        lines += [f'G1 Z{z:.3f} F300', 'M400', f'G4 P{int(settle * 1000)}']
        self.mr.gcode('\n'.join(lines), timeout=120)
        self.z, self.xy = z, (x, y)
        return z

    def shot(self):
        return self.mr.snapshot(self.camera.webcam)

    def best_of(self, x, y, zs, lift=True, count=False):
        '''The sharpest of shots at these z, from the top down -> (z, jpeg, [(z, score)]).
        count: each shot is a step of the job's progress.'''
        curve, best = [], None
        for z in sorted(zs, reverse=True):
            self._check()
            if count:
                self.state['i'] = len(curve)
            z = self.goto(x, y, z, lift=lift and not curve)
            jpeg = self.shot()
            score = sharpness(jpeg)
            curve.append((round(z, 3), round(score, 2)))
            if best is None or score > best[2]:
                best = (z, jpeg, score)
        return best[0], best[1], curve

    # What it does
    def focus(self, x, y):
        '''Sweep z over (x, y), keep the sharpest.'''
        zs = self.sweep()
        self.state['n'] = len(zs)
        self.carry()
        sid = self.store.new(self._meta('focus', (x, y, x, y)))
        self.state['scan'] = sid
        z, jpeg, curve = self.best_of(x, y, zs, count=True)
        self.state['i'] = len(zs)
        self.store.add(sid, 'best.jpg', jpeg, {'x': x, 'y': y, 'z': z})
        self.store.update(sid, curve=curve, z=z)
        self.state['result'] = {'z': z, 'curve': curve}

    def look(self, x, y, z):
        self.carry()
        sid = self.store.new(self._meta('look', (x, y, x, y), z=z))
        self.state['scan'] = sid
        z = self.goto(x, y, z)
        self.store.add(sid, 'look.jpg', self.shot(), {'x': x, 'y': y, 'z': z, 'sharpness': None})

    def scan(self):
        region = self.s.region
        z0 = self.s.z if self.s.z is not None else self.camera.focus_z
        plan = tiles(region, self.camera.fov, self.s.overlap, self.camera.turn)
        self.state['n'] = len(plan)
        self.carry()
        sid = self.store.new(self._meta('scan', region, z=z0))
        self.state['scan'] = sid
        for i, (r, c, x, y) in enumerate(plan):
            self._check()
            lift = i == 0 or not self.s.low
            if self.s.refocus > 0:
                step = self.s.refocus_step
                zs = list(np.arange(z0 - self.s.refocus, z0 + self.s.refocus + step / 2, step))
                z, jpeg, curve = self.best_of(x, y, zs, lift=lift)
            else:
                z = self.goto(x, y, z0, lift=lift)
                jpeg, curve = self.shot(), None
            self.store.add(sid, f'r{r:02d}c{c:02d}.jpg', jpeg,
                           {'row': r, 'col': c, 'x': x, 'y': y, 'z': round(z, 3), 'curve': curve})
            self.state['i'] = i + 1

    def _meta(self, kind, region, z=None):
        c = self.camera
        return {'kind': kind, 'region': list(region), 'z': z, 'camera': c.name, 'tool': c.id, 'webcam': c.webcam,
                'fov': list(c.fov), 'turn': c.turn, 'overlap': self.s.overlap, 'started': time.time(), 'done': False}
