"""The Excalidraw drawings in the Obsidian vault, cut into the diagrams the guide shows.

    uv run --group guide --group ui python guide/excalidraw.py [~/limn-shot/limn_v1]

The vault keeps each drawing LZ-string compressed in a .excalidraw.md. They are drawn here as SVG
(the pictures pasted into them included), cropped to the boxes in CROPS, and shot with Playwright's
Firefox into content/img/drawings/<name>.webp. The drawings are sketches: wires run as they were
drawn, and a crop cuts through whatever crosses its edge.
"""
import argparse
import base64
import html
import json
import math
import re
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / 'content' / 'img' / 'drawings'
WIRING = 'Plotter Tools 2026-02-25 23.40.24'          # the wiring overview: Pi, MCUs, Melzi, harness, beds
# name: (drawing, (x0, y0, x1, y1) in the drawing's own units or None for all of it)
CROPS = {
    'wiring-overview': (WIRING, (1080, -1712, 3580, -120)),
    'wiring-toolhead': (WIRING, (2380, -780, 3560, -120)),
    'wiring-tool-link': (WIRING, (3560, -900, 4830, -360)),
    'wiring-melzi-ext': (WIRING, (3260, -1300, 3960, -1030)),
    'wiring-beds': (WIRING, (1330, 20, 3260, 1170)),
    'wiring-coupling-detect': (WIRING, (560, -40, 920, 220)),
    'wiring-bed-power': ('FSR Pico', (880, 1290, 2800, 2120)),
    'wiring-bltouch-tool': ('FSR Pico', (4560, -300, 6260, 1120)),
    'melzi-a4982-srm1509': ('Pen Plotter 2026-02-10 18.18.05', None),
    'belts-corexy': ('Pen Plotter 2026-03-03 23.02.41', (-450, -250, 560, 560)),
    'belts-dock-tensioner': ('Pen Plotter 2026-08-19 17.11.22', None),
    'sketch-pen-dock': ('Pen Plotter 2026-01-24 08.15.19', None),
    'sketch-z-axis': ('Plotter Tools 2026-01-26 12.31.35', None),
    'sketch-electronics': ('Plotter Tools 2026-01-27 12.26.46', None),
    'sketch-coupling': ('Plotter Tools 2026-01-29 20.42.09', None),
}
KEY = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/='

def decompress(s):
    s = re.sub(r'\s', '', s)
    if not s:
        return ''
    vals = [KEY.index(c) for c in s]
    pos, val, idx = 32, vals[0], 1
    def bits(n):
        nonlocal pos, val, idx
        r, p = 0, 1
        for _ in range(n):
            resb = val & pos
            pos >>= 1
            if pos == 0:
                pos = 32
                val = vals[idx] if idx < len(vals) else 0
                idx += 1
            r |= (1 if resb else 0) * p
            p <<= 1
        return r
    d = {0: 0, 1: 1, 2: 2}
    enlarge, dsize, nb = 4, 4, 3
    c = bits(2)
    if c == 2:
        return ''
    c = chr(bits(8 if c == 0 else 16))
    d[3] = c
    w, out = c, [c]
    while True:
        if idx > len(vals) + 1:
            return ''.join(out)
        c = bits(nb)
        if c in (0, 1):
            d[dsize] = chr(bits(8 if c == 0 else 16)); dsize += 1
            c = dsize - 1
            enlarge -= 1
        elif c == 2:
            return ''.join(out)
        if enlarge == 0:
            enlarge = 2 ** nb; nb += 1
        if c in d:
            entry = d[c]
        elif c == dsize:
            entry = w + w[0]
        else:
            return None
        out.append(entry)
        d[dsize] = w + entry[0]; dsize += 1
        enlarge -= 1
        w = entry
        if enlarge == 0:
            enlarge = 2 ** nb; nb += 1

def source(name: str, vault: Path) -> Path:
    return next(p for p in vault.rglob('*.md') if p.name in (f'{name}.excalidraw.md', f'{name}.md'))


def load(path: Path) -> dict:
    t = path.read_text()
    m = re.search(r'```compressed-json\n(.*?)```', t, re.S)
    return json.loads(decompress(m.group(1)) if m else re.search(r'```json\n(.*?)```', t, re.S).group(1))


def files(path: Path) -> dict:
    """## Embedded Files: file id -> the picture's name in the vault."""
    return dict(re.findall(r'^([0-9a-f]{40}): \[\[(.+?)\]\]', path.read_text(), re.M))


FONTS = {1: 'Virgil, "Comic Sans MS", cursive', 5: '"Excalifont", "Comic Sans MS", cursive',
         2: 'Helvetica, Arial, sans-serif', 6: 'Nunito, Helvetica, Arial, sans-serif',
         3: 'Cascadia, "Courier New", monospace', 8: '"Comic Shanns", monospace'}


def color(c):
    return 'none' if c in (None, 'transparent') else c


def bbox(e):
    if e['type'] in ('line', 'arrow', 'freedraw'):
        xs = [e['x'] + p[0] for p in e['points']]; ys = [e['y'] + p[1] for p in e['points']]
        return min(xs), min(ys), max(xs), max(ys)
    return e['x'], e['y'], e['x'] + e['width'], e['y'] + e['height']


def freedraw(e):
    pts = e['points']
    if len(pts) < 2:
        x, y = pts[0] if pts else (0, 0)
        return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{e["strokeWidth"]:.1f}" fill="{color(e["strokeColor"])}"/>'
    d = 'M' + ' L'.join(f'{x:.1f},{y:.1f}' for x, y in pts)
    return (f'<path d="{d}" fill="none" stroke="{color(e["strokeColor"])}" stroke-width="{e["strokeWidth"] * 1.6:.1f}" '
            f'stroke-linecap="round" stroke-linejoin="round"/>')


def curve(pts) -> str:
    """A round line as Excalidraw draws it (rough.js's curve): Catmull-Rom through the points, as cubic
    Béziers, the ends doubled."""
    p = [pts[0], *pts, pts[-1]]
    d = f'M{p[1][0]:.1f},{p[1][1]:.1f}'
    for i in range(1, len(p) - 2):
        c1 = (p[i][0] + (p[i + 1][0] - p[i - 1][0]) / 6, p[i][1] + (p[i + 1][1] - p[i - 1][1]) / 6)
        c2 = (p[i + 1][0] - (p[i + 2][0] - p[i][0]) / 6, p[i + 1][1] - (p[i + 2][1] - p[i][1]) / 6)
        d += f' C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {p[i + 1][0]:.1f},{p[i + 1][1]:.1f}'
    return d


def arrowhead(x0, y0, x1, y1, w, c):
    a = math.atan2(y1 - y0, x1 - x0)
    L = 12 + 3 * w
    pts = [(x1 - L * math.cos(a - s), y1 - L * math.sin(a - s)) for s in (0.45, -0.45)]
    return f'<path d="M{pts[0][0]:.1f},{pts[0][1]:.1f} L{x1:.1f},{y1:.1f} L{pts[1][0]:.1f},{pts[1][1]:.1f}" fill="none" stroke="{c}" stroke-width="{w}" stroke-linecap="round"/>'


def element(e, pics: dict) -> str:
    """One element as SVG. pics: file id -> the picture's path."""
    t = e['type']
    st = color(e['strokeColor']); bg = color(e['backgroundColor']); w = e['strokeWidth']
    dash = {'dashed': f' stroke-dasharray="{w * 4},{w * 3}"', 'dotted': f' stroke-dasharray="{w},{w * 2.5}"'}.get(e['strokeStyle'], '')
    fill = bg if e.get('fillStyle') in ('solid', 'hachure', 'cross-hatch', 'zigzag') else 'none'
    fop = ' fill-opacity="0.35"' if e.get('fillStyle') in ('hachure', 'cross-hatch') and fill != 'none' else ''
    cx, cy = e['x'] + e['width'] / 2, e['y'] + e['height'] / 2
    rot = f' transform="rotate({math.degrees(e["angle"]):.2f} {cx:.1f} {cy:.1f})"' if e.get('angle') else ''
    op = f' opacity="{e["opacity"] / 100:.2f}"' if e.get('opacity', 100) != 100 else ''
    if t == 'rectangle':
        r = min(e['width'], e['height']) * 0.25 if e.get('roundness') else 0
        return f'<rect x="{e["x"]:.1f}" y="{e["y"]:.1f}" width="{e["width"]:.1f}" height="{e["height"]:.1f}" rx="{r:.1f}" fill="{fill}"{fop} stroke="{st}" stroke-width="{w}"{dash}{rot}{op}/>'
    if t == 'diamond':
        x, y, W, H = e['x'], e['y'], e['width'], e['height']
        return f'<path d="M{x + W / 2},{y} L{x + W},{y + H / 2} L{x + W / 2},{y + H} L{x},{y + H / 2}Z" fill="{fill}"{fop} stroke="{st}" stroke-width="{w}"{dash}{rot}{op}/>'
    if t == 'ellipse':
        return f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{e["width"] / 2:.1f}" ry="{e["height"] / 2:.1f}" fill="{fill}"{fop} stroke="{st}" stroke-width="{w}"{dash}{rot}{op}/>'
    if t in ('line', 'arrow'):
        pts = [(e['x'] + x, e['y'] + y) for x, y in e['points']]
        d = curve(pts) if e.get('roundness') and len(pts) > 2 else 'M' + ' L'.join(f'{x:.1f},{y:.1f}' for x, y in pts)
        closed = t == 'line' and len(pts) > 2 and math.dist(pts[0], pts[-1]) < 1
        out = f'<path d="{d}{"Z" if closed else ""}" fill="{fill if closed else "none"}"{fop} stroke="{st}" stroke-width="{w}"{dash} stroke-linecap="round" stroke-linejoin="round"/>'
        if t == 'arrow' and len(pts) > 1:
            if e.get('endArrowhead'):
                out += arrowhead(*pts[-2], *pts[-1], w, st)
            if e.get('startArrowhead'):
                out += arrowhead(*pts[1], *pts[0], w, st)
        return f'<g{rot}{op}>{out}</g>'
    if t == 'freedraw':
        return f'<g transform="translate({e["x"]:.1f} {e["y"]:.1f})"{op}>{freedraw(e)}</g>'
    if t == 'text':
        fs = e['fontSize']; lh = fs * e.get('lineHeight', 1.25)
        anchor = {'left': 'start', 'center': 'middle', 'right': 'end'}[e.get('textAlign', 'left')]
        x = {'start': e['x'], 'middle': cx, 'end': e['x'] + e['width']}[anchor]
        lines = e['text'].split('\n')
        tsp = ''.join(f'<tspan x="{x:.1f}" y="{e["y"] + lh * i + fs * 0.95:.1f}">{html.escape(l)}</tspan>' for i, l in enumerate(lines))
        return f'<text font-family=\'{FONTS.get(e["fontFamily"], FONTS[2])}\' font-size="{fs:.1f}" fill="{st}" text-anchor="{anchor}"{rot}{op}>{tsp}</text>'
    if t == 'image':
        pic = pics.get(e.get('fileId'))
        if pic is None:
            return f'<rect x="{e["x"]}" y="{e["y"]}" width="{e["width"]}" height="{e["height"]}" fill="#eee"/>'
        mime = 'image/png' if pic.suffix == '.png' else 'image/jpeg'
        href = f'data:{mime};base64,' + base64.b64encode(pic.read_bytes()).decode()
        sx, sy = e.get('scale', [1, 1])
        flip = ''
        if sx < 0 or sy < 0:
            flip = f' transform="translate({cx} {cy}) scale({sx} {sy}) translate({-cx} {-cy})"'
        crop = e.get('crop')
        if crop:   # crop: x, y, width, height in natural px of naturalWidth/Height
            nw, nh = crop['naturalWidth'], crop['naturalHeight']
            kx, ky = e['width'] / crop['width'], e['height'] / crop['height']
            cid = f'c{e["id"]}'
            return (f'<g{rot}{op}><clipPath id="{cid}"><rect x="{e["x"]}" y="{e["y"]}" width="{e["width"]}" height="{e["height"]}"/></clipPath>'
                    f'<image clip-path="url(#{cid})" href="{href}" x="{e["x"] - crop["x"] * kx:.1f}" y="{e["y"] - crop["y"] * ky:.1f}" '
                    f'width="{nw * kx:.1f}" height="{nh * ky:.1f}" preserveAspectRatio="none"{flip}/></g>')
        return f'<image href="{href}" x="{e["x"]:.1f}" y="{e["y"]:.1f}" width="{e["width"]:.1f}" height="{e["height"]:.1f}" preserveAspectRatio="none"{rot}{op}{flip}/>'
    return ''


def svg(path: Path, vault: Path, box=None, pad=20) -> tuple[str, float, float]:
    """The drawing as SVG, and its size. box: (x0, y0, x1, y1) in the drawing's units: what overlaps
    it is drawn, and it is the view. Without one, all of it."""
    d = load(path)
    pics = {}
    for fid, name in files(path).items():
        pic = next(vault.rglob(name), None)
        if pic is not None:
            pics[fid] = pic
    els = [e for e in d['elements'] if not e.get('isDeleted')]
    if box:
        x0, y0, x1, y1 = box
        els = [e for e in els if not (bbox(e)[2] < x0 or bbox(e)[0] > x1 or bbox(e)[3] < y0 or bbox(e)[1] > y1)]
    else:
        bs = [bbox(e) for e in els]
        x0, y0 = min(b[0] for b in bs) - pad, min(b[1] for b in bs) - pad
        x1, y1 = max(b[2] for b in bs) + pad, max(b[3] for b in bs) + pad
    body = '\n'.join(element(e, pics) for e in els)
    W, H = x1 - x0, y1 - y0
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0:.0f} {y0:.0f} {W:.0f} {H:.0f}" width="{W:.0f}" height="{H:.0f}">'
            f'<rect x="{x0}" y="{y0}" width="{W}" height="{H}" fill="#fff"/>{body}</svg>'), W, H


def main():
    from PIL import Image
    from playwright.sync_api import sync_playwright
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('vault', type=Path, nargs='?', default=Path('~/limn-shot/limn_v1'))
    ap.add_argument('--width', type=int, default=2000, help='px, the longer side at most')
    a = ap.parse_args()
    vault = a.vault.expanduser()
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p, tempfile.TemporaryDirectory() as tmp:
        browser = p.firefox.launch()
        for name, (drawing, box) in CROPS.items():
            text, W, H = svg(source(drawing, vault), vault, box)
            k = min(2.0, a.width / max(W, H))                    # small crops at 2x, for the text
            f = Path(tmp) / f'{name}.svg'
            f.write_text(text.replace(f'width="{W:.0f}" height="{H:.0f}"', f'width="{W * k:.0f}" height="{H * k:.0f}"', 1))
            page = browser.new_page(viewport={'width': round(W * k), 'height': round(H * k)})
            page.goto(f.as_uri())
            page.wait_for_timeout(300)
            page.screenshot(path=Path(tmp) / f'{name}.png')
            page.close()
            Image.open(Path(tmp) / f'{name}.png').convert('RGB').save(OUT / f'{name}.webp', quality=82)
            print(f'{name}: {round(W * k)} x {round(H * k)}')
        browser.close()


if __name__ == '__main__':
    main()
