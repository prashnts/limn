# Limn plot - the text of a drawing: in its own font, or in a line font
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Source fonts (TTF/OTF) are uploaded to the store: a text whose font-family
# is there is shaped with HarfBuzz (kerning, ligatures) and comes out as the
# glyphs' outlines, closed, to be filled like any other shape.
#
# Line fonts are single strokes: the Hershey fonts, or SVG fonts (EMS fonts,
# Inkscape's Hershey Text) uploaded to the store. A text drawn in one takes the
# place of the original: its caps as high as the source font's (0.7 of the
# font size without it), and with fit='width', as wide as the original too.
#
# Everything comes out in page mm (y down), like svg.load().
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import svgelements as S
import uharfbuzz as hb
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont
from HersheyFonts import HersheyFonts

from .svg import MM, _flatten

HERSHEY = ['futural', 'futuram', 'rowmans', 'rowmand', 'rowmant', 'scripts', 'scriptc', 'cursive',
           'timesr', 'timesrb', 'timesi', 'timesib', 'gothiceng', 'gothicger', 'gothicita', 'greek', 'cyrillic']
OUTLINE = ('.ttf', '.otf')
CAP = 0.7       # cap height per font size, when there is no source font to ask


@dataclass
class FontInfo:
    file: str
    kind: str           # 'outline' | 'line'
    family: str
    style: str
    weight: int
    italic: bool


def _families(css):
    return [f.strip().strip('\'"').lower() for f in (css or '').split(',') if f.strip()]


def _weight(w):
    try:
        return int(w)
    except (TypeError, ValueError):
        return {'bold': 700, 'bolder': 700, 'lighter': 300}.get(str(w).lower(), 400)


@lru_cache(maxsize=64)
def _ttfont(path, mtime):
    return TTFont(path, fontNumber=0, lazy=True)


def ttfont(path):
    return _ttfont(str(path), Path(path).stat().st_mtime_ns)


def outline_info(path) -> FontInfo:
    f = ttfont(path)
    name = f['name']
    os2 = f['OS/2'] if 'OS/2' in f else None
    style = name.getBestSubFamilyName() or 'Regular'
    italic = bool(os2 and os2.fsSelection & 1) or 'italic' in style.lower() or 'oblique' in style.lower()
    return FontInfo(Path(path).name, 'outline', name.getBestFamilyName() or Path(path).stem, style,
                    os2.usWeightClass if os2 else 400, italic)


def _svg_font(path):
    '''units per em, cap height, default advance, {char: (d, advance)} of an SVG font.'''
    root = ET.parse(path).getroot()
    local = lambda e: e.tag.rsplit('}', 1)[-1]
    font = next(e for e in root.iter() if local(e) == 'font')
    face = next((e for e in font if local(e) == 'font-face'), None)
    upem = float(face.get('units-per-em', 1000)) if face is not None else 1000.0
    cap = float(face.get('cap-height', upem * CAP)) if face is not None else upem * CAP
    family = (face.get('font-family') if face is not None else None) or Path(path).stem
    adv = float(font.get('horiz-adv-x', upem / 2))
    glyphs = {}
    for g in font:
        if local(g) == 'glyph' and g.get('unicode'):
            glyphs[g.get('unicode')] = (g.get('d', ''), float(g.get('horiz-adv-x', adv)))
    return upem, cap, adv, glyphs, family


def line_info(path) -> FontInfo:
    return FontInfo(Path(path).name, 'line', _svg_font(path)[4], 'Regular', 400, False)


class FontStore:
    '''The fonts uploaded to the server: a folder of TTF/OTF and SVG fonts.'''

    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)

    def fonts(self) -> list[FontInfo]:
        out = []
        for p in sorted(self.folder.iterdir()):
            try:
                if p.suffix.lower() in OUTLINE:
                    out.append(outline_info(p))
                elif p.suffix.lower() == '.svg':
                    out.append(line_info(p))
            except Exception:
                continue
        return out

    def add(self, filename, data: bytes) -> FontInfo:
        name = re.sub(r'[^\w.\- ]', '_', Path(filename).name)
        if Path(name).suffix.lower() not in (*OUTLINE, '.svg'):
            raise ValueError(f'{name}: a font is .ttf, .otf, or an SVG font')
        path = self.folder / name
        path.write_bytes(data)
        try:
            return outline_info(path) if path.suffix.lower() in OUTLINE else line_info(path)
        except Exception as e:
            path.unlink()
            raise ValueError(f'{name}: not a font ({e})')

    def remove(self, name):
        (self.folder / Path(name).name).unlink(missing_ok=True)

    def path(self, name):
        p = self.folder / Path(name).name
        return p if p.exists() else None

    def signature(self):
        return sorted((p.name, p.stat().st_mtime_ns) for p in self.folder.iterdir())

    def match(self, css_family, weight=None, style=None) -> FontInfo | None:
        '''The uploaded source font for a CSS font-family, weight and style.'''
        want_w, want_i = _weight(weight), (style or '').lower() in ('italic', 'oblique')
        fonts = [f for f in self.fonts() if f.kind == 'outline']
        for fam in _families(css_family):
            same = [f for f in fonts if f.family.lower() == fam or Path(f.file).stem.lower() == fam]
            if same:
                return min(same, key=lambda f: (f.italic != want_i, abs(f.weight - want_w)))
        return None


def _to_page(run):
    '''Text units to page px, for _flatten (which goes px -> mm).'''
    a, b, c, d, e, f = run.matrix
    return S.Matrix(a / MM, b / MM, c / MM, d / MM, e / MM, f / MM)


def _anchor(run, width):
    return {'middle': -width / 2, 'end': -width}.get(run.anchor or 'start', 0.0)


def shape_outline(path, text, size):
    '''HarfBuzz: [(glyph name, x, y)] in text units (y down) and the advance.'''
    f = ttfont(path)
    blob = hb.Blob.from_file_path(str(path))
    face = hb.Face(blob)
    font = hb.Font(face)
    k = size / face.upem
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf, {'kern': True, 'liga': True})
    order = f.getGlyphOrder()
    out, x = [], 0
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        out.append((order[info.codepoint], (x + pos.x_offset) * k, -pos.y_offset * k))
        x += pos.x_advance
    return out, x * k, k


def cap_height(path, size):
    f = ttfont(path)
    upem = f['head'].unitsPerEm
    os2 = f['OS/2'] if 'OS/2' in f else None
    cap = getattr(os2, 'sCapHeight', 0) if os2 else 0
    if not cap:
        gs = f.getGlyphSet()
        name = f.getBestCmap().get(ord('H'))
        if name:
            pen = BoundsPen(gs)
            gs[name].draw(pen)
            cap = pen.bounds[3] if pen.bounds else 0
    return (cap or upem * CAP) * size / upem


def outline_text(run, path, tolerance=0.02):
    '''The glyphs of `run` in the font at `path`: closed rings, page mm.'''
    glyphs, width, k = shape_outline(path, run.text, run.size)
    gs = ttfont(path).getGlyphSet()
    page = _to_page(run)
    dx = run.x + _anchor(run, width)
    rings = []
    for name, gx, gy in glyphs:
        pen = SVGPathPen(gs)
        gs[name].draw(pen)
        d = pen.getCommands()
        if not d:
            continue
        p = (S.Path(d) * S.Matrix(k, 0, 0, -k, dx + gx, run.y + gy) * page).reify()
        for sub in p.as_subpaths():
            pts, _ = _flatten(sub, tolerance)
            if pts is not None and len(pts) >= 3:
                rings.append(pts if np.allclose(pts[0], pts[-1]) else np.vstack([pts, pts[:1]]))
    return rings, width


@lru_cache(maxsize=32)
def _hershey(name):
    h = HersheyFonts()
    h.load_default_font(name)
    h.normalize_rendering(100)
    ys = np.vstack([np.array(s) for s in h.strokes_for_text('H')])[:, 1]
    return h, float(ys.min()), float(ys.max() - ys.min())       # baseline, cap height


def _line_strokes(font, text, store):
    '''Strokes of `text` in a line font, (x, y) y down from the baseline, and cap height, width.'''
    if font in HERSHEY:
        h, base, cap = _hershey(font)
        strokes = [np.array([(x, -(y - base)) for x, y in s], float) for s in h.strokes_for_text(text)]
        pts = [s for s in strokes if len(s)]
        width = max((s[:, 0].max() for s in pts), default=0.0)
        return pts, cap, width
    path = store.path(font) if store else None
    if path is None:
        raise ValueError(f'no line font {font!r}')
    upem, cap, adv, glyphs, _ = _svg_font(path)
    out, x = [], 0.0
    for ch in text:
        d, a = glyphs.get(ch, ('', adv))
        if d:
            p = (S.Path(d) * S.Matrix(1, 0, 0, -1, x, 0)).reify()
            for sub in p.as_subpaths():
                pts, _ = _flatten(sub, 0.02 * upem)
                if pts is not None:
                    out.append(pts / MM)
        x += a
    return out, cap, x


def line_text(run, font, cap_mm_units, width_units=None, store=None):
    '''`run` in a line font: strokes in page mm. cap_mm_units: the caps' height in text units;
    width_units: stretch to this width (text units), None keeps the font's proportions.'''
    strokes, cap, width = _line_strokes(font, run.text, store)
    if not strokes or not cap:
        return []
    sy = cap_mm_units / cap
    sx = width_units / width if width_units and width else sy
    dx = run.x + _anchor(run, width * sx)
    a, b, c, d, e, f = run.matrix
    out = []
    for s in strokes:
        X, Y = s[:, 0] * sx + dx, s[:, 1] * sy + run.y
        out.append(np.column_stack([a * X + c * Y + e, b * X + d * Y + f]))
    return out
