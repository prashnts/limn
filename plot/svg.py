# Limn plot - reading SVGs into shapes, by colour
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# svgelements resolves CSS, inherited styles, <use> and transforms. Each shape
# keeps its own stroke and fill colour, its paint order (for occlusion) and its
# subpaths, flattened to within `tolerance` mm. Coordinates are mm on the page,
# y down, as in the SVG. <text> is kept as text for the fonts to render.
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
import svgelements as S
from shapely.geometry import LinearRing, LineString

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


@dataclass
class RasterImage:
    '''An <image> of the drawing, kept to be made into lines (raster.py).'''
    index: int                  # paint order, as the shapes'
    id: str | None
    rgb: np.ndarray             # (h, w, 3) uint8, on white where it is transparent, at most MAX_PX across
    matrix: tuple               # its pixel (u, v) -> mm: x = a u + c v + e, y = b u + d v + f
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


@lru_cache(maxsize=16)
def _load_cached(path, mtime, tolerance):
    return load(path, tolerance)


def load_cached(path, tolerance=0.02) -> Drawing:
    '''load() of a file, again only when it changed. Don't change what it returns.'''
    path = Path(path)
    return _load_cached(str(path.resolve()), path.stat().st_mtime_ns, tolerance)


def load(src, tolerance=0.02) -> Drawing:
    svg = S.SVG.parse(src, reify=True, ppi=96)
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
                                 tuple(v * MM for v in (m.a, m.b, m.c, m.d, m.e, m.f)), fill, stroke))
            index += 1
            continue
        if isinstance(e, S.Image):         # (S.SVGImage is the same class)
            got = raster(e) if e.values.get('display') != 'none' else None
            if got is None:
                skipped['image (not embedded)'] += 1
            else:
                images.append(RasterImage(index, e.id, *got))
                index += 1
            continue
        if not isinstance(e, S.Shape):
            continue
        if e.values.get('visibility') == 'hidden' or e.values.get('display') == 'none':
            continue
        (sp, swhy), (fp, fwhy) = _paint_of(e, 'stroke'), _paint_of(e, 'fill')
        for why in {swhy, fwhy} - {None, 'var'}:
            skipped[f'{why} paint'] += 1
        stroke, stroke_opaque = paint(sp, _opacity(e.values, 'opacity', 'stroke-opacity'))
        fill, fill_opaque = paint(fp, _opacity(e.values, 'opacity', 'fill-opacity'))
        width = (e.stroke_width or 0) * MM
        if width <= 0:
            stroke = None
        if not stroke and not fill:
            continue
        shape = Shape(index, e.id, stroke, fill, width, stroke_opaque, fill_opaque,
                      e.values.get('fill-rule', 'nonzero'),
                      e.values.get('stroke-linecap', 'butt'), e.values.get('stroke-linejoin', 'miter'))
        path = e if isinstance(e, S.Path) else S.Path(e)
        for sub in path.as_subpaths():
            p, closed = _flatten(sub, tolerance)
            if p is not None:
                shape.paths.append(p)
                shape.closed.append(closed)
        if shape.paths:
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
