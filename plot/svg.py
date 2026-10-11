# Limn plot - reading SVGs into shapes, by colour
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# svgelements resolves CSS, inherited styles, <use> and transforms. Each shape
# keeps its own stroke and fill colour, its paint order (for occlusion) and its
# subpaths, flattened to within `tolerance` mm. Coordinates are mm on the page,
# y down, as in the SVG. <text> is kept as text for the fonts to render.
#
# Before svgelements reads it, a pass over the XML (_prepare) finds what
# svgelements doesn't do: clip-paths and masks (each shape, text and picture
# keeps the region it shows through, `clip`; a mask is the area its shapes
# fill, not their luminance), and gradients: a shape filled with one becomes
# a picture of its gradient (RasterImage, `gradient`) clipped to the shape,
# drawn as pictures are (dither, lines, halftone: raster.py).
import io
import math
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
import svgelements as S
from shapely.geometry import LinearRing, LineString, Polygon
from shapely.ops import unary_union

from .geometry import region

MM = 25.4 / 96      # svgelements works in px at 96 ppi
STEP = 0.1          # mm between samples on curves, before simplifying


@dataclass
class Shape:
    index: int                  # paint order: later is on top
    id: str | None
    stroke: str | None          # '#rrggbb', None: not stroked
    fill: str | None
    width: float                # stroke width, mm
    stroke_opaque: bool
    fill_opaque: bool
    rule: str                   # 'nonzero' | 'evenodd'
    cap: str
    join: str
    paths: list[np.ndarray] = field(default_factory=list)     # (n, 2) mm
    closed: list[bool] = field(default_factory=list)
    line: bool = False          # drawn on its lines with its fill's tool (text in a line font)
    raster: bool = False        # an <image> made into lines (raster.py): never too small for its tool
    background: bool = False    # a fill over the whole page, painted first: the paper, not drawn unless painted
    clip: object = None         # shapely area, page mm: drawn only inside it (clip-path, mask), None: anywhere

    def keys(self):
        return [k for k in (self.stroke and f'stroke {self.stroke}', self.fill and f'fill {self.fill}') if k]


@dataclass
class TextRun:
    index: int
    id: str | None
    text: str
    family: str | None
    size: float                 # font size, x, y: in the text's own units,
    weight: str | None
    style: str | None
    anchor: str | None
    x: float
    y: float
    matrix: tuple               # which `matrix` (a b c d e f) takes to page mm
    fill: str | None
    stroke: str | None
    clip: object = None         # as Shape.clip


@dataclass
class RasterImage:
    '''An <image> of the drawing, kept to be made into lines (raster.py).'''
    index: int                  # paint order, as the shapes'
    id: str | None
    rgb: np.ndarray             # (h, w, 3) uint8, on white where it is transparent, at most MAX_PX across
    matrix: tuple               # its pixel (u, v) -> mm: x = a u + c v + e, y = b u + d v + f
    clip: object = None         # as Shape.clip; a gradient's: the shape it fills
    gradient: bool = False      # a shape's gradient fill, not an <image>
    alpha: np.ndarray | None = field(default=None, compare=False, repr=False)     # a gradient's (h, w) 0..1:
                                # only to show it (on the canvas); rgb is it on white, as the plot draws it
    cache: dict = field(default_factory=dict, compare=False, repr=False)    # raster.py's planes and lines

    @property
    def dark(self):
        '''(h, w) 0 white .. 1 black.'''
        if 'dark' not in self.cache:
            self.cache['dark'] = 1 - (self.rgb @ np.array([0.2126, 0.7152, 0.0722], np.float32)) / 255
        return self.cache['dark']

    def corners(self):
        h, w = self.rgb.shape[:2]
        a, b, c, d, e, f = self.matrix
        return np.array([(a * u + c * v + e, b * u + d * v + f) for u, v in ((0, 0), (w, 0), (w, h), (0, h))])

    def area(self):
        '''What of it shows: its frame, within its clip.'''
        frame = Polygon(self.corners())
        return frame if self.clip is None else frame.intersection(self.clip)


@dataclass
class Drawing:
    size: tuple[float, float]   # the page, mm
    shapes: list[Shape]
    texts: list[TextRun]
    skipped: dict[str, int]
    images: list[RasterImage] = field(default_factory=list)

    def groups(self):
        '''Stats per colour key ('stroke #rrggbb', 'fill #rrggbb').'''
        out = {}
        for s in self.shapes:
            for key in s.keys():
                g = out.setdefault(key, {'shapes': 0, 'length': 0.0, 'widths': set()})
                g['shapes'] += 1
                g['length'] += sum(float(np.hypot(*np.diff(p, axis=0).T).sum()) for p in s.paths)
                if key.startswith('stroke'):
                    g['widths'].add(round(s.width, 3))
        for t in self.texts:
            colour = t.fill or t.stroke
            if colour:
                g = out.setdefault(f'fill {colour}', {'shapes': 0, 'length': 0.0, 'widths': set()})
                g['shapes'] += 1
                g['texts'] = g.get('texts', 0) + 1
        return out


def _opacity(values, *names):
    a = 1.0
    for n in names:
        try:
            a *= float(values.get(n, 1))
        except (TypeError, ValueError):
            pass
    return a


def paint(color, alpha):
    '''('#rrggbb' or None, opaque) of a paint.'''
    if color is None or color.value is None:
        return None, False
    a = alpha * (color.opacity if color.opacity is not None else 1.0)
    if a < 0.02:
        return None, False
    return color.hexrgb.lower(), a > 0.98


VAR = re.compile(r'^\s*var\(\s*--[\w-]+\s*(?:,\s*(.+?))?\s*\)\s*$')


def _paint_of(e, name):
    '''(paint, why it was left out): a CSS var() takes its fallback (svgelements reads any var()
    as black); a url() (a gradient, a pattern) can't be drawn: None, 'pattern'.'''
    raw = e.values.get(name)
    if isinstance(raw, str):
        m = VAR.match(raw)
        if m:
            return (S.Color(m.group(1)) if m.group(1) and not m.group(1).startswith(('var(', 'url(')) else None), 'var'
        if raw.strip().startswith('url('):
            return None, 'pattern'
    return getattr(e, name), None


def _background(shape, size):
    '''Is it the page's background: a fill, no stroke, one closed outline over nearly the whole page.'''
    if not shape.fill or shape.stroke or len(shape.paths) != 1 or not shape.closed[0] or len(shape.paths[0]) > 6:
        return False
    p = shape.paths[0]
    (x0, y0), (x1, y1) = p.min(axis=0), p.max(axis=0)
    w, h = size
    return w > 0 and h > 0 and (min(x1, w) - max(x0, 0)) * (min(y1, h) - max(y0, 0)) >= 0.97 * w * h


def _flatten(sub, tolerance):
    pts, closed = [], False
    for seg in sub:
        if isinstance(seg, S.Move):
            pts = [np.array([[seg.end.x, seg.end.y]])]
        elif isinstance(seg, S.Close):
            closed = True
            if pts and seg.end is not None:
                pts.append(np.array([[seg.end.x, seg.end.y]]))
        elif isinstance(seg, S.Line):
            pts.append(np.array([[seg.end.x, seg.end.y]]))
        else:
            # Length from a coarse polyline: close enough to pick the step
            coarse = seg.npoint(np.linspace(0, 1, 17))
            length = np.hypot(*np.diff(coarse, axis=0).T).sum() * MM
            n = max(2, math.ceil(length / STEP))
            pts.append(np.asarray(seg.npoint(np.linspace(0, 1, n + 1)[1:]), float))
    a = np.vstack(pts) * MM if pts else np.zeros((0, 2))
    if len(a) < 2:
        return None, closed
    if closed and len(a) >= 4:
        if np.hypot(*(a[0] - a[-1])) > 1e-9:
            a = np.vstack([a, a[:1]])
        s = np.asarray(LinearRing(a).simplify(tolerance).coords)
    else:
        closed = False if len(a) < 4 else closed
        s = np.asarray(LineString(a).simplify(tolerance).coords)
    return (s if len(s) >= 2 else a), closed


MAX_PX = 1600      # an image's pixels kept, across: about a 0.05 mm pen's line over an A5 page


def raster(e):
    '''An <image> -> (rgb, matrix), None when it can't be read (not embedded, not a picture).'''
    try:
        e.load()
    except Exception:
        return None
    im = e.image
    if im is None:
        return None
    from PIL import Image as PILImage
    im = im.convert('RGBA')
    w, h = im.size
    k = max(w, h) / MAX_PX
    if k > 1:
        im = im.resize((max(1, round(w / k)), max(1, round(h / k))), PILImage.BOX)
    white = PILImage.new('RGBA', im.size, (255, 255, 255, 255))
    rgb = PILImage.alpha_composite(white, im).convert('RGB')
    sx, sy = w / rgb.width, h / rgb.height                  # its pixels -> the image's own (load() puts its
    m = e.transform                                          # viewbox and placement in its transform)
    return np.asarray(rgb, np.uint8), (m.a * sx * MM, m.b * sx * MM, m.c * sy * MM, m.d * sy * MM, m.e * MM, m.f * MM)


IMAGE = re.compile(rb'<(?:[\w-]+:)?image\b(?:[^>"\']|"[^"]*"|\'[^\']*\')*?(?:/>|>.*?</(?:[\w-]+:)?image\s*>)', re.S)


def strip_images(data: bytes) -> tuple[bytes, int]:
    '''The SVG without its <image>s (a plotter can't draw them, and they make the file
    heavy) -> (svg, how many went).'''
    out, n = IMAGE.subn(b'', data)
    return out, n

# --- before svgelements: clip-paths, masks, gradients ---------------------------------------

XLINK = '{http://www.w3.org/1999/xlink}href'
URL = re.compile(r'url\(\s*["\']?#([^"\')\s]+)["\']?\s*\)')
NOT_DRAWN = {'defs', 'mask', 'clipPath', 'symbol', 'pattern', 'linearGradient', 'radialGradient', 'marker',
             'style', 'title', 'desc', 'metadata', 'filter'}
SHAPE_TAGS = {'path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon', 'use', 'image', 'text'}
GRADIENT_PX = 400           # a gradient's picture, pixels across: it is smooth, the dither's grid averages it


def _tag(el):
    return el.tag.rsplit('}', 1)[-1] if isinstance(el.tag, str) else ''


def _attr(el, name):
    '''An attribute, or the same in its style="".'''
    v = el.get(name)
    for part in (el.get('style') or '').split(';'):
        k, _, val = part.partition(':')
        if k.strip() == name:
            v = val.strip()
    return v


def _m(m):
    return tuple(float(x) for x in (m.a, m.b, m.c, m.d, m.e, m.f))


@dataclass
class Prepared:
    data: bytes                 # the SVG for svgelements: clip-paths and masks out (their shapes aren't drawn),
                                # each element tagged: data-limn-clip (its clips, a key of `clips`),
                                # data-limn-ctm (its own user space -> the root's, a b c d e f)
    clips: dict                 # key -> [(clip-path or mask element, its kind, ctm)]
    ids: dict                   # id -> element (gradients, clips)
    root: object


def _prepare(data: bytes):
    '''-> Prepared, None when the XML can't be read here (svgelements reads it as it is).'''
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None
    ids = {el.get('id'): el for el in root.iter() if el.get('id')}
    parents = {c: p for p in root.iter() for c in p}
    chains, clips = {}, {}

    def walk(el, ctm, chain):
        tag = _tag(el)
        if tag in NOT_DRAWN:
            return
        if el is not root and el.get('transform'):
            ctm = S.Matrix(el.get('transform')) * ctm
        own = False
        for attr, kind in (('clip-path', 'clip'), ('mask', 'mask')):
            m = URL.search(_attr(el, attr) or '')
            ref = ids.get(m.group(1)) if m else None
            if ref is not None and _tag(ref) == ('clipPath' if kind == 'clip' else 'mask'):
                chain = chain + ((m.group(1), kind, _m(ctm)),)
                own = True
        if own:
            key = chains.setdefault(chain, f'c{len(chains)}')
            clips[key] = [(ids[i], kind, m) for i, kind, m in chain]
            el.set('data-limn-clip', key)
        if tag == 'image':
            # Sketch writes a picture flipped in its app as a <g transform> inside the <image>: browsers
            # ignore it (an <image> has no children), Sketch shows the picture flipped, and what is drawn
            # over it is drawn over the flipped picture. Flipped here too (its mask, set above, not)
            flips = [c.get('transform') for c in el if _tag(c) == 'g' and c.get('transform')]
            for c in list(el):
                el.remove(c)
            if flips:
                el.set('transform', ' '.join(x for x in (el.get('transform'), *flips) if x))
        if tag in SHAPE_TAGS:
            m = ctm
            if tag == 'use':
                ref = ids.get((el.get(XLINK) or el.get('href') or '').lstrip('#'))
                m = S.Matrix(f'translate({el.get("x", "0") or 0},{el.get("y", "0") or 0})') * ctm
                if ref is not None and ref.get('transform'):
                    m = S.Matrix(ref.get('transform')) * m
            el.set('data-limn-ctm', ' '.join(f'{v:.9g}' for v in _m(m)))
        for c in el:
            walk(c, ctm, chain)

    try:
        walk(root, S.Matrix(), ())
    except (ValueError, TypeError):
        return None
    for el in list(root.iter()):
        if _tag(el) in ('mask', 'clipPath') and el in parents:
            parents[el].remove(el)
    ET.register_namespace('', 'http://www.w3.org/2000/svg')
    ET.register_namespace('xlink', 'http://www.w3.org/1999/xlink')
    return Prepared(ET.tostring(root), clips, ids, root)


def _clip_area(prep, el, kind, ctm, tolerance):
    '''The area a clip-path or a mask lets through, page mm; None: anywhere (one in the
    object's bounding box: not read).'''
    if (el.get('clipPathUnits') if kind == 'clip' else el.get('maskContentUnits')) == 'objectBoundingBox':
        return None
    doc = ET.Element(prep.root.tag, dict(prep.root.attrib))
    for d in prep.root.iter():
        if _tag(d) == 'defs':
            doc.append(d)
    # its own presentation attributes (Sketch's <mask fill="white">) go to what is in it
    own = {k: v for k, v in el.attrib.items() if k not in ('id', 'x', 'y', 'width', 'height', 'transform',
                                                          'maskUnits', 'maskContentUnits', 'clipPathUnits')}
    g = ET.SubElement(doc, prep.root.tag[:-3] + 'g' if prep.root.tag.endswith('svg') else 'g',
                      {**own, 'transform': 'matrix({},{},{},{},{},{})'.format(*ctm)})
    for c in el:
        g.append(c)
    try:
        svg = S.SVG.parse(io.BytesIO(ET.tostring(doc)), reify=True, ppi=96)
    except Exception:
        return None
    areas = []
    for e in svg.elements():
        if not isinstance(e, S.Shape):
            continue
        if kind == 'mask':          # what it fills, light (white lets through, black hides)
            fill, _ = paint(e.fill, _opacity(e.values, 'opacity', 'fill-opacity'))
            if fill is None or sum(int(fill[i:i + 2], 16) for i in (1, 3, 5)) < 3 * 64:
                continue
        rings = []
        for sub in (e if isinstance(e, S.Path) else S.Path(e)).as_subpaths():
            pts, _ = _flatten(sub, tolerance)
            if pts is not None and len(pts) >= 3:
                rings.append(pts if np.allclose(pts[0], pts[-1]) else np.vstack([pts, pts[:1]]))
        rule = e.values.get('clip-rule' if kind == 'clip' else 'fill-rule', 'nonzero')
        a = region(rings, rule)
        if not a.is_empty:
            areas.append(a)
    return unary_union(areas) if areas else Polygon()


def _clips(prep, tolerance):
    '''key -> the area its clips let through, all of them (page mm).'''
    one, out = {}, {}
    for key, chain in prep.clips.items():
        area = None
        for el, kind, ctm in chain:
            k = (id(el), kind, ctm)
            if k not in one:
                one[k] = _clip_area(prep, el, kind, ctm, tolerance)
            if one[k] is not None:
                area = one[k] if area is None else area.intersection(one[k])
        out[key] = area
    return out


def _gradient(el, ids):
    '''A linear or radial gradient, its attributes and stops taken through its hrefs.'''
    chain, seen = [], set()
    while el is not None and id(el) not in seen and _tag(el) in ('linearGradient', 'radialGradient'):
        chain.append(el)
        seen.add(id(el))
        el = ids.get((el.get(XLINK) or el.get('href') or '').lstrip('#') or None)
    if not chain:
        return None
    get = lambda k, d=None: next((c.get(k) for c in chain if c.get(k) is not None), d)
    stops = next(([x for x in c if _tag(x) == 'stop'] for c in chain if any(_tag(x) == 'stop' for x in c)), [])
    out, last = [], 0.0
    for st in stops:
        off = (st.get('offset') or '0').strip()
        off = float(off[:-1]) / 100 if off.endswith('%') else float(off or 0)
        last = max(last, min(1.0, max(0.0, off)))
        try:
            c = S.Color(_attr(st, 'stop-color') or 'black')
            rgb = (c.red, c.green, c.blue) if c.value is not None else (0, 0, 0)
            alpha = (c.opacity if c.opacity is not None else 1.0) * float(_attr(st, 'stop-opacity') or 1)
        except (ValueError, TypeError):
            rgb, alpha = (0, 0, 0), 1.0
        out.append((last, np.array(rgb, float), alpha))
    if not out:
        return None
    return {'kind': _tag(chain[0]), 'get': get, 'stops': out,
            'units': get('gradientUnits', 'objectBoundingBox'),
            'transform': S.Matrix(get('gradientTransform')) if get('gradientTransform') else S.Matrix(),
            'spread': get('spreadMethod', 'pad')}


def _length(v, default, bbox, ref):
    v = str(v if v is not None else default).strip()
    if v.endswith('%'):
        return float(v[:-1]) / 100 * (1 if bbox else ref)
    m = re.match(r'[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?', v)
    return float(m.group(0)) if m else 0.0


def _mid(g):
    '''A gradient as one colour, on white: its stops' average.'''
    c = np.mean([a * rgb + (1 - a) * 255 for _, rgb, a in g['stops']], axis=0)
    return '#' + ''.join(f'{int(round(v)):02x}' for v in c)


def _gradient_picture(g, to_px, paths, area, alpha, view):
    '''The gradient over `area` (page mm), on white -> (rgb, matrix, alpha) as RasterImage's.
    to_px: the shape's user space -> page px; paths: its outline (mm), for its bounding box.'''
    x0, y0, x1, y1 = area.bounds
    px = max(max(x1 - x0, y1 - y0) / GRADIENT_PX, 0.005)
    nu, nv = max(1, math.ceil((x1 - x0) / px)), max(1, math.ceil((y1 - y0) / px))
    X, Y = np.meshgrid(x0 + (np.arange(nu) + 0.5) * px, y0 + (np.arange(nv) + 0.5) * px)
    bbox = g['units'] != 'userSpaceOnUse'
    full = g['transform']
    if bbox:
        inv = ~to_px
        pts = np.vstack(paths) / MM
        lx = inv.a * pts[:, 0] + inv.c * pts[:, 1] + inv.e
        ly = inv.b * pts[:, 0] + inv.d * pts[:, 1] + inv.f
        bw, bh = max(np.ptp(lx), 1e-9), max(np.ptp(ly), 1e-9)
        full = full * S.Matrix(bw, 0, 0, bh, lx.min(), ly.min())
    full = full * to_px
    inv = ~full
    U, V = X / MM, Y / MM
    gx, gy = inv.a * U + inv.c * V + inv.e, inv.b * U + inv.d * V + inv.f
    get, (vw, vh) = g['get'], view
    if g['kind'] == 'linearGradient':
        ax, ay = _length(get('x1'), '0%', bbox, vw), _length(get('y1'), '0%', bbox, vh)
        bx, by = _length(get('x2'), '100%', bbox, vw), _length(get('y2'), '0%', bbox, vh)
        dx, dy = bx - ax, by - ay
        t = ((gx - ax) * dx + (gy - ay) * dy) / max(dx * dx + dy * dy, 1e-12)
    else:
        ref = math.sqrt((vw * vw + vh * vh) / 2)
        cx, cy = _length(get('cx'), '50%', bbox, vw), _length(get('cy'), '50%', bbox, vh)
        r = max(_length(get('r'), '50%', bbox, ref), 1e-9)
        fx, fy = _length(get('fx'), get('cx') or '50%', bbox, vw), _length(get('fy'), get('cy') or '50%', bbox, vh)
        # the circle from the focus (radius 0) out to (c, r) that goes through the point: t
        qx, qy, ddx, ddy = gx - fx, gy - fy, cx - fx, cy - fy
        a = ddx * ddx + ddy * ddy - r * r
        b = qx * ddx + qy * ddy
        cq = qx * qx + qy * qy
        if abs(a) < 1e-12:
            t = cq / np.where(np.abs(2 * b) < 1e-12, 1e-12, 2 * b)
        else:
            disc = np.sqrt(np.maximum(b * b - a * cq, 0))
            t = np.maximum((b - disc) / a, (b + disc) / a) if a > 0 else (b - disc) / a
    if g['spread'] == 'repeat':
        t = t - np.floor(t)
    elif g['spread'] == 'reflect':
        t = 1 - np.abs(np.mod(t, 2) - 1)
    t = np.clip(t, 0, 1)
    offs = [o for o, _, _ in g['stops']]
    a = np.interp(t, offs, [s[2] for s in g['stops']]) * alpha
    rgb = np.stack([np.interp(t, offs, [s[1][i] for s in g['stops']]) for i in range(3)], axis=-1)
    out = a[..., None] * rgb + (1 - a[..., None]) * 255
    return np.clip(out + 0.5, 0, 255).astype(np.uint8), (px, 0.0, 0.0, px, x0, y0), a.astype(np.float32)


@lru_cache(maxsize=16)
def _load_cached(path, mtime, tolerance):
    return load(path, tolerance)


def load_cached(path, tolerance=0.02) -> Drawing:
    '''load() of a file, again only when it changed. Don't change what it returns.'''
    path = Path(path)
    return _load_cached(str(path.resolve()), path.stat().st_mtime_ns, tolerance)


def load(src, tolerance=0.02) -> Drawing:
    data = src.read() if hasattr(src, 'read') else Path(src).read_bytes()
    prep = _prepare(data)
    svg = S.SVG.parse(io.BytesIO(prep.data if prep else data), reify=True, ppi=96)
    clips = _clips(prep, tolerance) if prep else {}
    root = S.Matrix(svg.viewbox_transform) if getattr(svg, 'viewbox_transform', None) else S.Matrix()
    vb = svg.viewbox
    view = (vb.width, vb.height) if vb is not None and vb.width else (svg.width or 100, svg.height or 100)
    clip_of = lambda e: clips.get(e.values.get('data-limn-clip'))
    shapes, texts, images, skipped = [], [], [], defaultdict(int)
    index = 0
    for e in svg.elements():
        if isinstance(e, S.Text):
            if not (e.text or '').strip():      # the whitespace between <tspan>s: nothing to draw
                index += 1                      # (its index kept: the shapes after it keep theirs)
                continue
            fill, _ = paint(e.fill, _opacity(e.values, 'opacity', 'fill-opacity'))
            stroke, _ = paint(e.stroke, _opacity(e.values, 'opacity', 'stroke-opacity'))
            m = e.transform
            texts.append(TextRun(index, e.id, e.text or '', e.font_family, e.font_size or 16,
                                 e.font_weight, e.values.get('font-style'), e.values.get('text-anchor'),
                                 e.x or 0, e.y or 0,
                                 tuple(v * MM for v in (m.a, m.b, m.c, m.d, m.e, m.f)), fill, stroke, clip_of(e)))
            index += 1
            continue
        if isinstance(e, S.Image):         # (S.SVGImage is the same class)
            got = raster(e) if e.values.get('display') != 'none' else None
            if got is None:
                skipped['image (not embedded)'] += 1
            else:
                images.append(RasterImage(index, e.id, *got, clip=clip_of(e)))
                index += 1
            continue
        if not isinstance(e, S.Shape):
            continue
        if e.values.get('visibility') == 'hidden' or e.values.get('display') == 'none':
            continue
        (sp, swhy), (fp, fwhy) = _paint_of(e, 'stroke'), _paint_of(e, 'fill')
        grads = {}                          # 'stroke'/'fill' -> its gradient
        for name, why in (('stroke', swhy), ('fill', fwhy)):
            if why == 'pattern' and prep:
                m = URL.search(e.values.get(name) or '')
                g = _gradient(prep.ids.get(m.group(1)), prep.ids) if m else None
                if g is not None:
                    grads[name] = g
        if 'stroke' in grads:               # a gradient outline: in its middle colour
            sp, swhy = S.Color(_mid(grads['stroke'])), None
        for why in {swhy, fwhy if 'fill' not in grads else None} - {None, 'var'}:
            skipped[f'{why} paint'] += 1
        stroke, stroke_opaque = paint(sp, _opacity(e.values, 'opacity', 'stroke-opacity'))
        fill, fill_opaque = paint(fp, _opacity(e.values, 'opacity', 'fill-opacity'))
        width = (e.stroke_width or 0) * MM
        if width <= 0:
            stroke = None
        if not stroke and not fill and 'fill' not in grads:
            continue
        shape = Shape(index, e.id, stroke, fill, width, stroke_opaque, fill_opaque,
                      e.values.get('fill-rule', 'nonzero'),
                      e.values.get('stroke-linecap', 'butt'), e.values.get('stroke-linejoin', 'miter'),
                      clip=clip_of(e))
        # A shape svgelements can't reify (an ellipse turned, a rect skewed) keeps its transform
        # apart: abs() applies it, or it is drawn where it is in its own user space
        path = e if isinstance(e, S.Path) else abs(S.Path(e))
        for sub in path.as_subpaths():
            p, closed = _flatten(sub, tolerance)
            if p is not None:
                shape.paths.append(p)
                shape.closed.append(closed)
        if not shape.paths:
            continue
        if 'fill' in grads:                 # its fill a picture of the gradient, under its outline
            rings = [p if c else np.vstack([p, p[:1]]) for p, c in zip(shape.paths, shape.closed)]
            area = region(rings, shape.rule)
            if shape.clip is not None:
                area = area.intersection(shape.clip)
            if not area.is_empty and area.area > 1e-6:
                ctm = [float(v) for v in (e.values.get('data-limn-ctm') or '1 0 0 1 0 0').split()]
                rgb, matrix, alpha = _gradient_picture(grads['fill'], S.Matrix(*ctm) * root, shape.paths, area,
                                                       _opacity(e.values, 'opacity', 'fill-opacity'), view)
                images.append(RasterImage(index, e.id, rgb, matrix, clip=area, gradient=True, alpha=alpha))
                index += 1
                shape.index = index
            if not stroke:
                continue
        shapes.append(shape)
        index += 1
    w, h = svg.width, svg.height
    if not w or not h:
        pts = np.vstack([p for s in shapes for p in s.paths]) if shapes else np.zeros((1, 2))
        w, h = pts[:, 0].max() / MM, pts[:, 1].max() / MM
    # Only with something drawn over it: a lone square that fills its page is the drawing
    over = bool(shapes) and len(shapes) + len(texts) + len(images) > 1
    if over and _background(shapes[0], (w * MM, h * MM)) and not (texts and texts[0].index < shapes[0].index) \
            and not (images and images[0].index < shapes[0].index):
        shapes[0].background = True
        skipped['background'] += 1
    return Drawing((w * MM, h * MM), shapes, texts, dict(skipped), images)
