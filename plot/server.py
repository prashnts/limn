# Limn plot - the web UI's server
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# One workspace, kept in a folder (LIMN_PLOT_DATA, default plot-data/): the
# job, the SVGs dropped on the bed (uploads/) and the fonts (fonts/). Every
# change is saved; the UI slices after each one, from the cache when only a
# placement changed. Plots go to Klipper through Moonraker.
#
#   uv run python -m plot serve [--port 4220] [--data plot-data]
import os
import re
import threading
import time
from pathlib import Path

import numpy as np
import requests
from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import pens as pen_library
from . import profile, svg
from .emit import load, plot
from .fonts import HERSHEY, FontStore
from .job import Group, Job, Obj, Placement, ShapePaint
from .preview import parse
from .profile import bed_papers, load_pens
from .slicer import Cache, default_groups, text_shapes

STATIC = Path(__file__).parent / 'static'
DEFAULT_DATA = Path(__file__).resolve().parent.parent / 'plot-data'
OBJ_KEYS = {'placement', 'scale', 'occlude', 'tolerance', 'groups', 'shapes', 'text', 'texts', 'surface'}


def _d(p, closed):
    s = 'M' + ' L'.join(f'{x:.3f},{y:.3f}' for x, y in np.round(p[:, :2], 3))
    return s + ('Z' if closed else '')


class Workspace:
    def __init__(self, data):
        self.data = Path(data)
        self.uploads = self.data / 'uploads'
        self.uploads.mkdir(parents=True, exist_ok=True)
        self.fonts = FontStore(self.data / 'fonts')
        self.job_path = self.data / 'job.json'
        self.job = Job.load(self.job_path) if self.job_path.exists() else Job()
        self.job._root = self.data
        self.cache = Cache()
        self.lock = threading.RLock()
        self.gcode, self.name = None, None
        self.unsafe = []            # the sliced G-code breaks safe_z: it isn't sent
        self.undos, self.redos = [], []
        self.tags = None            # printer.limn.tools: what the tools' tags say, None: not asked yet
        self.printer_job = None     # a scan or a tag write running on the printer, see run_on_printer()

    def save(self):
        self.job.save(self.job_path)

    def remember(self):
        '''Before a change: the job as it is, for undo.'''
        self.undos = self.undos[-199:] + [self.job.model_dump_json()]
        self.redos = []

    def step(self, back=True):
        '''Undo (back) or redo: whether there was anything to.'''
        src, dst = (self.undos, self.redos) if back else (self.redos, self.undos)
        if not src:
            return False
        dst.append(self.job.model_dump_json())
        job = Job.model_validate_json(src.pop())
        job._root = self.data
        self.job = job
        self.save()
        return True

    def obj(self, oid) -> Obj:
        for o in self.job.objects:
            if o.id == oid:
                return o
        raise HTTPException(404, f'no object {oid}')

    def drawing(self, o):
        return svg.load_cached(self.data / o.svg, o.tolerance)

    def fetch_tags(self, timeout=2):
        '''The tags from Klipper, when it can be reached -> whether they changed.'''
        machine, _ = load(self.job)
        try:
            r = requests.get(f'{machine.moonraker.rstrip("/")}/printer/objects/query', params={'limn': 'tools'},
                             timeout=timeout)
            r.raise_for_status()
            tags = (r.json()['result']['status'].get('limn') or {}).get('tools') or {}
        except Exception:
            if self.tags is None:
                self.tags = {}
            return False
        changed = tags != self.tags
        self.tags = tags
        return changed

    def state(self):
        if self.tags is None:
            self.fetch_tags()
        machine, tools = load(self.job, self.tags)
        objects = {}
        for o in self.job.objects:
            d = self.drawing(o)
            defaults = default_groups(d, tools)
            groups = [{'key': k, 'shapes': g['shapes'], 'texts': g.get('texts', 0), 'length': g['length'] * o.scale,
                       'widths': sorted(w * o.scale for w in g['widths']), 'default': defaults[k].model_dump()}
                      for k, g in sorted(d.groups().items(), key=lambda kv: -kv[1]['length'])]
            texts = []
            for t in d.texts:
                spec = o.texts.get(str(t.index), o.text)
                found = self.fonts.match(t.family, t.weight, t.style)
                texts.append({'index': t.index, 'text': t.text, 'family': t.family, 'weight': t.weight,
                              'style': t.style, 'colour': t.fill or t.stroke,
                              'size': t.size * abs(t.matrix[0] * t.matrix[3] - t.matrix[1] * t.matrix[2]) ** 0.5 * o.scale,
                              'found': found.file if found else None, 'spec': spec.model_dump()})
            objects[o.id] = {'size': [d.size[0] * o.scale, d.size[1] * o.scale], 'groups': groups,
                             'texts': texts, 'shapes': len(d.shapes), 'skipped': d.skipped}
        m = machine.model_dump()
        pens = load_pens()
        holders = [{'t': f'T{i}', 'holder': h, 'tag': (self.tags or {}).get(str(h))}
                   for i, h in enumerate(machine.holders)]
        return {'job': self.job.model_dump(), 'machine': m, 'beds': bed_papers(machine),
                'tools': {k: {**t.model_dump(), 'spacing': t.spacing} for k, t in tools.items()},
                'pens': pens, 'kinds': pen_library.kinds(), 'holders': holders,
                'fonts': [f.__dict__ for f in self.fonts.fonts()],
                'line_fonts': HERSHEY + [f.file for f in self.fonts.fonts() if f.kind == 'line'],
                'objects': objects}

    def shapes(self, o):
        '''What the drawing looks like, for the UI: its shapes, object mm (y up).'''
        d = self.drawing(o)
        h, s = d.size[1], o.scale
        local = lambda p: np.column_stack([p[:, 0] * s, (h - p[:, 1]) * s])
        out = []
        for sh in sorted(d.shapes + text_shapes(d, o, self.fonts, []), key=lambda sh: sh.index):
            out.append({'i': sh.index, 'stroke': sh.stroke, 'fill': sh.fill, 'w': sh.width * s,
                        'so': sh.stroke_opaque, 'fo': sh.fill_opaque, 'line': sh.line,
                        'text': sh.line or any(t.index == sh.index for t in d.texts), 'rule': sh.rule,
                        'd': ' '.join(_d(local(p), c) for p, c in zip(sh.paths, sh.closed))})
        return {'size': [d.size[0] * s, d.size[1] * s], 'shapes': out}

    def slice(self):
        t0 = time.monotonic()
        result, sliced = plot(self.job, self.cache, self.fonts, self.tags)
        self.gcode = result.gcode
        self.name = 'limn-' + '-'.join(o.id for o in self.job.objects)[:60] + '.gcode'
        sim = parse(result.gcode)
        runs = [[k, t, n, np.round(pts[:, :2], 3).ravel().tolist()] for k, t, pts, n in sim.runs()]
        bounds = {}
        for o in self.job.objects:
            b = sliced[o.id].bounds
            if b:
                c = o.placement.apply([[b[0], b[1], 0], [b[2], b[1], 0], [b[2], b[3], 0], [b[0], b[3], 0]])
                bounds[o.id] = [*c[:, :2].min(axis=0).tolist(), *c[:, :2].max(axis=0).tolist()]
        self.unsafe = result.unsafe
        return {'tools': sim.tools, 'runs': runs, 'lines': result.gcode.count('\n'), 'stats': result.stats,
                'problems': result.problems, 'unsafe': bool(result.unsafe), 'bounds': bounds, 'ms': round((time.monotonic() - t0) * 1000)}


def _unique(names, stem):
    stem = re.sub(r'[^\w\-]', '_', stem)[:40] or 'drawing'
    name, n = stem, 1
    while name in names:
        n += 1
        name = f'{stem}-{n}'
    return name


def create_app(data=None):
    ws = Workspace(data or os.environ.get('LIMN_PLOT_DATA') or DEFAULT_DATA)
    app = FastAPI(title='limn plot')
    app.state.ws = ws
    app.mount('/static', StaticFiles(directory=STATIC), name='static')

    @app.get('/', response_class=HTMLResponse)
    def index():
        return (STATIC / 'index.html').read_text()

    @app.get('/api/state')
    def state():
        with ws.lock:
            return ws.state()

    @app.get('/api/bed-art')
    def bed_art():
        machine, _ = load(ws.job)
        if not machine.bed_art or not Path(machine.bed_art).exists():
            raise HTTPException(404)
        return FileResponse(machine.bed_art)

    @app.post('/api/objects')
    async def add_object(file: UploadFile = File(...)):
        data = await file.read()
        with ws.lock:
            oid = _unique({o.id for o in ws.job.objects}, Path(file.filename or 'drawing').stem)
            path = ws.uploads / f'{oid}.svg'
            path.write_bytes(data)
            try:
                d = svg.load_cached(path)
            except Exception as e:
                path.unlink()
                raise HTTPException(400, f'{file.filename}: not an SVG I can read ({e})')
            machine, _ = load(ws.job)
            x0, y0, x1, y1 = machine.draw_area
            w, h = d.size
            scale = min(1.0, 0.95 * (x1 - x0) / w, 0.95 * (y1 - y0) / h) if w and h else 1.0
            obj = Obj(id=oid, svg=f'uploads/{path.name}', scale=round(scale, 4),
                      placement=Placement(x=(x0 + x1 - w * scale) / 2, y=(y0 + y1 - h * scale) / 2))
            ws.remember()
            ws.job.objects.append(obj)
            ws.save()
            return {'id': oid, 'state': ws.state()}

    @app.patch('/api/objects/{oid}')
    def patch_object(oid: str, body: dict = Body(...)):
        with ws.lock:
            o = ws.obj(oid)
            bad = set(body) - OBJ_KEYS
            if bad:
                raise HTTPException(400, f'not changeable: {", ".join(sorted(bad))}')
            new = Obj(**{**o.model_dump(), **body})
            ws.remember()
            ws.job.objects[ws.job.objects.index(o)] = new
            ws.save()
            return ws.state()

    @app.post('/api/objects/{oid}/duplicate')
    def duplicate(oid: str):
        with ws.lock:
            o = ws.obj(oid)
            nid = _unique({x.id for x in ws.job.objects}, o.id)
            p = o.placement
            ws.remember()
            ws.job.objects.append(o.model_copy(deep=True, update={
                'id': nid, 'placement': Placement(x=p.x + 5, y=p.y - 5, rotate=p.rotate)}))
            ws.save()
            return {'id': nid, 'state': ws.state()}

    @app.delete('/api/objects/{oid}')
    def delete_object(oid: str):
        with ws.lock:
            o = ws.obj(oid)
            ws.remember()
            ws.job.objects.remove(o)        # its SVG stays in uploads/: undo brings it back
            ws.save()
            return ws.state()

    @app.get('/api/objects/{oid}/shapes')
    def shapes(oid: str):
        with ws.lock:
            return ws.shapes(ws.obj(oid))

    @app.post('/api/objects/{oid}/paint')
    def paint(oid: str, body: dict = Body(...)):
        '''{index, target: stroke|fill|both, scope: shape|colour, to: <tool>|mask|skip|reset}'''
        with ws.lock:
            o = ws.obj(oid)
            _, tools = load(ws.job)
            d = ws.drawing(o)
            index, to = int(body['index']), body['to']
            target, scope = body.get('target', 'both'), body.get('scope', 'shape')
            sh = next((s for s in d.shapes if s.index == index), None)
            run = next((t for t in d.texts if t.index == index), None)
            colours = {'stroke': sh.stroke, 'fill': sh.fill} if sh else {'stroke': None, 'fill': run.fill or run.stroke}
            parts = [p for p in ('stroke', 'fill') if target in (p, 'both') and colours[p]]
            defaults = default_groups(d, tools)
            groups, shapes = dict(o.groups), dict(o.shapes)
            for part in parts:
                key = f'{part} {colours[part]}'
                base = groups.get(key) or defaults.get(key) or Group()
                g = None if to == 'reset' else base.model_copy(update={
                    'tool': to if to not in ('mask', 'skip') else None, 'mask': to == 'mask'})
                if scope == 'colour':
                    if g is None:
                        groups.pop(key, None)
                    else:
                        groups[key] = g
                else:
                    cur = shapes.get(str(index), ShapePaint())
                    cur = cur.model_copy(update={part: g})
                    if cur.stroke is None and cur.fill is None:
                        shapes.pop(str(index), None)
                    else:
                        shapes[str(index)] = cur
            ws.remember()
            ws.job.objects[ws.job.objects.index(o)] = o.model_copy(update={'groups': groups, 'shapes': shapes})
            ws.save()
            return ws.state()

    @app.patch('/api/job')
    def patch_job(body: dict = Body(...)):
        '''{machine_overrides: {key: value|null}, tool_overrides: {tool: {key: value|null}}, tool_order}'''
        with ws.lock:
            job = ws.job
            mo = dict(job.machine_overrides)
            for k, v in (body.get('machine_overrides') or {}).items():
                if v is None:
                    mo.pop(k, None)
                else:
                    mo[k] = v
            to = {k: dict(v) for k, v in job.tool_overrides.items()}
            for tid, over in (body.get('tool_overrides') or {}).items():
                cur = to.setdefault(tid, {})
                for k, v in over.items():
                    if v is None:
                        cur.pop(k, None)
                    else:
                        cur[k] = v
            new = job.model_copy(update={'machine_overrides': mo, 'tool_overrides': {k: v for k, v in to.items() if v},
                                         'tool_order': body.get('tool_order', job.tool_order)})
            new._root = ws.data
            try:
                load(new)
            except Exception as e:
                raise HTTPException(400, str(e))
            ws.remember()
            ws.job = new
            ws.save()
            return ws.state()

    @app.post('/api/undo')
    def undo():
        with ws.lock:
            return {'changed': ws.step(back=True), 'state': ws.state()}

    @app.post('/api/redo')
    def redo():
        with ws.lock:
            return {'changed': ws.step(back=False), 'state': ws.state()}

    @app.post('/api/slice')
    def slice_():
        with ws.lock:
            return ws.slice()

    @app.get('/api/gcode')
    def gcode(inline: bool = False):
        with ws.lock:
            if ws.gcode is None:
                ws.slice()
            headers = {} if inline else {'Content-Disposition': f'attachment; filename="{ws.name}"'}
            return PlainTextResponse(ws.gcode, headers=headers)

    @app.get('/api/fonts')
    def fonts():
        return [f.__dict__ for f in ws.fonts.fonts()]

    @app.post('/api/fonts')
    async def add_font(file: UploadFile = File(...)):
        data = await file.read()
        with ws.lock:
            try:
                info = ws.fonts.add(file.filename or 'font', data)
            except ValueError as e:
                raise HTTPException(400, str(e))
            return {'font': info.__dict__, 'state': ws.state()}

    @app.delete('/api/fonts/{name}')
    def delete_font(name: str):
        with ws.lock:
            ws.fonts.remove(name)
            return ws.state()

    def moonraker():
        machine, _ = load(ws.job)
        return machine.moonraker.rstrip('/')

    @app.get('/api/printer')
    def printer():
        url = moonraker()
        try:
            r = requests.get(f'{url}/printer/objects/query',
                             params={'print_stats': '', 'virtual_sdcard': '', 'limn': '', 'toolhead': ''}, timeout=3)
            r.raise_for_status()
            st = r.json()['result']['status']
        except Exception as e:
            return {'ok': False, 'url': url, 'error': str(e), 'job': ws.printer_job}
        ps, limn = st.get('print_stats', {}), st.get('limn') or {}
        holder = limn.get('tool_holder') or {}
        tags = limn.get('tools') or {}
        with ws.lock:
            changed = tags != ws.tags
            ws.tags = tags
        return {'ok': True, 'url': url, 'state': ps.get('state'), 'file': ps.get('filename'),
                'tools': tags, 'tools_changed': changed, 'job': ws.printer_job,
                'progress': (st.get('virtual_sdcard') or {}).get('progress'),
                'homed': (st.get('toolhead') or {}).get('homed_axes'),
                'bed': limn.get('bed'), 'occupied': holder.get('occupied'), 'tag': limn.get('tag'),
                'scan': limn.get('scan')}

    def run_on_printer(what, script):
        '''A script that moves the machine for a while (a scan, a tag write), in the
        background: one at a time, never while printing. /api/printer tells how it went.'''
        job = ws.printer_job
        if job and not job['done']:
            raise HTTPException(409, f"the printer is busy with {job['what']}")
        url = moonraker()
        try:
            st = requests.get(f'{url}/printer/objects/query', params={'print_stats': 'state'}, timeout=3)
            state = st.json()['result']['status']['print_stats']['state']
        except Exception as e:
            raise HTTPException(502, f'Moonraker at {url}: {e}')
        if state in ('printing', 'paused'):
            raise HTTPException(409, f'the printer is {state}')
        job = ws.printer_job = {'what': what, 'script': script, 'started': time.time(), 'done': False, 'error': None}

        def go():
            try:
                r = requests.post(f'{url}/printer/gcode/script', json={'script': script}, timeout=1800)
                if r.status_code != 200:
                    try:
                        job['error'] = r.json()['error']['message']
                    except Exception:
                        job['error'] = f'HTTP {r.status_code}'
            except Exception as e:
                job['error'] = str(e)
            finally:
                job['done'], job['ended'] = True, time.time()
                with ws.lock:
                    ws.fetch_tags()
        threading.Thread(target=go, daemon=True).start()
        return {'job': job}

    @app.post('/api/scan')
    def scan(body: dict = Body(default={})):
        '''TOOL_SCAN: every occupied holder, or {"holders": [41, 43]}.'''
        holders = [int(h) for h in body.get('holders') or []]
        return run_on_printer('scanning the tools', 'TOOL_SCAN' + (f" T={','.join(map(str, holders))}" if holders else ''))

    @app.post('/api/holders/{holder}/tag')
    def write_tag(holder: int, body: dict = Body(...)):
        '''{pen, color, name}: onto the tag of the tool in `holder` (TOOL_TAG_SET).'''
        machine, _ = load(ws.job)
        if holder not in machine.holders:
            raise HTTPException(404, f'no holder {holder}')
        pens = load_pens()
        pen = (body.get('pen') or '').strip().lower()
        if pen and pen not in pens:
            raise HTTPException(400, f'no pen {pen!r} in the library')
        color = (body.get('color') or '').strip().lstrip('#').lower()
        if color and (len(color) != 6 or any(c not in '0123456789abcdef' for c in color)):
            raise HTTPException(400, f'colour {body.get("color")!r}: #rrggbb')
        name = (body.get('name') or '').strip()
        if len(name.encode()) > 20 or any(c in name for c in '"\n;#'):
            raise HTTPException(400, f'name {name!r}: up to 20 characters, no quotes, ; or #')
        args = ''.join(f' {k}={v}' for k, v in (('PEN', pen), ('COLOR', color)) if v)
        if name:
            args += f' NAME="{name}"'
        if not args:
            raise HTTPException(400, 'nothing to write: pen, color or name')
        return run_on_printer(f'writing the tag of {holder}', f'TOOL_TAG_SET T={holder}{args}')

    @app.put('/api/pens/{key}')
    def save_pen(key: str, body: dict = Body(...)):
        '''A pen of the library, new or changed: {name, short, kind, colors: {name: #rrggbb}, width, ..}.
        The key goes on the tags: it can't be renamed, only added.'''
        with ws.lock:
            try:
                pen_library.save(profile.PENS, key, body)
            except ValueError as e:
                raise HTTPException(400, str(e))
            return ws.state()

    @app.delete('/api/pens/{key}')
    def delete_pen(key: str):
        with ws.lock:
            try:
                pen_library.delete(profile.PENS, key)
            except KeyError:
                raise HTTPException(404, f'no pen {key}')
            return ws.state()

    @app.post('/api/printer/upload')
    def upload(body: dict = Body(default={})):
        '''Send the G-code to Klipper; {"start": true} starts it too.'''
        with ws.lock:
            if ws.gcode is None:
                ws.slice()
            gcode, name, bad = ws.gcode, ws.name, ws.unsafe
        if bad:
            raise HTTPException(409, f'not sending it, the pen would be too low off the paper: {bad[0]}')
        url = moonraker()
        data = {'print': 'true'} if body.get('start') else {}
        try:
            r = requests.post(f'{url}/server/files/upload', files={'file': (name, gcode.encode(), 'text/plain')},
                              data=data, timeout=30)
            r.raise_for_status()
        except Exception as e:
            raise HTTPException(502, f'Moonraker at {url}: {e}')
        return {'ok': True, 'file': name, 'started': bool(body.get('start')), 'result': r.json()}

    return app


app = None


def main(host='0.0.0.0', port=4220, data=None, reload=False):
    import uvicorn
    if data:
        os.environ['LIMN_PLOT_DATA'] = str(Path(data).resolve())
    if reload:
        # Restarts when plot/ changes; the page itself is read from disk on every load
        uvicorn.run('plot.server:create_app', factory=True, host=host, port=port, reload=True,
                    reload_dirs=[str(Path(__file__).parent)])
    else:
        uvicorn.run(create_app(), host=host, port=port)
