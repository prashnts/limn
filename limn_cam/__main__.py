# Limn cam - command line
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
#   uv run python -m limn_cam ladder T0 T1 --z 2.4:1.0:0.1          # plot it, photograph, report
#   uv run python -m limn_cam ladder T0 T1 --plan -o ladder.gcode   # only the G-code
#   uv run python -m limn_cam analyze before.jpg after.jpg ladder.json
#   uv run python -m limn_cam play T3 --spots '10,125;55,125'       # the Z axis's play -> plot/profiles/play.toml
#   uv run python -m limn_cam tags --camera axiscam                 # ArUco tags in a shot
import json
import os
import time
from pathlib import Path

import typer

from . import backend as backends
from . import ladder as lad
from . import play as playmod
from .image import load
from .moonraker import Moonraker

app = typer.Typer(no_args_is_help=True, add_completion=False, help='Limn cam: what the cameras see of a plot.')
SHOTS = Path(os.environ.get('LIMN_SHOTS', Path.home() / 'limn-shot'))


def _machine(bed):
    from plot.profile import load_machine
    return load_machine(overrides={'bed_id': bed} if bed else None)


def _ladder(pens, z, origin, pitch, length, row_gap, margin, cross):
    top, bottom, step = (float(v) for v in z.split(':'))
    ox, oy = (float(v) for v in origin.split(','))
    return lad.Ladder(pens=list(pens), z_top=top, z_bottom=bottom, z_step=step, origin=(ox, oy),
                      pitch=pitch, length=length, row_gap=row_gap, margin=margin, cross=cross)


def _moonraker(url):
    return Moonraker(url or os.environ.get('LIMN_MOONRAKER') or _machine(None).moonraker)


@app.command()
def ladder(pens: list[str] = typer.Argument(None, help="tool macros: T0 T1 .."), z: str = typer.Option('2.4:1.0:0.1', help='top:bottom:step, G-code Z'),
           origin: str = '12,67', pitch: float = 2.5, length: float = 4.0, row_gap: float = 6.0,
           margin: float = 5.0, cross: float = 4.0, bed: str = 'BED_5',
           camera: str = 'IR Top', park: str = '0,0,9', url: str = None, backend: str = 'auto',
           touch: float = typer.Option(None, help="G-code z the new dz makes a pen touch at (the machine's z_touch)"),
           plan: bool = False, out: Path = typer.Option(None, '-o'),
           resume: Path = typer.Option(None, help="a ladder's base (…/ladder-<time>) cut short: draws only "
                                                  "--draw's rows where it had them, no crosses, and reads "
                                                  "all against its before shot"),
           draw: str = typer.Option(None, help='with --resume: the pens to draw now, T1,T3')):
    '''Each pen draws strokes at falling z; the camera tells where it starts to draw.'''
    if resume:
        ld = lad.Ladder(**json.loads(Path(f'{resume}.json').read_text()))
    else:
        ld = _ladder(pens, z, origin, pitch, length, row_gap, margin, cross)
    x0, y0, x1, y1 = ld.extent()
    typer.echo(f'ladder: {len(ld.zs)} z from {ld.zs[0]} to {ld.zs[-1]}, over ({x0:.1f}, {y0:.1f}) .. ({x1:.1f}, {y1:.1f})')
    machine = _machine(bed)
    only = draw.split(',') if draw else None
    text, problems = lad.gcode(ld, machine, only, anchors=not resume)
    for p in problems:
        typer.secho(f'! {p}', fg='red', err=True)
    if plan or problems:
        if out and not problems:
            out.write_text(text)
            typer.echo(f'wrote {out}')
        raise typer.Exit(1 if problems else 0)
    mr = _moonraker(url)
    if mr.busy():
        typer.secho('the printer is busy', fg='red', err=True)
        raise typer.Exit(1)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    SHOTS.mkdir(parents=True, exist_ok=True)
    px, py, pz = (float(v) for v in park.split(','))
    goto = f'LAZY_HOME\nG90\nG1 Z{pz} F600\nG1 X{px} Y{py} F6000\nM400\nG4 P1500'
    if resume:
        base = Path(f'{resume}-{stamp}')
        before = Path(f'{resume}-0-before.jpg').read_bytes()
    else:
        base = SHOTS / f'ladder-{stamp}'
        mr.run(goto)
        before = mr.snapshot(camera)
        Path(f'{base}-0-before.jpg').write_bytes(before)
        Path(f'{base}.json').write_text(json.dumps(ld.to_dict()))
    Path(f'{base}.gcode').write_text(text)
    typer.echo(f'plotting {base.name}.gcode ..')
    end = mr.print_file(f'limn-cam-{base.name}.gcode', text)
    if end['state'] != 'complete':
        typer.secho(f"the ladder ended {end['state']}: {end.get('message')}", fg='red', err=True)
        raise typer.Exit(1)
    mr.run(goto)
    after = mr.snapshot(camera)
    Path(f'{base}-1-after.jpg').write_bytes(after)
    _analyze(before, after, ld, backend, base, mr, machine, touch)


def _shoot(mr, camera, park, base, text, name):
    '''Park, shot, plot `text`, park, shot -> (before, after).'''
    px, py, pz = (float(v) for v in park.split(','))
    goto = f'LAZY_HOME\nG90\nG1 Z{pz} F600\nG1 X{px} Y{py} F6000\nM400\nG4 P1500'
    mr.run(goto)
    before = mr.snapshot(camera)
    Path(f'{base}-0-before.jpg').write_bytes(before)
    Path(f'{base}.gcode').write_text(text)
    typer.echo(f'plotting {Path(base).name}.gcode ..')
    end = mr.print_file(name, text)
    if end['state'] != 'complete':
        typer.secho(f"it ended {end['state']}: {end.get('message')}", fg='red', err=True)
        raise typer.Exit(1)
    mr.run(goto)
    after = mr.snapshot(camera)
    Path(f'{base}-1-after.jpg').write_bytes(after)
    return before, after


@app.command()
def play(pen: str, spots: str = typer.Option(..., help="where the rows of tests start: 'x,y;x,y' (mm), "
                                                       "3 or more spread over the sheet"),
         press: float = typer.Option(None, help="mm past touch while drawing: the pen's own (pens.toml) by default"),
         rises: str = typer.Option('0:3:0.25', help='trial rises over z_touch, from:to:step'),
         bed: str = 'BED_5', camera: str = 'IR Top', park: str = '0,0,9', url: str = None, backend: str = 'auto',
         save: bool = typer.Option(True, help='write plot/profiles/play.toml'), plan: bool = False,
         out: Path = typer.Option(None, '-o')):
    '''How far the Z axis's play keeps a pressed pen on the paper, at a few spots.'''
    from plot.emit import load
    from plot.job import Job
    from plot.profile import PROFILES
    machine = _machine(bed)
    if press is None:
        mr = _moonraker(url)
        _, tools = load(Job(machine_overrides={'bed_id': bed} if bed else {}), mr.query(limn='tools')['limn'].get('tools'))
        press = tools[pen].pressed if pen in tools and tools[pen].pressed is not None else 0.2
    lo, hi, step = (float(v) for v in rises.split(':'))
    test = playmod.PlayTest(pen=pen, press=press, z_touch=machine.z_touch,
                            spots=[tuple(float(v) for v in s.split(',')) for s in spots.split(';')],
                            rises=[round(lo + i * step, 3) for i in range(int(round((hi - lo) / step)) + 1)])
    x0, y0, x1, y1 = test.extent()
    typer.echo(f'play: {pen} pressed {press:g}, {len(test.spots)} spots x {len(test.rises)} rises, '
               f'over ({x0:.1f}, {y0:.1f}) .. ({x1:.1f}, {y1:.1f})')
    text, problems = playmod.gcode(test, machine)
    for p in problems:
        typer.secho(f'! {p}', fg='red', err=True)
    if plan or problems:
        if out and not problems:
            out.write_text(text)
            typer.echo(f'wrote {out}')
        raise typer.Exit(1 if problems else 0)
    mr = _moonraker(url)
    if mr.busy():
        typer.secho('the printer is busy', fg='red', err=True)
        raise typer.Exit(1)
    SHOTS.mkdir(parents=True, exist_ok=True)
    base = SHOTS / f'play-{time.strftime("%Y%m%d-%H%M%S")}'
    Path(f'{base}.json').write_text(json.dumps(test.to_dict()))
    before, after = _shoot(mr, camera, park, base, text, f'limn-cam-{base.name}.gcode')
    res = playmod.analyze(before, after, test, backends.get(backend))
    Path(f'{base}-result.json').write_text(json.dumps(res.to_dict(), indent=1))
    typer.echo(playmod.report(res))
    if save and any(s.per_press is not None for s in res.spots):
        playmod.save(res, PROFILES / 'play.toml', test)
        typer.echo(f'wrote {PROFILES / "play.toml"}: plot/ lifts by it from now on')


def _analyze(before, after, ld, backend, base, mr, machine, touch):
    res = lad.analyze(before, after, ld, backends.get(backend))
    sug = None
    if mr is not None:
        tags = mr.query(limn='tools')['limn'].get('tools')
        sug = lad.suggest(res, tags, machine.holders, machine.z_touch if touch is None else touch)
    Path(f'{base}-result.json').write_text(json.dumps({'result': res.to_dict(), 'suggest': sug}, indent=1))
    lad.overlay(after, res, ld).save(f'{base}-2-overlay.png')
    typer.echo(lad.report(res, sug))
    typer.echo(f'shots and results: {base}-*')


@app.command()
def analyze(before: Path, after: Path, spec: Path, backend: str = 'auto', url: str = None, bed: str = 'BED_5',
            touch: float = None, printer: bool = typer.Option(False, help='ask Klipper for the tags, to suggest dz')):
    '''A ladder's shots again: before, after, and the ladder's .json.'''
    ld = lad.Ladder(**json.loads(spec.read_text()))
    base = after.with_suffix('')
    _analyze(before.read_bytes(), after.read_bytes(), ld, backend, base,
             _moonraker(url) if printer else None, _machine(bed), touch)


@app.command()
def tags(camera: str = 'axiscam', image: Path = None, url: str = None, dictionary: str = None):
    '''The ArUco tags a camera (or an image) sees.'''
    gray = load(image) if image else load(_moonraker(url).snapshot(camera))
    found = backends.get('opencv').markers(gray, dictionary)
    for m in found:
        typer.echo(f'tag {m.id}: centre {m.centre.round(1).tolist()}, side {m.size:.1f} px')
    if not found:
        typer.echo('no tags')


if __name__ == '__main__':
    app()
