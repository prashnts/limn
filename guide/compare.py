"""Renders of the same designs across STEP exports, side by side.

    uv run --group guide python guide/compare.py out/ v11.step v46.step v88.step

For each design in DESIGNS: cut it out of every export that has it, mesh, shoot
it from the same side in each (guide/render/shot.py), then one strip per design
with the versions labelled. The whole machine is meshed coarse.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import glb
import step as stepfile
from build import slugify
from render.backdrop import backdrop

HERE = Path(__file__).parent
# (title, the design's name in each export (first that exists), bodies only?, view)
DESIGNS = [
    ('Limn', [None], False, 'iso'),
    ('Toolhead', ['Limn-ToolHead'], False, 'iso'),
    ('Toolchanger head', ['Limn-Toolchanger-Head'], False, 'iso'),
    ('Z axis rider', ['Limn-Z-Axis-Rider'], False, 'iso'),
    ('Tool dock', ['Limn-Export-42_Tool-Dock', 'Tool-Dock'], False, 'iso'),
    ('Bed', ['Plotter-Bed'], False, 'iso'),
    ('Extras', ['Limn-Extras'], False, 'iso'),
    ('plot-toolch-base', ['plot-toolch-base'], True, 'iso'),
    ('Plot-Extruder-Cover', ['Plot-Extruder-Cover'], True, 'iso'),
    ('Plot-Tool-Dock-Item', ['Plot-Tool-Dock-Item'], True, 'iso'),
    ('Limn-Calibration-Base', ['Limn-Calibration-Base'], True, 'iso'),
    ('Limn-Camera-Y-Endstop', ['Limn-Camera-Y-Endstop'], True, 'iso'),
    ('Limn-Touch-probe-Connector-Body', ['Limn-Touch-probe-Connector-Body'], True, 'iso'),
]


def version(path: Path) -> str:
    m = re.search(r'v(\d+)', path.stem)
    return f'v{m.group(1)}' if m else path.stem


def mended(st, part, f: Path, cache: Path) -> Path:
    """f's .glb, put together from the parts' own when OpenCASCADE left it empty."""
    g = f.with_suffix('.glb')
    if glb.broken(g) and part.children:
        kids = []
        for c, m in st.occurrences(part):
            cf = cache / 'parts' / f'{f.stem}-{c.pd}.step'
            cf.parent.mkdir(exist_ok=True)
            if not cf.exists():
                cf.write_bytes(st.cut(c))
                subprocess.run(['node', HERE / 'mesh' / 'mesh.mjs', cf], check=True, stdout=subprocess.DEVNULL)
            kids.append((mended(st, c, cf, cache), c.name, m))
        glb.compose(g, part.name, kids)
    return g


def main(out: Path, paths: list[Path]):
    cache = HERE / '.cache' / 'render' / 'compare'
    cache.mkdir(parents=True, exist_ok=True)
    have = {}                                   # (design, version) -> step file
    parts = {}
    for path in paths:
        v = version(path)
        st = stepfile.Step(stepfile.load(path))
        root = next(r for r in st.roots if r.children)
        for title, names, shallow, _ in DESIGNS:
            part = root if names == [None] else None
            for n in names if part is None else []:
                try:
                    part = st.find(n)
                    break
                except KeyError:
                    pass
            if part is None:
                continue
            f = cache / f'{slugify(title)}-{v}.step'
            data = st.cut(part, deep=not shallow)
            if not f.exists() or f.read_bytes() != data:
                f.write_bytes(data)
            have[title, v] = f
            parts[title, v] = part
        mine = [str(f) for (t, vv), f in have.items() if vv == v]
        subprocess.run(['node', HERE / 'mesh' / 'mesh.mjs', *mine], check=True)
        for (t, vv), f in have.items():
            if vv == v:
                mended(st, parts[t, vv], f, cache)
        print(f'{v}: {len(mine)} designs')
    views = {t: v for t, _, _, v in DESIGNS}
    jobs = [{'glb': str(f.with_suffix('.glb')), 'png': str(cache / f'{f.stem}-alpha.png'), 'view': views[t],
             'samples': 96, 'size': [1600, 1200], 'edges': t != 'Limn', 'engine': 'eevee'} for (t, _), f in have.items()]
    (cache / 'jobs.json').write_text(json.dumps(jobs, indent=1))
    subprocess.run(['blender', '-b', '-P', HERE / 'render' / 'shot.py', '--', cache / 'jobs.json'], check=True,
                   stdout=subprocess.DEVNULL)
    out.mkdir(parents=True, exist_ok=True)
    versions = [version(p) for p in paths]
    font = ImageFont.load_default(size=44)
    small = ImageFont.load_default(size=30)
    for title, *_ in DESIGNS:
        shots = []
        for v in versions:
            if (title, v) in have and (cache / f'{have[title, v].stem}-alpha.png').exists():
                f = have[title, v]
                png = cache / f'{f.stem}.png'
                backdrop(cache / f'{f.stem}-alpha.png', png)
                shots.append((v, Image.open(png)))
        if not shots:
            continue
        w, h = shots[0][1].size
        strip = Image.new('RGB', (w * len(shots), h), 'white')
        draw = ImageDraw.Draw(strip)
        for k, (v, im) in enumerate(shots):
            strip.paste(im, (k * w, 0))
            draw.text((k * w + 40, 34), v, fill=(40, 46, 54), font=font)
            if k:
                draw.line([(k * w, 0), (k * w, h)], fill=(205, 210, 216), width=3)
        draw.text((40, h - 64), title, fill=(90, 98, 108), font=small)
        strip.save(out / f'{slugify(title)}.png', optimize=True)
        for v, im in shots:
            im.save(out / f'{slugify(title)}-{v}.png', optimize=True)
        print(out / f'{slugify(title)}.png')


if __name__ == '__main__':
    main(Path(sys.argv[1]), [Path(p).expanduser() for p in sys.argv[2:]])
