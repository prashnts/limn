# How drawings stack and draw: settings for every tool, gaps (bleed), small detail,
# masked regions, drawings over drawings, and what the web UI's API does with them
import numpy as np
import pytest
from fastapi.testclient import TestClient

from plot import server
from plot.emit import load, plot
from plot.job import Group, Job, Obj, Placement, ShapePaint, ShapeSet
from plot.slicer import lost_detail, slice_object
from plot.svg import strip_images

from .conftest import svg_text
from .test_server import FONT, needs_font

RED = {'stroke #ff0000': Group(tool='T3')}


@pytest.fixture
def client(tmp_path):
    return TestClient(server.create_app(tmp_path / 'ws'))


def add(client, body, name='d.svg'):
    r = client.post('/api/objects', files={'file': (name, body.encode(), 'image/svg+xml')})
    assert r.status_code == 200, r.text
    return r.json()


def xs(paths):
    return np.vstack(paths)[:, 0]


def test_draw_settings_for_every_tool_a_tool_overrides_them(tmp_path):
    job = Job(draw={'feed': 1234, 'fill': 'concentric', 'bleed': 0.3}, tool_overrides={'T1': {'feed': 999}})
    job._root = tmp_path
    _, tools = load(job)
    assert tools['T0'].feed == 1234 and tools['T3'].fill == 'concentric' and tools['T3'].bleed == 0.3
    assert tools['T1'].feed == 999 and tools['T1'].fill == 'concentric'
    job.draw = {'nope': 1}
    with pytest.raises(ValueError, match='no setting nope'):
        load(job)


def test_a_colour_left_to_its_tool_fills_as_the_tool_does(write_svg, tools):
    p = write_svg('<rect x="10" y="10" width="20" height="20" fill="#ff0000"/>')
    g = {'fill #ff0000': Group(tool='T3')}
    hatch = slice_object(Obj(id='d', svg=str(p), groups=g), tools)
    ring = {**tools, 'T3': tools['T3'].model_copy(update={'fill': 'concentric'})}
    rings = slice_object(Obj(id='d', svg=str(p), groups=g), ring)
    assert len(rings.paths['T3']) != len(hatch.paths['T3'])
    # The colour's own setting wins over the tool's
    own = slice_object(Obj(id='d', svg=str(p), groups={'fill #ff0000': Group(tool='T3', fill='hatch')}), ring)
    assert len(own.paths['T3']) == len(hatch.paths['T3'])


def test_bleed_keeps_a_gap_from_another_tool_on_top(write_svg, tools):
    # Red under a 4mm green line: cut at 48..52, and 0.5 further with a bleed of 0.5
    p = write_svg('''
        <path d="M10 50 H90" stroke="#ff0000" stroke-width="0.5"/>
        <path d="M50 10 V90" stroke="#00ff00" stroke-width="4"/>''')
    groups = {'stroke #ff0000': Group(tool='T3'), 'stroke #00ff00': Group(tool='T0')}
    bled = {**tools, 'T3': tools['T3'].model_copy(update={'bleed': 0.5})}
    red = sorted(slice_object(Obj(id='d', svg=str(p), groups=groups), bled).paths['T3'], key=lambda a: a[0, 0])
    assert red[0][:, 0].max() == pytest.approx(47.5) and red[1][:, 0].min() == pytest.approx(52.5)
    # The same tool on top: no gap, it is one ink
    same = {'stroke #ff0000': Group(tool='T3'), 'stroke #00ff00': Group(tool='T3')}
    lines = [a for a in slice_object(Obj(id='d', svg=str(p), groups=same), bled).paths['T3'] if np.ptp(a[:, 1]) < 1]
    assert min(a[:, 0].max() for a in lines) == pytest.approx(48)


def test_small_dense_shapes_are_left_out_or_warned(write_svg, tools):
    # A scribble 1mm across (a letter at a tiny scale) and a 1mm dash, with a 0.5 pen
    p = write_svg('''
        <path d="M10 10 l1 0 l-1 0.5 l1 0 l-1 0.5 l1 0" stroke="#ff0000" stroke-width="0.1" fill="none"/>
        <path d="M30 10 h1" stroke="#ff0000" stroke-width="0.1" fill="none"/>
        <path d="M50 10 h20 v20 h-20 z" stroke="#ff0000" stroke-width="0.1" fill="none"/>''')
    s = slice_object(Obj(id='d', svg=str(p), groups=RED), tools)
    assert s.small == [0]
    assert len(s.paths['T3']) == 2                         # the dash and the square
    assert any('1 shape too small or dense for T3' in q and 'left out' in q for q in s.problems)
    warn = {**tools, 'T3': tools['T3'].model_copy(update={'small': 'warn'})}
    s = slice_object(Obj(id='d', svg=str(p), groups=RED), warn)
    assert s.small == [0] and len(s.paths['T3']) == 3 and any('drawn anyway' in q for q in s.problems)
    # Scaled up 5 times it reads again
    assert slice_object(Obj(id='d', svg=str(p), groups=RED, scale=5), tools).small == []


def test_lost_detail():
    w = 0.4
    ring = [np.array([[0, 0], [3, 0], [3, 3], [0, 3], [0, 0]], float)]
    assert lost_detail(ring, w) < 0.5                          # a 3mm square, inside mostly clear
    assert lost_detail([r * 0.3 for r in ring], w) == 1.0      # 0.9mm: under 2.5 pens, a blob
    assert lost_detail([r * 0.4 for r in ring], w) > 0.5       # 1.2mm: the pen fills most of it
    assert lost_detail([np.array([[0, 0], [5, 0]])], w) == 0   # a line
    assert lost_detail([np.array([[0, 0], [0.1, 0.1]])], w) == 0   # a dot


@needs_font
def test_tiny_text_goes_to_its_line_font(tmp_path, tools):
    from plot.fonts import FontStore
    fonts = FontStore(tmp_path / 'fonts')
    fonts.add(FONT.name, FONT.read_bytes())
    p = tmp_path / 't.svg'
    p.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100">'
                 '<text x="10" y="50" font-family="Liberation Sans" font-size="FS" fill="#ff0000">Hello</text></svg>'
                 .replace('FS', '2'))
    g = {'fill #ff0000': Group(tool='T3')}
    s = slice_object(Obj(id='d', svg=str(p), groups=g), tools, fonts=fonts)
    assert any('too small for T3' in q and 'futural' in q for q in s.problems)
    p.write_text(p.read_text().replace('font-size="2"', 'font-size="12"'))
    s = slice_object(Obj(id='d', svg=str(p), groups=g), tools, fonts=fonts)
    assert not any('too small' in q for q in s.problems)


def test_a_masked_region_isnt_drawn(write_svg, tools):
    p = write_svg('<path d="M10 50 H90" stroke="#ff0000" stroke-width="0.5"/>')
    # Object mm: y up from the page's bottom (100 high), so the line is at y 50
    o = Obj(id='d', svg=str(p), groups=RED, masks=[[(40, 40), (60, 40), (60, 60), (40, 60)]])
    red = sorted(slice_object(o, tools).paths['T3'], key=lambda a: a[0, 0])
    assert len(red) == 2 and red[0][:, 0].max() == pytest.approx(40) and red[1][:, 0].min() == pytest.approx(60)
    # Masks are in the drawing's own mm: they scale with it
    red = slice_object(o.model_copy(update={'scale': 0.5}), tools).paths['T3']
    assert len(red) == 2 and max(a[:, 0].max() for a in red if a[0, 0] < 20) == pytest.approx(20)


def test_a_drawing_hides_the_ones_under_it(write_svg, tmp_path):
    line = write_svg('<path d="M0 10 H100" stroke="#ff0000" stroke-width="0.5"/>', w=100, h=20, name='line.svg')
    sq = write_svg('<rect x="0" y="0" width="10" height="10" fill="#00ff00"/>', w=10, h=10, name='sq.svg')
    under = Obj(id='line', svg=str(line), groups=RED, placement=Placement(x=5, y=60))
    over = Obj(id='sq', svg=str(sq), groups={'fill #00ff00': Group(tool='T0')}, placement=Placement(x=50, y=65))
    job = Job(objects=[under, over])
    job._root = tmp_path
    r, _ = plot(job)
    def red_xs(gcode, cmd):
        lines = [l for l in gcode.split('--- T3')[1].split('---')[0].splitlines() if l.startswith(cmd) and 'X' in l]
        return [float(w[1:]) for l in lines for w in l.split() if w[0] == 'X']
    assert not any(50.01 < x < 59.99 for x in red_xs(r.gcode, 'G1'))
    assert {50, 60} <= {round(x, 3) for x in red_xs(r.gcode, 'G')}
    # Sent to the back: the line is whole again
    job.objects = [over, under]
    r, _ = plot(job)
    assert 'X50 ' not in r.gcode.split('--- T3')[1] + ' '
    # occlude off: it hides nothing
    job.objects = [under, over.model_copy(update={'occlude': False})]
    r2, _ = plot(job)
    assert not {50, 60} & {round(x, 3) for x in red_xs(r2.gcode, 'G')}


def test_images_are_taken_out_on_upload(client):
    body = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="50mm" '
            'height="50mm" viewBox="0 0 50 50"><image xlink:href="data:image/png;base64,iVBOR" width="50" height="50"/>'
            '<path d="M5 5 H45" stroke="#ff0000" stroke-width="0.5"/></svg>')
    r = add(client, body)
    assert r['images'] == 1
    ws = client.app.state.ws
    assert b'<image' not in (ws.data / 'uploads' / 'd.svg').read_bytes()
    assert strip_images(b'<svg><path/></svg>') == (b'<svg><path/></svg>', 0)


def test_order_draw_and_masks_through_the_api(client):
    body = '<svg xmlns="http://www.w3.org/2000/svg" width="20mm" height="20mm" viewBox="0 0 20 20"><path d="M2 10 H18" stroke="#ff0000" stroke-width="0.5"/></svg>'
    for n in 'abc':
        add(client, body, f'{n}.svg')
    ids = lambda st: [o['id'] for o in st['job']['objects']]
    st = client.post('/api/objects/a/order', json={'to': 'front'}).json()
    assert ids(st) == ['b', 'c', 'a']
    assert ids(client.post('/api/objects/a/order', json={'to': 'backward'}).json()) == ['b', 'a', 'c']
    assert ids(client.post('/api/objects/c/order', json={'to': 'back'}).json()) == ['c', 'b', 'a']
    assert ids(client.post('/api/objects/c/order', json={'to': 'backward'}).json()) == ['c', 'b', 'a']
    assert client.post('/api/objects/c/order', json={'to': 'up'}).status_code == 400
    assert ids(client.post('/api/undo').json()['state']) == ['b', 'a', 'c']

    st = client.patch('/api/job', json={'draw': {'feed': 1500, 'small': 'warn'}}).json()
    assert st['job']['draw'] == {'feed': 1500, 'small': 'warn'}
    assert all(t['feed'] == 1500 for t in st['tools'].values() if t['draws'])
    assert st['draw']['bleed'] == 0 and st['draw']['fill'] == 'hatch'
    st = client.patch('/api/job', json={'draw': {'feed': None}}).json()
    assert st['job']['draw'] == {'small': 'warn'}
    assert client.patch('/api/job', json={'draw': {'small': 'maybe'}}).status_code == 400

    r = client.patch('/api/objects/a', json={'masks': [[[0, 0], [10, 0], [10, 20], [0, 20]]]})
    a = next(o for o in r.json()['job']['objects'] if o['id'] == 'a')
    assert r.status_code == 200 and a['masks'][0][1] == [10, 0]


def test_printer_url_for_the_cameras(client, monkeypatch):
    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {'result': {'webcams': [{'name': 'top', 'stream_url': '/webcam4/?action=stream', 'enabled': True}]}}
    monkeypatch.setattr(server.requests, 'get', lambda *a, **k: R())
    w = client.get('/api/webcams').json()
    assert w['guessed'] and not w['set']            # Moonraker on localhost: the page's host, perhaps
    assert client.put('/api/settings', json={'printer_url': 'limn.local'}).status_code == 400
    assert client.put('/api/settings', json={'printer_url': 'https://limn.example/'}).json()['printer_url'] == 'https://limn.example'
    w = client.get('/api/webcams').json()
    assert w['fluidd'] == 'https://limn.example' and w['set'] and not w['guessed']
    assert client.put('/api/settings', json={'other': 1}).status_code == 400


def test_macro_buttons(client, monkeypatch):
    sent = []

    class R:
        status_code = 200

        def __init__(self, result):
            self.result = result

        def raise_for_status(self):
            pass

        def json(self):
            return {'result': self.result}

    def get(url, **k):
        if url.endswith('/printer/gcode/help'):
            return R({'G28': 'home', 'T0': 'tool', 'T1': 'tool', 'UNDOCK': 'put away', 'BED_MESH_CLEAR': 'clear',
                      'BED_MESH_PROFILE': 'mesh'})
        return R({'status': {'print_stats': {'state': 'standby'}}})
    monkeypatch.setattr(server.requests, 'get', get)
    monkeypatch.setattr(server.requests, 'post', lambda url, json=None, **k: sent.append(json['script']) or R({}))
    m = client.get('/api/printer/macros').json()
    gcodes = [x['gcode'] for x in m['macros']]
    assert m['checked'] and 'G28' in gcodes and 'T0' in gcodes and 'UNDOCK' in gcodes
    assert 'LAZY_HOME' not in gcodes and 'T2' not in gcodes        # Klipper has no such command
    assert 'BED_MESH_PROFILE LOAD=lrt_paper' in gcodes
    assert client.post('/api/printer/macro', json={'gcode': 'G28 X'}).status_code == 400
    assert client.post('/api/printer/macro', json={'gcode': 'FIRMWARE_RESTART'}).status_code == 400
    r = client.post('/api/printer/macro', json={'gcode': 'G28'})
    assert r.status_code == 200 and r.json()['job']['what'] == 'running G28'
    for _ in range(50):
        if sent:
            break
        import time
        time.sleep(0.02)
    assert sent == ['G28']


def test_light_under_dark(write_svg, tmp_path, tools):
    # A light yellow square with a black outline 1mm wide over its edge
    p = write_svg('<rect x="20" y="20" width="40" height="40" fill="#ffe000" stroke="#000000" stroke-width="1"/>')
    g = {'fill #ffe000': Group(tool='T1', fill='none', border=True), 'stroke #000000': Group(tool='T0')}
    light = tools['T1'].model_copy(update={'color': '#ffe000'})
    dark = tools['T0'].model_copy(update={'color': '#111111'})
    cut_out = {**tools, 'T1': light, 'T0': dark}
    edge = lambda s: np.vstack(s.paths['T1'])[:, 0].min()
    s = slice_object(Obj(id='d', svg=str(p), groups=g), cut_out)
    assert edge(s) == pytest.approx(20.5 + light.width / 2)              # inside the black outline
    layered = {**cut_out, 'T1': light.model_copy(update={'layers': True})}
    s = slice_object(Obj(id='d', svg=str(p), groups=g), layered)
    assert edge(s) == pytest.approx(20 + light.width / 2)                # the whole square, under the black
    # A darker ink never goes under a lighter one
    rev = {**cut_out, 'T0': dark.model_copy(update={'layers': True})}
    assert edge(slice_object(Obj(id='d', svg=str(p), groups=g), rev)) == pytest.approx(20.5 + light.width / 2)
    # Light first in the G-code, whatever the tools' order
    job = Job(objects=[Obj(id='d', svg=str(p), groups=g, placement=Placement(x=10, y=40))],
              draw={'layers': True}, tool_order=['T0', 'T1'])
    job._root = tmp_path
    machine_tools = load(job)[1]
    assert machine_tools['T1'].layers
    job.tool_overrides = {'T1': {'color': '#ffe000'}, 'T0': {'color': '#111111'}}
    r, _ = plot(job)
    assert r.gcode.index('--- T1') < r.gcode.index('--- T0')
    job.draw = {}
    r, _ = plot(job)
    assert r.gcode.index('--- T0') < r.gcode.index('--- T1')


def test_fill_margin_keeps_the_fill_inside_its_edge(write_svg, tools):
    # A 20 mm red square, T3 with a bleed of 1: with the margin its fill keeps 1 mm in from
    # the edge (and half the line), its border along that inner edge; the corners come round
    p = write_svg('<rect x="10" y="10" width="20" height="20" fill="#ff0000"/>')
    bled = {**tools, 'T3': tools['T3'].model_copy(update={'bleed': 1.0, 'border': True})}
    w = bled['T3'].width
    plain = np.vstack(slice_object(Obj(id='d', svg=str(p), groups={'fill #ff0000': Group(tool='T3')}), bled).paths['T3'])
    assert plain[:, 0].min() == pytest.approx(10 + w / 2, abs=0.01)
    g = {'fill #ff0000': Group(tool='T3', inset=True)}
    pts = np.vstack(slice_object(Obj(id='d', svg=str(p), groups=g), bled).paths['T3'])
    assert pts[:, 0].min() == pytest.approx(11 + w / 2, abs=0.01) and pts[:, 0].max() == pytest.approx(29 - w / 2, abs=0.01)
    corner = np.hypot(pts[:, 0] - (11 + w / 2), pts[:, 1] - (70 + 1 + w / 2)).min()
    assert corner > 0.2                     # rounded: nothing right in the corner
    # Per shape, over its colour's layer; a sliver too thin for the margin is filled as it is
    sliver = write_svg('<rect x="10" y="10" width="20" height="1.5" fill="#ff0000"/>', name='s.svg')
    o = Obj(id='d', svg=str(sliver), groups={'fill #ff0000': Group(tool='T3')}, shapes={'0': ShapePaint(inset=True)})
    assert np.vstack(slice_object(o, bled).paths['T3'])[:, 0].min() == pytest.approx(10 + w / 2, abs=0.01)


def test_a_closed_unfilled_shape_takes_a_fill_of_its_own_or_its_sets(write_svg, tools):
    p = write_svg('''
        <rect x="10" y="10" width="20" height="20" stroke="#ff0000" stroke-width="0.3" fill="none"/>
        <path d="M40 10 L60 30" stroke="#ff0000" stroke-width="0.3" fill="none"/>''')
    base = Obj(id='d', svg=str(p), groups=RED)
    n = len(slice_object(base, tools).paths['T3'])
    own = base.model_copy(update={'shapes': {'0': ShapePaint(fill=Group(tool='T0'))}})
    assert 'T0' in slice_object(own, tools).paths
    # The open line can't take one; a set paints both, its outlines' tool changed too
    st = base.model_copy(update={'sets': [ShapeSet(name='g', shapes=[0, 1], fill=Group(tool='T0'), stroke=Group(tool='T1'))]})
    s = slice_object(st, tools)
    assert 'T3' not in s.paths and len(s.paths['T1']) == n
    assert np.vstack(s.paths['T0'])[:, 0].max() < 31
    # A shape's own paint wins over its set's
    both = st.model_copy(update={'shapes': {'1': ShapePaint(stroke=Group(tool='T3'))}})
    assert len(slice_object(both, tools).paths['T3']) == 1


def test_api_shapes_fillable_groups_of_drawings_and_batch(client):
    add(client, svg_text('''
        <rect x="10" y="10" width="20" height="20" stroke="#ff0000" stroke-width="0.3" fill="none"/>
        <path d="M40 10 L60 30" stroke="#ff0000" stroke-width="0.3" fill="none"/>'''), 'a.svg')
    add(client, svg_text('<circle cx="50" cy="50" r="10" fill="#000000"/>'), 'b.svg')
    sh = client.get('/api/objects/a/shapes').json()['shapes']
    assert [s['fillable'] for s in sh] == [True, False]
    # Paint the rectangle's (missing) fill: it takes one of its own
    r = client.post('/api/objects/a/paint', json={'index': 0, 'to': 'T0', 'target': 'fill', 'scope': 'shape'}).json()
    assert r['job']['objects'][0]['shapes']['0']['fill']['tool'] == 'T0'
    r = client.patch('/api/objects', json={'a': {'group': 'g1', 'placement': {'x': 1, 'y': 2, 'rotate': 0}},
                                           'b': {'group': 'g1'}}).json()
    assert [o['group'] for o in r['job']['objects']] == ['g1', 'g1'] and r['job']['objects'][0]['placement']['x'] == 1
    assert client.patch('/api/objects', json={'a': {'id': 'x'}}).status_code == 400
    r = client.patch('/api/objects/a', json={'sets': [{'name': 'G', 'shapes': [0, 1], 'inset': True}]})
    assert r.status_code == 200 and r.json()['job']['objects'][0]['sets'][0]['inset'] is True
