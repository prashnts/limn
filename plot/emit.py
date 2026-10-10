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
from .profile import holder_tools, load_machine, load_pens, load_tools, plan_pens, reach, with_tags
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
    sim: object = None          # preview.Sim: the G-code read back
    plan: list = field(default_factory=list)    # the steps, in order: start, swap (by hand), tool, end


def _fields(machine, tool, tools):
    digits = ''.join(c for c in (tool.call if tool.swap else tool.id) if c.isdigit())
    # {prepare}: once the tool is picked up, before its offsets are applied: probed on the bed's
    # sensor when its tag has no offsets (or it was swapped in to be), primed in the wipe area
    prepare = 'TOOL_PREPARE CALIBRATE=' + ('1' if tool.calibrate else 'auto') + f' PRIME={int(machine.prime)}'
    return {'tool': tool, 'machine': machine, 'index': digits or '0',
            'mesh': f' MESH={machine.mesh}' if machine.mesh else '', 'prepare': prepare if tool.touches else ''}


def swaps(machine, tools, used, problems):
    '''The plan pens swapped into a holder by hand (profile.plan_pens): each gets its holder,
    one picked when the job leaves it (a holder whose pen this plot doesn't use, else the one
    whose pen is done first), and comes after that holder's own pen and the swaps before it.
    -> (tools, the order they draw in).'''
    real = holder_tools(tools, machine.holders)         # holder -> its tool
    out = dict(tools)
    into = {}                                           # holder -> the plan pens swapped into it
    for tid in used:
        t = tools[tid]
        if t.source != 'plan' or t.alias:
            continue
        h = t.swap
        if h is None:
            def cost(h):
                own = tools[real[h]]
                return (not own.draws, real[h] in used, used.index(real[h]) if real[h] in used else 0,
                        len(into.get(h, [])), machine.holders.index(h))
            if not real:
                problems.append(f'{tid}: no holder to swap it into')
                continue
            h = min(real, key=cost)
        into.setdefault(h, []).append(tid)
        out[tid] = t.model_copy(update={'swap': h, 'holder': h, 'macro': tools[real[h]].call if h in real else None})
    order, left = [], list(used)
    while left:                                         # each in its order, once what must go first went
        for tid in left:
            t = out[tid]
            if not t.swap:
                break
            first = [real.get(t.swap)] + into[t.swap][:into[t.swap].index(tid)]
            if all(f not in left for f in first):
                break
        else:
            tid = left[0]
        left.remove(tid)
        order.append(tid)
    return out, order


def _on_paper(machine, oid, tid, paths, placement, problems):
    '''The paths placed, and clipped to the paper; a problem when that cut any.'''
    if not paths:
        return []
    starts = np.cumsum([0] + [len(p) for p in paths[:-1]])
    pts = placement.apply(np.vstack(paths))     # all at once: a picture's lines are tens of thousands
    x0, y0, x1, y1 = machine.draw_area
    bad = ((pts[:, 0] < x0 - 1e-6) | (pts[:, 0] > x1 + 1e-6) | (pts[:, 1] < y0 - 1e-6) | (pts[:, 1] > y1 + 1e-6))
    off = np.logical_or.reduceat(bad, starts)
    out = []
    for p, cut_, a in zip(np.split(pts, starts[1:]), off, starts):
        if not cut_:
            out.append(p)
            continue
        if not any(q.startswith(f'{oid}: {tid} draws') for q in problems):
            x, y = pts[a + int(np.argmax(bad[a:a + len(p)])), :2]
            problems.append(f'{oid}: {tid} draws at ({num(x)}, {num(y)}), outside the draw area '
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


def drawing_order(s, tid, budget):
    '''The slice's paths of a tool in the order they are drawn, object mm: kept on the
    slice (cached with it), as moving or turning a drawing doesn't change how far apart
    its paths are. Nearest next from its corner, then improved for `budget` seconds.'''
    k = (tid, budget)
    if k not in s.orders:
        start = s.bounds[:2] if s.bounds else (0, 0)
        s.orders[k] = improve(order(s.paths[tid], start), start, budget)
    return s.orders[k]


def chain(blocks, start):
    '''Blocks of paths in their order, one after another: the nearest next, drawn from
    its last path back when that end is nearer.'''
    out, pos, left = [], np.asarray(start[:2], float), [b for b in blocks if b]
    while left:
        d = [(min(math.dist(pos, b[0][0, :2]), math.dist(pos, b[-1][-1, :2])), i) for i, b in enumerate(left)]
        b = left.pop(min(d)[1])
        if math.dist(pos, b[-1][-1, :2]) < math.dist(pos, b[0][0, :2]):
            b = [p[::-1] for p in reversed(b)]
        out += b
        pos = b[-1][-1, :2]
    return out


def emit(job, machine, tools, sliced) -> Result:
    problems = []
    by_tool: dict[str, list[list[np.ndarray]]] = {}     # tool -> each drawing's paths, in order
    obstacles = [ZoneObstacle(z) for z in machine.zones]
    under = hidden(job, tools, sliced)
    count = {}                  # paths of each tool: its ordering time is shared out by them
    for obj in job.objects:
        for tid, paths in sliced[obj.id].paths.items():
            count[tid] = count.get(tid, 0) + len(paths)
    for obj in job.objects:
        s = sliced[obj.id]
        problems += [p for p in s.problems if p not in problems]
        if s.surface.max_z > 0:
            obstacles.append(ObjectObstacle(obj, s.surface))
        for tid in s.paths:
            if tid not in tools:
                problems.append(f'{obj.id}: no tool {tid}')
                continue
            if not tools[tid].draws:
                problems.append(f'{obj.id}: {tid} is a {tools[tid].kind}, it doesn\'t draw: not drawn')
                continue
            budget = round(machine.order_time * len(s.paths[tid]) / count[tid], 3)
            paths = drawing_order(s, tid, budget)
            if tid in under.get(obj.id, {}):        # cut in order: the pieces stay in it
                paths = [s.surface.drape(p) for p in cut([p[:, :2] for p in paths], under[obj.id][tid])]
            placed = _on_paper(machine, obj.id, tid, paths, obj.placement, problems)
            by_tool.setdefault(tools[tid].alias or tid, []).append(placed)     # a plan pen a holder has: its tool

    first = job.tool_order or list(tools)
    by_tool = {t: bs for t, bs in by_tool.items() if any(bs)}
    used = [t for t in first if by_tool.get(t)] + [t for t in by_tool if t not in first]
    if any(tools[t].layers for t in used):
        used.sort(key=lambda t: -lightness(tools[t].color))     # light first: the dark goes over it
    tools, used = swaps(machine, tools, used, problems)
    e = Emitter(machine, Planner(machine, obstacles))
    g = e.g
    g.comment('limn-plot 1')
    for tid in used:
        t = tools[tid]
        g.comment(f'tool {tid}: {t.kind} {t.name!r} {num(t.width)}mm {t.color}'
                  + (f' press {num(t.pressed)}' if t.pressed is not None else '')
                  + (f', swapped into holder {t.swap} by hand' if t.swap else ''))
        if t.press is not None and t.press_max is not None and t.press > t.press_max:
            problems.append(f'{tid} asks for a press of {num(t.press)}, its pen takes {num(t.press_max)} at most: '
                            f'{num(t.press_max)} it is')
    if not used:
        problems.append('nothing to draw')
        return Result(g.text(), problems)
    if '{prepare}' not in machine.tool_begin and machine.prime:
        problems.append('the machine\'s tool_begin has no {prepare}: the pens are not primed (nor probed when new)')

    plan = [{'kind': 'start', 'line': len(g.lines) + 1}]
    g.raw(machine.start.format(**_fields(machine, tools[used[0]], tools)))
    held = {h: t for h, t in holder_tools(tools, machine.holders).items()}     # what each holder has now
    for tid in used:
        tool = tools[tid]
        if tool.swap:
            out = tools.get(held.get(tool.swap))
            g.comment(f'--- swap: holder {tool.swap} gets {tid} {tool.name}' + (f' for {out.name}' if out else ''))
            plan.append({'kind': 'swap', 'tool': tid, 'holder': tool.swap, 'out': out.id if out else None,
                         'out_name': out.name if out else '', 'line': len(g.lines) + 1})
            name = ''.join(c for c in tool.name if c not in '"#;\n')[:20]
            g.raw('UNDOCK\n' + f'TOOL_SWAP T={tool.swap}' + (f' PEN={tool.pen}' if tool.pen else '')
                  + f' COLOR={tool.color.lstrip("#")} NAME="{name}"' + (' CALIBRATE=1' if tool.calibrate else ''))
            held[tool.swap] = tid
        g.comment(f'--- {tid} {tool.name}')
        plan.append({'kind': 'tool', 'tool': tid, 'holder': tool.holder, 'line': len(g.lines) + 1,
                     'aliases': [p for p, t in tools.items() if t.alias == tid],
                     'prime': machine.prime and '{prepare}' in (tool.begin or machine.tool_begin)})
        g.raw((tool.begin or machine.tool_begin).format(**_fields(machine, tool, tools)))
        g.comment(f'tool {tid}')                # the preview: drawn by this tool, whatever macro picked it up
        g.at(*machine.park)
        e.surface_z = 0.0
        for p in join(chain(by_tool[tid], machine.park[:2]), link=tool.link_gap):
            e.stroke(tool, p)
        g.rapid(z=e.clamp(tool, max(g.z, min(machine.z_travel, machine.z_max))), f=machine.feed_z)
        end = tool.end if tool.end is not None else machine.tool_end
        if end.strip():
            g.raw(end.format(**_fields(machine, tool, tools)))
    plan.append({'kind': 'end', 'line': len(g.lines) + 1})
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
    st = stats(sim, machine, tools)
    for step in plan:
        if step['kind'] == 'tool':
            step.update(st['tools'].get(step['tool'], {'draw_mm': 0.0, 'strokes': 0, 'time_s': 0.0}))
    return Result(text, problems + e.problems, st, bad, sim, plan)


def load(job, tags=None):
    '''The job's machine and tools, with its overrides. tags: printer.limn.tools, what the
    tools' tags say they are (with_tags). Then the job's own pens (plan_pens): one a holder
    has is that holder's tool as it is, tuning and all.'''
    def near(name):
        p = job.root / name
        return str(p) if p.suffix == '.toml' and p.exists() else name
    machine = load_machine(near(job.machine), job.machine_overrides)
    tools = load_tools(near(job.tools))
    pens = load_pens()
    if tags:
        tools = with_tags(tools, pens, tags, machine.holders)
    bad = set(job.draw) - set(DRAW)
    if bad:
        raise ValueError(f'draw: no setting {", ".join(sorted(bad))} (there are {", ".join(DRAW)})')
    draw = {k: v for k, v in job.draw.items() if v is not None}

    def tuned(tools, only=None):
        if draw:
            tools = {tid: type(t)(**{**t.model_dump(), **{k: v for k, v in draw.items() if k in type(t).model_fields}})
                     if only is None or tid in only else t for tid, t in tools.items()}
        for tid, over in job.tool_overrides.items():
            if tid in tools and over and (only is None or tid in only):
                if 'press_max' in over:
                    raise ValueError(f'{tid}: press_max comes from the pen library, a job cannot raise it')
                t = tools[tid]
                tools[tid] = type(t)(**{**t.model_dump(), **over})
        return tools
    tools = tuned(tools)
    if job.pens:
        tools = plan_pens(tools, pens, job.pens, machine.holders)
        tools = tuned(tools, {pid for pid in job.pens if not tools[pid].alias})
    return machine, tools


def plot(job, cache=None, fonts=None, tags=None) -> tuple[Result, dict]:
    '''Slice what isn't sliced yet (cache), and write the job's G-code.'''
    machine, tools = load(job, tags)
    cache = cache or Cache()
    sliced = {obj.id: cache.get(obj, tools, job.root, fonts) for obj in job.objects}
    return emit(job, machine, tools, sliced), sliced
