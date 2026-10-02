"""The Hackaday logs from the Obsidian vault into guide/content/log, as the guide's own posts.

    uv run --group guide python guide/vault.py [~/limn-shot/limn_v1]

A post that's already there is left alone (they get edited by hand afterwards): delete it to import
it again. Pictures go to content/log/img as webp. Ones the vault doesn't have come from Hackaday's
CDN, which the post links to anyway.
"""
import argparse
import re
import sys
import urllib.request
from pathlib import Path

from PIL import Image

HERE = Path(__file__).parent
LOG = HERE / 'content' / 'log'
PROJECT = 'https://hackaday.io/project/205431-limn-pen-plotter-with-toolchanger'
AUTHOR = 'Prashant Sinha'
LOGS = {4: '247167-detecting-tools-tool-parameters-slicing',            # the ones other logs link to:
        6: '247188-rfid-read-source-available-on-github',               # the vault doesn't say
        9: '247548-applying-tool-parameters-tethered-tools'}
MAX = 1400                                      # px, the longer side


def slugify(s: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')


def picture(name: str, vault: Path) -> str | None:
    """The vault's (or Hackaday's) picture as content/log/img/<stem>.webp. Its site path."""
    out = LOG / 'img' / (Path(name).stem + '.webp')
    if not out.exists():
        src = next(vault.rglob(name), None)
        if src is None:
            tmp = out.with_suffix(Path(name).suffix)
            try:
                urllib.request.urlretrieve(f'https://cdn.hackaday.io/images/{name}', tmp)
            except OSError as e:
                print(f'{name}: not in the vault, and {e}', file=sys.stderr)
                return None
            src = tmp
        out.parent.mkdir(parents=True, exist_ok=True)
        im = Image.open(src)
        im = im.convert('RGBA' if im.mode in ('RGBA', 'LA', 'P') else 'RGB')
        im.thumbnail((MAX, MAX), Image.LANCZOS)
        im.save(out, quality=80)
        if src.parent == out.parent:
            src.unlink()
    return f'/log/img/{out.name}'


def convert(text: str, vault: Path) -> str:
    def image(m):
        path = picture(m.group(1).split('|')[0], vault)
        return f'![]({path})' if path else ''
    text = re.sub(r'^### \[.*?\]\(.*?\)\n+', '', text)                          # the title, again
    text = re.sub(r'^\d\d/\d\d/\d{4} at \d\d:\d\d • \[\d+ comments\]\(.*?\)\n+', '', text, flags=re.M)
    text = re.sub(r'^- ### \[\]\(.*?\)\s*$', '', text, flags=re.M)               # a link to the next log
    text = re.sub(r'\[!\[\[([^\]]+)\]\]\]\([^)]*\)', image, text)                 # [![[x.png]]](cdn/x.png)
    text = re.sub(r'!\[\[([^\]]+)\]\]', image, text)
    text = re.sub(r'^(IMG_\d+\.jpeg|\d+)\s*$', '', text, flags=re.M)              # stray file names
    if re.match(r'^- \S', text.lstrip()):                                        # a whole post in one bullet
        text = re.sub(r'^(?:- |    )', '', text.lstrip(), flags=re.M)
    text = re.sub(r'[ \t]+$', '', text, flags=re.M)
    text = re.sub(r'(!\[\]\([^)]+\))(?=\S)', r'\1\n\n', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip() + '\n'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('vault', type=Path, nargs='?', default=Path('~/limn-shot/limn_v1'))
    vault = ap.parse_args().vault.expanduser()
    for md in sorted(vault.rglob('hackaday_posts/*.md'), key=lambda p: int(p.name.split('.')[0]) if p.name[0].isdigit() else 0):
        m = re.match(r'(\d+)\. (.+)\.md$', md.name)
        if not m:
            continue
        n, title = int(m.group(1)), m.group(2)
        text = md.read_text()
        head, _, body = text[4:].partition('\n---\n') if text.startswith('---\n') else ('', '', text)
        date = re.search(r'published: (\S+)', head).group(1)
        url = re.match(r'### \[.*?\]\((https://hackaday\.io/project/205431/log/[^)#]+)\)', body.lstrip())
        url = url.group(1) if url else f'https://hackaday.io/project/205431/log/{LOGS[n]}' if n in LOGS else PROJECT + '/logs'
        out = LOG / f'{date[:10]}-{slugify(title)}.md'
        if out.exists():
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f'+++\ntitle = "{title}"\ndate = {date}\nauthor = "{AUTHOR}"\nhackaday = {n}\n'
                       f'source = "{url}"\n+++\n\n{convert(body, vault)}')
        print(f'wrote {out.relative_to(HERE)}')


if __name__ == '__main__':
    main()
