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


def test_drawings_hide_but_still_plot(page, base, drawing):
    oid = drawing()
    page.goto(base + '/')
    page.wait_for_selector('g.obj path.shape')
    page.click(f'#objects li[data-id="{oid}"] [data-act="eye"]')
    assert not page.is_visible(f'g.obj[data-id="{oid}"]')
    assert 'still plots' in page.text_content('#objects')
    assert requests.get(base + '/api/state').json()['job']['objects']      # still on the bed, in the job
    page.reload()
    page.wait_for_selector(f'#objects li.hidden[data-id="{oid}"]')       # remembered
    page.click(f'#objects li[data-id="{oid}"] [data-act="eye"]')
    assert page.is_visible(f'g.obj[data-id="{oid}"]')


def looks(tmp_path, n=2):
    '''n look captures in the capture store, one shot each.'''
    from limn_cam.scan import ScanStore, capture_root
    from limn_cam.tests.test_scan import jpeg, pattern
    store = ScanStore(capture_root(tmp_path))
    ids = []
    for i in range(n):
        sid = store.new({'kind': 'look', 'fov': [16, 9], 'turn': 0})
        store.add(sid, 'look.jpg', jpeg(pattern(i)), {'x': 40 + 30 * i, 'y': 80, 'z': 5})
        ids.append(sid)
        time.sleep(1.05)                    # ids are by the second
    return ids


def test_scans_show_and_hide(page, scanning, tmp_path):
    a, b = looks(tmp_path)
    open_scan(page, scanning)
    page.wait_for_function('() => document.querySelectorAll("#scan-layer image.shot").length === 2')
    page.click(f'#captures li[data-id="{a}"] [data-eye]')
    page.wait_for_function('() => document.querySelectorAll("#scan-layer image.shot").length === 1')
    assert 'hidden' in page.get_attribute(f'#captures li[data-id="{a}"]', 'class')
    # Both under the plot, then one hidden, then one unpinned
    page.evaluate(f'() => localStorage.setItem("limn-plot:scanUnders", JSON.stringify(["{a}", "{b}"]))')
    page.click('#ribbon [data-tab="plot"]')
    page.wait_for_function('() => document.querySelectorAll("#scan-under image").length === 2')
    assert page.locator('#unders li').count() == 2
    page.click(f'#unders li[data-under="{a}"] [data-act="eye"]')
    page.wait_for_function('() => document.querySelectorAll("#scan-under image").length === 1')
    page.click(f'#unders li[data-under="{b}"] [data-act="unpin"]')
    page.wait_for_function('() => document.querySelectorAll("#unders li").length === 1')
    assert page.locator('#scan-under image').count() == 0       # the one left is hidden


def viewbox(page):
    return [float(v) for v in page.get_attribute('#canvas', 'viewBox').split()]


def test_pan_and_zoom_by_mouse_and_trackpad(page, base, drawing):
    drawing()
    page.goto(base + '/')
    page.wait_for_selector('g.obj path.shape')
    box = page.locator('#canvas').bounding_box()
    page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
    v0 = viewbox(page)
    page.mouse.wheel(0, 100)                                    # a mouse wheel's notch: zoom out
    page.wait_for_timeout(100)
    v1 = viewbox(page)
    assert v1[2] > v0[2]
    page.wait_for_timeout(500)
    page.mouse.wheel(30, 12)                                    # two fingers on a trackpad: pan, same zoom
    page.wait_for_timeout(100)
    v2 = viewbox(page)
    assert v2[2] == pytest.approx(v1[2]) and v2[0] > v1[0] and v2[1] > v1[1]
    page.keyboard.down('Control')                               # a pinch: the browser sends Ctrl+wheel
    page.mouse.wheel(0, -20)
    page.keyboard.up('Control')
    page.wait_for_timeout(100)
    assert viewbox(page)[2] < v2[2]
    # The right button (a two-finger press) drags the canvas; no menu, nothing selected
    v3 = viewbox(page)
    x, y = box['x'] + box['width'] * 0.6, box['y'] + box['height'] * 0.3        # clear of the rail and the zoom buttons
    page.mouse.move(x, y)
    page.mouse.down(button='right')
    page.mouse.move(x + 80, y + 40, steps=4)
    page.mouse.up(button='right')
    v4 = viewbox(page)
    assert v4[2] == pytest.approx(v3[2]) and v4[0] < v3[0] and v4[1] < v3[1]


def test_a_scan_preview_zooms(page, scanning, tmp_path):
    a, = looks(tmp_path, 1)
    open_scan(page, scanning)
    page.click(f'#captures li[data-id="{a}"] .name')
    page.click('#viewer .grid-tiles img')
    page.wait_for_selector('#viewer .zoombox img.big')
    box = page.locator('#viewer .zoombox').bounding_box()
    page.mouse.move(box['x'] + box['width'] * 0.3, box['y'] + box['height'] * 0.4)
    page.mouse.wheel(0, -200)                                   # a mouse wheel notch the other way: zoom in
    page.wait_for_selector('#viewer .zoombox.zoomed')
    assert 'scale(' in page.get_attribute('#viewer .zoombox > img.big', 'style')
    assert '%' in page.text_content('#viewer .zoombadge')
    page.mouse.dblclick(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
    page.wait_for_selector('#viewer .zoombox:not(.zoomed)')


def test_corners_set_precisely_when_zoomed(page, scanning):
    open_scan(page, scanning)
    page.click('#camera-job [data-act="corners"]')
    page.wait_for_selector('#viewer svg[data-corner="tl"]', timeout=20000)
    cell = page.locator('#viewer .corner.zoombox').first
    b = cell.bounding_box()
    cx, cy = b['x'] + b['width'] / 2, b['y'] + b['height'] / 2
    page.mouse.move(cx, cy)
    page.keyboard.down('Control')                               # a pinch, 4x about the middle
    for _ in range(14):
        page.mouse.wheel(0, -10)
    page.keyboard.up('Control')
    k = page.evaluate('() => +getComputedStyle(document.querySelector("#viewer .corner .zin")).transform.split("(")[1].split(",")[0]')
    assert k > 3
    page.mouse.click(cx + 40, cy)                               # 40 px right of the middle, zoomed: k times less on the bed
    for _ in range(50):
        if region(scanning)[0] != 30:
            break
        time.sleep(0.1)
    cam = requests.get(scanning + '/api/camera').json()['cameras']['T0']
    import math
    t = math.radians(cam['turn'])
    fx = cam['fov'][0] * abs(math.cos(t)) + cam['fov'][1] * abs(math.sin(t))
    assert region(scanning)[0] == pytest.approx(30 + 40 / (b['width'] * k) * fx, abs=0.02)
    assert region(scanning)[3] == pytest.approx(80, abs=0.1)


def test_the_head_on_the_canvas(page, served, monkeypatch):
    url, app = served
    import plot.server as srv

    class R:
        def __init__(self, st):
            self.st = st

        def raise_for_status(self):
            pass

        def json(self):
            return {'result': {'status': self.st}}
    at = {'head': [60.0, 90.0, 9.4]}
    real = srv.requests.get

    def get(u, params=None, **kw):
        if params and 'motion_report' in params:
            return R({'motion_report': {'live_position': at['head'] + [0]}, 'toolhead': {'homed_axes': 'xyz'},
                      'gcode_move': {'homing_origin': [-2.5, -1.0, 0.2, 0]}})
        return real(u, params=params, **kw)
    monkeypatch.setattr(srv.requests, 'get', get)
    assert requests.get(url + '/api/toolhead.svg').text.count('id="toolhead"') == 1
    page.goto(url + '/')
    page.wait_for_selector('#head-layer .head-label')
    assert page.text_content('#head-layer .head-label') == 'X 62.5 Y 91 Z 9.4'        # the tip: less the tool's offset
    assert page.get_attribute('#head-layer .head-outline', 'transform') == 'translate(60 90) scale(1,-1)'
    at['head'] = [70.0, 90.0, 9.4]                                                     # it moves: it follows
    page.wait_for_function('() => document.querySelector("#head-layer .head-label").textContent.startsWith("X 72.5")')
    page.uncheck('#show-head')
    assert page.locator('#head-layer *').count() == 0


# --- the layout: panels over the canvas, windows, the LED display ------------------------
def drag(page, frm, to, steps=8):
    page.mouse.move(*frm)
    page.mouse.down()
    page.mouse.move(*to, steps=steps)
    page.mouse.up()


def test_panels_fold_float_dock_and_reset(page, base, drawing):
    drawing()
    page.goto(base + '/')
    page.evaluate('() => localStorage.removeItem("limn-plot:layout")')
    page.reload()
    page.wait_for_selector('section[data-panel="paint"] .phead')
    assert page.locator('#ruler-x').bounding_box()['width'] > 200          # the rulers sit between the panels
    # A tap on the header folds it, another unfolds it
    page.click('section[data-panel="machine"] .phead h2')
    assert 'collapsed' in page.get_attribute('section[data-panel="machine"]', 'class')
    page.click('section[data-panel="machine"] .phead h2')
    assert 'collapsed' not in page.get_attribute('section[data-panel="machine"]', 'class')
    # Out over the canvas: it floats
    h = page.locator('section[data-panel="paint"] .phead h2').bounding_box()
    drag(page, (h['x'] + 4, h['y'] + 6), (640, 300))
    assert page.locator('#floats section[data-panel="paint"]').count() == 1
    # To the left dock, and it stays there
    h = page.locator('section[data-panel="paint"] .phead h2').bounding_box()
    drag(page, (h['x'] + 4, h['y'] + 6), (60, 500))
    assert page.locator('#left section[data-panel="paint"]').count() == 1
    page.reload()
    page.wait_for_selector('#left section[data-panel="paint"]')
    # The fixed one doesn't move
    h = page.locator('section[data-panel="drawings"] .phead h2').bounding_box()
    drag(page, (h['x'] + 4, h['y'] + 6), (640, 300))
    assert page.locator('#left section[data-panel="drawings"]').count() == 1
    # Panels, shift-clicked: everything back
    page.once('dialog', lambda d: d.accept())
    page.click('#layout-button', modifiers=['Shift'])
    assert page.locator('#right section[data-panel="paint"]').count() == 1
    # Panels: all hidden, the canvas's tools move out to the edges
    left_rail = page.locator('#rail').bounding_box()['x']
    page.click('#layout-button')
    assert not page.is_visible('#right') and page.locator('#rail').bounding_box()['x'] < left_rail
    page.click('#layout-button')


def test_windows_move_and_resize(page, served, monkeypatch):
    url, app = served
    import plot.server as srv

    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {'result': {'webcams': [{'name': 'top', 'stream_url': '/webcam/?action=stream', 'snapshot_url': '/s', 'enabled': True}]}}
    real = srv.requests.get
    monkeypatch.setattr(srv.requests, 'get', lambda u, **kw: R() if 'webcams/list' in u else real(u, **kw))
    page.goto(url + '/')
    page.evaluate('() => localStorage.removeItem("limn-plot:layout")')
    page.reload()
    page.click('#cams-button')
    win = page.locator('.win[data-win="cams"]')
    page.wait_for_selector('.win[data-win="cams"] .vbar')
    b0 = win.bounding_box()
    bar = page.locator('.win[data-win="cams"] .vbar .grow').bounding_box()        # the bar, clear of its buttons
    cx, cy = bar['x'] + bar['width'] / 2, bar['y'] + bar['height'] / 2
    drag(page, (cx, cy), (cx - 200, cy - 100))
    b1 = win.bounding_box()
    assert b1['x'] == pytest.approx(b0['x'] - 200, abs=3) and b1['y'] == pytest.approx(b0['y'] - 100, abs=3)
    drag(page, (b1['x'] + b1['width'] - 6, b1['y'] + b1['height'] - 6), (b1['x'] + b1['width'] + 94, b1['y'] + b1['height'] + 44))
    b2 = win.bounding_box()
    assert b2['width'] == pytest.approx(b1['width'] + 100, abs=3) and b2['height'] == pytest.approx(b1['height'] + 50, abs=3)
    assert page.evaluate('() => JSON.parse(localStorage.getItem("limn-plot:layout")).windows.cams.w') == pytest.approx(b2['width'], abs=1)


def test_the_led_display_shows_klipper(page, served, monkeypatch):
    url, app = served
    import plot.server as srv
    ui = [[0, 0, 0]] * 32
    ui = [[0.5, 0.3, 0] if i in (0, 1, 8, 9) else [0, 0.4, 0] if i == 26 else [0, 0, 0] for i in range(32)]

    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {'result': {'status': {'neopixel picam': {'color_data': [c + [0] for c in ui]},
                                          'neopixel indockator': {'color_data': [[0, 0.3, 0.1]] * 30},
                                          'limn': {'leds': {'ui_alert': 'warn', 'ui_tool_43': 'carried', 'ui_tag': 'listening'}}}}}
    real = srv.requests.get
    monkeypatch.setattr(srv.requests, 'get', lambda u, params=None, **kw: R() if params and 'neopixel picam' in params else real(u, params=params, **kw))
    page.goto(url + '/')
    page.wait_for_selector('#leds .ledmatrix rect.led.lit')
    assert page.locator('#leds .ledmatrix rect.led.lit').count() == 5
    assert page.locator('#leds .dockstrip rect.led.lit').count() == 30
    legend = page.text_content('#leds .ledlegend')
    assert 'a tool is unaccounted for' in legend and 'T2 carried' in legend and 'listening' in legend


def test_two_fingers_pinch_the_canvas(page, base, drawing):
    drawing()
    page.goto(base + '/')
    page.wait_for_selector('g.obj path.shape')
    v0 = viewbox(page)
    # Two touch pointers 100 px apart, then 200: zoomed in twice; their middle moved 30 px right: panned
    page.evaluate('''() => {
        const svg = document.querySelector('#canvas'), r = svg.getBoundingClientRect();
        const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
        const ev = (type, id, x, y) => svg.dispatchEvent(new PointerEvent(type, { pointerId: id, pointerType: 'touch', clientX: x, clientY: y,
            bubbles: true, cancelable: true, isPrimary: id === 1, button: 0, buttons: 1 }));
        ev('pointerdown', 1, cx - 50, cy); ev('pointerdown', 2, cx + 50, cy);
        ev('pointermove', 1, cx - 100 + 30, cy); ev('pointermove', 2, cx + 100 + 30, cy);
        ev('pointerup', 1, cx - 70, cy); ev('pointerup', 2, cx + 130, cy);
    }''')
    v1 = viewbox(page)
    assert v1[2] == pytest.approx(v0[2] / 2, rel=0.02)
    assert requests.get(base + '/api/state').json()['job']['objects'][0]['placement'] == \
        page.evaluate('() => S.job.objects[0].placement')                    # nothing was moved by the fingers
