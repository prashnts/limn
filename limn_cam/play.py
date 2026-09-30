# Limn cam - the Z axis's play, measured on the paper
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Pressing past touch lifts the Z axis within its play (GEOMETRY.md), and the
# pen only lets go of the paper once the axis is back down. At each spot, one
# test per trial rise r: down to z_touch - press, a pressed stroke along +Y
# (the axis lifts), up to z_touch + r, and on along +Y at that height (the
# tail). A tail with ink: at r the pen still dragged. The lowest r from which
# every tail is clean is what the play adds there, for that press; per mm of
# press it goes into plot/profiles/play.toml (plot/profile.py, Play).
#
# The crosses around the tests register the shot, as for the ladder.
import time
from dataclasses import dataclass, field, asdict

import numpy as np

from .geometry import Homography
from .image import change, paper
from .ladder import SOLID, TOUCH, measure, register, threshold


@dataclass
class PlayTest:
    pen: str
    press: float                                # mm past touch while drawing
    spots: list[tuple[float, float]]            # where each row of tests starts, mm
    rises: list[float] = field(default_factory=lambda: [round(0.25 * i, 2) for i in range(13)])
    z_touch: float = 1.2
    pitch: float = 2.5                          # mm between tests, along X
    stroke: float = 2.0                         # the pressed part, along +Y
    tail: float = 3.0                           # at the trial height, along +Y
    cross: float = 3.5
    margin: float = 3.5
    feed: float = 1500
    feed_z: float = 300
    feed_travel: float = 6000

    @property
    def hop(self):
        return self.z_touch + max(self.rises) + 1.0

    def tests(self):
        '''[(spot index, rise, start, pressed end, tail end)]'''
        out = []
        for s, (sx, sy) in enumerate(self.spots):
            for i, r in enumerate(self.rises):
                x = sx + i * self.pitch
                out.append((s, r, (x, sy), (x, sy + self.stroke), (x, sy + self.stroke + self.tail)))
        return out

    def block(self):
        pts = np.array([p for t in self.tests() for p in t[2:]])
        return pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max()

    def anchors(self):
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


def gcode(test, machine):
    from plot.emit import unsafe
    from plot.gcode import Writer
    problems = []
    x0, y0, x1, y1 = test.extent()
    dx0, dy0, dx1, dy1 = machine.draw_area
    if x0 < dx0 or y0 < dy0 or x1 > dx1 or y1 > dy1:
        problems.append(f'the tests ({x0:.1f}, {y0:.1f}) .. ({x1:.1f}, {y1:.1f}) are off the paper {machine.draw_area}')
    if test.hop > machine.z_max:
        problems.append(f'its hop z {test.hop} is over z_max {machine.z_max}')
    down = test.z_touch - test.press
    mesh = f' MESH={machine.paper_mesh}' if machine.paper_mesh else ''
    g = Writer()
    g.comment('limn-plot 1')
    g.comment(f'limn_cam play: {test.to_dict()}')
    g.raw('LAZY_HOME')
    g.raw(f'_CLEAR_OFFSETS HOME=1\n{test.pen}\n_APPLY_OFFSETS HOME=1{mesh}')
    g.at(*machine.park)
    for _, r, a, m, e in test.tests():
        g.rapid(x=a[0], y=a[1], f=test.feed_travel)
        g.rapid(z=test.hop, f=test.feed_z)
        g.line(z=down, f=test.feed_z)
        g.line(x=m[0], y=m[1], f=test.feed)
        g.line(z=test.z_touch + r, f=test.feed_z)       # up to the trial height: slow, as a pen-up
        g.line(x=e[0], y=e[1], f=test.feed)             # on, at that height: ink here is a drag
        g.rapid(z=test.hop, f=test.feed_z)
    h = test.cross / 2
    for cx, cy in test.anchors():
        for a, b in (((cx - h, cy), (cx + h, cy)), ((cx, cy - h), (cx, cy + h))):
            g.rapid(x=a[0], y=a[1], f=test.feed_travel)
            g.rapid(z=test.hop, f=test.feed_z)
            g.line(z=down, f=test.feed_z)
            g.line(x=b[0], y=b[1], f=test.feed)
            g.rapid(z=test.hop, f=test.feed_z)
    g.rapid(z=max(machine.safe_z + 2, test.hop), f=test.feed_z)
    g.raw('PLOT_END')
    bad = unsafe(machine, g.moves)
    if bad:
        problems.append(f'UNSAFE: {bad[0]}')
    return g.text(), problems


@dataclass
class Spot:
    x: float
    y: float
    rise: float | None              # lowest rise from which every tail is clean
    per_press: float | None         # rise / press
    drew: float                     # coverage of the pressed strokes: did it touch at all
    tails: list[tuple[float, float]]    # (rise, coverage of its tail)


@dataclass
class Result:
    spots: list[Spot]
    press: float
    homography: list
    px_per_mm: float
    anchor_error: float
    notes: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def analyze(before, after, test, backend=None, roi='paper'):
    c = change(before, after)
    notes = []
    if roi == 'paper':
        roi = paper(before, backend)
    if roi is not None:
        x0, y0, x1, y1 = roi
        keep = np.zeros(c.shape, bool)
        keep[y0:y1 + 1, x0:x1 + 1] = True
        c[~keep] = 0
    d, t = np.clip(c, 0, None), threshold(c)
    h, rms, t, _ = register(d, test, backend, t)
    spots = []
    for s, (sx, sy) in enumerate(test.spots):
        tails, drew = [], []
        for si, r, a, m, e in test.tests():
            if si != s:
                continue
            drew.append(measure(d, h, a, m, t)[0])
            # the first 0.3mm of the tail: the ink the stroke itself leaves at its end
            start = (m[0], m[1] + 0.3)
            tails.append((r, round(measure(d, h, start, e, t)[0], 3)))
        rise = None
        for r, cov in reversed(tails):              # from the highest rise down
            if cov >= TOUCH:
                break
            rise = r
        pressed = float(np.mean(drew)) if drew else 0.0
        if pressed < SOLID:
            notes.append(f'spot ({sx:g}, {sy:g}): the pressed strokes drew only {pressed:.0%}: does the pen touch '
                         f'at z_touch {test.z_touch} there? (limn_cam ladder)')
        if rise is None:
            notes.append(f'spot ({sx:g}, {sy:g}): it dragged even at the highest rise {max(test.rises)}: rises higher')
        k = None if rise is None or test.press <= 0 else round(rise / test.press, 2)
        spots.append(Spot(sx, sy, rise, k, round(pressed, 2), tails))
    return Result(spots, test.press, h.to_list(), round(h.scale(test.spots[0]), 2), round(rms, 2), notes)


def save(result, path, test, clear=None):
    '''The spots into play.toml (plot/profile.py Play), over what it had.'''
    import tomllib
    old = tomllib.loads(path.read_text()) if path.exists() else {}
    spots = [[s.x, s.y, s.per_press] for s in result.spots if s.per_press is not None]
    lines = [f'# The Z axis\'s play, measured by limn_cam play: extra lift per mm of press at each spot,',
             f'# (x, y, factor). plot/profile.py (Play) reads it over limn.toml\'s [play].']
    if clear is not None or 'clear' in old:
        lines.append(f'clear = {clear if clear is not None else old["clear"]}')
    lines.append('spots = [' + ', '.join(f'[{x:g}, {y:g}, {k:g}]' for x, y, k in spots) + ']')
    lines.append(f'measured = "{test.pen} pressed {test.press:g}, {time.strftime("%Y-%m-%d %H:%M")}"')
    path.write_text('\n'.join(lines) + '\n')
    return spots


def report(result):
    out = [f'{result.px_per_mm} px/mm, crosses fit to {result.anchor_error} px, pressed {result.press}']
    for s in result.spots:
        row = ' '.join(f'{r:g}:{"x" if c >= TOUCH else "."}' for r, c in s.tails)
        out.append(f'({s.x:g}, {s.y:g}): lets go from rise {s.rise}, {s.per_press} per mm of press  [{row}]')
    out += [f'! {n}' for n in result.notes]
    return '\n'.join(out)
