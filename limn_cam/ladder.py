# Limn cam - the Z ladder: where each pen touches the paper, from a photo
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Each pen draws a row of short strokes along +Y, one per z, from high (in the
# air) to low (pressing), `pitch` apart along +X. Every stroke comes down from
# the same hop over the highest z: the Z axis has play, so all come from above
# the same way, as a plot's pen-downs do. The heights are G-code Z, as plot/
# has them: the tag's offsets and the paper mesh applied.
#
# Then the first pen draws five crosses around the block, at the lowest z, in
# a pattern that only fits one way round. They are the largest new ink in the
# photo: matched to where they were drawn, they give the homography from paper
# mm to pixels. No camera calibration, any camera that sees the block.
#
# A stroke is measured by sampling the ink map along where it should be:
# `coverage` is the share of it that is inked.
import itertools
import math
from dataclasses import dataclass, field, asdict

import numpy as np

from .backend import get as get_backend
from .geometry import Homography
from .image import change, noise, paper, sample

TOUCH, SOLID = 0.3, 0.8     # coverage: some ink / a whole line


@dataclass
class Ladder:
    pens: list[str]                             # tool macros, T0 ..
    z_top: float = 2.4
    z_bottom: float = 1.0
    z_step: float = 0.1
    origin: tuple[float, float] = (12.0, 40.0)  # the first stroke's start, mm
    pitch: float = 3.0                          # mm between strokes, along X
    length: float = 5.0                         # mm, along +Y
    row_gap: float = 6.0                        # mm between the rows of two pens
    hop: float = 1.0                            # over z_top: every stroke comes down from here
    cross: float = 4.0                          # anchor arms, mm end to end
    margin: float = 5.0                         # mm from the block to the anchors
    feed: float = 1500
    feed_z: float = 300
    feed_travel: float = 6000

    @property
    def zs(self):
        n = int(round((self.z_top - self.z_bottom) / self.z_step))
        return [round(self.z_top - i * self.z_step, 3) for i in range(n + 1)]

    def strokes(self):
        '''[(pen, z, (x, y) start, (x, y) end)], in drawing order.'''
        out = []
        ox, oy = self.origin
        for r, pen in enumerate(self.pens):
            y0 = oy + r * (self.length + self.row_gap)
            for i, z in enumerate(self.zs):
                x = ox + i * self.pitch
                out.append((pen, z, (x, y0), (x, y0 + self.length)))
        return out

    def block(self):
        ox, oy = self.origin
        x1 = ox + (len(self.zs) - 1) * self.pitch
        y1 = oy + len(self.pens) * self.length + (len(self.pens) - 1) * self.row_gap
        return ox, oy, x1, y1

    def anchors(self):
        '''Centres of the five crosses: the block's corners, and one a third of the
        way along its -Y side and further out, off the line of any two others, so
        the pattern fits only one way round (on the line, corners could swap).'''
        x0, y0, x1, y1 = self.block()
        m = self.margin
        a, b = (x0 - m, y0 - m), (x1 + m, y0 - m)
        return [a, b, (x1 + m, y1 + m), (x0 - m, y1 + m), (a[0] + (b[0] - a[0]) / 3, y0 - 2 * m)]

    def extent(self):
        pts = np.array(self.anchors())
        h = self.cross / 2
        return pts[:, 0].min() - h, pts[:, 1].min() - h, pts[:, 0].max() + h, pts[:, 1].max() + h

    def to_dict(self):
        return asdict(self)


def gcode(ladder, machine, pens=None, anchors=True):
    '''The ladder as plot G-code -> (text, problems). Problems: off the paper, or
    unsafe (plot.emit.unsafe): then it must not be run. pens: only these rows
    (the rest drawn already), anchors: the crosses too, with the first of them.'''
    from plot.emit import unsafe
    from plot.gcode import Writer
    problems = []
    x0, y0, x1, y1 = ladder.extent()
    dx0, dy0, dx1, dy1 = machine.draw_area
    if x0 < dx0 or y0 < dy0 or x1 > dx1 or y1 > dy1:
        problems.append(f'the ladder ({x0:.1f}, {y0:.1f}) .. ({x1:.1f}, {y1:.1f}) is off the paper {machine.draw_area}')
    hop = ladder.z_top + ladder.hop
    if hop > machine.z_max:
        problems.append(f'its hop z {hop} is over z_max {machine.z_max}')
    mesh = f' MESH={machine.paper_mesh}' if machine.paper_mesh else ''
    g = Writer()
    g.comment('limn-plot 1')
    g.comment(f'limn_cam ladder: {ladder.to_dict()}')
    g.raw('LAZY_HOME')
    by_pen = {}
    for s in ladder.strokes():
        by_pen.setdefault(s[0], []).append(s)
    for n, pen in enumerate(p for p in ladder.pens if pens is None or p in pens):
        g.comment(f'--- {pen}')
        g.raw(f'_CLEAR_OFFSETS HOME=1\n{pen}\n_APPLY_OFFSETS HOME=1{mesh}')
        g.at(*machine.park)
        for _, z, a, b in by_pen[pen]:
            g.rapid(x=a[0], y=a[1], f=ladder.feed_travel)
            g.rapid(z=hop, f=ladder.feed_z)
            g.line(z=z, f=ladder.feed_z)
            g.line(x=b[0], y=b[1], f=ladder.feed)
            g.rapid(z=hop, f=ladder.feed_z)
        if n == 0 and anchors:
            h, z = ladder.cross / 2, ladder.zs[-1]
            for cx, cy in ladder.anchors():
                for a, b in (((cx - h, cy), (cx + h, cy)), ((cx, cy - h), (cx, cy + h))):
                    g.rapid(x=a[0], y=a[1], f=ladder.feed_travel)
                    g.rapid(z=hop, f=ladder.feed_z)
                    g.line(z=z, f=ladder.feed_z)
                    g.line(x=b[0], y=b[1], f=ladder.feed)
                    g.rapid(z=hop, f=ladder.feed_z)
        g.rapid(z=max(machine.safe_z + 2, hop), f=ladder.feed_z)
    g.raw('PLOT_END')
    bad = unsafe(machine, g.moves)
    if bad:
        problems.append(f'UNSAFE: {bad[0]}')
    return g.text(), problems


@dataclass
class Step:
    pen: str
    z: float
    coverage: float
    ink: float                  # median ink along it


@dataclass
class PenResult:
    pen: str
    touch_z: float | None       # the highest z it drew at (with every z under it drawn too)
    solid_z: float | None       # the highest z of a whole line
    steps: list[Step] = field(default_factory=list)


@dataclass
class Result:
    pens: dict                  # pen -> PenResult
    homography: list            # 3x3, paper mm -> pixels
    px_per_mm: float
    anchor_error: float         # px, rms over the five crosses
    threshold: float
    notes: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def threshold(c):
    '''Ink from a change() map: well over its noise.'''
    return max(6 * noise(c), 0.02)


def register(d, ladder, backend=None, t=None):
    '''Paper mm -> pixels, from the five crosses in the ink map `d`.
    -> (Homography, rms px, threshold, blobs).'''
    backend = backend or get_backend()
    t = t or 0.03
    blobs = [b for b in backend.components(d > t, d) if b.area >= 3]
    if len(blobs) < 5:
        raise ValueError(f'{len(blobs)} marks found in the photo, the ladder has 5 crosses at least: '
                         f'is it in view, and did the lowest z draw?')
    # The crosses: square boxes, the largest of those (a stroke's box is long and
    # thin; a cross drawn light may weigh less than a stroke pressed hard)
    def side(b):
        return max(b.box[2] - b.box[0], b.box[3] - b.box[1]) + 1

    def squareness(b):
        w, h = b.box[2] - b.box[0] + 1, b.box[3] - b.box[1] + 1
        return min(w, h) / max(w, h)

    square = [b for b in blobs if squareness(b) >= 0.55 and side(b) >= 5]
    if len(square) < 5:
        raise ValueError(f'{len(square)} cross-like marks in the photo, the ladder has 5: is it in view?')
    square.sort(key=lambda b: -side(b))
    cand = square[:8]
    pts = np.array([b.centre for b in cand])
    anchors = np.array(ladder.anchors())
    best = None
    for idx in itertools.permutations(range(len(cand)), 4):
        try:
            h = Homography.fit(anchors[:4], pts[list(idx)])
        except np.linalg.LinAlgError:
            continue
        e = h(anchors[4])
        k = int(np.argmin(np.linalg.norm(pts - e, axis=1)))
        if k in idx:
            continue
        err = np.linalg.norm(pts[k] - e)
        scale = h.scale(anchors[0])
        if err > 1.5 * scale:                   # the fifth cross is within 1.5mm of where it should be
            continue
        sel = list(idx) + [k]
        h5 = Homography.fit(anchors, pts[sel])
        rms = float(np.sqrt(np.mean(h5.error(anchors, pts[sel]) ** 2)))
        # The five are the largest crosses: a fit to smaller ones loses to one that takes them
        weight = sum(side(cand[i]) for i in sel)
        score = rms / max(scale, 1e-9) - weight / sum(side(b) for b in cand)
        if best is None or score < best[0]:
            best = (score, h5, rms)
    if best is None:
        raise ValueError('the crosses are not where the ladder has them: no fit')
    return best[1], best[2], t, blobs


def measure(d, h, a, b, t, width=0.6, n=None):
    '''Ink along the segment a -> b (mm): (coverage, median ink). At each point
    the most ink within `width` mm across it: registration is good to a few tenths.'''
    a, b = np.asarray(a, float), np.asarray(b, float)
    length = np.linalg.norm(b - a)
    u = (b - a) / length
    across = np.array([-u[1], u[0]])
    scale = h.scale((a + b) / 2)
    n = n or max(8, int(length * scale))
    ts = np.linspace(0.1, 0.9, n)
    offs = np.linspace(-width / 2, width / 2, max(3, int(width * scale) + 1))
    vals = np.max([sample(d, h(a[None] + ts[:, None] * (b - a) + o * across)) for o in offs], axis=0)
    return float(np.mean(vals > t)), float(np.median(vals))


def lowest_run(steps, level):
    '''The highest z from which every step down drew at `level`, None if the lowest didn't.'''
    z = None
    for s in reversed(steps):                   # from the lowest z up
        if s.coverage < level:
            break
        z = s.z
    return z


def analyze(before, after, ladder, backend=None, homography=None, roi='paper'):
    '''roi: 'paper' (found in `before`), (x0, y0, x1, y1) pixels, or None: the whole shot.'''
    c = change(before, after)
    notes = []
    if roi == 'paper':
        roi = paper(before, backend)
        if roi is None:
            notes.append('no paper found in the shot: looking at all of it')
    if roi is not None:
        x0, y0, x1, y1 = roi
        keep = np.zeros(c.shape, bool)
        keep[y0:y1 + 1, x0:x1 + 1] = True
        c[~keep] = 0
    d, t = np.clip(c, 0, None), threshold(c)
    if homography is None:
        h, rms, t, _ = register(d, ladder, backend, t)
    else:
        h, rms = homography, float('nan')
    scale = h.scale(ladder.origin)
    if scale < 2:
        notes.append(f'{scale:.1f} px/mm: too few pixels to tell a line from a smudge, bring the camera closer')
    pens = {}
    for pen in ladder.pens:
        steps = []
        for p, z, a, b in ladder.strokes():
            if p == pen:
                cov, med = measure(d, h, a, b, t)
                steps.append(Step(pen, z, round(cov, 3), round(med, 4)))
        pens[pen] = PenResult(pen, lowest_run(steps, TOUCH), lowest_run(steps, SOLID), steps)
        if steps and steps[-1].coverage < TOUCH:
            notes.append(f'{pen} did not draw even at z {steps[-1].z}: go lower (z_bottom)')
        elif steps and steps[0].coverage >= TOUCH:
            notes.append(f'{pen} drew already at z {steps[0].z}: go higher (z_top)')
    # Between the strokes there should be nothing: ink there is a registration or a light problem
    gaps = []
    for p, z, a, b in ladder.strokes()[:-1]:
        o = np.array([ladder.pitch / 2, 0])
        gaps.append(measure(d, h, np.add(a, o), np.add(b, o), t)[0])
    if gaps and np.mean(gaps) > 0.2:
        notes.append(f'ink between the strokes too ({np.mean(gaps):.0%}): the fit or the light is off, check the overlay')
    return Result(pens, h.to_list(), round(scale, 2), round(rms, 2), round(t, 4), notes)


def suggest(result, tags, holders, z_touch):
    '''New tag dz per pen so it touches the paper at G-code z `z_touch`:
    dz + (touch_z - z_touch). tags: printer.limn.tools (by holder), holders: T0, T1 ..'s.'''
    out = {}
    for pen, r in result.pens.items():
        i = int(''.join(c for c in pen if c.isdigit()) or 0)
        tag = (tags or {}).get(str(holders[i])) if i < len(holders) else None
        if r.touch_z is None or not tag:
            out[pen] = None
            continue
        out[pen] = {'holder': holders[i], 'dz': tag['dz'], 'touch_z': r.touch_z,
                    'new_dz': round(tag['dz'] + r.touch_z - z_touch, 2)}
    return out


def overlay(after, result, ladder):
    '''The after shot with where each stroke should be, green inked, red not; the crosses in blue.'''
    from PIL import Image, ImageDraw
    from .image import load
    img = Image.fromarray((load(after) * 255).astype(np.uint8)).convert('RGB')
    dr = ImageDraw.Draw(img)
    h = Homography(result.homography)
    cov = {(s.pen, s.z): s.coverage for r in result.pens.values() for s in r.steps}
    for p, z, a, b in ladder.strokes():
        c = cov.get((p, z), 0)
        colour = (0, 200, 0) if c >= SOLID else (230, 170, 0) if c >= TOUCH else (220, 0, 0)
        dr.line([tuple(h(a)), tuple(h(b))], fill=colour, width=1)
    for cx, cy in ladder.anchors():
        q = h((cx, cy))
        dr.ellipse([q[0] - 4, q[1] - 4, q[0] + 4, q[1] + 4], outline=(0, 90, 255))
    return img


def report(result, suggestions=None):
    lines = [f'{result.px_per_mm} px/mm, crosses fit to {result.anchor_error} px, ink threshold {result.threshold}']
    for pen, r in result.pens.items():
        row = ' '.join(f'{s.z:g}:{"#" if s.coverage >= SOLID else "+" if s.coverage >= TOUCH else "."}' for s in r.steps)
        lines.append(f'{pen}: touches at z {r.touch_z}, a whole line from z {r.solid_z}   [{row}]')
        s = (suggestions or {}).get(pen)
        if s:
            lines.append(f'    holder {s["holder"]}: tag dz {s["dz"]} -> {s["new_dz"]}')
    lines += [f'! {n}' for n in result.notes]
    return '\n'.join(lines)
