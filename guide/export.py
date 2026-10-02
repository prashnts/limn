"""Every printed part of a Limn STEP export as its own STEP and STL, for Printables.

    uv run --group guide python guide/export.py ~/limn-shot/"Limn-Export-42 v88.step" printables [--shots]

Printed parts are the bodies of Limn's own designs (an assembly's own bodies
without what sits in it), less what is cut from stock (rods, belts, MDF) and
boards (NOT_PRINTED). The same design used in
several places is one file, with its count. Mirrored copies are files of their
own: they print as modelled. Writes <out>/step/*.step, <out>/stl/*.stl (mm, as
modelled: turn them flat in the slicer) and <out>/parts.csv. --shots renders
<out>/images/<part>.png and <part>-rear.png in Blender (guide/render/shot.py), transparent.
"""
import array
import csv
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import build
import step as stepfile
from build import STOCK, clean, slugify

HERE = Path(__file__).parent
NOT_PRINTED = re.compile(r'^(Unicorn PHAT|Belt-Movable|Belt-A-2|SteelRod|MDF-Plaque|Belt-)', re.I)
GENERIC = re.compile(r'^(Component\d*|Body\d*|cat|end|sensor|PCB|Part\d*)$', re.I)


def printed(st: stepfile.Step):
    """[(file stem, part, qty, assembly, mirrored)] of the printed parts."""
    root = next(r for r in st.roots if r.children)
    found = {}

    def visit(part, mult, where):
        for c, n in part.children:
            title = clean(c.source or c.name)
            if c.vendor:
                continue
            if c.children:
                visit(c, mult * n, title)
            if STOCK.match(title) or NOT_PRINTED.match(title) or not c.bodies:
                continue
            mirrored = '(Mirror)' in c.name + c.source
            stem = slugify((f'{where} {title}' if GENERIC.match(title) else title) + (' mirrored' if mirrored else ''))
            shape = st.shape(c)
            # one file per design and shape: another shape under the same name gets a number
            for k in range(1, 99):
                key = stem if k == 1 else f'{stem}-{k}'
                if key not in found or found[key]['shape'] == shape:
                    break
            e = found.setdefault(key, {'part': c, 'qty': 0, 'where': set(), 'mirrored': mirrored, 'shape': shape})
            e['qty'] += mult * n
            e['where'].add(where)
    visit(root, 1, clean(root.source or root.name))
    return found


def stl_size(f: Path) -> tuple:
    """The bounding box of a binary STL, mm."""
    data = f.read_bytes()
    n = int.from_bytes(data[80:84], 'little')
    lo, hi = [float('inf')] * 3, [float('-inf')] * 3
    for t in range(n):
        v = array.array('f', data[84 + 50 * t + 12:84 + 50 * t + 48])
        for k in range(9):
            lo[k % 3] = min(lo[k % 3], v[k])
            hi[k % 3] = max(hi[k % 3], v[k])
    return tuple(round(h - l, 1) for l, h in zip(lo, hi)) if n else ()


def shots(out: Path, stems, views=('iso', 'rear'), samples=128):
    """Blender product shots of the exported parts, from .glb meshed beside a copy of each STEP."""
    cache = HERE / '.cache' / 'render' / 'parts'
    cache.mkdir(parents=True, exist_ok=True)
    for stem in stems:
        src, dst = out / 'step' / f'{stem}.step', cache / f'{stem}.step'
        if not dst.exists() or dst.read_bytes() != src.read_bytes():
            dst.write_bytes(src.read_bytes())
    subprocess.run(['node', HERE / 'mesh' / 'mesh.mjs', *sorted(str(cache / f'{s}.step') for s in stems)], check=True)
    (out / 'images').mkdir(parents=True, exist_ok=True)
    jobs = [{'glb': str(cache / f'{stem}.glb'), 'png': str(out / 'images' / f'{stem}{"" if v == "iso" else "-" + v}.png'),
             'view': v, 'samples': samples, 'engine': 'eevee'} for stem in stems for v in views]
    (cache / 'jobs.json').write_text(json.dumps(jobs, indent=1))
    subprocess.run(['blender', '-b', '-P', HERE / 'render' / 'shot.py', '--', cache / 'jobs.json'], check=True,
                   stdout=subprocess.DEVNULL)
    print(f'{len(jobs)} shots in {out / "images"}')


def readme(out: Path, src: Path, st=None):
    """<out>/README.md: the print list and the hardware, for the Printables page."""
    src_name = src.name
    cat = build.Catalog(st or stepfile.Step(stepfile.load(src)))
    shop = sorted(((p, n) for p, n in cat.top.bom().items() if p.shop), key=lambda pn: pn[0].code)
    rows = list(csv.DictReader(open(out / 'parts.csv')))
    hw = tomllib.loads((HERE / 'components.toml').read_text())['part']
    by_asm = {}
    for r in rows:
        by_asm.setdefault(r['assembly'].split('; ')[0], []).append(r)
    lines = [
        '# Limn: printed parts',
        '',
        f'Every printed part of Limn, a pen plotter with a toolchanger, cut out of the Fusion export `{src_name}`',
        'by `guide/export.py`. One STEP and one STL per part, in mm, placed as modelled: lay them flat in the slicer.',
        '',
        f'**{len(rows)} parts, {sum(int(r["qty"]) for r in rows)} prints.** Mirrored parts are files of their own.',
        'Parts of several bodies (the diffusers, the icons, the inlays on the tool brackets) are multi-colour: keep',
        'their bodies together and give each its filament.',
        '',
        '## To print',
        '',
    ]
    for asm in sorted(by_asm, key=str.lower):
        shot = Path('images') / 'assemblies' / f'{slugify(asm)}.png'
        lines += [f'### {asm}', '', *([f'![{asm}]({shot})', ''] if (out / shot).exists() else []), '| Part | Qty | Size (mm) | Bodies | |', '|---|---:|---|---:|---|']
        for r in sorted(by_asm[asm], key=lambda r: r['file']):
            img = f'![](images/{r["file"]}.png)' if (out / 'images' / f'{r["file"]}.png').exists() else ''
            lines.append(f'| `{r["file"]}`{" (mirrored)" if r["mirrored"] else ""} | {r["qty"]} | {r["size_mm"]} | {r["bodies"]} | {img} |')
        lines.append('')
    lines += ['## Hardware', '', 'From the project\'s [component list](https://hackaday.io/project/205431/components).', '',
              '| Qty | Part | For |', '|---:|---|---|']
    for h in hw:
        lines.append(f'| {h["qty"]} | {h["name"]}{" (reclaimed)" if h.get("reclaimed") else ""} | {h.get("use", "")} |')
    if shop:
        lines += ['', '### From the Bambu Lab store', '',
                  "The screws, nuts, pins, bushings and the power switch are Bambu Lab's Maker's Supply parts, from the",
                  '[EU store](https://eu.store.bambulab.com/collections/makers-supply).', '',
                  '| Qty | Part | Code | Packs |', '|---:|---|---|---:|']
        for p, n in shop:
            lines.append(f'| {n} | {p.shop["name"]} | [{p.code}]({p.shop["url"]}) | {-(-n // p.shop["pack"])} of {p.shop["pack"]} |')
    lines += ['', '## Print settings', '', '<!-- to fill: printer, material, layer height, walls, infill, supports, per part where it differs -->', '']
    (out / 'README.md').write_text('\n'.join(lines))


def main(src: Path, out: Path, with_shots=False):
    st = stepfile.Step(stepfile.load(src))
    found = printed(st)
    (out / 'step').mkdir(parents=True, exist_ok=True)
    (out / 'stl').mkdir(parents=True, exist_ok=True)
    for stem, e in found.items():
        f = out / 'step' / f'{stem}.step'
        data = st.cut(e['part'], {e['part'].pd: stem}, deep=False)
        if not f.exists() or f.read_bytes() != data:
            f.write_bytes(data)
    # mesh beside the STEP files, then move the STLs to their folder
    subprocess.run(['node', HERE / 'mesh' / 'mesh.mjs', '--stl', *sorted(map(str, (out / 'step').glob('*.step')))], check=True)
    for f in (out / 'step').glob('*.stl'):
        f.replace(out / 'stl' / f.name)
    with open(out / 'parts.csv', 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['file', 'qty', 'mirrored', 'assembly', 'bodies', 'size_mm', 'fusion_name'])
        for stem, e in sorted(found.items()):
            bodies = e['shape'][0]
            box = stl_size(out / 'stl' / f'{stem}.stl')
            w.writerow([stem, e['qty'], 'yes' if e['mirrored'] else '', '; '.join(sorted(e['where'])), bodies,
                        ' x '.join(f'{v:g}' for v in box), e['part'].name])
    print(f'{len(found)} parts, {sum(e["qty"] for e in found.values())} to print, in {out}')
    if with_shots:
        shots(out, sorted(found))
    readme(out, src, st)


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    main(Path(args[0]).expanduser(), Path(args[1]), '--shots' in sys.argv)
