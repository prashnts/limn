# Limn plot - KiCad schematics and boards, as drawings
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# A .kicad_sch or .kicad_pcb (or a project as a .zip, for a schematic's sub-sheets) goes through
# kicad-cli (KiCad 8 on, on the plot server) into SVGs, in KiCad's colours: wires, symbols, text
# and each board layer are colours of their own, so each is a layer to give a pen. A schematic
# gives a drawing for each of its sheets; a board one of the layers asked for, its board area
# only. Then they are drawings like any SVG. KiCad's own text is drawn as strokes; the invisible
# copies it writes beside them (opacity 0, to search the SVG) are left out by svg.py.
import shutil
import subprocess
import zipfile
from pathlib import Path

from .job import Group

KINDS = {'.kicad_sch': 'schematic', '.kicad_pcb': 'board', '.zip': 'project'}
LAYERS = ['F.Cu', 'B.Cu', 'F.Silkscreen', 'B.Silkscreen', 'F.Mask', 'B.Mask', 'F.Fab', 'B.Fab',
          'F.Courtyard', 'B.Courtyard', 'Edge.Cuts', 'User.Drawings', 'User.Comments']
DEFAULT_LAYERS = ['F.Cu', 'Edge.Cuts']
TIMEOUT = 120


class KicadError(Exception):
    pass


def kind(name: str) -> str | None:
    '''schematic, board, project (a .zip), None: not KiCad's.'''
    return KINDS.get(Path(name).suffix.lower())


def cli() -> str:
    exe = shutil.which('kicad-cli')
    if not exe:
        raise KicadError('KiCad is not installed on the plot server (kicad-cli, KiCad 8 or later)')
    return exe


def _run(args):
    r = subprocess.run([cli(), *map(str, args)], capture_output=True, text=True, timeout=TIMEOUT)
    if r.returncode:
        raise KicadError((r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout).strip()
                         else f'kicad-cli failed ({r.returncode})')


def unpack(src: Path, into: Path) -> Path:
    '''A project .zip: unpacked into `into` -> the file to plot, its root schematic (the one named
    as its .kicad_pro), else its only schematic or board.'''
    with zipfile.ZipFile(src) as z:
        for m in z.infolist():
            p = (into / m.filename).resolve()
            if not str(p).startswith(str(into.resolve())):
                raise KicadError(f'{m.filename}: outside the project')
        z.extractall(into)
    files = [p for p in into.rglob('*') if p.suffix in ('.kicad_sch', '.kicad_pcb') and '__MACOSX' not in p.parts]
    for pro in into.rglob('*.kicad_pro'):
        root = pro.with_suffix('.kicad_sch')
        if root.exists():
            return root
    if len(files) == 1:
        return files[0]
    sch = [p for p in files if p.suffix == '.kicad_sch']
    if not files:
        raise KicadError('no schematic or board in the .zip')
    raise KicadError(f'which of its {len(files)} files? A .kicad_pro names the root schematic' if len(sch) > 1
                     else 'a .zip with a board and a schematic: upload the one to plot')


def to_svgs(src: Path, out: Path, layers=None, mirror=False, frame=False) -> list[Path]:
    '''The file as SVGs in `out`: a schematic's sheets in the order KiCad has them, or the board's
    layers as one drawing (board area only; mirror: seen from below, for the B. layers).'''
    out.mkdir(parents=True, exist_ok=True)
    if src.suffix == '.kicad_sch':
        _run(['sch', 'export', 'svg', '--no-background-color', *([] if frame else ['--exclude-drawing-sheet']),
              '-o', out, src])
        svgs = sorted(out.glob('*.svg'), key=lambda p: (p.stem != src.stem, p.stem))     # the root sheet first
    elif src.suffix == '.kicad_pcb':
        bad = [x for x in (layers or []) if x not in LAYERS]
        if bad:
            raise KicadError(f'no layer {", ".join(bad)} (there are {", ".join(LAYERS)})')
        f = out / f'{src.stem}.svg'
        _run(['pcb', 'export', 'svg', '--mode-single', '--layers', ','.join(layers or DEFAULT_LAYERS),
              '--page-size-mode', '2', '--exclude-drawing-sheet', '--drill-shape-opt', '2',
              *(['--mirror'] if mirror else []), '-o', f, src])
        svgs = [f]
    else:
        raise KicadError(f'{src.name}: not a KiCad schematic or board')
    if not svgs or not all(p.exists() and p.stat().st_size for p in svgs):
        raise KicadError(f'{src.name}: KiCad wrote nothing')
    return svgs


def groups(src_kind, d) -> dict[str, Group]:
    '''Its colours' first say: a schematic's pale fills (the symbols' bodies) not drawn; a
    board's white (the drill holes, through the copper) a mask, so the copper's fill leaves them.'''
    out = {}
    for k in d.groups():
        part, colour = k.split(' ')
        if part != 'fill':
            continue
        r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
        light = (r + g + b) / 3 > 215
        if src_kind == 'board' and light:
            out[k] = Group(mask=True)
        elif src_kind == 'schematic' and light:
            out[k] = Group()
    return out
