# The web UI in a browser (Firefox): uv run --group ui pytest plot/tests/test_ui.py
# (once: uv run --group ui playwright install firefox). Skipped without Playwright.
import os
import socket
import time
from pathlib import Path

import pytest
import requests

pytest.importorskip('playwright')
from playwright.sync_api import sync_playwright

with sync_playwright() as _p:
    if not Path(_p.firefox.executable_path).exists():
        pytest.skip('no Firefox for Playwright: uv run --group ui playwright install firefox', allow_module_level=True)

from .test_server import METRO

ROOT = Path(__file__).resolve().parents[2]
THIN = '''<svg xmlns="http://www.w3.org/2000/svg" width="60mm" height="40mm" viewBox="0 0 60 40">
<path d="M5 20 H55" stroke="#ff0000" stroke-width="0.05" fill="none"/>
<path d="M5 30 H55" stroke="#0000ff" stroke-width="0.05" fill="none"/>
</svg>'''


@pytest.fixture(scope='module')
def served(tmp_path_factory):
    '''The app in this process (so a test can give it tags, a fake printer), on a free port.'''
    import threading
    import uvicorn
    from plot import server
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
    old = os.environ.get('LIMN_MOONRAKER')
    os.environ['LIMN_MOONRAKER'] = 'http://127.0.0.1:9'
    app = server.create_app(tmp_path_factory.mktemp('ws'))
    srv = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning'))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f'http://127.0.0.1:{port}', app
    srv.should_exit = True
    t.join(5)
    if old is None:
        os.environ.pop('LIMN_MOONRAKER', None)
    else:
        os.environ['LIMN_MOONRAKER'] = old


@pytest.fixture
def base(served):
    return served[0]


@pytest.fixture
def drawing(base):
    def place(body=METRO, name='d.svg'):
        for o in requests.get(base + '/api/state').json()['job']['objects']:
            requests.delete(f"{base}/api/objects/{o['id']}")
        return requests.post(base + '/api/objects', files={'file': (name, body.encode(), 'image/svg+xml')}).json()['id']
    return place


def painted(base):
    return requests.get(base + '/api/state').json()['job']['objects'][0]['shapes']


def screen_point(page, i, along=0.5, off=(0, 0)):
    '''A point on shape i's outline, in page px, moved by `off` px.'''
    return page.evaluate('''([i, along, off]) => {
        const p = document.querySelector(`g.obj path.shape[data-i="${i}"]`);
        const q = p.getPointAtLength(p.getTotalLength() * along), m = p.getScreenCTM();
        return [q.x * m.a + q.y * m.c + m.e + off[0], q.x * m.b + q.y * m.d + m.f + off[1]] }''', [i, along, list(off)])


def test_paint_a_hairline_near_miss(page, base, drawing):
    drawing(THIN)
    page.goto(base + '/')
    page.wait_for_selector('g.obj path.shape')
    page.click('#palette button[data-to="T4"]')
    # 3px beside a 0.05mm line: still that line
    with page.expect_response(lambda r: '/paint' in r.url):
        page.mouse.click(*screen_point(page, 0, off=(0, 3)))
    assert painted(base)['0']['stroke']['tool'] == 'T4'
    assert '1' not in painted(base)
    # Hovering shows which shape a click paints
    page.mouse.move(*screen_point(page, 1, off=(0, -2)))
    page.wait_for_selector('path.shape.hot[data-i="1"]')


def test_paint_miss_says_so(page, base, drawing):
    drawing(THIN)
    page.goto(base + '/')
    page.wait_for_selector('g.obj path.shape')
    page.click('#palette button[data-to="T4"]')
    page.mouse.click(*screen_point(page, 0, off=(0, -25)))       # inside the drawing, far from both lines
    assert 'No shape here' in page.text_content('#hint')
    assert painted(base) == {}


def test_paths_view_hides_the_drawing(page, base, drawing):
    drawing()
    page.goto(base + '/')
    page.wait_for_selector('g.obj path.shape')
    page.click('#views button[data-view="paths"]')
    page.wait_for_selector('#paths-layer polyline', state='attached')
    assert not page.is_visible('#design-layer')
    page.check('#show-drawing')
    assert page.is_visible('#design-layer')
    assert page.get_attribute('g.obj path.shape[data-i="1"]', 'fill') == 'none'


# --- the Scan tab ----------------------------------------------------------------------
CAMERA_TAG = {'41': {'pen': 'cam-u20', 'name': 'Camera U20', 'dx': 0, 'dy': 0, 'dz': 0.5}}


@pytest.fixture
def scanning(served, monkeypatch):
    '''The camera tool in holder 41, a fake printer, a region; the page on the Scan tab.'''
    import limn_cam.moonraker as mrmod
    from limn_cam.tests.test_scan import FakeMoonraker
    url, app = served
    fake = FakeMoonraker()
    monkeypatch.setattr(mrmod, 'Moonraker', lambda u: fake)
    app.state.ws.tags = dict(CAMERA_TAG)
    app.state.ws.camera_job = None
    requests.patch(url + '/api/camera', json={'tool': 'T0', 'region': [30, 60, 60, 80], 'z': 5.0, 'settle': 0})
    return url


def open_scan(page, url):
    page.goto(url + '/')
    page.click('#ribbon [data-tab="scan"]')
    page.wait_for_selector('#s-film')


def region(url):
    return requests.get(url + '/api/camera').json()['settings']['region']


def test_corners_set_the_region_edges(page, scanning):
    open_scan(page, scanning)
    page.click('#camera-job [data-act="corners"]')
    page.wait_for_selector('#viewer svg[data-corner="tl"]', timeout=20000)
    box = page.locator('#viewer svg[data-corner="tl"]').bounding_box()
    # A quarter of the shot right of and below its middle: the region's top left corner goes there
    page.mouse.click(box['x'] + box['width'] * 0.75, box['y'] + box['height'] * 0.75)
    for _ in range(50):
        if region(scanning)[0] != 30:
            break
        time.sleep(0.1)
    cam = requests.get(scanning + '/api/camera').json()['cameras']['T0']
    import math
    t = math.radians(cam['turn'])
    fx = cam['fov'][0] * abs(math.cos(t)) + cam['fov'][1] * abs(math.sin(t))      # what one shot covers, upright
    fy = cam['fov'][0] * abs(math.sin(t)) + cam['fov'][1] * abs(math.cos(t))
    r = region(scanning)
    assert r[0] == pytest.approx(30 + fx / 4, abs=0.1) and r[3] == pytest.approx(80 - fy / 4, abs=0.1)
    assert r[1:3] == [60, 60]
    page.wait_for_selector(f'#viewer .corner .note:has-text("X {r[0]:g}")')


def test_region_drags_and_nudges(page, scanning):
    open_scan(page, scanning)
    page.click('#scan-rail [data-sact="region"]')            # zoomed to it
    rect = page.locator('#scan-layer rect.scan-region').bounding_box()
    # Its right edge, dragged 1/6 of its width further right
    x, y = rect['x'] + rect['width'], rect['y'] + rect['height'] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + rect['width'] / 6, y, steps=4)
    page.mouse.up()
    time.sleep(0.3)
    r = region(scanning)
    assert r[0] == 30 and r[2] == pytest.approx(65, abs=0.3)
    page.keyboard.press('ArrowUp')
    time.sleep(0.3)
    assert region(scanning)[1] == pytest.approx(61) and region(scanning)[3] == pytest.approx(81)
    page.keyboard.press('Alt+ArrowLeft')
    time.sleep(0.3)
    assert region(scanning)[0] == pytest.approx(29.9)


def test_film_format_around_the_region(page, scanning):
    open_scan(page, scanning)
    page.fill('#s-margin', '2')
    page.dispatch_event('#s-margin', 'change')
    page.select_option('#s-film', '24x36')
    time.sleep(0.3)
    assert region(scanning) == pytest.approx([45 - 14, 70 - 20, 45 + 14, 70 + 20])


def test_hugin_from_the_viewer(page, scanning, tmp_path):
    from limn_cam import hugin
    if hugin.missing():
        pytest.skip('no Hugin here')
    from limn_cam.scan import ScanStore, capture_root
    from limn_cam.tests.test_hugin import make_scan
    store, sid = make_scan(Path(capture_root(tmp_path)).parent / 'made')
    import shutil
    shutil.copytree(store.dir(sid), Path(capture_root(tmp_path)) / sid)
    open_scan(page, scanning)
    page.click(f'#captures li[data-id="{sid}"] .name')
    page.click('#viewer [data-view="hugin"]')
    page.click('#viewer [data-act="hugin"]')
    page.wait_for_selector('#viewer img.big', timeout=60000)
    assert 'matches over' in page.text_content('#viewer .stitchbar')


def test_cameras_overlay_and_fluidd(page, served, monkeypatch):
    url, app = served
    import plot.server as srv

    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {'result': {'webcams': [
                {'name': 'top', 'stream_url': '/webcam/?action=stream', 'snapshot_url': '/webcam/?action=snapshot', 'enabled': True},
                {'name': 'tool', 'stream_url': '/webcam2/?action=stream', 'snapshot_url': '/webcam2/?action=snapshot', 'enabled': True}]}}
    real = srv.requests.get
    monkeypatch.setattr(srv.requests, 'get', lambda u, **kw: R() if 'webcams/list' in u else real(u, **kw))
    page.goto(url + '/')
    page.click('#cams-button')
    page.wait_for_selector('#cams [data-cam="top"].on')
    # Moonraker on 127.0.0.1 (the UI on the Pi): the cameras and Fluidd are at this page's host
    # (no stream there in a test: the picture says it doesn't answer; its link shows where it went)
    opened = lambda: page.get_attribute('#cams a.button:has-text("open")', 'href')
    assert opened() == 'http://127.0.0.1/webcam/?action=stream'
    assert page.get_attribute('#fluidd-link', 'href').rstrip('/') == 'http://127.0.0.1'
    page.click('#cams [data-cam="tool"]')
    assert opened().endswith('/webcam2/?action=stream')
    page.click('#cams [data-act="cams-close"]')
    assert page.locator('#cams *').count() == 0                # the stream is closed
