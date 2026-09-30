# Limn plot - an object's drawing into paths per tool
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Each colour of the drawing (stroke or fill) goes to a tool, is masked, or
# isn't drawn (job.Group). With `occlude`, shapes are painted like the SVG
# is: what is painted later hides what is under it, so two metro lines that
# cross keep their colours, and a white casing cuts the line under it. Only
# opaque paint that is drawn or masked hides anything.
#
# Strokes wider than the tool fill their area (concentric), thinner ones are
# drawn on their centre line. Paths come out in object mm, y up, draped on
# the object's surface: (n, 3), z the surface.
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import shapely
from shapely.ops import unary_union

from . import svg
from .fonts import CAP, cap_height, line_text, outline_text, shape_outline
from .geometry import centerlines, fill, lines_of, region, stroke_area
from .job import Group, Obj
from .surface import make

WIDE = 1.5      # auto: strokes this many tool widths wide or more fill their area


@dataclass
class Sliced:
    paths: dict[str, list[np.ndarray]]
    surface: object
    bounds: tuple | None            # x0, y0, x1, y1 of the paths, object mm
    texts: int = 0                  # <text> not drawn (yet)
    problems: list[str] = field(default_factory=list)


def _rgb(hexc):
    return np.array([int(hexc[i:i + 2], 16) for i in (1, 3, 5)], float)


def colour_distance(a, b):
    '''"Redmean": close enough to how different two colours look.'''
    a, b = _rgb(a), _rgb(b)
    r = (a[0] + b[0]) / 2
    d = a - b
    return float(np.sqrt((2 + r / 256) * d[0] ** 2 + 4 * d[1] ** 2 + (2 + (255 - r) / 256) * d[2] ** 2))


def nearest_tool(colour, tools):
    tools = {k: t for k, t in (tools or {}).items() if t.draws}      # not a camera
    if not tools:
        return None
    return min(tools.values(), key=lambda t: colour_distance(colour, t.color)).id


def default_groups(drawing, tools):
    '''Each colour to the tool of the nearest colour; near white is the paper: a mask.'''
    out = {}
    for key in drawing.groups():
        colour = key.split(' ', 1)[1]
        if (_rgb(colour) @ (0.2126, 0.7152, 0.0722)) / 255 > 0.92:
            out[key] = Group(mask=True)
        else:
            out[key] = Group(tool=nearest_tool(colour, tools))
    return out


def groups_for(obj, drawing, tools):
    return {**default_groups(drawing, tools), **obj.groups}


def text_font(run, spec, fonts):
    '''The uploaded source font file for a text run, or None.'''
    if fonts is None:
        return None
    if spec.font:
        return fonts.path(spec.font)
    info = fonts.match(run.family, run.weight, run.style)
    return fonts.path(info.file) if info else None


def text_shapes(d, obj, fonts, problems):
    '''The drawing's <text> as shapes: the glyphs' outlines (source) or strokes (line).'''
    out = []
    for run in d.texts:
        spec = obj.texts.get(str(run.index), obj.text)
        colour = run.fill or run.stroke
        if spec.mode == 'skip' or not colour or not run.text.strip():
            continue
        src = text_font(run, spec, fonts)
        mode = ('source' if src else 'line') if spec.mode == 'auto' else spec.mode
        if mode == 'source' and src is None:
            problems.append(f'{obj.id}: no font for {run.family or "?"} ("{run.text[:20]}"), '
                            f'drawn in {spec.line_font}')
            mode = 'line'
        try:
            if mode == 'source':
                rings, _ = outline_text(run, src, obj.tolerance)
                out.append(svg.Shape(run.index, run.id, None, colour, 0, False, True, 'nonzero', 'butt', 'miter',
                                     rings, [True] * len(rings)))
            else:
                cap = cap_height(src, run.size) if src else CAP * run.size
                width = shape_outline(src, run.text, run.size)[1] if (src and spec.fit == 'width') else None
                strokes = line_text(run, spec.line_font, cap, width, fonts)
                out.append(svg.Shape(run.index, run.id, None, colour, 0, False, False, 'nonzero', 'butt', 'miter',
                                     strokes, [False] * len(strokes), line=True))
        except ValueError as e:
            problems.append(f'{obj.id}: {e}')
    return out


def slice_object(obj: Obj, tools, root=Path('.'), drawing=None, fonts=None) -> Sliced:
    d = drawing or svg.load_cached(root / obj.svg, obj.tolerance)
    groups = groups_for(obj, d, tools)
    height, s = d.size[1], obj.scale
    problems = []
    shapes = sorted(d.shapes + text_shapes(d, obj, fonts, problems), key=lambda sh: sh.index)

    def local(p):
        return np.column_stack([p[:, 0] * s, (height - p[:, 1]) * s])

    def tool_of(g):
        if g is None or g.tool is None:
            return None
        if g.tool not in tools:
            problems.append(f'no tool {g.tool} (for {obj.id})')
            return None
        return tools[g.tool]

    items = []      # (shape, paths, stroke group, fill group, fill area, stroke area, cover)
    for sh in shapes:
        paths = [local(p) for p in sh.paths]
        paint = obj.shapes.get(str(sh.index))
        sg = ((paint.stroke if paint and paint.stroke else None) or groups.get(f'stroke {sh.stroke}')) if sh.stroke else None
        fg = ((paint.fill if paint and paint.fill else None) or groups.get(f'fill {sh.fill}')) if sh.fill else None
        if sh.line:
            items.append((sh, paths, None, fg, None, None, False, False, None))
            continue
        stroke_on = sg is not None and (sg.tool is not None or sg.mask)
        fill_on = fg is not None and (fg.tool is not None or fg.mask)
        fill_area = None
        if fill_on:
            rings = [p if c else np.vstack([p, p[:1]]) for p, c in zip(paths, sh.closed)]
            fill_area = region(rings, sh.rule)
        st = tool_of(sg)
        wide = st is not None and (sg.stroke == 'width' or (sg.stroke == 'auto' and sh.width * s >= st.width * WIDE))
        stroke_covers = obj.occlude and stroke_on and sh.stroke_opaque
        s_area = stroke_area(paths, sh.closed, sh.width * s, sh.cap, sh.join) if (wide or stroke_covers) else None
        cover = []
        if obj.occlude and fill_on and sh.fill_opaque and fill_area is not None:
            cover.append(fill_area)
        if stroke_covers:
            cover.append(s_area)
        items.append((sh, paths, sg, fg, fill_area, s_area, wide, stroke_covers,
                      unary_union(cover) if cover else None))

    covers = [it[-1] for it in items]
    idx = [i for i, c in enumerate(covers) if c is not None and not c.is_empty]
    tree = shapely.STRtree([covers[i] for i in idx]) if idx else None

    def above(i, geom):
        if tree is None or geom is None or geom.is_empty:
            return None
        hits = [idx[j] for j in tree.query(geom) if idx[j] > i]
        return unary_union([covers[j] for j in hits]) if hits else None

    out: dict[str, list[np.ndarray]] = {}
    for i, (sh, paths, sg, fg, fill_area, s_area, wide, stroke_covers, _) in enumerate(items):
        ft = tool_of(fg)
        if sh.line:
            if ft is not None:
                lines = centerlines(paths, sh.closed)
                hide = above(i, lines)
                out.setdefault(ft.id, []).extend(lines_of(lines if hide is None else lines.difference(hide)))
            continue
        if ft is not None and fill_area is not None:
            area = fill_area
            if stroke_covers:
                area = area.difference(s_area)
            hide = above(i, area)
            if hide is not None:
                area = area.difference(hide)
            out.setdefault(ft.id, []).extend(
                fill(area, ft.width, fg.spacing or ft.spacing, fg.fill, fg.angle, fg.border))
        st = tool_of(sg)
        if st is not None:
            if wide:
                area = s_area
                hide = above(i, area)
                if hide is not None:
                    area = area.difference(hide)
                out.setdefault(st.id, []).extend(fill(area, st.width, st.spacing, 'concentric', border=True))
            else:
                lines = centerlines(paths, sh.closed)
                hide = above(i, lines)
                if hide is not None:
                    lines = lines.difference(hide)
                out.setdefault(st.id, []).extend(lines_of(lines))

    surface = make(obj.surface, root)
    draped = {t: [surface.drape(p) for p in ps] for t, ps in out.items() if ps}
    pts = [p for ps in draped.values() for p in ps]
    bounds = None
    if pts:
        a = np.vstack(pts)
        bounds = (*a[:, :2].min(axis=0), *a[:, :2].max(axis=0))
    return Sliced(draped, surface, bounds, len(d.texts), problems)


class Cache:
    '''Sliced objects by everything that makes them, but their placement.'''

    def __init__(self):
        self.sliced = {}
        self.slices = 0

    def key(self, obj, tools, root, fonts=None):
        src = Path(root) / obj.svg
        st = src.stat()
        # Validated again: defaults aren't, 45 and 45.0 must make the same key
        norm = lambda m, **kw: type(m).model_validate(m.model_dump()).model_dump(mode='json', **kw)
        data = {'obj': norm(obj, exclude={'placement'}), 'src': [str(src.resolve()), st.st_mtime_ns, st.st_size],
                'tools': {k: norm(t) for k, t in tools.items()}}
        if fonts is not None:
            data['fonts'] = fonts.signature()
        if obj.surface.path:
            sp = Path(root) / obj.surface.path
            data['surface'] = [str(sp.resolve()), sp.stat().st_mtime_ns]
        return hashlib.sha1(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()

    def get(self, obj, tools, root=Path('.'), fonts=None):
        k = self.key(obj, tools, root, fonts)
        if k not in self.sliced:
            if len(self.sliced) > 64:
                self.sliced.pop(next(iter(self.sliced)))
            self.sliced[k] = slice_object(obj, tools, root, fonts=fonts)
            self.slices += 1
        return self.sliced[k]
