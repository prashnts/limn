# KiCad schematics and boards as drawings (plot/kicad.py): through kicad-cli, skipped without it
import io
import math
import shutil
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(not shutil.which('kicad-cli'), reason='no kicad-cli (KiCad 8 on)')

KICAD = Path(__file__).resolve().parents[2] / 'docs' / 'kicad'
BOARD = '''(kicad_pcb (version 20240108) (generator "limn-test")
  (general (thickness 1.6))
  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (37 "F.SilkS" user "F.Silkscreen") (44 "Edge.Cuts" user))
  (net 0 "")
  (gr_rect (start 100 100) (end 140 120) (stroke (width 0.1) (type solid)) (fill none) (layer "Edge.Cuts"))
  (segment (start 105 105) (end 135 105) (width 1) (layer "F.Cu") (net 0))
  (via (at 120 112) (size 2) (drill 0.8) (layers "F.Cu" "B.Cu") (net 0))
)'''


@pytest.fixture
def client(tmp_path, monkeypatch):
    from plot import server
    monkeypatch.setenv('LIMN_MOONRAKER', 'http://127.0.0.1:9')
    return TestClient(server.create_app(tmp_path))


def add(c, name, data, **form):
    return c.post('/api/objects', files={'file': (name, data)}, data={k: str(v) for k, v in form.items()})


def test_a_board_is_a_drawing_of_its_layers(client):
    r = add(client, 'tiny.kicad_pcb', BOARD.encode(), layers='F.Cu,Edge.Cuts')
    assert r.status_code == 200, r.text
    got = r.json()
    assert got['kicad'] == 'board' and got['ids'] == ['tiny']
    st = got['state']
    w, h = st['objects']['tiny']['size']
    assert w == pytest.approx(40, abs=1) and h == pytest.approx(20, abs=1)       # the board area only, 1:1
    o = st['job']['objects'][0]
    assert o['scale'] == 1.0
    assert o['groups']['fill #ffffff']['mask'] is True                          # the via's drill: through the copper
    keys = {g['key'] for g in st['objects']['tiny']['groups']}
    assert {'fill #c83434', 'stroke #d0d2cd'} <= keys                           # copper and the edge: a pen each
    pv = client.post('/api/slice').json()
    assert pv['stats']['draw_mm'] > 30


def test_a_schematic_without_its_search_copies_of_the_text(client):
    r = add(client, 'cal_bed.kicad_sch', (KICAD / 'cal_bed.kicad_sch').read_bytes())
    assert r.status_code == 200, r.text
    st = r.json()['state']
    (oid,) = r.json()['ids']
    assert st['objects'][oid]['texts'] == []                # the opacity 0 copies: not texts to draw
    o = st['job']['objects'][0]
    assert o['groups']['fill #ffffc2'] == {**o['groups']['fill #ffffc2'], 'tool': None, 'mask': False}   # bodies not filled
    assert o['scale'] < 1                                   # fitted onto the paper by what is drawn


def test_a_project_gives_a_drawing_for_each_sheet_side_by_side(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for f in [*KICAD.glob('*.kicad_sch'), KICAD / 'limn.kicad_pro']:
            z.write(f, f'limn/{f.name}')
    client.patch('/api/job', json={'poster': {'sheet': 'portrait'}})
    r = add(client, 'limn.zip', buf.getvalue())
    assert r.status_code == 200, r.text
    ids, st = r.json()['ids'], r.json()['state']
    assert len(ids) > 1 and ids[0] == 'limn'                # the root sheet first
    objs = {o['id']: o for o in st['job']['objects']}
    assert all(objs[i]['scale'] == 1.0 for i in ids)        # a poster: as big as they are
    per = math.ceil(math.sqrt(len(ids)))                     # in rows, about as many as across
    ys = [round(objs[i]['placement']['y']) for i in ids]
    xs = [objs[i]['placement']['x'] for i in ids[:per]]
    assert xs == sorted(xs) and len(set(xs)) == len(xs)     # one beside the other
    assert min(ys[per:]) < min(ys[:per])                    # the next row under
    lay = st['poster']
    assert lay['cols'] < 3 * lay['rows']                    # not one long row


def test_what_kicad_cant_do_is_said(client, monkeypatch):
    r = add(client, 'tiny.kicad_pcb', BOARD.encode(), layers='F.Cu,Nope')
    assert r.status_code == 400 and 'no layer Nope' in r.json()['detail']
    r = add(client, 'x.zip', b'not a zip')
    assert r.status_code == 400
    monkeypatch.setattr(shutil, 'which', lambda name: None)
    r = add(client, 'tiny.kicad_pcb', BOARD.encode())
    assert r.status_code == 400 and 'not installed' in r.json()['detail']
    assert client.get('/api/state').json()['job']['objects'] == []
