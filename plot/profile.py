# Limn plot - the machine and its tools, from TOML profiles
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Profiles are looked up by name in plot/profiles/, or given as a path.
# Heights are G-code z with the tag offsets and the mesh applied.
import importlib.util
import os
import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .tools import Tool, load_plugin, resolve

PROFILES = Path(__file__).parent / 'profiles'
PENS = PROFILES / 'pens.toml'       # the pen library, the web UI edits it (pens.py)

Rect = tuple[float, float, float, float]    # x0, y0, x1, y1


class Zone(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str
    rect: Rect
    z: float | None = None      # its top; None: keep out


class Machine(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: str = 'limn'
    bed: tuple[float, float] = (135, 180)
    bed_art: str | None = None
    travel_area: Rect = (0, 0, 180, 177)
    draw_area: Rect = (0, 35, 110, 174)
    beds: str | None = None
    bed_id: str = ''
    paper_mesh: str = 'lrt_paper'
    draw_limit: Rect = (0, 0, 110, 177)
    tool_max_dxy: float = 5
    z_min: float = -2.5
    z_max: float = 7
    z_travel: float = 2.5
    hop_distance: float = 10
    clearance: float = 1
    feed_travel: float = 7800
    feed_z: float = 300
    accel: float = 3000
    accel_z: float = 100
    order_time: float = 0.25
    toolchange_time: float = 30
    mesh: str = ''
    park: tuple[float, float, float] = (42, 123, 7)
    moonraker: str = 'http://localhost:7125'
    holders: tuple[int, ...] = (41, 42, 43, 44, 45)     # T0, T1, .. (limn.cfg: T0 -> DOCK T=41)
    start: str = ''
    tool_begin: str = '{tool.call}'
    tool_end: str = ''
    end: str = ''
    zones: list[Zone] = []


def _path(name, suffix='.toml'):
    p = Path(name)
    return p if p.suffix == suffix or p.exists() else PROFILES / f'{name}{suffix}'


def load_machine(name='limn', overrides=None) -> Machine:
    path = _path(name)
    data = tomllib.loads(path.read_text())
    for key in ('bed_art', 'beds'):
        if data.get(key):
            data[key] = str((path.parent / data[key]).resolve())
    m = Machine(**{**data, **(overrides or {})})
    if os.environ.get('LIMN_MOONRAKER'):
        m = m.model_copy(update={'moonraker': os.environ['LIMN_MOONRAKER']})
    papers = bed_papers(m)
    if m.bed_id in papers:
        m = m.model_copy(update={'draw_area': papers[m.bed_id], 'mesh': m.paper_mesh})
    return m.model_copy(update={'draw_area': _inside(m.draw_area, reach(m))})


def reach(machine) -> Rect:
    '''Where every tool gets to: the travel area less a tag's dx/dy on each side. Klipper
    refuses a move past its limits, with the tool's offset added (2026-09-29: X2 with a
    Stabilo of dx -2.54 was X-0.54).'''
    x0, y0, x1, y1 = machine.travel_area
    d = machine.tool_max_dxy
    return (x0 + d, y0 + d, x1 - d, y1 - d)


def _inside(a, b):
    return (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))


def bed_papers(machine) -> dict[str, Rect]:
    '''The paper of each bed in `machine.beds`: its paper_mesh, inside draw_limit.'''
    if not machine.beds or not Path(machine.beds).exists():
        return {}
    # beds.py is data only; loaded on its own, not through the Klipper extension
    spec = importlib.util.spec_from_file_location('limn_plot_beds', machine.beds)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    lx0, ly0, lx1, ly1 = machine.draw_limit
    out = {}
    for name, bed in getattr(module, 'BEDS', {}).items():
        for mesh in bed.get('meshes', []):
            if mesh.get('profile') == machine.paper_mesh:
                (ox, oy), (w, h) = mesh['origin'], mesh['size']
                out[name] = (max(ox, lx0), max(oy, ly0), min(ox + w, lx1), min(oy + h, ly1))
    return out


def load_tools(name='tools') -> dict[str, Tool]:
    path = _path(name)
    data = tomllib.loads(path.read_text())
    for plugin in data.pop('plugins', []):
        load_plugin(path.parent / plugin)
    tools = {}
    for tid, spec in data.items():
        cls = resolve(spec.get('kind', 'pen'))
        tools[tid] = cls(id=tid, **spec)
    return tools


def load_pens(name=None) -> dict[str, dict]:
    '''The pen library: key -> {name, colors, and tool keys}.'''
    path = _path(name) if name else PENS
    return tomllib.loads(path.read_text()) if path.exists() else {}


def with_tags(tools, pens, tags, holders) -> dict[str, Tool]:
    '''The tools as the holders have them. A tag that names a pen of the library makes
    that tool this pen, in the tag's colour, under the tag's name; a tag without one
    (format 1) only names it; no tag: tools.toml. tags: printer.limn.tools, by holder.'''
    out = dict(tools)
    for i, holder in enumerate(holders):
        tag = (tags or {}).get(str(holder))
        if not tag:
            continue
        tid = f'T{i}'
        base = out.get(tid)
        source = 'stale' if tag.get('stale') else 'tag'
        pen = pens.get(tag.get('pen') or '')
        if pen:
            spec = {k: v for k, v in pen.items() if k not in ('name', 'short', 'colors')}
            kind = spec.pop('kind', 'pen')
            keep = {k: getattr(base, k) for k in ('macro', 'begin', 'end')} if base else {}
            colors = list((pen.get('colors') or {}).values())
            out[tid] = resolve(kind)(id=tid, kind=kind, **keep, **spec, name=tag.get('name') or pen.get('name', ''),
                                     color=tag.get('color') or (colors[0] if colors else '#000000'),
                                     pen=tag['pen'], holder=holder, source=source)
        elif base is not None:
            out[tid] = type(base)(**{**base.model_dump(), 'name': tag.get('name') or base.name,
                                     'color': tag.get('color') or base.color, 'holder': holder, 'source': source})
    return out
