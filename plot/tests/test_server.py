# The web UI's API, and texts in their own font or a line font
import time
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
    assert client.get('/api/printer').json() == {'ok': False, 'url': 'http://localhost:7125', 'error': 'refused',
                                                 'job': None}


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


TAGS = {'41': {'name': 'Fineliner 0.05', 'pen': None, 'color': None, 'dx': -2.4, 'dy': -0.14, 'dz': 0.75,
               'stale': False},
        '43': {'name': 'Micron 01 Blue', 'pen': 'mic-01', 'color': '#1f4aa8', 'dx': -4.44,
               'dy': -0.27, 'dz': 1.45, 'stale': False},
        '44': {'name': 'Micron 01 Green', 'pen': 'mic-01', 'color': None, 'dx': 0, 'dy': 0, 'dz': 0,
               'stale': True}}


def test_tags_make_the_tools():
    from plot.profile import load_machine, load_pens, load_tools, with_tags
    m, pens = load_machine(), load_pens()
    tools = with_tags(load_tools(), pens, TAGS, m.holders)
    t0, t2, t3, t4 = tools['T0'], tools['T2'], tools['T3'], tools['T4']
    # a pen on the tag: that pen of the library, its colour, the tag's name
    assert (t2.pen, t2.width, t2.color, t2.name, t2.holder, t2.source) == \
        ('mic-01', pens['mic-01']['width'], '#1f4aa8', 'Micron 01 Blue', 43, 'tag')
    assert t2.macro is None and t2.feed == pens['mic-01']['feed']
    # no colour on the tag: the pen's first; a hand on the holder since: stale
    assert t3.color == list(pens['mic-01']['colors'].values())[0] and t3.source == 'stale'
    # format 1: tools.toml, named as the tag
    assert (t0.pen, t0.name, t0.width, t0.source) == (None, 'Fineliner 0.05', load_tools()['T0'].width, 'tag')
    assert t4 == load_tools()['T4']                  # no tag


def test_scan_and_write_through_moonraker(client, monkeypatch):
    add(client)
    sent = []

    class R:
        status_code = 200
        def __init__(self, j): self._j = j
        def raise_for_status(self): pass
        def json(self): return self._j

    def get(url, params=None, timeout=None):
        return R({'result': {'status': {'print_stats': {'state': 'standby'}, 'limn': {'tools': TAGS}}}})

    def post(url, json=None, timeout=None, **kw):
        sent.append(json['script'])
        return R({'result': 'ok'})

    monkeypatch.setattr(server.requests, 'get', get)
    monkeypatch.setattr(server.requests, 'post', post)
    p = client.get('/api/printer').json()               # the UI polls this: it brings the tags
    assert p['tools_changed'] and p['tools'] == TAGS
    assert client.get('/api/printer').json()['tools_changed'] is False
    st = client.get('/api/state').json()
    assert st['holders'][2] == {'t': 'T2', 'holder': 43, 'tag': TAGS['43']}
    assert st['tools']['T2']['name'] == 'Micron 01 Blue' and 'mic-01' in st['pens']
    r = client.post('/api/holders/42/tag', json={'pen': 'mic-01', 'color': '#6A2C8F', 'name': 'Micron 01 Purple'})
    assert r.status_code == 200, r.text
    for _ in range(50):
        if client.get('/api/printer').json()['job']['done']:
            break
        time.sleep(0.02)
    assert sent[-1] == 'TOOL_TAG_SET T=42 PEN=mic-01 COLOR=6a2c8f NAME="Micron 01 Purple"'
    assert client.post('/api/scan', json={'holders': [41, 43]}).status_code == 200
    for _ in range(50):
        if client.get('/api/printer').json()['job']['done']:
            break
        time.sleep(0.02)
    assert sent[-1] == 'TOOL_SCAN T=41,43'
    for bad in ({'pen': 'crayon'}, {'color': 'blue'}, {'name': 'x"; G28'}, {}):
        assert client.post('/api/holders/42/tag', json=bad).status_code == 400, bad
    assert client.post('/api/holders/40/tag', json={'name': 'x'}).status_code == 404


def test_no_tag_writes_while_printing(client, monkeypatch):
    class R:
        def json(self): return {'result': {'status': {'print_stats': {'state': 'printing'}}}}
    monkeypatch.setattr(server.requests, 'get', lambda *a, **k: R())
    r = client.post('/api/scan', json={})
    assert r.status_code == 409 and 'printing' in r.text


def test_pen_keys_fit_a_tag():
    '''The key goes on the tag: up to 8 of a-z 0-9 - _ . (tool_holder.py encode_pen).'''
    from plot.profile import load_pens
    ok = set('abcdefghijklmnopqrstuvwxyz0123456789-_.')
    for key, pen in load_pens().items():
        assert len(key) <= 8 and set(key) <= ok, key
        assert len(pen.get('short', '')) <= 20, key
        if pen.get('kind', 'pen') != 'camera':
            assert pen.get('width', 0) > 0, key


@pytest.fixture
def pens_file(tmp_path, monkeypatch):
    from plot import profile
    p = tmp_path / 'pens.toml'
    p.write_text(profile.PENS.read_text())
    monkeypatch.setattr(profile, 'PENS', p)
    return p


def test_pen_library_add_edit_delete(client, pens_file):
    import tomllib
    before = pens_file.read_text()
    new = {'name': 'Uni Pin 0.1', 'short': 'Uni Pin 01', 'width': 0.2, 'feed': 2000,
           'colors': {'black': '#111111', 'dark grey': '#555555'}}
    st = client.put('/api/pens/uni-01', json=new).json()
    assert st['pens']['uni-01'] == new and 'pen' in st['kinds'] and 'z_down' in st['kinds']['pen']
    # Changed: the other lines keep their comments, the rest of the file stays
    mic = {**tomllib.loads(before)['mic-01'], 'width': 0.3, 'hop': 1.5}
    mic['colors'] = {**mic['colors'], 'teal': '#008080'}
    st = client.put('/api/pens/mic-01', json=mic).json()
    assert st['pens']['mic-01']['width'] == 0.3 and st['pens']['mic-01']['colors']['teal'] == '#008080'
    text = pens_file.read_text()
    assert 'width = 0.3                 # Sakura: 01 draws 0.25 mm' in text
    assert text.startswith(before.split('[mic-01]')[0]) and '# Sakura: 005 draws 0.20 mm' in text
    # A key taken off goes: back to the kind's default
    del mic['hop']
    assert 'hop' not in client.put('/api/pens/mic-01', json=mic).json()['pens']['mic-01']
    for key, bad in (('Too-Long-Key', new), ('uni-01', {**new, 'name': ''}), ('uni-01', {**new, 'widht': 1}),
                     ('uni-01', {**new, 'colors': {'black': 'black'}}), ('uni-01', {**new, 'kind': 'crayon'}),
                     ('uni-01', {**new, 'short': 'x' * 21})):
        assert client.put(f'/api/pens/{key}', json=bad).status_code == 400, bad
    assert 'uni-01' not in client.delete('/api/pens/uni-01').json()['pens']
    assert client.delete('/api/pens/uni-01').status_code == 404
    assert tomllib.loads(pens_file.read_text())['stb-88'] == tomllib.loads(before)['stb-88']


def test_pencil_kind_in_the_library(client, pens_file):
    st = client.put('/api/pens/hb', json={'name': 'HB pencil', 'kind': 'pencil', 'width': 0.3, 'wear': 0.05}).json()
    assert st['pens']['hb'] == {'name': 'HB pencil', 'kind': 'pencil', 'width': 0.3, 'wear': 0.05}
    assert 'wear' in st['kinds']['pencil'] and 'wear' not in st['kinds']['pen']


def test_unsafe_gcode_is_not_sent(client, monkeypatch):
    add(client)
    client.post('/api/slice')
    ws = client.app.state.ws
    ws.unsafe = ['the tool goes to z 0.5 at (150, 100), off the paper: under safe_z 5']
    monkeypatch.setattr(server.requests, 'post', lambda *a, **k: (_ for _ in ()).throw(AssertionError('sent')))
    r = client.post('/api/printer/upload', json={'start': True})
    assert r.status_code == 409 and 'too low off the paper' in r.text
    assert client.post('/api/slice').json()['unsafe'] is False


def test_clear_all_and_undo(client):
    add(client), add(client, name='two.svg')
    assert len(client.get('/api/state').json()['job']['objects']) == 2
    assert client.delete('/api/objects').json()['job']['objects'] == []
    assert len(client.post('/api/undo').json()['state']['job']['objects']) == 2   # one step back: both again


def test_camera_docked_by_hand(client, monkeypatch):
    '''A camera tool docked by hand (printer.limn.tools['90']) whose pen has its own URL: a fixed camera,
    its stream among the webcams.'''
    tags = {'90': {'uid': '04aa', 'name': 'Pi HQ', 'pen': 'picam', 'color': '', 'dx': 0, 'dy': 0, 'dz': 0,
                   'reference': False, 'stale': False, 'by': 'hand'}}

    class R:
        status_code = 200
        def __init__(self, j): self._j = j
        def raise_for_status(self): pass
        def json(self): return self._j

    def get(url, params=None, timeout=None):
        if url.endswith('/server/webcams/list'):
            return R({'result': {'webcams': []}})
        return R({'result': {'status': {'print_stats': {'state': 'standby'}, 'limn': {'tools': tags}}}})

    monkeypatch.setattr(server.requests, 'get', get)
    client.get('/api/printer')
    cams = client.get('/api/camera').json()['cameras']
    assert cams['manual']['fixed'] and cams['manual']['name'] == 'Pi HQ'
    assert cams['manual']['webcam'].endswith('/capture.jpg')
    w = {c['name']: c for c in client.get('/api/webcams').json()['webcams']}
    assert w['Pi HQ']['stream_url'] == 'http://limn-picam.local:4250/stream.mjpg'
