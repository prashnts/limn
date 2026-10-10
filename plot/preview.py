# Limn plot - reading G-code back: what gets drawn, where the tool travels
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Any G-code, not only ours: the preview shows the file, not what we meant.
# - Ours ('; limn-plot' at the top): G1 across is drawing, G0 travel.
# - A laser (M3/M4 .. M5): G1 across with it on is drawing.
# - Anything else: G1 across at z <= z_draw is drawing.
# A macro (T0, _APPLY_OFFSETS, ..) may move the head: the next move starts
# from nowhere, it isn't drawn.
import base64
import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

TRAVEL, DRAW = 0, 1
TOOL = re.compile(r'T(\d+)$')


@dataclass
class Sim:
    segs: np.ndarray        # (n, 6): x0 y0 z0 x1 y1 z1, z nan when unknown
    kind: np.ndarray        # TRAVEL | DRAW
    tool: np.ndarray        # index into `tools`, -1 before the first
    feed: np.ndarray        # mm/min, 0: not set
    line: np.ndarray        # line in the file, from 1
    tools: list[str]
    events: list[tuple[int, str]]   # (line, command) of everything that isn't a move
    ours: bool

    def runs(self):
        '''Continuous runs of one kind and tool: (kind, tool, (m, 3) points, first line).'''
        n = len(self.segs)
        if not n:
            return []
        same = np.ones(n, bool)
        same[0] = False
        same[1:] = ((self.kind[1:] == self.kind[:-1]) & (self.tool[1:] == self.tool[:-1])
                    & (np.abs(self.segs[1:, :2] - self.segs[:-1, 3:5]).max(axis=1) < 1e-6))
        starts = np.flatnonzero(~same)
        ends = np.append(starts[1:], n)
        return [(int(self.kind[a]), int(self.tool[a]),
                 np.vstack([self.segs[a, :3], self.segs[a:b, 3:]]), int(self.line[a]))
                for a, b in zip(starts, ends)]


def _arc(start, end, i, j, cw, step):
    cx, cy = start[0] + i, start[1] + j
    r = math.hypot(start[0] - cx, start[1] - cy)
    a0 = math.atan2(start[1] - cy, start[0] - cx)
    a1 = math.atan2(end[1] - cy, end[0] - cx)
    sweep = a1 - a0
    if cw and sweep >= 0:
        sweep -= 2 * math.pi
    elif not cw and sweep <= 0:
        sweep += 2 * math.pi
    n = max(1, math.ceil(abs(sweep) * r / step))
    pts = []
    for k in range(1, n + 1):
        a = a0 + sweep * k / n
        z = start[2] + (end[2] - start[2]) * k / n if start[2] is not None and end[2] is not None else end[2]
        pts.append([cx + r * math.cos(a), cy + r * math.sin(a), z])
    pts[-1][:2] = end[:2]
    return pts


def parse(text, z_draw=1.5, arc_step=0.2) -> Sim:
    rows, tools, events = [], [], []
    pos = [None, None, None]
    absolute, feed, tool, laser = True, 0.0, -1, None
    ours = '; limn-plot' in text[:500]
    for n, raw in enumerate(text.splitlines(), 1):
        if ours and raw.startswith('; tool T') and ':' not in raw:
            # ours: the tool drawing from here, whatever macro picked it up (a plan pen
            # swapped into a holder is picked up by that holder's macro)
            name = raw[7:].strip()
            if name not in tools:
                tools.append(name)
            tool = tools.index(name)
            continue
        line = raw.split(';', 1)[0].strip()
        if not line:
            continue
        words = line.split()
        cmd = words[0].upper()
        params = {}
        for w in words[1:]:
            if '=' in w:
                k, v = w.split('=', 1)
                params[k.upper()] = v
            elif w[0].isalpha():
                params[w[0].upper()] = w[1:]
        if cmd in ('G0', 'G1', 'G2', 'G3'):
            target = list(pos)
            for i, axis in enumerate('XYZ'):
                if axis in params:
                    v = float(params[axis])
                    target[i] = v if absolute or pos[i] is None else pos[i] + v
            if 'F' in params:
                feed = float(params['F'])
            start, pos = pos, target
            if None in (start[0], start[1], target[0], target[1]):
                continue
            if cmd in ('G2', 'G3') and ('I' in params or 'J' in params):
                pts = _arc(start, target, float(params.get('I', 0)), float(params.get('J', 0)), cmd == 'G2', arc_step)
            else:
                pts = [target]
            a = start
            for b in pts:
                across = math.hypot(b[0] - a[0], b[1] - a[1]) > 1e-9
                if cmd == 'G0':
                    k = TRAVEL
                elif laser is not None:
                    k = DRAW if laser and across else TRAVEL
                elif ours:
                    k = DRAW if across else TRAVEL
                else:
                    k = DRAW if across and b[2] is not None and b[2] <= z_draw else TRAVEL
                z0 = math.nan if a[2] is None else a[2]
                z1 = math.nan if b[2] is None else b[2]
                rows.append((a[0], a[1], z0, b[0], b[1], z1, k, tool, feed, n))
                a = b
        elif cmd == 'G90':
            absolute = True
        elif cmd == 'G91':
            absolute = False
        elif cmd == 'G92':
            for i, axis in enumerate('XYZ'):
                if axis in params:
                    pos[i] = float(params[axis])
        elif cmd in ('M3', 'M4'):
            laser = float(params.get('S', 255)) > 0
        elif cmd == 'M5':
            laser = False
        elif TOOL.match(cmd):
            if cmd not in tools:
                tools.append(cmd)
            tool = tools.index(cmd)
            events.append((n, line))
            pos = [None, None, None]
        elif cmd.startswith('M') and cmd[1:].isdigit():
            events.append((n, line))
        else:
            # G28 and the macros: the head may be anywhere after
            events.append((n, line))
            pos = [None, None, None]
    a = np.array(rows, float).reshape(-1, 10)
    return Sim(a[:, :6], a[:, 6].astype(np.int8), a[:, 7].astype(int), a[:, 8], a[:, 9].astype(int),
               tools, events, ours)


def stats(sim, machine, tools=None):
    '''Lengths per tool, bounds of the drawing, and a rough time.'''
    d = sim.segs
    lengths = np.sqrt((d[:, 3] - d[:, 0]) ** 2 + (d[:, 4] - d[:, 1]) ** 2
                      + np.nan_to_num(d[:, 5] - d[:, 2]) ** 2)
    v = np.where(sim.feed > 0, sim.feed, machine.feed_travel) / 60
    zonly = np.hypot(d[:, 3] - d[:, 0], d[:, 4] - d[:, 1]) < 1e-9
    v = np.where(zonly, np.minimum(v, machine.feed_z / 60), v)
    a = np.where(zonly, machine.accel_z, machine.accel)
    # trapezoid, from and to standstill: short moves never reach v
    t = np.where(lengths > v * v / a, lengths / v + v / a, 2 * np.sqrt(lengths / a))
    changes = sum(1 for _, c in sim.events if TOOL.match(c.split()[0].upper()))
    swaps = sum(1 for _, c in sim.events if c.split()[0].upper() == 'TOOL_SWAP')     # a pen swapped by hand
    out = {'draw_mm': float(lengths[sim.kind == DRAW].sum()), 'travel_mm': float(lengths[sim.kind == TRAVEL].sum()),
           'tool_changes': changes, 'swaps': swaps,
           'time_s': float(t.sum() + changes * machine.toolchange_time + swaps * getattr(machine, 'swap_time', 60)),
           'tools': {}}
    drawn = sim.kind == DRAW
    if drawn.any():
        xy = np.vstack([d[drawn][:, [0, 1]], d[drawn][:, [3, 4]]])
        out['bounds'] = [*map(float, xy.min(axis=0)), *map(float, xy.max(axis=0))]
    runs = sim.runs()
    for i, name in enumerate(sim.tools):
        mine = sim.tool == i
        if not mine.any() and name in out['tools']:
            continue
        cur = out['tools'].get(name, {'draw_mm': 0.0, 'strokes': 0, 'time_s': 0.0})
        out['tools'][name] = {'draw_mm': cur['draw_mm'] + float(lengths[mine & drawn].sum()),
                              'strokes': cur['strokes'] + sum(1 for k, t_, _, _ in runs if k == DRAW and t_ == i),
                              'time_s': cur['time_s'] + float(t[mine].sum())}
    out['tools'] = {k: v for k, v in out['tools'].items() if v['draw_mm'] > 0 or not sim.ours}
    return out


def _art(path):
    p = Path(path)
    mime = {'.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg'}[p.suffix.lower()]
    return f'data:{mime};base64,' + base64.b64encode(p.read_bytes()).decode()


def render_svg(sim, machine, tools=None, travel=True, art=True):
    '''The plot over the bed, as an SVG: bed art, draw area, travels, strokes in their tools' colour.'''
    tools = tools or {}
    w, h = machine.bed
    x0, y0, x1, y1 = machine.travel_area
    vb = (min(0, x0), min(0, y0), max(w, x1), max(h, y1))
    W, H = vb[2] - vb[0], vb[3] - vb[1]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W * 4}" height="{H * 4}" '
           f'viewBox="{vb[0]} {-vb[3]} {W} {H}">',
           f'<rect x="0" y="{-h}" width="{w}" height="{h}" fill="#f7f5ef" stroke="#bbb" stroke-width="0.3"/>']
    if art and machine.bed_art and Path(machine.bed_art).exists():
        out.append(f'<image href="{_art(machine.bed_art)}" x="0" y="{-h}" width="{w}" height="{h}" '
                   f'preserveAspectRatio="none" opacity="0.45"/>')
    out.append('<g transform="scale(1,-1)">')
    dx0, dy0, dx1, dy1 = machine.draw_area
    out.append(f'<rect x="{dx0}" y="{dy0}" width="{dx1 - dx0}" height="{dy1 - dy0}" fill="none" '
               f'stroke="#4a90d9" stroke-width="0.3" stroke-dasharray="2 1"/>')
    for z in machine.zones:
        zx0, zy0, zx1, zy1 = z.rect
        out.append(f'<rect x="{zx0}" y="{zy0}" width="{zx1 - zx0}" height="{zy1 - zy0}" '
                   f'fill="{"#d33" if z.z is None else "#e90"}" fill-opacity="0.12"/>')
    for k, t, pts, _ in sim.runs():
        d = ' '.join(f'{p[0]:.3f},{p[1]:.3f}' for p in pts)
        if k == TRAVEL:
            if travel:
                out.append(f'<polyline points="{d}" fill="none" stroke="#888" stroke-width="0.12" '
                           f'stroke-dasharray="0.8 0.6"/>')
            continue
        tool = tools.get(sim.tools[t]) if t >= 0 else None
        colour, width = (tool.color, tool.width) if tool else ('#222', 0.4)
        out.append(f'<polyline points="{d}" fill="none" stroke="{colour}" stroke-width="{width}" '
                   f'stroke-linecap="round" stroke-linejoin="round" stroke-opacity="0.9"/>')
    out.append('</g></svg>')
    return '\n'.join(out)
