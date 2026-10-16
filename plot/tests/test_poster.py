# Posters: drawings bigger than the paper, plotted sheet by sheet (plot/poster.py)
import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from plot import poster
from plot.emit import plot
from plot.job import Group, Placement, Poster
from plot.preview import DRAW, parse
from plot.profile import load_machine

RED = {'stroke #ff0000': Group(tool='T3')}
# A frame 280 x 180 mm (the SVG's y down): bigger than the paper (about 105 x 137) both ways
FRAME = '<path d="M10 10 H290 V190 H10 Z" stroke="#ff0000" stroke-width="0.5" fill="none"/>'


def drawn(r):
    '''[(sheet, its draw runs on the bed (n, 2))]'''
    by = {s.n: s for s in r.layout.sheets}
    out = []
    for k, t, pts, n in r.sim.runs():
        if k != DRAW:
            continue
        sh = next(by[x['n']] for x in r.sheets if n <= x['last'])
        out.append((sh, pts[:, :2]))
    return out


def on_frame(p, placement):
    '''How far each point (poster mm) is from the frame, as the drawing is placed.'''
    q = placement.local(p)
    x, y = q[:, 0], q[:, 1]                         # object mm, y up: the frame is x 10..290, y 10..190
    dx = np.minimum(np.abs(x - 10), np.abs(x - 290))
    dy = np.minimum(np.abs(y - 10), np.abs(y - 190))
    inside = (x > 9.9) & (x < 290.1) & (y > 9.9) & (y < 190.1)
    return np.where(inside, np.minimum(dx, dy), 99)


@pytest.mark.parametrize('sheet', ['portrait', 'landscape'])
@pytest.mark.parametrize('turn', [0, 30])
def test_every_sheet_draws_its_part_and_they_join(write_svg, job_of, sheet, turn):
    p = write_svg(FRAME, w=300, h=200)
    job = job_of(p, x=0, y=0, groups=RED)
    job.objects[0].placement = Placement(rotate=turn)
    job.poster = Poster(sheet=sheet, marks=False)
    r, _ = plot(job)
    m, lay = load_machine(), r.layout
    w, h = m.draw_area[2] - m.draw_area[0], m.draw_area[3] - m.draw_area[1]
    assert (lay.sheet_w, lay.sheet_h) == ((w, h) if sheet == 'portrait' else (h, w))
    # The grid goes round what is drawn, the sheets sharing the overlap
    c = lay.content
    assert lay.origin[0] <= c[0] and lay.origin[0] + lay.cols * (lay.sheet_w - lay.overlap) + lay.overlap >= c[2]
    assert lay.origin[1] <= c[1] and lay.origin[1] + lay.rows * (lay.sheet_h - lay.overlap) + lay.overlap >= c[3]
    assert lay.cols * lay.rows >= 4
    runs = drawn(r)
    assert {s.n for s, _ in runs} == {s.n for s in lay.sheets if s.n not in
                                       [int(x.split()[1].rstrip(':')) for x in r.problems if x.endswith('left out')]}
    total = 0.0
    x0, y0, x1, y1 = m.draw_area
    for sh, pts in runs:
        assert (pts[:, 0] >= x0 - 1e-6).all() and (pts[:, 0] <= x1 + 1e-6).all()      # on the paper
        assert (pts[:, 1] >= y0 - 1e-6).all() and (pts[:, 1] <= y1 + 1e-6).all()
        back = poster.to_poster(sh, m, sheet == 'landscape', pts)
        assert (back[:, 0] >= sh.rect[0] - 1e-6).all() and (back[:, 0] <= sh.rect[2] + 1e-6).all()   # its own part
        assert (back[:, 1] >= sh.rect[1] - 1e-6).all() and (back[:, 1] <= sh.rect[3] + 1e-6).all()
        assert on_frame(back, job.objects[0].placement).max() < 0.05                 # of the frame, where it is
        total += float(np.hypot(*np.diff(back, axis=0).T).sum())
    # Every bit of the frame on a sheet: all of it, and the overlaps twice at most
    perimeter = 2 * (280 + 180)
    assert perimeter - 0.5 < total < perimeter + 4 * (lay.cols + lay.rows) * lay.overlap
    n = len(r.sheets)
    assert r.gcode.count('SHEET_NEXT') == n - 1 and r.gcode.count('PLOT_END') == n
    assert [s['sheet'] for s in r.plan if s['kind'] == 'sheet'] == [x['n'] for x in r.sheets]


def test_crop_marks_where_the_sheets_are_cut(write_svg, job_of):
    p = write_svg(FRAME, w=300, h=200)
    job = job_of(p, x=0, y=0, groups=RED)
    job.poster = Poster(overlap=8)
    r, _ = plot(job)
    m, lay = load_machine(), r.layout
    sh = next(s for s in lay.sheets if s.col == 0 and s.row == lay.rows - 1)    # the top left one: cut right, below
    assert sorted(a for a, _ in sh.cuts) == ['x', 'y']
    ticks = poster.marks(sh, m, False)
    assert len(ticks) == 4 and all(len(t) == 2 for t in ticks)
    for t in ticks:
        back = poster.to_poster(sh, m, False, t[:, :2])
        assert math.dist(back[0], back[1]) == pytest.approx(poster.MARK)
    cut_x = next(v for a, v in sh.cuts if a == 'x')
    assert cut_x == pytest.approx(sh.rect[2] - 4)                                   # the middle of the overlap


def test_a_drawing_off_a_sheet_is_left_out_of_it(write_svg, job_of):
    p = write_svg(FRAME, w=300, h=200)
    job = job_of(p, x=0, y=0, groups=RED)
    job.poster = Poster(marks=False)
    r, _ = plot(job)
    boxes = {'d': (10, 10, 290, 190)}
    far = job.model_copy(update={'objects': [job.objects[0].model_copy(update={'placement': Placement(x=5000)})]})
    assert poster.sheet_job(far, r.layout.sheets[0], load_machine(), False, boxes).objects == []


def test_a_locked_grid_stays_where_it_is(write_svg, job_of):
    p = write_svg(FRAME, w=300, h=200)
    job = job_of(p, x=0, y=0, groups=RED)
    m, boxes = load_machine(), {'d': (10, 10, 290, 190)}
    free = poster.layout(Poster(), m, job.objects, boxes)
    locked = Poster(locked=True, origin=free.origin, cols=free.cols, rows=free.rows)
    moved = [job.objects[0].model_copy(update={'placement': Placement(x=40)})]
    assert poster.layout(Poster(), m, moved, boxes).origin != free.origin           # free: it follows
    held = poster.layout(locked, m, moved, boxes)
    assert (held.origin, held.cols, held.rows) == (free.origin, free.cols, free.rows)


def test_the_server_lays_out_the_poster_and_keeps_locks(tmp_path, monkeypatch):
    from plot import server
    from .conftest import svg_text
    monkeypatch.setenv('LIMN_MOONRAKER', 'http://127.0.0.1:9')
    c = TestClient(server.create_app(tmp_path))
    st = c.patch('/api/job', json={'poster': {'sheet': 'portrait'}}).json()
    assert st['poster']['cols'] == 1 and st['poster']['content'] is None        # nothing on it yet: one sheet
    oid = c.post('/api/objects', files={'file': ('f.svg', svg_text(FRAME, 300, 200).encode(), 'image/svg+xml')}).json()['id']
    st = c.get('/api/state').json()
    assert [o['scale'] for o in st['job']['objects']] == [1.0]                  # as big as it is
    lay = st['poster']
    assert lay['cols'] * lay['rows'] >= 4 and len(lay['sheets']) == lay['cols'] * lay['rows']
    # The preview's paths are on the poster: inside the grid, not all on the bed's paper
    pv = c.post('/api/slice').json()
    xs = [v for _, _, _, f in pv['runs'] for v in f[0::2]]
    assert max(xs) - min(xs) > 200 and len(pv['sheets']) >= 4
    # Locked: the grid as it is, and nothing moves until it is unlocked
    st = c.patch('/api/job', json={'poster': {'locked': True}}).json()
    assert st['job']['poster']['origin'] == lay['origin'] and st['job']['poster']['cols'] == lay['cols']
    r = c.patch(f'/api/objects/{oid}', json={'placement': {'x': 99, 'y': 0, 'rotate': 0}})
    assert r.status_code == 409
    assert c.patch(f'/api/objects/{oid}', json={'occlude': False}).status_code == 200      # the rest changes
    c.patch('/api/job', json={'poster': {'locked': False}})
    assert c.patch(f'/api/objects/{oid}', json={'locked': True}).status_code == 200
    assert c.patch(f'/api/objects/{oid}', json={'scale': 2}).status_code == 409
    assert c.patch(f'/api/objects/{oid}', json={'scale': 2, 'locked': False}).status_code == 200
    st = c.patch('/api/job', json={'poster': None}).json()
    assert st['poster'] is None and st['job']['poster'] is None
