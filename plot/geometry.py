# Limn plot - areas, fills and lines
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Fills keep the ink inside the shape: the tool's centre runs half its width
# in from the edge, so the edge of the ink is the edge of the shape.
import hashlib
import math
from collections import OrderedDict

import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import LinearRing, LineString, MultiLineString, Polygon
from shapely.ops import polygonize, unary_union

CAPS = {'butt': 'flat', 'round': 'round', 'square': 'square'}
JOINS = {'miter': 'mitre', 'miter-clip': 'mitre', 'arcs': 'round', 'round': 'round', 'bevel': 'bevel'}


def lines_of(geom) -> list[np.ndarray]:
    '''Every line of `geom` as (n, 2) arrays, polygons as their rings, points as dots.'''
    if geom is None or geom.is_empty:
        return []
    t = geom.geom_type
    if t in ('LineString', 'LinearRing'):
        out = [np.asarray(geom.coords)[:, :2]]
    elif t == 'Polygon':
        out = [np.asarray(r.coords)[:, :2] for r in (geom.exterior, *geom.interiors)]
    elif t == 'Point':
        c = np.asarray(geom.coords)[:, :2]
        out = [np.vstack([c, c])]
    else:
        out = [p for g in geom.geoms for p in lines_of(g)]
    return [p for p in out if len(p) >= 2]


def region(rings, rule='nonzero'):
    '''The area closed rings enclose, by the SVG fill rule.'''
    rings = [r for r in rings if len(r) >= 4]
    if not rings:
        return Polygon()
    if len(rings) == 1:
        return shapely.make_valid(Polygon(rings[0])).buffer(0)
    polys = [shapely.make_valid(Polygon(r)) for r in rings]
    signs = [1 if LinearRing(r).is_ccw else -1 for r in rings]
    for p in polys:
        shapely.prepare(p)
    faces = polygonize(unary_union([LinearRing(r) for r in rings]))
    keep = []
    for f in faces:
        pt = f.representative_point()
        w = sum(s for p, s in zip(polys, signs) if p.contains(pt))
        if (w != 0) if rule == 'nonzero' else (w % 2):
            keep.append(f)
    return unary_union(keep)


def stroke_area(paths, closed, width, cap='butt', join='miter'):
    geoms = [LinearRing(p) if c else LineString(p) for p, c in zip(paths, closed)]
    return unary_union([g.buffer(width / 2, cap_style=CAPS.get(cap, 'flat'),
                                 join_style=JOINS.get(join, 'mitre'), mitre_limit=4) for g in geoms])


def centerlines(paths, closed):
    return MultiLineString([p for p in paths if len(p) >= 2])


def inset(area, d):
    return area.buffer(-d, join_style='mitre', mitre_limit=5) if d else area


def margin(area, d):
    '''`area` kept `d` mm inside its own edge, its corners rounded. A part too small for
    the rounding (it would lose a neck or a tip) keeps sharp corners; one too small for
    any margin stays as it is.'''
    if not d or d <= 0 or area is None or area.is_empty:
        return area
    out = []
    for part in polygons(area):
        sharp = part.buffer(-d, join_style='mitre', mitre_limit=5)
        if sharp.is_empty:
            out.append(part)
            continue
        smooth = part.buffer(-2 * d, join_style='round').buffer(d, join_style='round')
        same = not smooth.is_empty and len(polygons(smooth)) == len(polygons(sharp)) and smooth.area >= 0.8 * sharp.area
        out.append(smooth if same else sharp)
    return unary_union(out)


def polygons(geom):
    '''The polygons of a geometry, whatever it is.'''
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == 'Polygon':
        return [geom]
    return [p for g in getattr(geom, 'geoms', []) for p in polygons(g)]


def hatch(area, spacing, angle):
    '''Parallel lines `spacing` apart at `angle` degrees, clipped to `area`, on a
    grid that doesn't depend on the area (neighbouring shapes line up).'''
    if area.is_empty:
        return []
    r = affinity.rotate(area, -angle, origin=(0, 0))
    x0, y0, x1, y1 = r.bounds
    ks = np.arange(math.ceil(y0 / spacing), math.floor(y1 / spacing) + 1)
    if not len(ks):
        return []
    lines = MultiLineString([[(x0 - 1, k * spacing), (x1 + 1, k * spacing)] for k in ks])
    cut = r.intersection(lines)
    return lines_of(affinity.rotate(cut, angle, origin=(0, 0)))


def concentric(area, spacing):
    out, g, last = [], area, None
    while not g.is_empty:
        out += lines_of(g)
        last, g = g, inset(g, spacing)
    # What the last ring leaves in its middle, less than a step wide: half a step more
    if last is not None:
        out += lines_of(inset(last, spacing / 2))
    return out


def centerline(area, step):
    '''The middle of a thin area: the Voronoi edges of its outline that stay
    clear of the outline (the spurs into corners don't).'''
    edge = shapely.segmentize(area.boundary, step)
    pts = shapely.MultiPoint(shapely.get_coordinates(edge))
    edges = shapely.get_parts(shapely.voronoi_polygons(pts, only_edges=True))
    shapely.prepare(area)
    keep = [e for e in edges if area.contains(e) and area.boundary.distance(e) > step / 4]
    return lines_of(shapely.line_merge(MultiLineString(keep))) if keep else []


def thin(area, inner, width):
    '''What of `area` the tool's centre can't get into (thinner than the tool):
    drawn on its centre line, a dot when it is small.'''
    left = area if inner.is_empty else area.difference(
        inner.buffer(width / 2, join_style='mitre', mitre_limit=5).buffer(width * 0.05))
    out = []
    for piece in shapely.get_parts(left):
        if piece.area < (width * width) / 4:
            continue
        if piece.area < width * width:
            out += lines_of(piece.centroid)
        else:
            out += centerline(piece, width / 4) or lines_of(piece.centroid)
    return out


def link(paths, area, max_gap):
    '''Join consecutive paths whose gap is short and inside `area`: hatches become zigzags.'''
    if not paths:
        return []
    zone = area.buffer(1e-6)
    shapely.prepare(zone)
    out = [paths[0]]
    for p in paths[1:]:
        a, b = out[-1][-1], p[0]
        if math.dist(a, b) <= max_gap and zone.covers(LineString([a, b])):
            out[-1] = np.vstack([out[-1], p])
        else:
            out.append(p)
    return out


FILLS = OrderedDict()   # the fills made, by their area and settings: most of a slice's time,
FILLS_KEPT = 4096       # and the same again when only something else of the drawing changed


def fill(area, width, spacing, pattern='hatch', angle=45, border=True):
    '''Paths that cover `area` with a tool of `width`, lines `spacing` apart.'''
    if area.is_empty:
        return []
    k = (hashlib.sha1(shapely.to_wkb(area)).digest(), width, spacing, pattern, angle, border)
    if k in FILLS:
        FILLS.move_to_end(k)
    else:
        FILLS[k] = _fill(area, width, spacing, pattern, angle, border)
        if len(FILLS) > FILLS_KEPT:
            FILLS.popitem(last=False)
    return list(FILLS[k])


def _fill(area, width, spacing, pattern, angle, border):
    from .order import order
    inner = inset(area, width / 2)
    out = thin(area, inner, width)
    if inner.is_empty:
        return out
    out += lines_of(inner) if border else []
    if pattern == 'concentric':
        out += concentric(inset(inner, spacing) if border else inner, spacing)
    elif pattern in ('hatch', 'crosshatch'):
        lines = hatch(inner, spacing, angle)
        if pattern == 'crosshatch':
            lines += hatch(inner, spacing, angle + 90)
        start = lines[0][0] if lines else (0, 0)
        out += link(order(lines, start), inner, spacing * 2.5)
    return out
