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
    '''n focus captures in the capture store, one shot each (not looks: the next capture deletes a look).'''
    from limn_cam.scan import ScanStore, capture_root
    from limn_cam.tests.test_scan import jpeg, pattern
    store = ScanStore(capture_root(tmp_path))
    ids = []
    for i in range(n):
        sid = store.new({'kind': 'focus', 'fov': [16, 9], 'turn': 0})
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
    page.click('section[data-panel="output"] .phead h2')
    assert 'collapsed' in page.get_attribute('section[data-panel="output"]', 'class')
    page.click('section[data-panel="output"] .phead h2')
    assert 'collapsed' not in page.get_attribute('section[data-panel="output"]', 'class')
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
    page.click('#layout-button', modifiers=['Shift'])            # twice(): armed (yellow) ..
    page.click('#layout-button', modifiers=['Shift'])            # .. and done
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


# --- 2026-10-02: a phone, the drawings' order, masks, keys, how every tool draws, macros ----
def objects(base):
    return requests.get(base + '/api/state').json()['job']['objects']


def place_three(base, drawing):
    drawing(THIN, 'a.svg')
    for n in 'bc':
        requests.post(base + '/api/objects', files={'file': (f'{n}.svg', THIN.encode(), 'image/svg+xml')})
    return [o['id'] for o in objects(base)]


def test_a_phone_scrolls_the_panels_under_the_canvas(page, base, drawing):
    drawing()
    page.set_viewport_size({'width': 390, 'height': 844})
    page.goto(base + '/')
    page.wait_for_selector('section[data-panel="paint"] .phead')
    stage, drawings = page.locator('#stage').bounding_box(), page.locator('section[data-panel="drawings"]').bounding_box()
    assert stage['y'] < drawings['y'] and drawings['y'] >= stage['y'] + stage['height'] - 1     # under the canvas
    assert drawings['width'] > 340                                                         # the page's width
    assert page.evaluate('document.scrollingElement.scrollHeight') > 2 * 844                 # it scrolls
    assert page.locator('#floats section').count() == 0
    # The printer's panel is reached by scrolling the page; a tap on its header folds it
    page.locator('section[data-panel="printer"] .phead h2').scroll_into_view_if_needed()
    assert page.evaluate('scrollY') > 0
    page.click('section[data-panel="printer"] .phead h2')
    assert 'collapsed' in page.get_attribute('section[data-panel="printer"]', 'class')
    # A wide screen again: the panels float over the canvas
    page.set_viewport_size({'width': 1280, 'height': 720})
    page.wait_for_function('() => getComputedStyle(document.querySelector("#right")).position === "fixed"')


def test_order_drawings_from_the_list_and_keys(page, base, drawing):
    a, b, c = place_three(base, drawing)
    page.goto(base + '/')
    page.wait_for_selector(f'#objects li[data-id="{c}"]')
    assert page.eval_on_selector_all('#objects li[data-id]', 'ls => ls.map(l => l.dataset.id)') == [c, b, a]   # top first
    page.click(f'#objects li[data-id="{a}"] .name')
    with page.expect_response(lambda r: '/order' in r.url):
        page.click(f'#objects li[data-id="{a}"] [data-order="front"]')
    assert [o['id'] for o in objects(base)] == [b, c, a]
    page.wait_for_function(f'() => [...document.querySelectorAll("#design-layer g.obj")].pop().dataset.id === "{a}"')
    page.mouse.click(5, 400)                                    # off the panels: keys go to the canvas
    page.click(f'#objects li[data-id="{a}"] .name')
    with page.expect_response(lambda r: '/order' in r.url):
        page.keyboard.press('BracketLeft')
    assert [o['id'] for o in objects(base)] == [b, a, c]
    with page.expect_response(lambda r: '/order' in r.url):
        page.keyboard.press('Shift+BracketLeft')
    assert [o['id'] for o in objects(base)] == [a, b, c]
    # Tab: the next in the list; 1 2 3: the views; ?: the shortcuts
    page.keyboard.press('Tab')
    assert page.get_attribute('#objects li.on', 'data-id') == c
    page.keyboard.press('3')
    assert 'on' in page.get_attribute('#views [data-view="paths"]', 'class')
    page.keyboard.press('1')
    assert 'on' in page.get_attribute('#views [data-view="original"]', 'class')
    page.keyboard.press('2')
    page.keyboard.press('Shift+Slash')
    assert page.is_visible('#keys-help') and 'Bring forward'.lower() in page.text_content('#keys-help').lower()
    page.keyboard.press('Escape')
    assert not page.is_visible('#keys-help')
    page.keyboard.press('Shift+Digit4')
    assert 'on' in page.get_attribute('#palette [data-to="T4"]', 'class')
    page.keyboard.press('Escape')


def test_mask_a_region_with_the_mask_tool(page, base, drawing):
    oid = drawing(THIN)
    page.goto(base + '/')
    page.wait_for_selector('g.obj path.shape')
    page.click(f'#objects li[data-id="{oid}"] .name')
    page.keyboard.press('m')
    assert 'on' in page.get_attribute('#rail [data-mode="mask"]', 'class')
    # Over the middle of both lines: they are cut there
    p0, p1 = screen_point(page, 0, 0.4, (0, -40)), screen_point(page, 1, 0.6, (0, 40))
    with page.expect_response(lambda r: f'/api/objects/{oid}' in r.url and r.request.method == 'PATCH'):
        drag(page, p0, p1)
    masks = objects(base)[0]['masks']
    assert len(masks) == 1 and len(masks[0]) == 4
    page.wait_for_selector('g.obj path.objmask')
    page.wait_for_function('() => !document.querySelector("#paths-layer").classList.contains("stale")')
    gcode = requests.get(base + '/api/gcode?inline=1').text
    assert gcode.count('\nG1 X') >= 4                                    # 2 lines, each in 2 pieces
    # Click the region, Del: drawn there again
    box = page.locator('g.obj path.objmask').bounding_box()
    page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
    with page.expect_response(lambda r: r.request.method == 'PATCH'):
        page.keyboard.press('Delete')
    assert objects(base)[0]['masks'] == []
    page.keyboard.press('Escape')


def test_how_every_tool_draws(page, base, drawing):
    drawing()
    page.goto(base + '/')
    page.click('section[data-panel="drawset"] .phead h2')
    page.wait_for_selector('#drawset [data-dk="bleed"]')
    page.fill('#drawset [data-dk="bleed"]', '0.3')
    with page.expect_response(lambda r: '/api/job' in r.url):
        page.press('#drawset [data-dk="bleed"]', 'Enter')
        page.locator('#drawset [data-dk="bleed"]').blur()
    st = requests.get(base + '/api/state').json()
    assert st['job']['draw'] == {'bleed': 0.3} and st['tools']['T1']['bleed'] == 0.3
    with page.expect_response(lambda r: '/api/job' in r.url):
        page.select_option('#drawset [data-dk="small"]', 'warn')
    assert requests.get(base + '/api/state').json()['job']['draw'] == {'bleed': 0.3, 'small': 'warn'}
    page.click('#drawset [data-act="reset-draw"]')
    page.wait_for_function('() => !document.querySelector("#drawset [data-act=reset-draw]")')
    assert requests.get(base + '/api/state').json()['job']['draw'] == {}


def test_colour_buttons_are_round(page, base, drawing):
    drawing()
    page.goto(base + '/')
    page.wait_for_selector('#palette .swatch')
    for sel in ('#palette .swatch', '#tools .sws input[type=color]'):
        b = page.locator(sel).first.bounding_box()
        assert abs(b['width'] - b['height']) < 1, sel
    page.select_option('#tools .tool select[data-d="pen"]', index=1)
    b = page.locator('#tools .sws .sw').first.bounding_box()
    assert abs(b['width'] - b['height']) < 1 and b['width'] >= 24


def test_macro_buttons_run_on_klipper(page, served, monkeypatch):
    url, app = served
    import plot.server as srv
    sent = []

    class R:
        status_code = 200

        def __init__(self, result):
            self.result = result

        def raise_for_status(self):
            pass

        def json(self):
            return {'result': self.result}

    def get(u, **kw):
        if u.endswith('/printer/gcode/help'):
            return R({'G28': 'Home', 'LAZY_HOME': '', 'T0': '', 'T1': '', 'UNDOCK': '', 'BED_MESH_CLEAR': ''})
        if 'objects/query' in u:
            return R({'status': {'print_stats': {'state': 'standby'}}})
        raise requests.ConnectionError('no')
    monkeypatch.setattr(srv.requests, 'get', get)
    monkeypatch.setattr(srv.requests, 'post', lambda u, json=None, **kw: sent.append(json['script']) or R({}))
    app.state.ws.gcode_help = None
    try:
        page.goto(url + '/')
        page.wait_for_selector('#macros button[data-gcode="G28"]')
        assert page.locator('#macros button[data-gcode="LIMN_CALIBRATE_ALL"]').count() == 0     # Klipper hasn't it
        assert page.locator('#macros button[data-gcode="T0"] .swatch').count() == 1
        page.click('#macros button[data-gcode="G28"]')
        assert page.locator('#macros button[data-gcode="G28"].armed').count() == 1 and not sent    # armed, not sent
        page.click('#macros button[data-gcode="G28"]')
        page.wait_for_function('() => document.querySelector("#toast").textContent.includes("G28 sent")')
        for _ in range(50):
            if sent:
                break
            time.sleep(0.05)
        assert sent == ['G28']
        # One without a question
        page.click('#macros button[data-gcode="BED_MESH_CLEAR"]')
        for _ in range(50):
            if len(sent) > 1:
                break
            time.sleep(0.05)
        assert sent[-1] == 'BED_MESH_CLEAR'
    finally:
        app.state.ws.gcode_help = None
        app.state.ws.printer_job = None


def test_where_fluidd_is_for_the_cameras(page, served, monkeypatch):
    url, app = served
    import plot.server as srv

    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {'result': {'webcams': [{'name': 'top', 'stream_url': '/webcam4/?action=stream', 'enabled': True}]}}
    real = srv.requests.get
    monkeypatch.setattr(srv.requests, 'get', lambda u, **kw: R() if 'webcams/list' in u else real(u, **kw))
    try:
        page.goto(url + '/')
        page.wait_for_selector('#printer-url-in')
        page.fill('#printer-url-in', 'https://limn.example')
        page.click('#printer-url [data-act="save-url"]')
        page.wait_for_function('() => document.querySelector("#fluidd-link").href.startsWith("https://limn.example")')
        page.click('#cams-button')
        page.wait_for_selector('#cams [data-cam="top"]')
        assert page.get_attribute('#cams a.button:has-text("open")', 'href') == 'https://limn.example/webcam4/?action=stream'
    finally:
        requests.put(url + '/api/settings', json={'printer_url': ''})


def test_clear_all_takes_two_presses(page, base, drawing):
    drawing()
    page.goto(base + '/')
    page.wait_for_selector('#objects li[data-id]')
    page.click('#clear-objects')
    assert page.locator('#clear-objects.armed').count() == 1                  # yellow: nothing done yet
    assert page.inner_text('#clear-objects') == 'Press again'
    assert len(requests.get(base + '/api/state').json()['job']['objects']) == 1
    page.click('#clear-objects')
    page.wait_for_function('() => !document.querySelector("#objects li[data-id]")')
    assert requests.get(base + '/api/state').json()['job']['objects'] == []
    # one press, then too late: it disarms
    drawing()
    page.reload()
    page.wait_for_selector('#objects li[data-id]')
    page.click('#clear-objects')
    time.sleep(4.2)
    assert page.locator('#clear-objects.armed').count() == 0
    assert page.inner_text('#clear-objects') == 'Clear all'                    # its label back
    page.click('#clear-objects')
    assert len(requests.get(base + '/api/state').json()['job']['objects']) == 1    # armed again, not cleared


def test_captures_hide_all_and_delete_all(page, scanning, tmp_path):
    looks(tmp_path)
    open_scan(page, scanning)
    page.wait_for_function('() => document.querySelectorAll("#scan-layer image.shot").length === 2')
    page.click('#captures-eye')
    page.wait_for_function('() => document.querySelectorAll("#scan-layer image.shot").length === 0')
    assert page.text_content('#captures-eye') == 'Show all'
    page.click('#captures-eye')
    page.wait_for_function('() => document.querySelectorAll("#scan-layer image.shot").length === 2')
    page.click('#captures-clear')                               # twice: it asks first
    page.click('#captures-clear')
    page.wait_for_function('() => !document.querySelector("#captures li[data-id]")')
    assert requests.get(scanning + '/api/captures').json() == []


def test_an_svg_with_a_picture_asks_what_to_do_with_it(page, base, tmp_path):
    from .test_layers import gradient_svg
    p = tmp_path / 'pic.svg'
    p.write_text(gradient_svg())
    page.goto(base + '/')
    page.wait_for_selector('#svg-input', state='attached')
    page.set_input_files('#svg-input', str(p))
    page.click('#image-ask [data-raster="lines"]')
    page.wait_for_selector('#object-panel #r-pitch')
    o = next(o for o in requests.get(base + '/api/state').json()['job']['objects'] if o['id'].startswith('pic'))
    assert o['raster']['mode'] == 'lines'
    page.select_option('#r-mode', 'skip')                       # left out after all
    page.wait_for_selector('#object-panel #r-pitch', state='detached')
