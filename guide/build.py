"""The Limn guide: a static site from the STEP export and the Markdown in guide/content.

    uv run --group guide python guide/build.py [--step ~/limn-shot/"Limn-Export-42 v88.step"]  # -> guide/out
    uv run --group guide python guide/build.py --no-mesh --no-shots   # pages only, with what's there
    uv run python guide/serve.py                     # http://localhost:4231, never cached

Shots (Blender, guide/render/shot.py) of every design, assemblies at every level
included, are cached in guide/.cache/render/site and only redone when the model
changes.

Every design in the STEP tree gets a page (parts/<slug>.html): its 3D model, the
STEP and STL to download, what it holds and where it goes. The machine page is a
picture of the whole of it from the front that names what is under the pointer
(machine_map). downloads/limn-printables-<date>.zip has every printed part's STL
and STEP (printables/, guide/export.py) and the bill of materials. With guide/motion.json (recorded
in Fusion by guide/fusion/LimnMotion), assemblies get sliders for their joints (motion.py). guide/content/parts/<slug>.md
adds to it (print settings, steps, wiring), guide/catalog.toml says what kind of
part each is and where to get it. Other pages are the .md files in guide/content.
"""
import argparse
import collections
import csv
import datetime
import io
import json
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import jinja2
import markdown

import glb
import motion
import step as stepfile

HERE = Path(__file__).parent
REPO = HERE.parent
CONTENT = HERE / 'content'
KINDS = {
    'assembly': 'Assembly',
    'printed': '3D printed',
    'stock': 'Cut from stock',
    'bought': 'Bought',
    'reclaimed': 'Reclaimed',
}
STOCK = re.compile(r'^(SteelRod|MDF-Plaque|Belt-|Cutting Mat)', re.I)
CODE = re.compile(r'\b([A-Z]{2}\d{3})\b')     # AA041, EA006: the vendor's reference
GITHUB = 'https://github.com/prashnts/limn'
SHOP = tomllib.loads((HERE / 'bambu.toml').read_text())   # code -> the Bambu Lab EU store's variant
SITE_MODEL_MAX = 40e6                          # bigger STEP and STL files aren't published
TOP_VIEW, TOP_SIZE = 'front-iso', [2800, 2100]   # the whole machine from the front, big: the machine map
BRANCH = subprocess.run(['git', '-C', REPO, 'branch', '--show-current'], capture_output=True, text=True).stdout.strip() or 'master'


def slugify(s: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-') or 'part'


def clean(s: str) -> str:
    """'Limn-ToolHead-Key-Basic v9 (1)' -> 'Limn-ToolHead-Key-Basic'."""
    s = re.sub(r'\s*\(Mirror\)|\s*\(\d+\)|\s+v\d+\b|_\d+$', '', s)
    s = re.sub(r'\s*\(Mirror\)|\s*\(\d+\)|\s+v\d+\b|_\d+$', '', s)   # 'v1(Mirror) (1)'
    return s.strip() or s


def frontmatter(path: Path) -> tuple[dict, str]:
    """TOML between +++ lines, then Markdown."""
    text = path.read_text()
    if text.startswith('+++\n'):
        head, _, body = text[4:].partition('\n+++\n')
        return tomllib.loads(head), body
    return {}, text


@dataclass(eq=False)
class Page:
    slug: str
    title: str
    parts: list = field(default_factory=list)                 # step.Part, the first is the one shown
    qty: int = 0                                              # in the whole machine
    mirrored: int = 0
    parents: dict = field(default_factory=dict)               # slug -> Page
    children: list = field(default_factory=list)              # [(Page, count per unit)]
    meta: dict = field(default_factory=dict)                  # catalog.toml + frontmatter
    body: str = ''
    model: str = ''                                           # models/<slug>.glb if there is one
    model_bytes: int = 0
    step: str = ''                                            # models/<slug>.step if published
    stl: str = ''                                             # models/<slug>.stl if published
    motion: str = ''                                          # models/<slug>.motion.json: its joints (motion.py)
    image: str = ''                                           # img/<slug>.webp, the Blender shot
    thumb: str = ''                                           # img/<slug>-480.webp
    locator: str = ''                                         # img/map/<slug>.webp: where it is in Limn
    hardware: dict = field(default_factory=dict)              # the Hackaday list's entry, if any
    by_pd: dict = field(default_factory=dict, repr=False)     # the catalog's STEP part -> Page
    videos: list = field(default_factory=list)                # guide/videos.toml entries that name this page

    @property
    def part(self):
        return self.parts[0]

    @property
    def kind(self):
        if 'kind' in self.meta:
            return self.meta['kind']
        if self.part.vendor:
            return 'bought'
        if self.children:
            return 'assembly'
        return 'stock' if STOCK.match(self.title) else 'printed'

    @property
    def name(self):
        return self.meta.get('title', self.title)

    @property
    def code(self):
        m = CODE.search(' '.join(p.source for p in self.parts))
        return m and m.group(1)

    @property
    def shop(self):
        """Where to buy it (guide/bambu.toml), by its reference code."""
        return SHOP.get(self.code) if self.code else None

    @property
    def designs(self):
        return sorted({p.source or p.name for p in self.parts})

    def bom(self, part=None, mult=1, acc=None):
        """Everything bought or cut for one of this, through its sub-assemblies. Walks the STEP tree, not
        the pages: two designs of one name (Plot-Tool-Bracket) share a page but not their insides."""
        acc = collections.Counter() if acc is None else acc
        part = part or self.part
        if part.vendor:                                   # a bought part's insides aren't bought
            return acc
        for c, n in part.children:
            page = self.by_pd[c.pd]
            if page.kind == 'assembly' and not c.vendor:
                self.bom(c, mult * n, acc)
            else:
                acc[page] += mult * n
        return acc


class Catalog:
    def __init__(self, step: stepfile.Step):
        self.step = step
        self.pages: dict[str, Page] = {}
        self.by_pd: dict[int, Page] = {}
        self.root = next(r for r in step.roots if r.children)
        self.top = self.page(self.root, ())
        self.top.qty = 1
        self.visit(self.root, 1, (self.top.slug,))

    def page(self, part, ancestors) -> Page:
        if part.pd in self.by_pd:
            return self.by_pd[part.pd]
        title = clean(part.source or part.name)
        slug = slugify(title)
        if slug in ancestors:                      # 'Limn-Aux-PCB' inside 'Limn-Aux-PCB'
            slug = slugify(part.name)
        page = self.pages.setdefault(slug, Page(slug, title, by_pd=self.by_pd))
        page.parts.append(part)
        page.parts.sort(key=lambda p: '(Mirror)' in p.name + p.source)   # shown: the unmirrored one
        self.by_pd[part.pd] = page
        return page

    def visit(self, part, mult, ancestors):
        here = self.by_pd[part.pd]
        for c, n in part.children:
            page = self.page(c, ancestors)
            page.qty += mult * n
            if '(Mirror)' in c.name + c.source:
                page.mirrored += mult * n
            page.parents[here.slug] = here
            if part is here.part:                  # a part and its mirror on one page: add them up
                i = next((i for i, (p, _) in enumerate(here.children) if p is page), None)
                if i is None:
                    here.children.append((page, n))
                else:
                    here.children[i] = (page, here.children[i][1] + n)
            if not c.vendor:
                self.visit(c, mult * n, ancestors + (page.slug,))

    def load_meta(self):
        catalog = tomllib.loads((HERE / 'catalog.toml').read_text()) if (HERE / 'catalog.toml').exists() else {}
        for slug, meta in catalog.items():
            if slug in self.pages:
                self.pages[slug].meta.update(meta)
            else:
                print(f'catalog.toml: no part {slug!r}', file=sys.stderr)
        for md in sorted((CONTENT / 'parts').glob('*.md')):
            if md.stem not in self.pages:
                print(f'{md.relative_to(HERE)}: no part {md.stem!r} in the STEP file', file=sys.stderr)
                continue
            meta, body = frontmatter(md)
            self.pages[md.stem].meta.update(meta)
            self.pages[md.stem].body = body


# --- Markdown -------------------------------------------------------------

class Renderer:
    """Markdown with a few guide-isms:

    ## Step: Press the inserts      a numbered step card, its pictures beside its text
    - [!] / [i] / [?] text          a caution / note / open question bullet
    [[limn-nfc-rail]]               a link to that part's page, by its name
    /docs/plot-ui.png               site-absolute paths (the repo's docs/ is copied in)
    """

    def __init__(self, catalog: Catalog):
        self.catalog = catalog

    def __call__(self, text: str, root: str) -> tuple[str, list]:
        def partlink(m):
            slug, label = m.group(1), m.group(2)
            page = self.catalog.pages.get(slug)
            if not page:
                print(f'[[{slug}]]: no such part', file=sys.stderr)
                return label or slug
            return f'[{label or page.name}](/parts/{slug}.html)'
        text = re.sub(r'\[\[([a-z0-9-]+)(?:\|([^\]]+))?\]\]', partlink, text)
        md = markdown.Markdown(extensions=['tables', 'fenced_code', 'attr_list', 'toc', 'sane_lists'],
                               extension_configs={'toc': {'permalink': False}})
        out = md.convert(text)
        out = re.sub(r'<li>\[(!|i|\?)\]\s*', lambda m: f'<li class="b-{ {"!": "caution", "i": "note", "?": "open"}[m.group(1)]}">', out)
        out = re.sub(r'(src|href)="/(?!/)', rf'\1="{root}', out)
        out = re.sub(r'(compare/[\w.-]+)\.png"', r'\1.webp"', out)                 # compare_images()
        out = re.sub(r'<img (?![^>]*loading=)', '<img loading="lazy" decoding="async" ', out)
        return self.steps(out), md.toc_tokens

    @staticmethod
    def steps(out: str) -> str:
        parts = re.split(r'(<h2[^>]*>.*?</h2>)', out)
        html_, n, in_step = [parts[0]], 0, False
        for head, body in zip(parts[1::2], parts[2::2]):
            m = re.match(r'<h2([^>]*)>\s*Step\s*[:.\-–—]?\s*(.*?)</h2>', head, re.S)
            if in_step:
                html_.append('</div></section>')
                in_step = False
            if not m:
                html_ += [head, body]
                continue
            n += 1
            imgs = re.findall(r'<p>\s*(<img[^>]*>)\s*</p>', body)
            text = re.sub(r'<p>\s*<img[^>]*>\s*</p>', '', body)
            media = ''.join(f'<a class="shot" href="{re.search(r"src=\"([^\"]+)", i).group(1)}">{i}</a>' for i in imgs)
            html_.append(f'<section class="step"{m.group(1)}><h2><span class="n">Step {n}</span> {m.group(2)}</h2>'
                         f'<div class="step-body">' + (f'<div class="media">{media}</div>' if media else '')
                         + f'<div class="text">{text}')
            in_step = True
        if in_step:
            html_.append('</div></section>')
        return ''.join(html_)


# --- Models ---------------------------------------------------------------

def models(catalog: Catalog, out: Path, mesh: bool):
    """Cut every page's part out of the STEP file and mesh it. Unchanged cuts keep
    their mtime, so the mesher skips them."""
    cache = HERE / '.cache' / 'models'
    cache.mkdir(parents=True, exist_ok=True)
    names = {pd: page.slug for pd, page in catalog.by_pd.items()}
    if mesh:
        for page in catalog.pages.values():
            data = catalog.step.cut(page.part, names)
            f = cache / f'{page.slug}.step'
            if not f.exists() or f.read_bytes() != data:
                f.write_bytes(data)
        steps = sorted(str(cache / f'{p.slug}.step') for p in catalog.pages.values() if p is not catalog.top)
        subprocess.run(['node', HERE / 'mesh' / 'mesh.mjs', *steps], check=True)
        subprocess.run(['node', HERE / 'mesh' / 'mesh.mjs', '--coarse', cache / f'{catalog.top.slug}.step'], check=True)

    def model_of(part):
        """The .glb of this very part: its page's, unless the page shows another
        (a mirrored copy is its own geometry)."""
        page = catalog.by_pd[part.pd]
        if part is page.part:
            return mended(page)
        f = cache / f'{page.slug}@{part.pd}.step'
        data = catalog.step.cut(part, names)
        if not f.exists() or f.read_bytes() != data:
            f.write_bytes(data)
            subprocess.run(['node', HERE / 'mesh' / 'mesh.mjs', f], check=True)
        return f.with_suffix('.glb')

    def mended(page):
        """Its .glb, put together from its children's when OpenCASCADE left it empty."""
        f = cache / f'{page.slug}.glb'
        if f in done:
            return f
        done.add(f)
        if (glb.broken(f) or f in composed) and page.children:
            kids = [(model_of(c), catalog.by_pd[c.pd].slug, m) for c, m in catalog.step.occurrences(page.part)]
            glb.compose(f, page.slug, kids)
            composed.add(f)
            print(f'{f.name}: put together from {len(kids)} parts')
        return f
    done = set()
    composed = set(cache / n for n in json.loads((cache / 'composed.json').read_text())) \
        if (cache / 'composed.json').exists() else set()
    if mesh:
        for page in catalog.pages.values():
            mended(page)
        (cache / 'composed.json').write_text(json.dumps(sorted(f.name for f in composed)))
    (out / 'models').mkdir(parents=True, exist_ok=True)
    for page in catalog.pages.values():
        for ext in ('glb', 'step'):
            f = cache / f'{page.slug}.{ext}'
            if f.exists() and (ext == 'glb' or f.stat().st_size < SITE_MODEL_MAX):
                shutil.copy2(f, out / 'models' / f.name)
                setattr(page, 'model' if ext == 'glb' else 'step', f'models/{f.name}')
                if ext == 'glb':
                    page.model_bytes = f.stat().st_size
        # STL to download (the .glb is only for the 3D view), from the same mesh; not the whole machine
        f, s = cache / f'{page.slug}.glb', cache / f'{page.slug}.stl'
        if f.exists() and page is not catalog.top and not glb.broken(f):
            if not s.exists() or s.stat().st_mtime < f.stat().st_mtime:
                glb.stl(f, s, page.name)
            if s.stat().st_size < SITE_MODEL_MAX:
                shutil.copy2(s, out / 'models' / s.name)
                page.stl = f'models/{s.name}'


def tree(catalog: Catalog) -> Path:
    """The whole machine composed down to single designs, each one a node named by its page: what
    the ID shot needs, where the meshed assemblies have no names inside. Same geometry as the shot."""
    models, cache = HERE / '.cache' / 'models', HERE / '.cache' / 'models' / 'tree'
    cache.mkdir(parents=True, exist_ok=True)
    top = cache / f'{catalog.top.slug}.glb'
    newest = max(f.stat().st_mtime for f in models.glob('*.glb'))
    if top.exists() and top.stat().st_mtime > newest and 'occ' in json.dumps(glb.read(top)[0]['nodes'][-3:]):
        return top                                            # (made before the occurrence names: again)
    done = {}

    def glb_of(part):
        page = catalog.by_pd[part.pd]
        if page.children and not part.vendor and part is page.part:
            if page.slug not in done:
                f = cache / f'{page.slug}.glb'
                glb.compose(f, page.slug, [(glb_of(c), catalog.by_pd[c.pd].slug, m, name) for (c, m), name in
                                           zip(catalog.step.occurrences(part), catalog.step.occurrence_names(part))])
                done[page.slug] = f
            return done[page.slug]
        if part is page.part:
            return models / f'{page.slug}.glb'
        mirror = models / f'{page.slug}@{part.pd}.glb'          # a mirrored copy is its own geometry
        if not mirror.exists():
            mirror.with_suffix('.step').write_bytes(catalog.step.cut(part, names))
            subprocess.run(['node', HERE / 'mesh' / 'mesh.mjs', mirror.with_suffix('.step')], check=True)
        return mirror
    names = {pd: page.slug for pd, page in catalog.by_pd.items()}
    return glb_of(catalog.top.part)


def shots(catalog: Catalog, out: Path, render: bool):
    """A Blender shot of every page's model (alpha PNG in the cache), as transparent webp on the site."""
    from PIL import Image
    cache = HERE / '.cache' / 'render' / 'site'
    cache.mkdir(parents=True, exist_ok=True)
    models = HERE / '.cache' / 'models'
    todo = []
    seen = json.loads((cache / 'views.json').read_text()) if (cache / 'views.json').exists() else {}

    def stale(png, src, job):
        """Not shot yet, shot before the model changed, or from another view or size."""
        was = seen.get(png.name, {'view': 'iso', 'size': [2000, 1500]})
        return (not png.exists() or png.stat().st_mtime < src.stat().st_mtime
                or was != {'view': job['view'], 'size': job['size']})
    for page in catalog.pages.values():
        glb_, png = models / f'{page.slug}.glb', cache / f'{page.slug}-alpha.png'
        top = page is catalog.top
        job = {'glb': str(glb_), 'png': str(png), 'view': TOP_VIEW if top else 'iso', 'samples': 96,
               'size': TOP_SIZE if top else [2000, 1500], 'engine': 'eevee', 'edges': not top}
        if glb_.exists() and not glb.broken(glb_) and stale(png, glb_, job):     # an empty model: no shot
            todo.append(job)
    top = catalog.top.slug
    whole, ids = models / f'{top}.glb', cache / f'{top}-ids.png'
    job = {'glb': None, 'png': str(ids), 'ids': str(cache / f'{top}-ids.json'), 'view': TOP_VIEW,
           'samples': 1, 'size': TOP_SIZE, 'engine': 'eevee', 'edges': False}
    if whole.exists() and stale(ids, whole, job):
        # the whole machine again, each mesh a flat colour that is its number: the locator maps, the machine's map
        job['glb'] = str(tree(catalog))
        todo.append(job)
    if render and todo:
        # assemblies first: they're the pictures the site needs most
        todo.sort(key=lambda j: -(models / Path(j['glb']).name).stat().st_size)
        print(f'rendering {len(todo)} shots')
        (cache / 'jobs.json').write_text(json.dumps(todo, indent=1))
        subprocess.run(['blender', '-b', '-P', HERE / 'render' / 'shot.py', '--', cache / 'jobs.json'],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for j in todo:
            seen[Path(j['png']).name] = {'view': j['view'], 'size': j['size']}
        (cache / 'views.json').write_text(json.dumps(seen, indent=1))
    (out / 'img').mkdir(parents=True, exist_ok=True)
    for page in catalog.pages.values():
        png = cache / f'{page.slug}-alpha.png'
        if not png.exists():
            continue
        full, thumb = out / 'img' / f'{page.slug}.webp', out / 'img' / f'{page.slug}-480.webp'
        if not full.exists() or full.stat().st_mtime < png.stat().st_mtime:
            im = Image.open(png).convert('RGBA')   # webp keeps the transparency
            im.save(full, quality=86)
            im.resize((480, 360), Image.LANCZOS).save(thumb, quality=82)
        page.image, page.thumb = f'img/{full.name}', f'img/{thumb.name}'


def locators(catalog: Catalog, out: Path, size=(560, 420)):
    """A small map per page: the whole machine greyed out, this design lit (every one of it), from the
    ID shot (render/shot.py). Out of sight inside the machine: a ring where it is."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter
    cache = HERE / '.cache' / 'render' / 'site'
    top = catalog.top.slug
    shot, ids_png, ids_json = (cache / f'{top}-{s}' for s in ('alpha.png', 'ids.png', 'ids.json'))
    if not (shot.exists() and ids_png.exists() and ids_json.exists()):
        return
    shot_im = Image.open(shot).convert('RGBA')
    x0, y0, x1, y1 = shot_im.getchannel('A').point(lambda v: 255 if v > 8 else 0).getbbox()
    pad = int(0.06 * max(x1 - x0, y1 - y0))                  # the machine, not the shot's margins
    cx, cy, half = (x0 + x1) / 2, (y0 + y1) / 2, max((x1 - x0) / size[0], (y1 - y0) / size[1]) / 2 + pad / size[0]
    crop = (int(cx - half * size[0]), int(cy - half * size[1]), int(cx + half * size[0]), int(cy + half * size[1]))
    work = (size[0] * 2, size[1] * 2)                         # drawn at 2x, then shrunk: fast enough
    a = np.asarray(Image.open(ids_png).convert('RGBA').crop(crop).resize(work, Image.NEAREST)).astype(np.int32)
    lv = np.rint(a[..., :3] / 17).astype(np.int32)
    idx = (lv[..., 0] << 8) | (lv[..., 1] << 4) | lv[..., 2]
    idx[a[..., 3] < 128] = 0
    meshes = json.loads(ids_json.read_text())

    def slug(name):
        name = re.sub(r'\.\d{3}$', '', name)
        for s in (name, slugify(clean(name))):
            if s in catalog.pages:
                return s
    on = collections.defaultdict(lambda: collections.defaultdict(set))   # page slug -> its node -> meshes
    for i, m in meshes.items():
        for n in m['names']:
            if (s := slug(n)) and s != top:
                on[s][n].add(int(i))

    base = shot_im.crop(crop).resize(work, Image.LANCZOS)
    grey =base.convert('LA').convert('RGBA')
    grey = Image.blend(grey, Image.new('RGBA', grey.size, (255, 255, 255, 0)), 0.35)
    grey.putalpha(Image.eval(base.getchannel('A'), lambda v: v * 0.55))
    w, h = base.size
    W, H = shot_im.size
    (out / 'img' / 'map').mkdir(parents=True, exist_ok=True)
    stamp = ids_png.stat().st_mtime
    for s, copies in on.items():
        nums = set().union(*copies.values())
        page, f = catalog.pages[s], out / 'img' / 'map' / f'{s}.webp'
        page.locator = f'img/map/{f.name}'
        if f.exists() and f.stat().st_mtime > stamp:
            continue
        lut = np.zeros(4096, bool)
        lut[list(nums)] = True
        mask = lut[idx]
        im = grey.copy()
        if mask.any():
            m = Image.fromarray((mask * 255).astype(np.uint8))
            lit = Image.composite(base, Image.new('RGBA', base.size, (226, 113, 29, 255)), m)
            tint = Image.blend(lit, Image.new('RGBA', base.size, (226, 113, 29, 255)), 0.45)
            im.paste(tint, (0, 0), m)
            edge = m.filter(ImageFilter.MaxFilter(5))
            ring = Image.new('RGBA', base.size, (160, 60, 0, 255))
            im.paste(ring, (0, 0), Image.fromarray(((np.asarray(edge) > 0) & ~mask).astype(np.uint8) * 255))
        if mask.sum() < 400:                                  # hidden inside, or a speck: a ring too
            d = ImageDraw.Draw(im)
            for ns in copies.values():                        # one ring a copy
                bs = [meshes[str(n)]['box'] for n in ns]
                x0, y0, x1, y1 = min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)
                sx, sy = w / (crop[2] - crop[0]), h / (crop[3] - crop[1])     # full shot (0-1) -> the crop
                cx = ((x0 + x1) / 2 * W - crop[0]) * sx
                cy = ((y0 + y1) / 2 * H - crop[1]) * sy
                r = max(22, (x1 - x0) * W * sx / 2 + 8)
                d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(226, 113, 29, 255), width=6)
        im.thumbnail(size, Image.LANCZOS)
        im.save(f, quality=85)
    print(f'{len(on)} locator maps')


def machine_map(catalog: Catalog, out: Path, width=1400) -> dict | None:
    """The machine page's picture: the whole machine from the front, and beside it what is where,
    from the ID shot (render/shot.py) cut to the same frame: img/machine-ids.png, each pixel's colour
    its mesh's number, and static/machine-map.json, each mesh's pages from the machine's assemblies
    down to the single design. static/machine.js lights what is under the pointer."""
    import numpy as np
    from PIL import Image
    cache = HERE / '.cache' / 'render' / 'site'
    top = catalog.top.slug
    shot, ids_png, ids_json = (cache / f'{top}-{s}' for s in ('alpha.png', 'ids.png', 'ids.json'))
    if not (shot.exists() and ids_png.exists() and ids_json.exists()):
        return None
    im = Image.open(shot).convert('RGBA')
    W, H = im.size
    x0, y0, x1, y1 = im.getchannel('A').point(lambda v: 255 if v > 8 else 0).getbbox()
    pad = int(0.03 * max(x1 - x0, y1 - y0))
    crop = (max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(H, y1 + pad))
    w = min(width, crop[2] - crop[0])
    h = round(w * (crop[3] - crop[1]) / (crop[2] - crop[0]))
    (out / 'img').mkdir(parents=True, exist_ok=True)
    im.crop(crop).resize((w, h), Image.LANCZOS).save(out / 'img' / 'machine.webp', quality=88)
    ids = Image.open(ids_png).convert('RGBA').crop(crop).resize((w, h), Image.NEAREST)
    a = np.asarray(ids).copy()
    a[a[..., 3] < 128] = 0                                    # the background: number 0
    a[..., 3] = 255                                           # opaque: a browser keeps the colours exact
    Image.fromarray(a).save(out / 'img' / 'machine-ids.png', optimize=True)

    def slug(name):
        name = re.sub(r'\.\d{3}$', '', name)
        for s_ in (name, slugify(clean(name))):
            if s_ in catalog.pages:
                return s_
    meshes = {}
    for i, m in json.loads(ids_json.read_text()).items():
        chain = []
        for n in reversed(m['names']):                        # from the root down
            s_ = slug(n)
            if s_ and s_ != top and (not chain or chain[-1] != s_):
                chain.append(s_)
        if chain:
            bx = m['box']                                     # the full shot's 0-1 -> this picture's 0-1
            box = [(bx[0] * W - crop[0]) / (crop[2] - crop[0]), (bx[1] * H - crop[1]) / (crop[3] - crop[1]),
                   (bx[2] * W - crop[0]) / (crop[2] - crop[0]), (bx[3] * H - crop[1]) / (crop[3] - crop[1])]
            meshes[int(i)] = {'chain': chain, 'box': [round(v, 4) for v in box]}
    used = {s_ for m in meshes.values() for s_ in m['chain']}
    pages = {s_: {'name': catalog.pages[s_].name, 'kind': KINDS[catalog.pages[s_].kind], 'qty': catalog.pages[s_].qty,
                  'thumb': catalog.pages[s_].thumb} for s_ in sorted(used)}
    (out / 'static' / 'machine-map.json').write_text(json.dumps({'meshes': meshes, 'pages': pages}, separators=(',', ':')))
    print(f'machine map: {len(meshes)} meshes, {len(pages)} designs, {w}x{h}')
    return {'image': 'img/machine.webp', 'ids': 'img/machine-ids.png', 'width': w, 'height': h}


def downloads(catalog: Catalog, out: Path, src: Path) -> dict | None:
    """downloads/limn-printables-<date>.zip: every printed part's STL and STEP and what they are
    (printables/, from guide/export.py), the bill of materials, dated by the build."""
    pr = REPO / 'printables'
    if not (pr / 'stl').exists():
        return None
    date = datetime.date.today().isoformat()
    name = f'limn-printables-{date}'
    (out / 'downloads').mkdir(parents=True, exist_ok=True)
    f = out / 'downloads' / f'{name}.zip'
    bom = io.StringIO()
    w = csv.writer(bom)
    w.writerow(['kind', 'name', 'qty', 'reference', 'where to get it', 'page'])
    for page, n in sorted(catalog.top.bom().items(), key=lambda pn: (pn[0].kind, pn[0].name.lower())):
        w.writerow([KINDS[page.kind], page.name, n, page.code or '', page.shop['url'] if page.shop else '',
                    f'parts/{page.slug}.html'])
    readme = (f'# Limn: the printed parts, {date}\n\n'
              f'From the CAD export `{src.name}`. `stl/` and `step/`: each printed part once (mm, as modelled: '
              f'lay them flat in the slicer), `parts.csv`: how many of each and where they go, `bom.csv`: '
              f'everything in the machine with counts, `README-printables.md`: the notes that come with them.\n\n'
              f'The guide: {GITHUB} (guide/), the parts on Printables: '
              f'https://www.printables.com/model/1786450\n')
    with zipfile.ZipFile(f, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr(f'{name}/README.md', readme)
        z.writestr(f'{name}/bom.csv', bom.getvalue())
        for extra, arc in (('parts.csv', 'parts.csv'), ('README.md', 'README-printables.md')):
            if (pr / extra).exists():
                z.write(pr / extra, f'{name}/{arc}')
        for sub in ('stl', 'step'):
            for p in sorted((pr / sub).glob(f'*.{sub}')):
                z.write(p, f'{name}/{sub}/{p.name}')
        files = len(z.namelist())
    print(f'{f.name}: {files} files, {f.stat().st_size / 1e6:.0f} MB')
    return {'url': f'downloads/{f.name}', 'date': date, 'mb': round(f.stat().st_size / 1e6), 'files': files}


def motions(catalog: Catalog, out: Path):
    """The joints recorded in Fusion (guide/motion.json, guide/fusion/LimnMotion) onto the assembly pages
    that move inside: their model becomes the one composed from the parts (tree(): its nodes know their
    occurrences), and models/<slug>.motion.json drives it (static/viewer.js)."""
    data = motion.load(HERE / 'motion.json')
    if not data:
        return
    per = motion.page_motions(data, catalog)
    if not per:
        print('motion.json: nothing in it moves a part of this export (occurrence names changed?)', file=sys.stderr)
        return
    tree(catalog)
    composed = HERE / '.cache' / 'models' / 'tree'
    for slug, m in per.items():
        page, f = catalog.pages[slug], composed / f'{slug}.glb'
        if not f.exists():
            continue
        shutil.copy2(f, out / 'models' / f'{slug}.anim.glb')
        (out / 'models' / f'{slug}.motion.json').write_text(json.dumps(m, separators=(',', ':')))
        page.model, page.model_bytes = f'models/{slug}.anim.glb', f.stat().st_size
        page.motion = f'models/{slug}.motion.json'
    print(f'motion: {len(data["drives"])} joints, {len(per)} pages move (from {data.get("document")}, {data.get("made")})')


def compare_images(src: Path, dst: Path, width=2400):
    """The CAD comparison strips (guide/compare.py, 4800 px PNGs, ~4 MB each) as WebP a page can afford."""
    from PIL import Image
    dst.mkdir(parents=True, exist_ok=True)
    for old in dst.glob('*.png'):                             # copied as they were, before
        old.unlink()
    for p in sorted(src.glob('*.png')):
        f = dst / f'{p.stem}.webp'
        if f.exists() and f.stat().st_mtime > p.stat().st_mtime:
            continue
        im = Image.open(p)
        if im.width > width:
            im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
        im.save(f, quality=80, method=5)


def parts_index(catalog: Catalog) -> dict:
    """The parts gallery's order and filters: biggest assemblies first (by the parts in them, all the
    way down), then the rest by how many Limn has; and every assembly a design is in, at any depth."""
    size = {p.slug: sum(p.bom().values()) for p in catalog.pages.values() if p.kind == 'assembly'}

    def within(p, seen=None):
        seen = set() if seen is None else seen
        for q in p.parents.values():
            if q.slug not in seen:
                seen.add(q.slug)
                within(q, seen)
        return seen
    tree = []                                                 # (page, depth): assemblies, as they nest

    def walk(p, depth):
        tree.append((p, depth))
        for c, _ in sorted(p.children, key=lambda cn: -size.get(cn[0].slug, 0)):
            if c.slug in size and all(c is not t for t, _ in tree):
                walk(c, depth + 1)
    walk(catalog.top, 0)
    pages = sorted(catalog.pages.values(), key=lambda p: (-size.get(p.slug, 0), -p.qty, p.name.lower()))
    return {'pages': pages, 'size': size, 'within': {p.slug: within(p) for p in pages}, 'tree': tree}


def hardware(catalog: Catalog):
    """The Hackaday component list (guide/components.toml) onto the pages it names."""
    entries = tomllib.loads((HERE / 'components.toml').read_text())['part']
    by_title = {}
    for page in catalog.pages.values():
        for p in page.parts:
            for n in (p.name, p.source):
                by_title.setdefault(clean(n).lower(), page)
    for e in entries:
        e['pages'] = [by_title[n.lower()] for n in e.get('step', []) if n.lower() in by_title]
        for page in e['pages']:
            page.hardware = e
    return entries


def youtube(catalog: Catalog):
    """The playlist (guide/videos.toml) onto the part pages and written pages its videos name."""
    data = tomllib.loads((HERE / 'videos.toml').read_text())
    by_doc = collections.defaultdict(list)                    # 'software.html' -> [video]
    for v in data['video']:
        v['url'] = f'https://www.youtube.com/watch?v={v["id"]}&list={data["playlist"]}'
        for doc in v.get('docs', []):
            if (CONTENT / f'{doc}.md').exists():
                by_doc[f'{doc}.html'].append(v)
            else:
                print(f'videos.toml: no page content/{doc}.md', file=sys.stderr)
        for slug in v.get('pages', []):
            if slug in catalog.pages:
                catalog.pages[slug].videos.append(v)
            else:
                print(f'videos.toml: no part {slug!r}', file=sys.stderr)
    return data['video'], f'https://www.youtube.com/playlist?list={data["playlist"]}', by_doc


@dataclass
class Post:
    """A dated page in content/log: a Hackaday log mirrored, or a write-up. `include` takes the text
    from a file in the repository (notebooks/act-*.md), less its # title; the post's own text follows it."""
    url: str
    title: str
    date: object
    author: str
    body: str
    source: str = ''
    hackaday: int = 0
    include: str = ''
    note: str = ''
    videos: list = field(default_factory=list)
    thumb: str = ''
    excerpt: str = ''


def posts(by_id: dict) -> list[Post]:
    out = []
    for md in sorted((CONTENT / 'log').glob('*.md')):
        meta, body = frontmatter(md)
        if meta.get('include'):
            body = re.sub(r'\A# .*\n+', '', (REPO / meta['include']).read_text()) + '\n\n' + body
        vids = [by_id[v] for v in meta.get('videos', []) if v in by_id]
        text = re.sub(r'```.*?```|!\[[^\]]*\]\([^)]*\)|^\s*[#>|].*$', '', body, flags=re.S | re.M)
        para = next((p for p in re.split(r'\n\s*\n', text) if len(p.strip()) > 40), '')
        para = re.sub(r'\[([^\]]+)\]\([^)]*\)|[*_`]', r'\1', ' '.join(para.split()))
        thumb = re.search(r'!\[[^\]]*\]\(/([^)\s]+)', body)
        out.append(Post(url=f'log/{md.stem}.html', title=meta['title'], date=meta['date'], author=meta['author'],
                        body=body, source=meta.get('source', ''), hackaday=meta.get('hackaday', 0),
                        include=meta.get('include', ''), note=meta.get('note', ''), videos=vids,
                        thumb=thumb.group(1) if thumb else meta.get('thumb', '')
                        or (vids and f'https://i.ytimg.com/vi/{vids[0]["id"]}/hqdefault.jpg'),
                        excerpt=para if len(para) < 260 else para[:para.rfind(' ', 0, 250)] + ' …'))
    return sorted(out, key=lambda p: str(p.date))


# --- Site -----------------------------------------------------------------

def build(out: Path, mesh: bool, render: bool, src: Path | None = None):
    src = src or max(REPO.glob('step/*.step.zip'), key=lambda p: p.stat().st_mtime)
    print(f'reading {src}')
    step = stepfile.Step(stepfile.load(src))
    catalog = Catalog(step)
    catalog.load_meta()
    print(f'{len(catalog.pages)} designs: ' + ', '.join(f'{n} {k}' for k, n in collections.Counter(p.kind for p in catalog.pages.values()).most_common()))

    if out.exists():
        for f in out.iterdir():
            if f.name not in ('models', 'img', 'compare'):     # kept: slow to make again
                shutil.rmtree(f) if f.is_dir() else f.unlink()
    out.mkdir(parents=True, exist_ok=True)
    models(catalog, out, mesh)
    shots(catalog, out, render)
    locators(catalog, out)
    motions(catalog, out)
    components = hardware(catalog)
    zipped = downloads(catalog, out, src)
    videos, playlist, doc_videos = youtube(catalog)
    shutil.copytree(HERE / 'static', out / 'static')
    three = HERE / 'mesh' / 'node_modules' / 'three'
    for f in ('build/three.module.js', 'build/three.core.js', 'examples/jsm/loaders/GLTFLoader.js',
              'examples/jsm/controls/OrbitControls.js', 'examples/jsm/environments/RoomEnvironment.js',
              'examples/jsm/utils/BufferGeometryUtils.js', 'examples/jsm/utils/SkeletonUtils.js'):
        dst = out / 'static' / 'three' / f.replace('build/', '').replace('examples/jsm/', 'addons/')
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(three / f, dst)
    (out / 'static' / 'pages.json').write_text(json.dumps({p.slug: p.name for p in catalog.pages.values()}))
    mapped = machine_map(catalog, out)
    shutil.copytree(REPO / 'docs', out / 'docs')
    if (REPO / 'printables' / 'compare').exists():
        compare_images(REPO / 'printables' / 'compare', out / 'compare')
    for f in CONTENT.rglob('*'):
        if f.is_file() and f.suffix != '.md':
            (out / f.relative_to(CONTENT)).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, out / f.relative_to(CONTENT))

    env = jinja2.Environment(loader=jinja2.FileSystemLoader(HERE / 'templates'), autoescape=True,
                             trim_blocks=True, lstrip_blocks=True)
    env.globals.update(KINDS=KINDS, GITHUB=GITHUB, BRANCH=BRANCH, catalog=catalog, source=src.name, zipped=zipped)
    render = Renderer(catalog)
    docs = []
    for md in sorted(CONTENT.rglob('*.md')):
        rel = md.relative_to(CONTENT)
        if rel.parts[0] in ('parts', 'log'):
            continue
        meta, body = frontmatter(md)
        docs.append((rel.with_suffix('.html').as_posix(), meta, body))
    nav = sorted(((url, meta) for url, meta, _ in docs if 'nav' in meta), key=lambda um: um[1].get('order', 99))

    def write(url, template, **kw):
        root = '../' * url.count('/')
        (out / url).parent.mkdir(parents=True, exist_ok=True)
        (out / url).write_text(env.get_template(template).render(root=root, url=url, nav=nav, **kw))

    for url, meta, body in docs:
        root = '../' * url.count('/')
        content, toc = render(body, root)
        write(url, 'doc.html', meta=meta, content=content, toc=toc, videos=doc_videos.get(url, []))
    for page in catalog.pages.values():
        content, toc = render(page.body, '../')
        write(f'parts/{page.slug}.html', 'part.html', page=page, content=content, toc=toc,
              bom=sorted(page.bom().items(), key=lambda pn: (pn[0].kind, pn[0].name.lower())))
    write('machine.html', 'machine.html', page=catalog.top, mapped=mapped)
    # the CAD's history is part of the story now: old links land there
    (out / 'changes.html').write_text('<!doctype html><meta charset="utf-8"><title>Moved</title>'
                                      '<meta http-equiv="refresh" content="0; url=story.html#the-cad-over-time">'
                                      '<a href="story.html#the-cad-over-time">The CAD over time</a>')
    write('parts/index.html', 'parts.html', **parts_index(catalog))
    write('videos.html', 'videos.html', videos=videos, playlist=playlist)
    log = posts({v['id']: v for v in videos})
    for i, post in enumerate(log):
        content, toc = render(post.body, '../')
        write(post.url, 'post.html', post=post, content=content, toc=toc,
              prev=log[i - 1] if i else None, next=log[i + 1] if i + 1 < len(log) else None)
    write('log/index.html', 'log.html', posts=log)
    write('bom.html', 'bom.html', components=components,
          bom=sorted(catalog.top.bom().items(), key=lambda pn: (pn[0].kind, pn[0].name.lower())))
    (out / '.nojekyll').touch()
    print(f'wrote {out}')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', type=Path, default=HERE / 'out')
    ap.add_argument('--step', type=Path, help='the STEP export (default: the newest step/*.step.zip)')
    ap.add_argument('--no-mesh', action='store_true', help="don't cut and mesh, use the models already there")
    ap.add_argument('--no-shots', action='store_true', help="don't render, use the shots already there")
    a = ap.parse_args()
    build(a.out, not a.no_mesh, not a.no_shots, a.step and a.step.expanduser())
