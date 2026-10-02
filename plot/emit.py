# Limn plot - the G-code of a job
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Tool by tool, nearest path next, over all objects. Between strokes the
# tool travels:
# - short hops (under hop_distance) at the tool's lift over the surface,
# - longer ones at least at z_travel,
# - over a zone or an object that is in the way, `clearance` above its top,
# - off the paper (the draw area), or leaving it, at least at safe_z: the pen
#   is never under safe_z off the paper. Drawings are clipped to the paper,
#   and every move written is checked for it (Result.unsafe),
# - never above z_max: a travel that would need to is a problem.
# It goes up where it is, across, and down only where it arrives.
# Every z is kept inside the machine's and the tool's z limits; a z that had
# to be clamped is a problem too.
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from .gcode import Writer, num
from .order import improve, join, order
from .preview import parse, stats
from .profile import load_machine, load_pens, load_tools, reach, with_tags
from .slicer import Cache, cut, goes_under, lightness
from .tools import DRAW

KEEP_OUT = math.inf


class ZoneObstacle:
    def __init__(self, zone):
        self.name = zone.name
        self.poly = box(*zone.rect)
        self.z = KEEP_OUT if zone.z is None else zone.z

    def top(self, geom):
        return self.z if self.poly.intersects(geom) else None


class ObjectObstacle:
    '''A placed object that isn't flat: travels go clear of its surface.'''

    def __init__(self, obj, surface):
        self.name = obj.id
        self.placement = obj.placement
        self.surface = surface
        fp = np.asarray(surface.footprint.exterior.coords)
        self.poly = Polygon(obj.placement.apply(fp)[:, :2])

    def top(self, geom):
        if not self.poly.intersects(geom):
            return None
        pts = self.placement.local(np.asarray(geom.coords)[:, :2])
        a, b = pts[0], pts[-1]
        return self.surface.max_along(a, b)


def on_paper(machine, p):
    '''Whether the point (x, y, ..) is on the paper: the draw area. None: not known.'''
    if p[0] is None or p[1] is None:
        return False
    x0, y0, x1, y1 = machine.draw_area
    return x0 - 1e-6 <= p[0] <= x1 + 1e-6 and y0 - 1e-6 <= p[1] <= y1 + 1e-6


def clip(pts, rect):
    '''The parts of the polyline `pts` (n, 3) inside `rect`, z carried along.'''
    x0, y0, x1, y1 = rect
    if len(pts) == 1:
        inside = x0 <= pts[0][0] <= x1 and y0 <= pts[0][1] <= y1
        return [pts] if inside else []
    parts, cur = [], []
    for a, b in zip(pts[:-1], pts[1:]):
        d = b - a
        t0, t1 = 0.0, 1.0
        for p, q in ((-d[0], a[0] - x0), (d[0], x1 - a[0]), (-d[1], a[1] - y0), (d[1], y1 - a[1])):
            if abs(p) < 1e-12:
                if q < 0:
                    t0, t1 = 1.0, 0.0
            elif p < 0:
                t0 = max(t0, q / p)
            else:
                t1 = min(t1, q / p)
        if t0 > t1:                                 # all of it off the paper
            if len(cur) > 1:
                parts.append(np.array(cur))
            cur = []
            continue
        s, e = a + d * t0, a + d * t1
        if not cur or np.abs(cur[-1] - s).max() > 1e-9:
            if len(cur) > 1:
                parts.append(np.array(cur))
            cur = [s]
        cur.append(e)
        if t1 < 1.0:                                # leaves the paper here
            parts.append(np.array(cur))
            cur = []
    if len(cur) > 1:
        parts.append(np.array(cur))
    return [p for p in parts if np.abs(p[-1] - p[0]).max() > 1e-9 or len(p) > 2]


def unsafe(machine, moves):
    '''The moves that go under safe_z off the paper, or that can't be told not to.'''
    out = []
    for a, b in moves:
        if a[2] is None or b[2] is None or None in a[:2] or None in b[:2]:
            out.append(f'a move to ({b[0]}, {b[1]}, {b[2]}) from where a macro left the tool: '
                       f'its height off the paper is not known')
        elif not (on_paper(machine, a) and on_paper(machine, b)) and min(a[2], b[2]) < machine.safe_z - 1e-9:
            p = b if not on_paper(machine, b) else a
            out.append(f'the tool goes to z {num(min(a[2], b[2]))} at ({num(p[0])}, {num(p[1])}), off the paper: '
                       f'under safe_z {num(machine.safe_z)}')
    return out


class Planner:
    def __init__(self, machine, obstacles=()):
        self.m = machine
        self.obstacles = list(obstacles)

    def off_paper(self, here, to):
        return here is None or not on_paper(self.m, here) or not on_paper(self.m, to)

    def z_for(self, here, to, lo):
        '''z to travel from `here` (None: unknown) to `to` at, at least `lo`; and why not.'''
        m, why = self.m, []
        if here is None:
            z, geom = max(lo, m.z_travel), Point(to[:2])
        else:
            d = math.dist(here[:2], to[:2])
            z = lo if d <= m.hop_distance else max(lo, m.z_travel)
            geom = LineString([here[:2], to[:2]]) if d > 0 else Point(to[:2])
        if self.off_paper(here, to):
            z = max(z, m.safe_z)
        for ob in self.obstacles:
            top = ob.top(geom)
            if top is None:
                continue
            if top == KEEP_OUT:
                why.append(f'a travel to ({num(to[0])}, {num(to[1])}) crosses {ob.name}, keep out')
                continue
            z = max(z, top + m.clearance)
        if z > m.z_max + 1e-9:
            why.append(f'a travel to ({num(to[0])}, {num(to[1])}) needs z {num(z)}, over z_max {num(m.z_max)}')
            z = m.z_max
        return z, why


class Emitter:
    '''What the tools see (tools.py): g, m, clamp(), travel(), drawn, state.'''

    def __init__(self, machine, planner):
        self.m = machine
        self.g = Writer()
        self.planner = planner
        self.drawn = {}             # mm drawn per tool
        self.state = {}             # the tools' own
        self.problems = []
        self.surface_z = 0.0

    def problem(self, text):
        if text not in self.problems:
            self.problems.append(text)

    def clamp(self, tool, z):
        lo, hi = tool.z_limits(self.m)
        if z < lo - 1e-9 or z > hi + 1e-9:
            self.problem(f'{tool.id}: z {num(z)} outside its limits [{num(lo)}, {num(hi)}], clamped')
        return min(max(z, lo), hi)

    def travel(self, tool, p):
        g, m = self.g, self.m
        here = None if g.x is None or g.y is None else (g.x, g.y)
        lo = max(self.surface_z, p[2]) + tool.lift(self, here)
        z, why = self.planner.z_for(here, p, lo)
        for w in why:
            self.problem(w)
        z = self.clamp(tool, z)
        if self.planner.off_paper(here, p) and z < m.safe_z:
            z = m.safe_z                    # the tool's own limits don't take it under safe_z
            if z > m.z_max + 1e-9:
                self.problem(f'safe_z {num(m.safe_z)} is over z_max {num(m.z_max)}')
        if g.z is None or z > g.z:
            g.rapid(z=z, f=m.feed_z)
        g.rapid(x=p[0], y=p[1], f=m.feed_travel)
        if g.z > z:
            g.rapid(z=z, f=m.feed_z)
        self.surface_z = p[2]

    def stroke(self, tool, pts):
        self.travel(tool, pts[0])
        tool.engage(self, pts[0])
        tool.draw(self, pts)
        tool.disengage(self)
        self.surface_z = pts[-1][2]


@dataclass
class Result:
    gcode: str
    problems: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    unsafe: list[str] = field(default_factory=list)     # it must not be sent to the plotter


def _fields(machine, tool, tools):
    digits = ''.join(c for c in tool.id if c.isdigit())
    return {'tool': tool, 'machine': machine, 'index': digits or '0',
            'mesh': f' MESH={machine.mesh}' if machine.mesh else ''}


def _outside(machine, pts):
    '''The first point of `pts` off the draw area, or None.'''
    x0, y0, x1, y1 = machine.draw_area
    xy = pts[:, :2]
    bad = (xy[:, 0] < x0 - 1e-6) | (xy[:, 0] > x1 + 1e-6) | (xy[:, 1] < y0 - 1e-6) | (xy[:, 1] > y1 + 1e-6)
    return xy[bad][0] if bad.any() else None


def _on_paper(machine, oid, tid, placed, problems):
    '''The paths clipped to the paper; a problem when that cut any.'''
    out = []
    for p in placed:
        off = _outside(machine, p)
        if off is None:
            out.append(p)
            continue
        if not any(q.startswith(f'{oid}: {tid} draws') for q in problems):
            problems.append(f'{oid}: {tid} draws at ({num(off[0])}, {num(off[1])}), outside the draw area '
                            f'{list(machine.draw_area)}: only the part on the paper is drawn')
        out += clip(p, machine.draw_area)
    return out


def _placed(geom, src, dst):
    '''geom in the coordinates of a drawing placed at `src`, in those of one at `dst`.'''
    g = affinity.translate(affinity.rotate(geom, src.rotate, origin=(0, 0)), src.x, src.y)
    return affinity.rotate(affinity.translate(g, -dst.x, -dst.y), -dst.rotate, origin=(0, 0))


def hidden(job, tools, sliced):
    '''Drawings hide what is under them, like the SVGs do inside one: the later in the
    job (sent to the front) over the earlier, where they paint opaque (occlude on).
    -> {object id: {tool: the area of it hidden, its own mm}}, kept the tool's bleed
    clear of what another tool (or a mask) draws over it.'''
    out = {}
    objs = job.objects
    for i, lo in enumerate(objs):
        s = sliced[lo.id]
        if not s.paths or not s.bounds:
            continue
        x0, y0, x1, y1 = s.bounds
        mine = box(x0, y0, x1, y1)
        tops = []
        for hi in objs[i + 1:]:
            if not hi.occlude:
                continue
            for t, geom in sliced[hi.id].cover.items():
                g = _placed(geom, hi.placement, lo.placement)
                if g.intersects(mine):
                    tops.append((t, g))
        if not tops:
            continue
        hide = {}
        for tid in s.paths:
            tool = tools.get(tid)
            bleed = tool.bleed if tool is not None else 0
            gs = [g.buffer(bleed) if bleed > 0 and t != tid else g for t, g in tops
                  if not goes_under(tool, tools.get(t))]
            if gs:
                hide[tid] = unary_union(gs)
        out[lo.id] = hide
    return out


def emit(job, machine, tools, sliced) -> Result:
    problems = []
    by_tool: dict[str, list[np.ndarray]] = {}
    obstacles = [ZoneObstacle(z) for z in machine.zones]
    under = hidden(job, tools, sliced)
    for obj in job.objects:
        s = sliced[obj.id]
        problems += [p for p in s.problems if p not in problems]
        if s.surface.max_z > 0:
            obstacles.append(ObjectObstacle(obj, s.surface))
        for tid, paths in s.paths.items():
            if tid not in tools:
                problems.append(f'{obj.id}: no tool {tid}')
                continue
            if not tools[tid].draws:
                problems.append(f'{obj.id}: {tid} is a {tools[tid].kind}, it doesn\'t draw: not drawn')
                continue
            if tid in under.get(obj.id, {}):
                paths = [s.surface.drape(p) for p in cut([p[:, :2] for p in paths], under[obj.id][tid])]
            placed = _on_paper(machine, obj.id, tid, [obj.placement.apply(p) for p in paths], problems)
            by_tool.setdefault(tid, []).extend(placed)

    first = job.tool_order or list(tools)
    used = [t for t in first if by_tool.get(t)] + [t for t in by_tool if t not in first]
    if any(tools[t].layers for t in used):
        used.sort(key=lambda t: -lightness(tools[t].color))     # light first: the dark goes over it
    e = Emitter(machine, Planner(machine, obstacles))
    g = e.g
    g.comment('limn-plot 1')
    for tid in used:
        t = tools[tid]
        g.comment(f'tool {tid}: {t.kind} {t.name!r} {num(t.width)}mm {t.color}'
                  + (f' press {num(t.pressed)}' if t.pressed is not None else ''))
        if t.press is not None and t.press_max is not None and t.press > t.press_max:
            problems.append(f'{tid} asks for a press of {num(t.press)}, its pen takes {num(t.press_max)} at most: '
                            f'{num(t.press_max)} it is')
    if not used:
        problems.append('nothing to draw')
        return Result(g.text(), problems)

    g.raw(machine.start.format(**_fields(machine, tools[used[0]], tools)))
    for tid in used:
        tool = tools[tid]
        g.comment(f'--- {tid} {tool.name}')
        g.raw((tool.begin or machine.tool_begin).format(**_fields(machine, tool, tools)))
        g.at(*machine.park)
        e.surface_z = 0.0
        paths = improve(order(by_tool[tid], machine.park[:2]), machine.park[:2], machine.order_time)
        for p in join(paths, link=tool.link_gap):
            e.stroke(tool, p)
        g.rapid(z=e.clamp(tool, max(g.z, min(machine.z_travel, machine.z_max))), f=machine.feed_z)
        end = tool.end if tool.end is not None else machine.tool_end
        if end.strip():
            g.raw(end.format(**_fields(machine, tool, tools)))
    g.raw(machine.end.format(**_fields(machine, tools[used[-1]], tools)))
    text = g.text()
    sim = parse(text)
    x0, y0, x1, y1 = reach(machine)
    ends = sim.segs[:, 3:5]
    bad = (ends[:, 0] < x0 - 1e-6) | (ends[:, 0] > x1 + 1e-6) | (ends[:, 1] < y0 - 1e-6) | (ends[:, 1] > y1 + 1e-6)
    if bad.any():
        x, y = ends[bad][0]
        problems.append(f'a move to ({num(x)}, {num(y)}) is within {num(machine.tool_max_dxy)} of the travel limits: '
                        f'with a tool\'s offset Klipper could refuse it ({int(bad.sum())} such moves)')
    bad = unsafe(machine, g.moves)
    if bad:
        problems.append(f'UNSAFE, not for the plotter: {bad[0]}' + (f' (and {len(bad) - 1} more)' if len(bad) > 1 else ''))
    return Result(text, problems + e.problems, stats(sim, machine, tools), bad)


def load(job, tags=None):
    '''The job's machine and tools, with its overrides. tags: printer.limn.tools, what the
    tools' tags say they are (with_tags).'''
    def near(name):
        p = job.root / name
        return str(p) if p.suffix == '.toml' and p.exists() else name
    machine = load_machine(near(job.machine), job.machine_overrides)
    tools = load_tools(near(job.tools))
    if tags:
        tools = with_tags(tools, load_pens(), tags, machine.holders)
    bad = set(job.draw) - set(DRAW)
    if bad:
        raise ValueError(f'draw: no setting {", ".join(sorted(bad))} (there are {", ".join(DRAW)})')
    draw = {k: v for k, v in job.draw.items() if v is not None}
    if draw:
        tools = {tid: type(t)(**{**t.model_dump(), **{k: v for k, v in draw.items() if k in type(t).model_fields}})
                 for tid, t in tools.items()}
    for tid, over in job.tool_overrides.items():
        if tid in tools and over:
            if 'press_max' in over:
                raise ValueError(f'{tid}: press_max comes from the pen library, a job cannot raise it')
            t = tools[tid]
            tools[tid] = type(t)(**{**t.model_dump(), **over})
    return machine, tools


def plot(job, cache=None, fonts=None, tags=None) -> tuple[Result, dict]:
    '''Slice what isn't sliced yet (cache), and write the job's G-code.'''
    machine, tools = load(job, tags)
    cache = cache or Cache()
    sliced = {obj.id: cache.get(obj, tools, job.root, fonts) for obj in job.objects}
    return emit(job, machine, tools, sliced), sliced
