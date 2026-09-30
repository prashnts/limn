# Limn plot - command line
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
#   uv run python -m plot colors drawing.svg
#   uv run python -m plot slice drawing.svg --map '#ffcd00=T1' --map '#ffffff=mask' -o out.gcode --preview out.svg --save-job job.json
#   uv run python -m plot job job.json -o out.gcode --preview out.svg
#   uv run python -m plot preview any.gcode -o preview.svg
#   uv run python -m plot serve           # the web UI, http://<host>:4220
from pathlib import Path

import typer

from . import svg as svgmod
from .emit import plot
from .job import Group, Job, Obj, Placement
from .preview import parse, render_svg, stats
from .profile import load_machine, load_tools
from .slicer import Cache, default_groups

app = typer.Typer(no_args_is_help=True, add_completion=False, help='Limn plot: SVG to G-code, and G-code previews.')


def _minutes(s):
    return f'{int(s // 60)}m{int(s % 60):02d}s'


def _report(result):
    st = result.stats
    if st:
        typer.echo(f"draw {st['draw_mm'] / 1000:.2f} m, travel {st['travel_mm'] / 1000:.2f} m, "
                   f"{st['tool_changes']} tool changes, ~{_minutes(st['time_s'])}")
        for name, t in st['tools'].items():
            typer.echo(f"  {name}: {t['draw_mm'] / 1000:.2f} m in {t['strokes']} strokes")
        if 'bounds' in st:
            typer.echo('  drawn inside ' + ', '.join(f'{v:.1f}' for v in st['bounds']))
    for p in result.problems:
        typer.secho(f'! {p}', fg='yellow', err=True)


def _write(job, result, out, preview):
    if out:
        Path(out).write_text(result.gcode)
        typer.echo(f'wrote {out}')
    if preview:
        machine = load_machine(job.machine, job.machine_overrides)
        Path(preview).write_text(render_svg(parse(result.gcode), machine, load_tools(job.tools)))
        typer.echo(f'wrote {preview}')


@app.command()
def colors(svg: Path, tools: str = 'tools'):
    '''The colours of a drawing, and the tool each goes to by default.'''
    d = svgmod.load(svg)
    t = load_tools(tools)
    defaults = default_groups(d, t)
    typer.echo(f'page {d.size[0]:.1f} x {d.size[1]:.1f} mm, {len(d.shapes)} shapes, {len(d.texts)} texts')
    for key, g in sorted(d.groups().items(), key=lambda kv: -kv[1]['length']):
        grp = defaults[key]
        to = 'mask' if grp.mask else grp.tool or '-'
        widths = ', '.join(f'{w:g}' for w in sorted(g['widths'])) or '-'
        typer.echo(f"{key:18} {g['shapes']:5} shapes {g['length']:9.1f} mm  widths {widths:12} -> {to}")


def _groups(maps):
    '''--map 'COLOR=TO': '#ffcd00=T1' (stroke and fill), 'stroke #ffcd00=T1', '#ffffff=mask', '#000=skip'.'''
    out = {}
    for m in maps:
        key, to = m.rsplit('=', 1)
        key = key.strip().lower()
        g = Group(mask=True) if to == 'mask' else Group() if to == 'skip' else Group(tool=to)
        keys = [key] if ' ' in key else [f'stroke {key}', f'fill {key}']
        for k in keys:
            out[k] = g
    return out


@app.command('slice')
def slice_(svg: Path,
           out: Path = typer.Option(None, '-o', help='G-code file'),
           preview: Path = typer.Option(None, help='SVG preview of the G-code'),
           save_job: Path = typer.Option(None, help='the job, to change and run with `job`'),
           at: str = typer.Option(None, help="x,y of the drawing's bottom left; default: centred in the draw area"),
           rotate: float = 0.0,
           scale: float = 1.0,
           map: list[str] = typer.Option([], help="COLOR=T1|mask|skip, e.g. '#ffcd00=T1' or 'fill #fff=mask'"),
           fill: str = typer.Option('hatch', help='hatch, crosshatch, concentric, none'),
           angle: float = 45.0,
           occlude: bool = typer.Option(True, help='what is painted over hides what is under'),
           machine: str = 'limn', tools: str = 'tools'):
    '''One SVG to G-code.'''
    t = load_tools(tools)
    d = svgmod.load(svg)
    groups = {k: g.model_copy(update={'fill': fill, 'angle': angle}) for k, g in default_groups(d, t).items()}
    groups.update(_groups(map))
    obj = Obj(id=svg.stem, svg=str(svg.resolve()), scale=scale, occlude=occlude, groups=groups,
              placement=Placement(rotate=rotate))
    job = Job(machine=machine, tools=tools, objects=[obj])
    cache = Cache()
    if at:
        x, y = (float(v) for v in at.split(','))
        obj.placement = Placement(x=x, y=y, rotate=rotate)
    else:
        s = cache.get(obj, t)
        if s.bounds:
            m = load_machine(machine)
            corners = obj.placement.apply([[s.bounds[0], s.bounds[1], 0], [s.bounds[2], s.bounds[3], 0],
                                           [s.bounds[0], s.bounds[3], 0], [s.bounds[2], s.bounds[1], 0]])
            cx, cy = corners[:, 0].mean(), corners[:, 1].mean()
            ax0, ay0, ax1, ay1 = m.draw_area
            obj.placement = Placement(x=(ax0 + ax1) / 2 - cx, y=(ay0 + ay1) / 2 - cy, rotate=rotate)
    result, _ = plot(job, cache)
    _report(result)
    _write(job, result, out, preview)
    if save_job:
        job.save(save_job)
        typer.echo(f'wrote {save_job}')


@app.command('job')
def job_(path: Path,
         out: Path = typer.Option(None, '-o'),
         preview: Path = typer.Option(None)):
    '''A saved job to G-code.'''
    job = Job.load(path)
    result, _ = plot(job)
    _report(result)
    _write(job, result, out, preview)


@app.command('preview')
def preview_(gcode: Path,
             out: Path = typer.Option(..., '-o'),
             travel: bool = True,
             machine: str = 'limn', tools: str = 'tools'):
    '''Any G-code as an SVG over the bed.'''
    m, t = load_machine(machine), load_tools(tools)
    sim = parse(gcode.read_text())
    st = stats(sim, m, t)
    typer.echo(f"{'ours' if sim.ours else 'foreign'}: draw {st['draw_mm'] / 1000:.2f} m, "
               f"travel {st['travel_mm'] / 1000:.2f} m, {st['tool_changes']} tool changes, ~{_minutes(st['time_s'])}")
    out.write_text(render_svg(sim, m, t, travel=travel))
    typer.echo(f'wrote {out}')


@app.command()
def serve(host: str = '0.0.0.0', port: int = 4220,
          data: Path = typer.Option(None, help='the workspace folder (default plot-data/, or LIMN_PLOT_DATA)'),
          reload: bool = typer.Option(False, help='restart when the code changes')):
    '''The web UI: drop SVGs on the bed, paint them, preview and plot.'''
    from .server import main
    main(host, port, data, reload)


@app.command('tools')
def tools_(tools: str = 'tools'):
    '''The tools and what they are.'''
    for tid, t in load_tools(tools).items():
        typer.echo(f'{tid:4} {t.kind:7} {t.name:18} {t.width:g}mm {t.color}  z {t.z_limits(load_machine())}')


if __name__ == '__main__':
    app()
