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
import json
import os
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np
import requests
from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from . import pens as pen_library
from . import profile, svg
from .emit import load, plot
from .fonts import HERSHEY, FontStore
from .job import Group, Job, Obj, Placement, ShapePaint
from .preview import parse
from .profile import bed_papers, load_pens, reach
from .slicer import Cache, default_groups, fillable, image_keys, image_shapes, text_shapes
from .tools import DRAW, Tool

STATIC = Path(__file__).parent / 'static'
DEFAULT_DATA = Path(__file__).resolve().parent.parent / 'plot-data'
MANUAL_HOLDER = 90      # printer.limn.tools' key of the tool docked by hand (MANUAL_TOOL in ext/limn)
OBJ_KEYS = {'placement', 'scale', 'occlude', 'tolerance', 'groups', 'shapes', 'sets', 'group', 'text', 'texts', 'surface',
            'masks', 'raster'}
SETTINGS = {'printer_url': '',      # the web UI's own (settings.json): printer_url, where Fluidd and its cameras are;
            'endoscope_url': ''}    # the endoscope's snapshot URL (limn_endoscope, /snapshot.jpg?flip=1): a camera too


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
        self.camera_job = None      # limn_cam.scan.Job: the camera tool focusing, looking or scanning
        self.nas_uploads = {}       # scan id -> limn_cam.nas.Upload
        self.hugin_jobs = {}        # scan id -> {ppm, done, error, log}: stitching with Hugin
        self.scan_path = self.data / 'scan.json'
        self.settings_path = self.data / 'settings.json'
        self.gcode_help = None      # Klipper's commands (Moonraker's gcode/help), None: not asked yet

    def settings(self):
        try:
            got = json.loads(self.settings_path.read_text())
        except (OSError, ValueError):
            got = {}
        return {**SETTINGS, **{k: v for k, v in got.items() if k in SETTINGS}}

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
            defaults = default_groups(d, tools, o)
            stats = d.groups()
            for k in image_keys(d, o, tools):      # the images' inks: a layer each, even with nothing drawn
                stats.setdefault(k, {'shapes': 0, 'length': 0.0, 'widths': set()}).setdefault('images', 0)
            for sh in image_shapes(d, o, tools):
                g = stats[f'stroke {sh.stroke}']
                g['shapes'] += 1
                g['images'] += 1
                g['length'] += sum(float(np.hypot(*np.diff(p, axis=0).T).sum()) for p in sh.paths)
            groups = [{'key': k, 'shapes': g['shapes'], 'texts': g.get('texts', 0), 'images': g.get('images'),
                       'length': g['length'] * o.scale, 'widths': sorted(w * o.scale for w in g['widths']),
                       'default': defaults[k].model_dump()}
                      for k, g in sorted(stats.items(), key=lambda kv: -kv[1]['length'])]
            images = [{'index': im.index, 'id': im.id, 'px': list(im.rgb.shape[1::-1]),
                       'size': (np.ptp(im.corners(), axis=0) * o.scale).round(1).tolist()} for im in d.images]
            texts = []
            for t in d.texts:
                spec = o.texts.get(str(t.index), o.text)
                found = self.fonts.match(t.family, t.weight, t.style)
                texts.append({'index': t.index, 'text': t.text, 'family': t.family, 'weight': t.weight,
                              'style': t.style, 'colour': t.fill or t.stroke,
                              'size': t.size * abs(t.matrix[0] * t.matrix[3] - t.matrix[1] * t.matrix[2]) ** 0.5 * o.scale,
                              'found': found.file if found else None, 'spec': spec.model_dump()})
            objects[o.id] = {'size': [d.size[0] * o.scale, d.size[1] * o.scale], 'groups': groups,
                             'texts': texts, 'shapes': len(d.shapes), 'skipped': d.skipped, 'images': images}
        m = machine.model_dump()
        pens = load_pens()
        holders = [{'t': f'T{i}', 'holder': h, 'tag': (self.tags or {}).get(str(h))}
                   for i, h in enumerate(machine.holders)]
        draw = {k: Tool.model_fields[k].default for k in DRAW if k in Tool.model_fields}
        draw['plunge_feed'] = None
        return {'job': self.job.model_dump(), 'machine': m, 'beds': bed_papers(machine), 'draw': draw,
                'tools': {k: {**t.model_dump(), 'spacing': t.spacing, 'draws': t.draws} for k, t in tools.items()},
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
        _, tools = load(self.job, self.tags)
        for sh in sorted(d.shapes + text_shapes(d, o, self.fonts, [], tools) + image_shapes(d, o, tools),
                         key=lambda sh: sh.index):
            out.append({'i': sh.index, 'stroke': sh.stroke, 'fill': sh.fill, 'w': sh.width * s,
                        'so': sh.stroke_opaque, 'fo': sh.fill_opaque, 'line': sh.line, 'fillable': fillable(sh),
                        'bg': sh.background,
                        'text': sh.line or any(t.index == sh.index for t in d.texts), 'rule': sh.rule, 'raster': sh.raster,
                        'd': ' '.join(_d(local(p), c) for p, c in zip(sh.paths, sh.closed))})
        return {'size': [d.size[0] * s, d.size[1] * s], 'shapes': out}

    def slice(self):
        t0 = time.monotonic()
        result, sliced = plot(self.job, self.cache, self.fonts, self.tags)
        self.gcode = result.gcode
        self.name = 'limn-' + '-'.join(o.id for o in self.job.objects)[:60] + '.gcode'
        sim = result.sim or parse(result.gcode)
        runs = [[k, t, n, np.round(pts[:, :2], 3).ravel().tolist()] for k, t, pts, n in sim.runs()]
        bounds = {}
        for o in self.job.objects:
            b = sliced[o.id].bounds
            if b:
                c = o.placement.apply([[b[0], b[1], 0], [b[2], b[1], 0], [b[2], b[3], 0], [b[0], b[3], 0]])
                bounds[o.id] = [*c[:, :2].min(axis=0).tolist(), *c[:, :2].max(axis=0).tolist()]
        self.unsafe = result.unsafe
        return {'tools': sim.tools, 'runs': runs, 'lines': result.gcode.count('\n'), 'stats': result.stats,
                'problems': result.problems, 'unsafe': bool(result.unsafe), 'bounds': bounds,
                'small': {o.id: sliced[o.id].small for o in self.job.objects if sliced[o.id].small},
                'ms': round((time.monotonic() - t0) * 1000)}


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
        # Each script and stylesheet by its version: a browser never runs an old one with a new page
        html = (STATIC / 'index.html').read_text()
        for name in ('app.js', 'zoom.js', 'scan.js', 'cams.js', 'head.js', 'leds.js', 'panels.js', 'app.css'):
            html = html.replace(f'/static/{name}"', f'/static/{name}?v={int((STATIC / name).stat().st_mtime)}"')
        return HTMLResponse(html, headers={'Cache-Control': 'no-cache'})

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
        data = await file.read()          # its <image>s stay: left out, or made into lines (Obj.raster)
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
            return {'id': oid, 'images': len(d.images), 'unreadable': d.skipped.get('image (not embedded)', 0),
                    'state': ws.state()}

    @app.patch('/api/objects/{oid}')
    def patch_object(oid: str, body: dict = Body(...)):
        with ws.lock:
            o = ws.obj(oid)
            bad = set(body) - OBJ_KEYS
            if bad:
                raise HTTPException(400, f'not changeable: {", ".join(sorted(bad))}')
            try:
                new = Obj(**{**o.model_dump(), **body})
            except ValueError as e:
                raise HTTPException(400, f'{oid}: {e}')
            ws.remember()
            ws.job.objects[ws.job.objects.index(o)] = new
            ws.save()
            return ws.state()

    @app.patch('/api/objects')
    def patch_objects(body: dict = Body(...)):
        '''{id: changes, ..}: several drawings at once, one step for undo (a group moved).'''
        with ws.lock:
            news = {}
            for oid, changes in body.items():
                o = ws.obj(oid)
                bad = set(changes) - OBJ_KEYS
                if bad:
                    raise HTTPException(400, f'not changeable: {", ".join(sorted(bad))}')
                try:
                    news[oid] = Obj(**{**o.model_dump(), **changes})
                except ValueError as e:
                    raise HTTPException(400, f'{oid}: {e}')
            ws.remember()
            ws.job.objects = [news.get(o.id, o) for o in ws.job.objects]
            ws.save()
            return ws.state()

    @app.post('/api/objects/{oid}/order')
    def order(oid: str, body: dict = Body(...)):
        '''{to: front|back|forward|backward}: later in the job is on top (it hides what
        is under it, emit.hidden), as the canvas draws them.'''
        with ws.lock:
            o = ws.obj(oid)
            objs = list(ws.job.objects)
            i = objs.index(o)
            j = {'front': len(objs) - 1, 'back': 0, 'forward': i + 1, 'backward': i - 1}.get(body.get('to'))
            if j is None:
                raise HTTPException(400, 'to: front, back, forward or backward')
            j = min(max(j, 0), len(objs) - 1)
            if j != i:
                ws.remember()
                objs.insert(j, objs.pop(i))
                ws.job.objects = objs
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

    @app.delete('/api/objects')
    def clear_objects():
        '''Every drawing off the bed, as one step for undo.'''
        with ws.lock:
            ws.remember()
            ws.job.objects.clear()
            ws.save()
            return ws.state()

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
            sh = next((s for s in d.shapes + image_shapes(d, o, tools) if s.index == index), None)
            run = next((t for t in d.texts if t.index == index), None)
            colours = {'stroke': sh.stroke, 'fill': sh.fill} if sh else {'stroke': None, 'fill': run.fill or run.stroke}
            # A shape closed but not filled in its SVG takes a fill of its own (not a whole colour's)
            bare = sh is not None and not sh.fill and fillable(sh) and scope == 'shape'
            parts = [p for p in ('stroke', 'fill') if target in (p, 'both') and (colours[p] or (p == 'fill' and bare))]
            defaults = default_groups(d, tools)
            groups, shapes = dict(o.groups), dict(o.shapes)
            for part in parts:
                key = f'{part} {colours[part]}'
                base = (groups.get(key) or defaults.get(key) or Group()) if colours[part] else Group()
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
                    if not cur.model_dump(exclude_none=True):
                        shapes.pop(str(index), None)
                    else:
                        shapes[str(index)] = cur
            ws.remember()
            ws.job.objects[ws.job.objects.index(o)] = o.model_copy(update={'groups': groups, 'shapes': shapes})
            ws.save()
            return ws.state()

    @app.patch('/api/job')
    def patch_job(body: dict = Body(...)):
        '''{machine_overrides: {key: value|null}, tool_overrides: {tool: {key: value|null}},
        draw: {key: value|null} (every tool, tools.DRAW), tool_order}'''
        with ws.lock:
            job = ws.job
            mo, draw = dict(job.machine_overrides), dict(job.draw)
            for cur, key in ((mo, 'machine_overrides'), (draw, 'draw')):
                for k, v in (body.get(key) or {}).items():
                    if v is None:
                        cur.pop(k, None)
                    else:
                        cur[k] = v
            to = {k: dict(v) for k, v in job.tool_overrides.items()}
            for tid, over in (body.get('tool_overrides') or {}).items():
                cur = to.setdefault(tid, {})
                for k, v in over.items():
                    if v is None:
                        cur.pop(k, None)
                    else:
                        cur[k] = v
            new = job.model_copy(update={'machine_overrides': mo, 'draw': draw, 'tool_overrides': {k: v for k, v in to.items() if v},
                                         'tool_order': body.get('tool_order', job.tool_order)})
            new._root = ws.data
            try:
                load(new, ws.tags)
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
                'scan': limn.get('scan'), 'drying': limn.get('drying') or {}}

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

    @app.get('/api/printer/position')
    def printer_position():
        '''Where the head is, often (the canvas shows it): Klipper's live position (the
        tool point with no tool offset, moving or not), and where the carried tool's
        tip is (that less the G-code offset: its tag's dx, dy).'''
        url = moonraker()
        try:
            r = requests.get(f'{url}/printer/objects/query',
                             params={'motion_report': 'live_position', 'toolhead': 'position,homed_axes',
                                     'gcode_move': 'homing_origin'}, timeout=2)
            r.raise_for_status()
            st = r.json()['result']['status']
        except Exception as e:
            return {'ok': False, 'error': str(e)}
        live = (st.get('motion_report') or {}).get('live_position') or (st.get('toolhead') or {}).get('position')
        off = (st.get('gcode_move') or {}).get('homing_origin') or [0, 0, 0, 0]
        homed = (st.get('toolhead') or {}).get('homed_axes') or ''
        if not live or 'x' not in homed or 'y' not in homed:
            return {'ok': True, 'homed': homed, 'head': None}
        return {'ok': True, 'homed': homed, 'head': [round(live[0], 3), round(live[1], 3), round(live[2], 3)],
                'tip': [round(live[0] - off[0], 3), round(live[1] - off[1], 3)], 'offset': [round(v, 3) for v in off[:3]]}

    @app.get('/api/printer/leds')
    def printer_leds():
        '''What the LEDs show now: the UI matrix (neopixel picam, 8 x 4, 1 the top left,
        row by row) and the dock strip (indockator), as 0-1 RGB, and the states the
        limn extension set (ext/limn/leds.py), when its Klipper is new enough.'''
        url = moonraker()
        try:
            r = requests.get(f'{url}/printer/objects/query',
                             params={'neopixel picam': 'color_data', 'neopixel indockator': 'color_data', 'limn': 'leds'},
                             timeout=2)
            r.raise_for_status()
            st = r.json()['result']['status']
        except Exception as e:
            return {'ok': False, 'error': str(e)}
        rgb = lambda name: [[round(c, 3) for c in px[:3]] for px in (st.get(name) or {}).get('color_data') or []]
        return {'ok': True, 'ui': rgb('neopixel picam'), 'dock': rgb('neopixel indockator'),
                'states': (st.get('limn') or {}).get('leds')}

    @app.get('/api/toolhead.svg')
    def toolhead_svg():
        '''The toolhead from above (mm, the tool point at the origin): the workspace's
        toolhead.svg if there is one, else plot/profiles/toolhead.svg.'''
        p = ws.data / 'toolhead.svg'
        if not p.exists():
            p = Path(profile.PROFILES) / 'toolhead.svg'
        return FileResponse(p, media_type='image/svg+xml', headers={'Cache-Control': 'no-cache'})

    def snapshot_urls(url, bare='/snapshot.jpg'):
        '''(snapshot, stream) of a camera's own server (the endoscope, limn_picam): its address alone gets
        `bare`; the stream is the snapshot's twin, /stream.mjpg with the same query (flip).'''
        if not url:
            return '', ''
        u = urlsplit(url)
        if u.path in ('', '/'):
            url = url.rstrip('/') + bare
            u = urlsplit(url)
        base = url[:url.index(u.path)] if u.path else url
        stream = base + u.path.rsplit('/', 1)[0] + '/stream.mjpg' + (f'?{u.query}' if u.query else '')
        return url, stream

    def endoscope_urls():
        '''(snapshot, stream) of the endoscope, or ('', ''): its server's address alone gets /snapshot.jpg?flip=1.'''
        return snapshot_urls(ws.settings()['endoscope_url'], '/snapshot.jpg?flip=1')

    def manual_camera():
        '''The camera tool docked by hand (printer.limn.tools['90']), when its pen is a camera with a URL of its
        own (`webcam = "http://.."` in pens.toml, eg. limn_picam): (tag, pen) or None.'''
        with ws.lock:
            tag = (ws.tags or {}).get(str(MANUAL_HOLDER))
        pen = load_pens().get((tag or {}).get('pen') or '') if tag else None
        if not pen or pen.get('kind') != 'camera' or '://' not in str(pen.get('webcam', '')):
            return None
        return tag, pen

    @app.get('/api/webcams')
    def webcams():
        '''Klipper's cameras (Moonraker's list) and where Fluidd is, for the browser.
        Their URLs may be relative to Fluidd: fluidd '' means the page's own host.'''
        from urllib.parse import urlsplit
        with ws.lock:
            machine, _ = load(ws.job)
        set_url = ws.settings()['printer_url']
        fluidd = set_url or machine.fluidd
        guessed = False
        if not fluidd:
            u = urlsplit(machine.moonraker)
            if u.hostname not in ('localhost', '127.0.0.1', '::1'):
                fluidd = f'{u.scheme}://{u.hostname}' + (f':{u.port}' if u.port and u.port != 7125 else '')
            else:
                guessed = True      # Moonraker on this host: Fluidd is on the page's host, perhaps
        try:
            r = requests.get(f'{machine.moonraker.rstrip("/")}/server/webcams/list', timeout=3)
            r.raise_for_status()
            cams = [{k: c.get(k) for k in ('name', 'stream_url', 'snapshot_url', 'flip_horizontal', 'flip_vertical',
                                           'rotation', 'service', 'enabled')}
                    for c in r.json()['result']['webcams'] if c.get('enabled', True)]
            error = None
        except Exception as e:
            cams, error = [], f'Moonraker at {machine.moonraker}: {e}'
        own = [('endoscope', endoscope_urls())]     # not Klipper's: their own servers
        manual = manual_camera()
        if manual:
            own.append((manual[0].get('name') or manual[1].get('short', 'manual'), snapshot_urls(manual[1]['webcam'])))
        for name, (snap, live) in own:
            if snap:
                cams.append({'name': name, 'stream_url': live, 'snapshot_url': snap, 'flip_horizontal': False,
                             'flip_vertical': False, 'rotation': 0, 'service': 'mjpegstreamer', 'enabled': True})
                error = None
        return {'fluidd': fluidd.rstrip('/'), 'guessed': guessed, 'set': bool(set_url), 'webcams': cams, 'error': error}

    @app.get('/api/settings')
    def settings_get():
        return ws.settings()

    @app.put('/api/settings')
    def settings_put(body: dict = Body(...)):
        '''{printer_url}: where Fluidd (and its cameras' relative URLs) is, as this browser
        reaches it, eg. https://limn.example: when the page's own host isn't it.'''
        cur = ws.settings()
        for k, v in body.items():
            if k not in SETTINGS:
                raise HTTPException(400, f'no setting {k}')
            v = (v or '').strip().rstrip('/')
            if k in ('printer_url', 'endoscope_url') and v and not re.match(r'^https?://[^\s/]+', v):
                raise HTTPException(400, f'{k} {v!r}: http(s)://host[:port][/path]')
            cur[k] = v
        ws.settings_path.write_text(json.dumps(cur, indent=2) + '\n')
        return cur

    def macro_list():
        '''The machine's macro buttons, and one per holder (T0..) and UNDOCK; the ones
        Klipper has no command for left out (all when it can't be asked).'''
        machine, tools = load(ws.job, ws.tags)
        url = moonraker()
        if ws.gcode_help is None:
            try:
                r = requests.get(f'{url}/printer/gcode/help', timeout=3)
                r.raise_for_status()
                ws.gcode_help = {k.upper(): v for k, v in r.json()['result'].items()}
            except Exception:
                pass
        helps = ws.gcode_help
        out = [m.model_dump() for m in machine.macros]
        for i, h in enumerate(machine.holders):
            t = tools.get(f'T{i}')
            out.append({'label': f'T{i}', 'gcode': f'T{i}', 'group': 'Tools', 'confirm': True,
                        'title': f'Pick up T{i} (holder {h})' + (f': {t.name}' if t and t.name else ''),
                        'color': t.color if t else None})
        out.append({'label': 'Put away', 'gcode': 'UNDOCK', 'group': 'Tools', 'confirm': True,
                    'title': 'The carried tool back into its holder'})
        if helps is not None:
            out = [m for m in out if m['gcode'].split()[0].upper() in helps]
        return out, helps is not None

    @app.get('/api/printer/macros')
    def macros():
        out, known = macro_list()
        return {'macros': out, 'checked': known}

    @app.post('/api/printer/macro')
    def run_macro(body: dict = Body(...)):
        '''{gcode}: one of the macro buttons (no other G-code), run in the background.'''
        gcode = (body.get('gcode') or '').strip()
        out, _ = macro_list()
        m = next((m for m in out if m['gcode'] == gcode), None)
        if m is None:
            raise HTTPException(400, f'{gcode!r} is not one of the macro buttons')
        return run_on_printer(f'running {gcode}', gcode)

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

    # The camera tool: focus, look, scan a region (limn_cam/scan.py). limn_cam is only
    # needed here: without it the rest of the app works on.
    def scan_settings():
        from limn_cam.scan import Settings
        if ws.scan_path.exists():
            try:
                return Settings(**json.loads(ws.scan_path.read_text()))
            except (TypeError, ValueError):
                pass
        return Settings()

    def captures():
        from limn_cam.scan import ScanStore, capture_root
        return ScanStore(capture_root(ws.data))

    def cameras():
        '''The camera tools (from the tags), and the endoscope when its URL is set: fixed on the carriage, its
        geometry from the library's `endo` (pens.toml).'''
        with ws.lock:
            machine, tools = load(ws.job, ws.tags)
        cams = {k: t for k, t in tools.items() if t.kind == 'camera'}
        url = endoscope_urls()[0]
        if url:
            from .tools import REGISTRY
            spec = {k: v for k, v in load_pens().get('endo', {}).items() if k not in ('name', 'short', 'kind', 'colors')}
            cams['endoscope'] = REGISTRY['camera'](id='endoscope', kind='camera', **{**spec, 'fixed': True}, webcam=url,
                                                   name=load_pens().get('endo', {}).get('short', 'Endoscope'),
                                                   pen='endo', source='settings')
        manual = manual_camera()
        if manual:                      # docked by hand: on the carriage until taken off, like the endoscope
            from .tools import REGISTRY
            tag, pen = manual
            spec = {k: v for k, v in pen.items() if k not in ('name', 'short', 'kind', 'colors', 'dry')}
            cams['manual'] = REGISTRY['camera'](id='manual', kind='camera', **{**spec, 'fixed': True},
                                                name=tag.get('name') or pen.get('short', ''), pen=tag['pen'],
                                                source='tag')
        return machine, cams

    @app.get('/api/camera')
    def camera_state():
        machine, cams = cameras()
        job = ws.camera_job
        return {'settings': scan_settings().to_dict(),
                'cameras': {k: {**t.model_dump(), 'z_limits': t.z_limits(machine)} for k, t in cams.items()},
                'job': job.state if job else None, 'captures': captures().list(),
                'store': {'volatile': captures().volatile, 'mb': round(captures().size() / 1e6, 1), 'max_mb': captures().max_mb},
                'travel_area': machine.travel_area, 'zones': [z.model_dump() for z in machine.zones],
                'mark': mark_spot()}

    @app.patch('/api/camera')
    def camera_settings(body: dict = Body(...)):
        from limn_cam.scan import Settings
        s = {**scan_settings().to_dict(), **body}
        try:
            settings = Settings(**s)
            if settings.region is not None:
                x0, y0, x1, y1 = settings.region
                settings.region = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
            if not 0 <= settings.overlap < 0.9 or settings.refocus < 0 or settings.refocus_step <= 0:
                raise ValueError('overlap 0 to 0.9, refocus 0 or more, its step over 0')
            if settings.flicker not in ('auto', 'always', 'off') or not 1 <= int(settings.flicker_frames) <= 8:
                raise ValueError('flicker: auto, always or off, 1 to 8 frames')
            settings.flicker_frames = int(settings.flicker_frames)
        except (TypeError, ValueError) as e:
            raise HTTPException(400, f'scan settings: {e}')
        ws.scan_path.write_text(json.dumps(settings.to_dict()))
        return camera_state()

    def camera_job(what, fn_name, *args):
        from limn_cam.moonraker import Moonraker
        from limn_cam.scan import Job
        if ws.camera_job and not ws.camera_job.state['done']:
            raise HTTPException(409, f"the camera is busy: {ws.camera_job.state['what']}")
        if ws.printer_job and not ws.printer_job['done']:
            raise HTTPException(409, f"the printer is busy with {ws.printer_job['what']}")
        machine, cams = cameras()
        settings = scan_settings()
        cam = cams.get(settings.tool) or next(iter(cams.values()), None)
        if cam is None:
            raise HTTPException(400, 'no camera tool: write a camera type (eg. cam-u20) onto a tool\'s tag first')
        if cam.holder is None and not cam.fixed:
            raise HTTPException(400, f'{cam.id}: which holder it is in is not known (its tag)')
        mr = Moonraker(machine.moonraker)
        try:
            state = mr.query(print_stats='state')['print_stats']['state']
        except Exception as e:
            raise HTTPException(502, f'Moonraker at {machine.moonraker}: {e}')
        if state in ('printing', 'paused'):
            raise HTTPException(409, f'the printer is {state}')
        job = Job(what, mr, cam, machine, captures(), settings)
        if fn_name == 'scan':
            job.on_done = lambda j: nas_settings().auto and not j.state['error'] and j.state['scan'] \
                and start_upload(j.state['scan'])
        ws.camera_job = job.start(lambda: getattr(job, fn_name)(*args))
        return {'job': job.state}

    # Keeping scans: uploads to the NAS (an S3 bucket, limn_cam/nas.py)
    def nas_settings():
        from limn_cam import nas
        return nas.load_settings(ws.data / 'nas.json')

    def start_upload(sid):
        from limn_cam import nas
        cur = ws.nas_uploads.get(sid)
        if cur and not cur.state['done']:
            return cur.state
        try:
            up = nas.Upload(captures(), sid, nas_settings())
        except ValueError as e:
            raise HTTPException(400, str(e))
        ws.nas_uploads[sid] = up.start()
        return up.state

    @app.get('/api/nas')
    def nas_get():
        return {'settings': nas_settings().public(), 'uploads': {k: u.state for k, u in ws.nas_uploads.items()}}

    @app.put('/api/nas')
    def nas_put(body: dict = Body(...)):
        '''The NAS settings; a secret_key left out or empty keeps the one there is.'''
        from limn_cam import nas
        cur = nas_settings()
        fields = {k: v for k, v in body.items() if k in nas.Settings.__dataclass_fields__}
        if not fields.get('secret_key'):
            fields.pop('secret_key', None)
        try:
            s = nas.Settings(**{**cur.__dict__, **fields})
        except TypeError as e:
            raise HTTPException(400, str(e))
        nas.save_settings(ws.data / 'nas.json', s)
        return nas_get()

    @app.post('/api/nas/check')
    def nas_check():
        '''A small file into the bucket: that the settings work.'''
        from limn_cam import nas
        try:
            return {'ok': True, 'key': nas.Bucket(nas_settings(), timeout=15).check()}
        except ValueError as e:
            raise HTTPException(400, str(e))
        except Exception as e:
            raise HTTPException(502, f'the NAS: {e}')

    @app.post('/api/captures/{sid}/upload')
    def capture_upload(sid: str):
        try:
            captures().dir(sid)
        except KeyError:
            raise HTTPException(404, f'no capture {sid}')
        return start_upload(sid)

    def check_spot(x, y):
        '''x, y: where the image's middle goes; the tool point is off by the camera's center.'''
        machine, cams = cameras()
        cam = cams.get(scan_settings().tool) or next(iter(cams.values()), None)
        if cam is not None:
            x, y = x - cam.center[0], y - cam.center[1]
        tx0, ty0, tx1, ty1 = reach(machine)
        if not (tx0 <= x <= tx1 and ty0 <= y <= ty1):
            raise HTTPException(400, f'({x:g}, {y:g}) is out of reach {reach(machine)}')
        for z in machine.zones:
            zx0, zy0, zx1, zy1 = z.rect
            if z.z is None and zx0 <= x <= zx1 and zy0 <= y <= zy1:
                raise HTTPException(400, f'({x:g}, {y:g}) is in {z.name}, keep out')

    @app.post('/api/camera/focus')
    def camera_focus(body: dict = Body(...)):
        '''{x, y}: the sharpest z there, sweeping settings.sweep.'''
        x, y = float(body['x']), float(body['y'])
        check_spot(x, y)
        return camera_job('finding the focus', 'focus', x, y)

    @app.post('/api/camera/look')
    def camera_look(body: dict = Body(...)):
        '''{x, y, z}: one shot there.'''
        x, y, z = float(body['x']), float(body['y']), float(body['z'])
        check_spot(x, y)
        return camera_job('looking', 'look', x, y, z)

    @app.post('/api/camera/scan')
    def camera_scan():
        '''The region of the settings, tile by tile.'''
        from limn_cam.scan import tiles
        s = scan_settings()
        if not s.region:
            raise HTTPException(400, 'no region: draw one on the bed')
        machine, cams = cameras()
        cam = cams.get(s.tool) or next(iter(cams.values()), None)
        if cam is None:
            raise HTTPException(400, 'no camera tool')
        for _, _, x, y in tiles(s.region, cam.fov, s.overlap, cam.turn):
            check_spot(x, y)
        return camera_job('scanning', 'scan')

    @app.post('/api/camera/corners')
    def camera_corners():
        '''A shot on each corner of the region: to set its edges on what is there.'''
        s = scan_settings()
        if not s.region:
            raise HTTPException(400, 'no region: draw one on the bed')
        x0, y0, x1, y1 = s.region
        for x, y in ((x0, y0), (x0, y1), (x1, y0), (x1, y1)):
            check_spot(x, y)
        return camera_job('checking the corners', 'corners')

    MARK = 'camera-mark'            # the drawing of the cross the camera is calibrated on

    def mark_spot():
        '''Where the calibration cross's middle is on the bed, None: it isn't in the job.'''
        from limn_cam.scan import MARK_MID
        o = next((o for o in ws.job.objects if o.id == MARK), None)
        if o is None:
            return None
        p = o.placement.apply([[MARK_MID[0] * o.scale, MARK_MID[1] * o.scale, 0]])[0]
        return round(float(p[0]), 3), round(float(p[1]), 3)

    @app.post('/api/camera/mark')
    def camera_mark(body: dict = Body(...)):
        '''{x, y}: the calibration cross as a drawing, its middle there (one only: moved when it is there).
        Plotted like any drawing, with a pen, before the camera goes on: a camera docked by hand keeps
        the dock out of reach.'''
        from limn_cam.scan import MARK_MID, MARK_SVG
        x, y = float(body['x']), float(body['y'])
        with ws.lock:
            (ws.uploads / f'{MARK}.svg').write_text(MARK_SVG)
            ws.remember()
            at = Placement(x=x - MARK_MID[0], y=y - MARK_MID[1])
            old = next((o for o in ws.job.objects if o.id == MARK), None)
            if old is not None:
                old.placement, old.scale = at, 1.0
            else:
                ws.job.objects.append(Obj(id=MARK, svg=f'uploads/{MARK}.svg', placement=at))
            ws.save()
            return ws.state()

    @app.post('/api/camera/calibrate')
    def camera_calibrate(body: dict = Body(None)):
        '''Measure the camera: on the calibration cross when the job has it (and then its center too), else at
        {x, y}. The result is the job's: /api/camera/calibration saves it.'''
        spot = mark_spot()
        if spot is None and not (body and 'x' in body and 'y' in body):
            raise HTTPException(400, 'no cross to calibrate on: add one (Calibration cross) and plot it, or give x, y')
        x, y = spot or (float(body['x']), float(body['y']))
        check_spot(x, y)
        return camera_job('calibrating the camera', 'calibrate', x, y, spot is not None)

    @app.post('/api/camera/calibration')
    def camera_calibration_save():
        '''The last calibration into its camera's pen (pens.toml): fov, turn, focus_z, center when measured.'''
        job = ws.camera_job
        cal = ((job.state.get('result') or {}).get('calibration') if job and job.state['done'] else None)
        if not cal or job.state['error']:
            raise HTTPException(400, 'no calibration to save: calibrate first')
        key = cal.get('pen')
        pens = load_pens()
        if not key or key not in pens:
            raise HTTPException(400, f'the camera has no pen of the library to save into ({key!r})')
        spec = {**pens[key], 'fov': cal['fov'], 'turn': cal['turn'], 'focus_z': cal['focus_z']}
        if cal.get('center') is not None:
            spec['center'] = cal['center']
        with ws.lock:
            try:
                saved = pen_library.save(profile.PENS, key, spec)
            except ValueError as e:
                raise HTTPException(400, str(e))
        return {'pen': key, 'saved': saved, 'camera': camera_state()}

    @app.post('/api/camera/stop')
    def camera_stop():
        if ws.camera_job and not ws.camera_job.state['done']:
            ws.camera_job.stop()
        return {'job': ws.camera_job.state if ws.camera_job else None}

    @app.post('/api/camera/park')
    def camera_park():
        '''The camera back in its holder.'''
        if ws.camera_job and not ws.camera_job.state['done']:
            raise HTTPException(409, 'the camera is busy')
        return run_on_printer('putting the camera away', 'UNDOCK')

    @app.get('/api/captures')
    def captures_list():
        return captures().list()

    @app.get('/api/captures/{sid}')
    def capture_meta(sid: str):
        try:
            return captures().meta(sid)
        except KeyError:
            raise HTTPException(404, f'no capture {sid}')

    @app.get('/api/captures/{sid}/file/{name}')
    def capture_file(sid: str, name: str, download: bool = False):
        try:
            p = captures().file(sid, name)
        except KeyError:
            raise HTTPException(404, f'no {name} in {sid}')
        return FileResponse(p, filename=f'{sid}-{name}' if download else None)

    @app.get('/api/captures/{sid}/thumb/{name}')
    def capture_thumb(sid: str, name: str, width: int = 320):
        try:
            return FileResponse(captures().thumb(sid, name, max(64, min(width, 1200))))
        except KeyError:
            raise HTTPException(404, f'no {name} in {sid}')

    @app.get('/api/captures/{sid}/mosaic')
    def capture_mosaic(sid: str, px_per_mm: float = 12.0):
        try:
            return FileResponse(captures().mosaic(sid, max(1.0, min(px_per_mm, 60.0))))
        except KeyError as e:
            raise HTTPException(404, f'{sid}: {e}')

    @app.get('/api/captures/{sid}/stitch/info')
    def capture_stitch_info(sid: str, px_per_mm: float = 0):
        '''Where the tiles really are (registered), and how big a stitch at px_per_mm would be.'''
        from limn_cam import stitch
        try:
            return stitch.info(captures(), sid, px_per_mm or None)
        except KeyError as e:
            raise HTTPException(404, f'{sid}: {e}')

    @app.get('/api/captures/{sid}/stitch')
    def capture_stitch(sid: str, px_per_mm: float = 25, download: bool = False):
        '''The scan as one picture: tiles registered on their overlaps, seams faded.'''
        from limn_cam import stitch
        try:
            path, _ = stitch.stitch(captures(), sid, max(1.0, min(px_per_mm, 200.0)))
        except KeyError as e:
            raise HTTPException(404, f'{sid}: {e}')
        except ValueError as e:
            raise HTTPException(400, str(e))
        return FileResponse(path, filename=f'limn-{sid}-{px_per_mm:g}ppmm.jpg' if download else None)

    @app.post('/api/captures/{sid}/hugin')
    def capture_hugin(sid: str, px_per_mm: float = 25):
        '''Stitch with Hugin, in the background (limn_cam/hugin.py): GET .../hugin/status.'''
        from limn_cam import hugin
        if hugin.missing():
            raise HTTPException(400, f'Hugin is missing ({", ".join(hugin.missing())}): '
                                     'sudo apt install hugin-tools enblend')
        try:
            captures().dir(sid)
        except KeyError:
            raise HTTPException(404, f'no capture {sid}')
        cur = ws.hugin_jobs.get(sid)
        if cur and not cur['done']:
            return cur
        ppm = max(1.0, min(px_per_mm, 200.0))
        job = {'ppm': ppm, 'done': False, 'error': None, 'log': [], 'started': time.time()}

        def run():
            try:
                hugin.stitch(captures(), sid, ppm, log=job['log'].append)
                captures().prune()
                if nas_settings().auto:
                    start_upload(sid)
            except Exception as e:
                job['error'] = str(e)
            finally:
                job['done'] = True
        ws.hugin_jobs[sid] = job
        threading.Thread(target=run, daemon=True).start()
        return job

    @app.get('/api/captures/{sid}/hugin/status')
    def capture_hugin_status(sid: str, px_per_mm: float = 25):
        from limn_cam import hugin
        try:
            got = hugin.done(captures(), sid, px_per_mm)
        except KeyError:
            raise HTTPException(404, f'no capture {sid}')
        return {'job': ws.hugin_jobs.get(sid), 'info': got[1] if got else None, 'missing': hugin.missing()}

    @app.get('/api/captures/{sid}/hugin')
    def capture_hugin_file(sid: str, px_per_mm: float = 25, download: bool = False):
        from limn_cam import hugin
        try:
            got = hugin.done(captures(), sid, px_per_mm)
        except KeyError:
            got = None
        if not got:
            raise HTTPException(404, f'{sid}: not stitched with Hugin at {px_per_mm:g} px/mm yet')
        return FileResponse(got[0], filename=f'limn-{sid}-hugin-{px_per_mm:g}ppmm.jpg' if download else None)

    @app.get('/api/captures/{sid}/zip')
    def capture_zip(sid: str):
        import io
        import zipfile
        try:
            d = captures().dir(sid)
        except KeyError:
            raise HTTPException(404, f'no capture {sid}')
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as z:
            for p in sorted(d.iterdir()):
                if not p.name.startswith(('thumb-', 'mosaic-')):
                    z.write(p, f'{sid}/{p.name}')
        return Response(buf.getvalue(), media_type='application/zip',
                        headers={'Content-Disposition': f'attachment; filename="limn-{sid}.zip"'})

    @app.delete('/api/captures')
    def captures_clear():
        '''Every capture but the one the camera is taking now.'''
        job = ws.camera_job
        busy = job.state.get('scan') if job and not job.state['done'] else None
        store = captures()
        for c in store.list():
            if c['id'] != busy:
                try:
                    store.delete(c['id'])
                except KeyError:
                    pass
        return store.list()

    @app.delete('/api/captures/{sid}')
    def capture_delete(sid: str):
        try:
            captures().delete(sid)
        except KeyError:
            raise HTTPException(404, f'no capture {sid}')
        return captures().list()

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
