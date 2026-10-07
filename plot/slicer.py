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
#
# What another tool (or a mask) draws on top is kept `bleed` mm clear of, so
# inks that run don't meet. Shapes too small or too dense for the tool's line
# (the pen would fill in their insides: small handwriting, tiny text) are
# skipped, or only warned about (the tool's `small`). The object's masks are
# regions where nothing of it is drawn. With a tool's `layers`, a darker ink on
# top doesn't cut it: it is drawn whole, first, and the dark ink over it keeps
# its edges crisp (a light fill under a black outline).
#
# A page's background (svg: a fill over the whole page, painted first) is the
# paper: not drawn by its colour's layer, only when painted on purpose.
#
# How a shape's stroke or fill is drawn (part_group): its own paint, else the set
# (shapes grouped by hand) it is in, else its colour's. A shape closed but not filled
# in the SVG takes a fill from its own paint or its set's. A fill with `inset` keeps
# its tool's bleed inside its own edge (geometry.margin), as well as clear of inks on
# top of it; its border, if any, runs along that inner edge.
import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import MultiLineString, Polygon
from shapely.ops import unary_union

from . import svg
from .fonts import CAP, cap_height, line_text, outline_text, shape_outline
from .geometry import centerlines, fill, lines_of, margin, region, stroke_area
from .job import Group, Obj
from .raster import drawn, keys as raster_keys, raster_shapes
from .surface import make

WIDE = 1.5      # auto: strokes this many tool widths wide or more fill their area
SMALL = 2.5     # a shape less than this many tool widths across is a blob (but a dot, under half one)
LOST = 0.7      # too dense: the tool's line paints over this much of the space inside a shape
TEXT_MIN = 8    # auto: text whose caps are under this many tool widths is drawn in its line font


@dataclass
class Sliced:
    paths: dict[str, list[np.ndarray]]
    surface: object
    bounds: tuple | None            # x0, y0, x1, y1 of the paths, object mm
    texts: int = 0                  # <text> not drawn (yet)
    problems: list[str] = field(default_factory=list)
    cover: dict = field(default_factory=dict)   # tool ('': a mask) -> the area its opaque paint hides, object mm
    small: list[int] = field(default_factory=list)  # shapes too small or dense for their tool


def lost_detail(paths, width, ink=None):
    '''How much of a shape's inside a line `width` wide paints over: 0 nothing (a line,
    a dot), 1 all of it (a blob). ink: the area it really covers (the stroke as wide
    as the SVG has it, a fill's area); paths: its lines, object mm.'''
    lines = [p for p in paths if len(p) >= 2]
    if not lines:
        return 0.0
    g = MultiLineString(lines)
    x0, y0, x1, y1 = g.bounds
    across = max(x1 - x0, y1 - y0)
    if across < width / 2:
        return 0.0                  # a dot, meant as one
    hull = g.convex_hull
    if hull.area < 1e-9:
        return 0.0                  # straight
    r = np.asarray(shapely.minimum_rotated_rectangle(hull).exterior.coords)
    thick = min(math.dist(r[0], r[1]), math.dist(r[1], r[2]))
    if thick < width / 4:
        return 0.0                  # a line
    if across < SMALL * width:
        return 1.0                  # small: the pen makes a blob of it
    if thick < width:
        return 0.0                  # long and thinner than the pen: a line, only its wobble is lost
    inside = hull.difference(ink if ink is not None else g.buffer(0.01))
    if inside.area < 0.15 * hull.area:
        return 0.0
    pen = ink.buffer(width / 2) if ink is not None else g.buffer(width / 2)
    return inside.intersection(pen).area / inside.area


def cut(paths, geom):
    '''The paths (n, 2) less what lies in `geom`.'''
    if geom is None or geom.is_empty:
        return paths
    shapely.prepare(geom)
    out = []
    for p in paths:
        line = MultiLineString([p]) if len(p) >= 2 else None
        if line is None or not geom.intersects(line):
            out.append(p)
        elif not geom.covers(line):
            out += lines_of(line.difference(geom))
    return out


def mask_area(obj):
    '''The object's masks, object mm (scaled).'''
    polys = [shapely.make_valid(Polygon([(x * obj.scale, y * obj.scale) for x, y in m]))
             for m in obj.masks if len(m) >= 3]
    return unary_union(polys) if polys else None


def _rgb(hexc):
    return np.array([int(hexc[i:i + 2], 16) for i in (1, 3, 5)], float)


def lightness(hexc):
    '''0 black .. 1 white: how light an ink looks (relative luminance).'''
    try:
        return float(_rgb(hexc) @ (0.2126, 0.7152, 0.0722)) / 255
    except (ValueError, TypeError, IndexError):
        return 0.0


def goes_under(tool, over):
    '''Whether `tool`'s ink is drawn whole under the ink of `over` (a tool, None: a mask):
    with `layers`, a lighter ink isn't cut by a darker one; it plots first (emit).'''
    return (tool is not None and over is not None and tool.layers and over.id != tool.id
            and lightness(over.color) < lightness(tool.color) - 0.05)


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


def image_keys(drawing, obj, tools):
    '''The colour keys of the inks its images are made into (none when it leaves them out).'''
    return raster_keys(obj.raster, tools) if obj is not None and drawn(obj, drawing) else []


def default_groups(drawing, tools, obj=None):
    '''Each colour to the tool of the nearest colour; near white is the paper: a mask (not
    an image's ink: yellow is light, but it is ink). Fill and stroke settings left None:
    as the tool draws.'''
    out = {}
    inks = image_keys(drawing, obj, tools)
    for key in [*drawing.groups(), *(k for k in inks if k not in drawing.groups())]:
        colour = key.split(' ', 1)[1]
        if key not in inks and (_rgb(colour) @ (0.2126, 0.7152, 0.0722)) / 255 > 0.92:
            out[key] = Group(mask=True)
        else:
            out[key] = Group(tool=nearest_tool(colour, tools))
    return out


def groups_for(obj, drawing, tools):
    return {**default_groups(drawing, tools, obj), **obj.groups}


def fillable(sh):
    '''Whether a shape can take a fill: not a line (text in a line font), and filled in
    its SVG or closed.'''
    return not sh.line and (sh.fill is not None or any(sh.closed))


def sets_of(obj):
    '''Shape index -> the set it is in (the later one, when in two).'''
    return {i: st for st in obj.sets for i in st.shapes}


def part_group(obj, sh, part, groups, sets=None):
    '''How a shape's 'stroke' or 'fill' is drawn (a Group), None: it has none. Its own
    paint, else its set's, else its colour's (`groups`); a fill's inset and border as
    the shape or its set tweak them. A line shape draws with its fill's.'''
    colour = sh.stroke if part == 'stroke' else sh.fill
    if part == 'stroke' and not colour:
        return None
    if part == 'fill' and not sh.line and not fillable(sh):
        return None
    own = obj.shapes.get(str(sh.index))
    st = (sets if sets is not None else sets_of(obj)).get(sh.index)
    layer = groups.get(f'{part} {colour}') if colour and not sh.background else None      # the paper: only on purpose
    g = next((getattr(p, part) for p in (own, st) if p is not None and getattr(p, part) is not None), layer)
    if part == 'fill' and g is not None and not sh.line:
        tweak = {k: v for p in (st, own) if p is not None             # the shape's own over its set's
                 for k in ('inset', 'border') if (v := getattr(p, k)) is not None}
        if tweak:
            g = g.model_copy(update=tweak)
    return g


def image_shapes(d, obj, tools, problems=None):
    '''The images' lines, one shape for each ink, its pitch from the pen of its layer.'''
    if not drawn(obj, d):
        return []
    groups = groups_for(obj, d, tools)

    def pen_of(colour):
        g = groups.get(f'stroke {colour}')
        return tools.get(g.tool) if g is not None and g.tool else None
    return raster_shapes(d, obj, tools, pen_of, problems)


def text_font(run, spec, fonts):
    '''The uploaded source font file for a text run, or None.'''
    if fonts is None:
        return None
    if spec.font:
        return fonts.path(spec.font)
    info = fonts.match(run.family, run.weight, run.style)
    return fonts.path(info.file) if info else None


def text_shapes(d, obj, fonts, problems, tools=None):
    '''The drawing's <text> as shapes: the glyphs' outlines (source) or strokes (line).
    With the tools: in auto, text too small for its tool's line in its own font is
    drawn in its line font.'''
    out = []
    groups = groups_for(obj, d, tools) if tools else {}
    for run in d.texts:
        spec = obj.texts.get(str(run.index), obj.text)
        colour = run.fill or run.stroke
        if spec.mode == 'skip' or not colour or not run.text.strip():
            continue
        src = text_font(run, spec, fonts)
        mode = ('source' if src else 'line') if spec.mode == 'auto' else spec.mode
        g = groups.get(f'fill {colour}')
        tool = tools.get(g.tool) if g is not None and g.tool else None
        if mode == 'source' and spec.mode == 'auto' and tool is not None:
            m = run.matrix
            cap = cap_height(src, run.size) * abs(m[0] * m[3] - m[1] * m[2]) ** 0.5 * obj.scale
            if cap < TEXT_MIN * tool.width:
                problems.append(f'{obj.id}: "{run.text[:20]}" is {cap:.1f} mm high, too small for {tool.id}\'s '
                                f'{tool.width:g} mm line in its own font: drawn in {spec.line_font}')
                mode = 'line'
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
    shapes = sorted(d.shapes + text_shapes(d, obj, fonts, problems, tools) + image_shapes(d, obj, tools, problems),
                    key=lambda sh: sh.index)

    def local(p):
        return np.column_stack([p[:, 0] * s, (height - p[:, 1]) * s])

    def tool_of(g):
        if g is None or g.tool is None:
            return None
        if g.tool not in tools:
            problems.append(f'no tool {g.tool} (for {obj.id})')
            return None
        return tools[g.tool]

    def setting(g, t, k):
        '''A colour's own fill or stroke setting, else how its tool draws.'''
        v = getattr(g, k) if g is not None else None
        return v if v is not None else getattr(t, k)

    small = {}                      # tool -> shapes too small or dense for it

    def too_small(sh, t, paths, ink):
        '''Whether to leave this part out: too small or dense for the tool (its `small`).'''
        if t is None or t.small == 'draw' or sh.raster or lost_detail(paths, t.width, ink) < LOST:
            return False
        small.setdefault(t.id, set()).add(sh.index)
        return t.small == 'skip'

    items = []      # (shape, paths, stroke group, fill group, fill area, stroke area, wide, stroke covers, covers)
    sets = sets_of(obj)
    for sh in shapes:
        paths = [local(p) for p in sh.paths]
        sg = part_group(obj, sh, 'stroke', groups, sets)
        fg = part_group(obj, sh, 'fill', groups, sets)
        if sh.line:
            if too_small(sh, tool_of(fg), paths, None):
                fg = None
            items.append((sh, paths, None, fg, None, None, False, False, []))
            continue
        stroke_on = sg is not None and (sg.tool is not None or sg.mask)
        fill_on = fg is not None and (fg.tool is not None or fg.mask)
        fill_area = None
        if fill_on:
            rings = [p if c else np.vstack([p, p[:1]]) for p, c in zip(paths, sh.closed)]
            fill_area = region(rings, sh.rule)
            if too_small(sh, tool_of(fg), paths, fill_area):
                fg, fill_on, fill_area = None, False, None
        st = tool_of(sg)
        wide = st is not None and (setting(sg, st, 'stroke') == 'width'
                                   or (setting(sg, st, 'stroke') == 'auto' and sh.width * s >= st.width * WIDE))
        if st is not None and not wide and not sh.raster and too_small(sh, st, paths,
                                                     stroke_area(paths, sh.closed, max(sh.width * s, 0.02))):
            sg, stroke_on, st = None, False, None
        stroke_covers = obj.occlude and stroke_on and sh.stroke_opaque
        s_area = stroke_area(paths, sh.closed, sh.width * s, sh.cap, sh.join) if (wide or stroke_covers) else None
        covers = []                 # (area, tool id; '' a mask): what it hides of the shapes under it
        if obj.occlude and fill_on and (sh.fill_opaque or not sh.fill) and fill_area is not None:
            covers.append((fill_area, fg.tool or ''))
        if stroke_covers:
            covers.append((s_area, sg.tool or ''))
        items.append((sh, paths, sg, fg, fill_area, s_area, wide, stroke_covers, covers))

    flat = [(i, geom, t) for i, it in enumerate(items) for geom, t in it[-1] if not geom.is_empty]
    tree = shapely.STRtree([g for _, g, _ in flat]) if flat else None
    grown = {}

    def above(i, geom, tool):
        '''What the shapes painted after shape i hide of `geom`: what another tool
        (or a mask) draws there is kept the tool's `bleed` clear of.'''
        if tree is None or geom is None or geom.is_empty:
            return None
        bleed = tool.bleed if tool is not None else 0
        hits = []
        for j in tree.query(geom.buffer(bleed) if bleed > 0 else geom):
            k, g, t = flat[j]
            if k <= i or goes_under(tool, tools.get(t)):
                continue
            if bleed > 0 and t != tool.id:
                if (j, bleed) not in grown:
                    grown[(j, bleed)] = g.buffer(bleed)
                g = grown[(j, bleed)]
            hits.append(g)
        return unary_union(hits) if hits else None

    def less(geom, hide):
        return geom if hide is None else geom.difference(hide)

    out: dict[str, list[np.ndarray]] = {}
    for i, (sh, paths, sg, fg, fill_area, s_area, wide, stroke_covers, _) in enumerate(items):
        ft = tool_of(fg)
        if sh.line:
            if ft is not None:
                lines = centerlines(paths, sh.closed)
                out.setdefault(ft.id, []).extend(lines_of(less(lines, above(i, lines, ft))))
            continue
        st = tool_of(sg)
        if ft is not None and fill_area is not None:
            area = margin(fill_area, ft.bleed) if fg.inset else fill_area
            if stroke_covers and not goes_under(ft, st):
                gap = ft.bleed if st is None or st.id != ft.id else 0
                area = area.difference(s_area.buffer(gap) if gap > 0 else s_area)
            area = less(area, above(i, area, ft))
            out.setdefault(ft.id, []).extend(
                fill(area, ft.width, fg.spacing or ft.spacing, setting(fg, ft, 'fill'), setting(fg, ft, 'angle'),
                     setting(fg, ft, 'border')))
        if st is not None:
            if wide:
                area = less(s_area, above(i, s_area, st))
                out.setdefault(st.id, []).extend(fill(area, st.width, st.spacing, 'concentric', border=True))
            else:
                lines = centerlines(paths, sh.closed)
                out.setdefault(st.id, []).extend(lines_of(less(lines, above(i, lines, st))))

    for t, idx in small.items():
        how = 'left out' if tools[t].small == 'skip' else 'drawn anyway'
        problems.append(f'{obj.id}: {len(idx)} shape{"s" if len(idx) > 1 else ""} too small or dense for '
                        f'{t}\'s {tools[t].width:g} mm line, {how} (scale it up, or a finer pen)')

    masked = mask_area(obj)
    if masked is not None:
        out = {t: cut(ps, masked) for t, ps in out.items()}
    cover = {}
    if obj.occlude:
        by = {}
        for it in items:
            for geom, t in it[-1]:
                by.setdefault(t, []).append(geom)
        cover = {t: less(unary_union(gs), masked) for t, gs in by.items()}
        cover = {t: g for t, g in cover.items() if not g.is_empty}

    surface = make(obj.surface, root)
    draped = {t: [surface.drape(p) for p in ps] for t, ps in out.items() if ps}
    pts = [p for ps in draped.values() for p in ps]
    bounds = None
    if pts:
        a = np.vstack(pts)
        bounds = (*a[:, :2].min(axis=0), *a[:, :2].max(axis=0))
    return Sliced(draped, surface, bounds, len(d.texts), problems, cover,
                  sorted(set().union(*small.values())) if small else [])


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
