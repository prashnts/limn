# The web UI's API, and texts in their own font or a line font
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from plot import server
from plot.fonts import FontStore
from plot.job import Job, Obj, Placement, TextSpec
from plot.slicer import slice_object
from plot.svg import load

FONT = Path('/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf')
needs_font = pytest.mark.skipif(not FONT.exists(), reason='no Liberation Sans here')

METRO = '''<svg xmlns="http://www.w3.org/2000/svg" width="60mm" height="40mm" viewBox="0 0 60 40">
<path d="M5 20 H55" stroke="#ff0000" stroke-width="0.5" fill="none"/>
<path d="M30 5 V35" stroke="#21ff06" stroke-width="2" fill="none"/>
<circle cx="30" cy="20" r="2" fill="#ffffff"/>
<text x="5" y="10" font-family="Liberation Sans" font-size="5" fill="#000000">Hi</text>
</svg>'''


@pytest.fixture
def client(tmp_path):
    app = server.create_app(tmp_path / 'ws')
    return TestClient(app)


def add(client, body=METRO, name='metro.svg'):
    r = client.post('/api/objects', files={'file': (name, body.encode(), 'image/svg+xml')})
    assert r.status_code == 200, r.text
    return r.json()


def test_add_move_paint_slice(client):
    r = add(client)
    oid, st = r['id'], r['state']
    assert oid == 'metro'
    keys = [g['key'] for g in st['objects'][oid]['groups']]
    assert {'stroke #ff0000', 'stroke #21ff06', 'fill #ffffff', 'fill #000000'} <= set(keys)
    # Placed inside the draw area
    o = st['job']['objects'][0]
    x0, y0, x1, y1 = st['machine']['draw_area']
    assert x0 <= o['placement']['x'] and o['placement']['x'] + 60 * o['scale'] <= x1 + 1e-6

    s1 = client.post('/api/slice').json()
    assert not [p for p in s1['problems'] if 'outside' in p]
    assert s1['stats']['draw_mm'] > 0

    # Moving doesn't slice again
    ws = client.app.state.ws
    before = ws.cache.slices
    client.patch(f'/api/objects/{oid}', json={'placement': {**o['placement'], 'x': o['placement']['x'] + 3}})
    s2 = client.post('/api/slice').json()
    assert ws.cache.slices == before
    assert s2['stats']['draw_mm'] == pytest.approx(s1['stats']['draw_mm'])
    assert s2['bounds'][oid][0] == pytest.approx(s1['bounds'][oid][0] + 3)

    # Paint the red line (shape 0) with T4: only that shape
    st = client.post(f'/api/objects/{oid}/paint', json={'index': 0, 'to': 'T4', 'target': 'stroke', 'scope': 'shape'}).json()
    assert st['job']['objects'][0]['shapes']['0']['stroke']['tool'] == 'T4'
    s3 = client.post('/api/slice').json()
    assert 'T4' in s3['stats']['tools']
    # The whole green colour to mask
    st = client.post(f'/api/objects/{oid}/paint', json={'index': 1, 'to': 'mask', 'target': 'both', 'scope': 'colour'}).json()
    assert st['job']['objects'][0]['groups']['stroke #21ff06']['mask'] is True
    # Reset the shape
    st = client.post(f'/api/objects/{oid}/paint', json={'index': 0, 'to': 'reset', 'target': 'stroke'}).json()
    assert st['job']['objects'][0]['shapes'] == {}


def test_shapes_and_gcode(client):
    oid = add(client)['id']
    sh = client.get(f'/api/objects/{oid}/shapes').json()
    assert sh['size'][0] > 0 and len(sh['shapes']) >= 4
    assert any(s['text'] for s in sh['shapes'])                 # the text, in a line font
    g = client.get('/api/gcode')
    assert g.status_code == 200 and 'attachment' in g.headers['content-disposition']
    assert g.text.startswith('; limn-plot 1')


def test_bed_and_z_overrides(client):
    add(client)
    st = client.patch('/api/job', json={'machine_overrides': {'bed_id': 'BED_5', 'z_travel': 4.5}}).json()
    assert st['machine']['draw_area'] == [5, 30, 93, 160]         # its paper, within reach of every tool
    assert st['machine']['mesh'] == 'lrt_paper' and st['machine']['z_travel'] == 4.5
    assert 'MESH=lrt_paper' in client.get('/api/gcode?inline=1').text or client.post('/api/slice') and \
        'MESH=lrt_paper' in client.get('/api/gcode?inline=1').text
    st = client.patch('/api/job', json={'machine_overrides': {'bed_id': None, 'z_travel': None}}).json()
    from plot.profile import load_machine
    assert st['machine']['bed_id'] == '' and st['machine']['z_travel'] == load_machine().z_travel
    assert client.patch('/api/job', json={'machine_overrides': {'z_max': 'high'}}).status_code == 400


def test_tool_overrides(client):
    add(client)
    st = client.patch('/api/job', json={'tool_overrides': {'T3': {'width': 0.3, 'color': '#123456'}}}).json()
    assert st['tools']['T3']['width'] == 0.3 and st['tools']['T3']['color'] == '#123456'
    st = client.patch('/api/job', json={'tool_overrides': {'T3': {'width': None, 'color': None}}}).json()
    assert st['tools']['T3']['width'] == 0.5 and 'T3' not in st['job']['tool_overrides']


def test_bad_uploads(client):
    assert client.post('/api/objects', files={'file': ('x.svg', b'not svg', 'image/svg+xml')}).status_code == 400
    assert client.post('/api/fonts', files={'file': ('x.ttf', b'nope', 'font/ttf')}).status_code == 400
    assert client.post('/api/fonts', files={'file': ('x.exe', b'nope', 'x')}).status_code == 400


@needs_font
def test_font_upload_draws_the_source_font(client):
    oid = add(client)['id']
    s_line = client.post('/api/slice').json()
    assert not any('no font' in p for p in s_line['problems'])      # auto: a line font, no complaint
    r = client.post('/api/fonts', files={'file': (FONT.name, FONT.read_bytes(), 'font/ttf')}).json()
    assert r['font']['family'] == 'Liberation Sans' and r['font']['kind'] == 'outline'
    t = r['state']['objects'][oid]['texts'][0]
    assert t['found'] == FONT.name and t['text'] == 'Hi'
    s_src = client.post('/api/slice').json()
    assert s_src['stats']['draw_mm'] != pytest.approx(s_line['stats']['draw_mm'])
    # Forced to a line font again
    st = client.patch(f'/api/objects/{oid}', json={'texts': {str(t['index']): {'mode': 'line', 'line_font': 'scripts'}}}).json()
    assert st['job']['objects'][0]['texts'][str(t['index'])]['line_font'] == 'scripts'
    assert client.delete(f'/api/fonts/{FONT.name}').json()['fonts'] == []


def test_printer(client, monkeypatch):
    add(client)
    sent = {}

    class R:
        def __init__(self, j): self._j = j
        def raise_for_status(self): pass
        def json(self): return self._j

    def get(url, params=None, timeout=None):
        return R({'result': {'status': {'print_stats': {'state': 'standby'}, 'limn': {'bed': 'BED_3',
                 'tool_holder': {'occupied': [41, 42]}}, 'virtual_sdcard': {'progress': 0}, 'toolhead': {'homed_axes': 'xyz'}}}})

    def post(url, files=None, data=None, timeout=None):
        sent.update(url=url, name=files['file'][0], body=files['file'][1], data=data)
        return R({'item': {'path': files['file'][0]}})

    monkeypatch.setattr(server.requests, 'get', get)
    monkeypatch.setattr(server.requests, 'post', post)
    p = client.get('/api/printer').json()
    assert p['ok'] and p['bed'] == 'BED_3' and p['occupied'] == [41, 42]
    r = client.post('/api/printer/upload', json={'start': True}).json()
    assert r['started'] and sent['url'].endswith('/server/files/upload') and sent['data'] == {'print': 'true'}
    assert sent['body'].startswith(b'; limn-plot 1')


def test_printer_offline(client, monkeypatch):
    def get(*a, **k):
        raise ConnectionError('refused')
    monkeypatch.setattr(server.requests, 'get', get)
    assert client.get('/api/printer').json() == {'ok': False, 'url': 'http://localhost:7125', 'error': 'refused'}


# The fonts on their own

def run_of(tmp_path, text='Hi', family='Liberation Sans', size=10, anchor=None):
    p = tmp_path / 't.svg'
    a = f' text-anchor="{anchor}"' if anchor else ''
    p.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="50mm" viewBox="0 0 100 50">'
                 f'<text x="50" y="30" font-family="{family}" font-size="{size}"{a} fill="#000000">{text}</text></svg>')
    return p, load(p).texts[0]


@needs_font
def test_line_font_takes_the_source_cap_height(tmp_path):
    from plot.fonts import cap_height, line_text
    p, run = run_of(tmp_path, 'H')
    cap = cap_height(FONT, run.size)
    strokes = line_text(run, 'futural', cap)
    ys = np.vstack(strokes)[:, 1]
    assert ys.max() == pytest.approx(30, abs=1e-4)           # on the baseline
    assert ys.max() - ys.min() == pytest.approx(cap, rel=1e-6)


@needs_font
def test_source_text_anchor_and_kerning(tmp_path):
    from plot.fonts import outline_text, shape_outline
    p, run = run_of(tmp_path, 'AV', anchor='middle')
    rings, width = outline_text(run, FONT)
    xs = np.vstack(rings)[:, 0]
    assert (xs.min() + xs.max()) / 2 == pytest.approx(50, abs=0.3)
    glyphs, w, _ = shape_outline(FONT, 'AV', 10)
    ga, _, _ = shape_outline(FONT, 'A', 10)
    assert glyphs[1][1] < shape_outline(FONT, 'A', 10)[1]     # V is kerned under the A


@needs_font
def test_text_modes_in_the_slicer(tmp_path, tools):
    p, run = run_of(tmp_path, 'Hi')
    fonts = FontStore(tmp_path / 'fonts')
    obj = Obj(id='t', svg=str(p))
    line = slice_object(obj, tools, fonts=fonts)
    fonts.add(FONT.name, FONT.read_bytes())
    src = slice_object(obj, tools, fonts=fonts)
    assert line.paths and src.paths
    skip = slice_object(obj.model_copy(update={'text': TextSpec(mode='skip')}), tools, fonts=fonts)
    assert not skip.paths
    forced = slice_object(obj.model_copy(update={'text': TextSpec(mode='source')}), tools, fonts=FontStore(tmp_path / 'none'))
    assert any('no font for Liberation Sans' in p for p in forced.problems) and forced.paths


def test_undo_redo(client):
    oid = add(client)['id']
    o = client.get('/api/state').json()['job']['objects'][0]
    client.patch(f'/api/objects/{oid}', json={'placement': {**o['placement'], 'x': 1}})
    client.delete(f'/api/objects/{oid}')
    assert client.get('/api/state').json()['job']['objects'] == []
    r = client.post('/api/undo').json()
    assert r['changed'] and r['state']['job']['objects'][0]['placement']['x'] == 1
    assert client.post('/api/slice').status_code == 200          # its SVG is still there
    r = client.post('/api/undo').json()
    assert r['state']['job']['objects'][0]['placement']['x'] == o['placement']['x']
    r = client.post('/api/redo').json()
    assert r['state']['job']['objects'][0]['placement']['x'] == 1
    client.post('/api/undo'); client.post('/api/undo')
    assert client.post('/api/undo').json()['changed'] is False    # before the upload: nothing left
