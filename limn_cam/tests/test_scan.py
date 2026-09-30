# Scanning with the camera tool: tiles, focus by height, the store, the jobs, the app
import io
import json
import time

import numpy as np
import pytest
from PIL import Image, ImageFilter

from limn_cam import scan as sc


def pattern(seed=1, size=(320, 180)):
    rng = np.random.default_rng(seed)
    a = (rng.random((size[1] // 8, size[0] // 8)) > 0.5).astype(np.uint8) * 255
    return Image.fromarray(a).resize(size, Image.NEAREST)


def jpeg(im):
    buf = io.BytesIO()
    im.convert('RGB').save(buf, 'JPEG', quality=92)
    return buf.getvalue()


def test_sharpness_prefers_the_focused_shot():
    sharp = pattern()
    blurred = sharp.filter(ImageFilter.GaussianBlur(3))
    assert sc.sharpness(jpeg(sharp)) > 3 * sc.sharpness(jpeg(blurred))


def test_tiles_cover_the_region_and_snake():
    t = sc.tiles((10, 20, 50, 40), (16, 9), overlap=0.2)
    xs = sorted({x for _, _, x, _ in t})
    ys = sorted({y for _, _, _, y in t})
    assert xs[0] - 8 <= 10 and xs[-1] + 8 >= 50 and ys[0] - 4.5 <= 20 and ys[-1] + 4.5 >= 40
    assert all(b - a <= 16 * 0.8 + 1e-6 for a, b in zip(xs, xs[1:]))          # overlap kept
    rows = [[x for r, _, x, _ in t if r == k] for k in range(len(ys))]
    assert rows[0] == sorted(rows[0]) and rows[1] == sorted(rows[1], reverse=True)   # snaking
    assert sc.tiles((10, 20, 12, 21), (16, 9)) == [(0, 0, 11.0, 20.5)]              # smaller than a shot
    assert sc.footprint((16, 9), 90) == pytest.approx((9, 16))


class FakeMoonraker:
    '''Klipper with the camera tool: shots are sharpest at z 5.'''

    def __init__(self, holder=41):
        self.z, self.x, self.y = 7.0, 0.0, 0.0
        self.scripts = []
        self.carried = 0
        self.holder = holder
        self.zs = []

    def gcode(self, script, timeout=120):
        self.scripts.append(script)
        for line in script.splitlines():
            w = line.split()
            if w and w[0] == 'G1':
                for v in w[1:]:
                    if v[0] in 'XYZ':
                        setattr(self, v[0].lower(), float(v[1:]))
                self.zs.append(self.z)
            if w and w[0] == 'T0':
                self.carried = self.holder

    def query(self, **objects):
        out = {}
        if 'save_variables' in objects:
            out['save_variables'] = {'variables': {'currently_docked_tool': self.carried}}
        if 'gcode_move' in objects:
            out['gcode_move'] = {'homing_origin': [0, 0, 0.5, 0]}
        if 'bed_mesh' in objects:
            out['bed_mesh'] = {'profile_name': 'lrt_paper'}
        if 'print_stats' in objects:
            out['print_stats'] = {'state': 'standby'}
        return out

    def sideways_low(self, clear):
        '''G1 moves along X/Y made under clear_z.'''
        z, low = None, []
        for script in self.scripts:
            for line in script.splitlines():
                w = line.split()
                if not w or w[0] != 'G1':
                    continue
                vals = {v[0]: float(v[1:]) for v in w[1:] if v[0] in 'XYZ'}
                z = vals.get('Z', z)
                if ('X' in vals or 'Y' in vals) and (z is None or z < clear - 1e-9):
                    low.append(line)
        return low

    def snapshot(self, camera):
        return jpeg(pattern().filter(ImageFilter.GaussianBlur(abs(self.z - 5.0) * 4 + 0.01)))


def camera():
    from plot.tools import REGISTRY
    return REGISTRY['camera'](id='T0', name='Camera U20', webcam='tethered_camera_tool', fov=(16, 9),
                              focus_z=5.0, holder=41, settle=0.0)


def machine():
    from plot.profile import load_machine
    return load_machine(overrides={'bed_id': 'BED_5'})


def run(job, fn, *args):
    job.start(lambda: getattr(job, fn)(*args))
    for _ in range(500):
        if job.state['done']:
            return job.state
        time.sleep(0.01)
    raise TimeoutError


def test_focus_sweep_finds_the_sharp_z(tmp_path):
    mr, store = FakeMoonraker(), sc.ScanStore(tmp_path)
    job = sc.Job('focus', mr, camera(), machine(), store, sc.Settings(sweep=(3.0, 7.0, 0.5)))
    st = run(job, 'focus', 40, 90)
    assert st['error'] is None and st['result']['z'] == pytest.approx(5.0)
    assert 'T0' in mr.scripts[0] and '_CLEAR_OFFSETS\n' in mr.scripts[0] and 'MESH' not in mr.scripts[0]
    assert mr.sideways_low(7.5) == [] and mr.z == pytest.approx(7.5)            # sideways only up high; left there
    assert min(mr.zs) >= 4.0 - 1e-9                                               # never under z_min
    assert max(mr.zs) <= camera().Z_TOP + 1e-9                                   # its own limits, not the plot's
    curve = st['result']['curve']
    assert [z for z, _ in curve] == sorted([z for z, _ in curve], reverse=True)  # from above: the play
    assert store.meta(st['scan'])['kind'] == 'focus' and store.list()[0]['count'] == 1


def test_scan_takes_every_tile_and_stops_on_request(tmp_path):
    mr, store = FakeMoonraker(), sc.ScanStore(tmp_path)
    settings = sc.Settings(region=(20, 60, 60, 80), overlap=0.2)
    job = sc.Job('scan', mr, camera(), machine(), store, settings)
    st = run(job, 'scan')
    plan = sc.tiles(settings.region, (16, 9), 0.2)
    assert st['error'] is None and st['i'] == st['n'] == len(plan)
    meta = store.meta(st['scan'])
    assert [(t['x'], t['y']) for t in meta['tiles']] == [(x, y) for _, _, x, y in plan] and meta['done']
    assert mr.sideways_low(7.5) == []                                             # lifted between tiles
    mosaic = Image.open(store.mosaic(st['scan'], px_per_mm=4))
    assert abs(mosaic.size[0] - (40 + 0) * 4) <= 8 * 4 and mosaic.size[1] > 0
    assert Image.open(store.thumb(st['scan'], meta['tiles'][0]['file'], 100)).size[0] == 100
    # Stopped: it ends between shots, with an error saying so
    job = sc.Job('scan', mr, camera(), machine(), store, settings)
    job.stop()
    st = run(job, 'scan')
    assert st['error'] == 'stopped' and st['i'] == 0


def test_stay_low_between_tiles(tmp_path):
    mr, store = FakeMoonraker(), sc.ScanStore(tmp_path)
    settings = sc.Settings(region=(20, 60, 60, 80), low=True)
    st = run(sc.Job('scan', mr, camera(), machine(), store, settings), 'scan')
    assert st['error'] is None and len(mr.sideways_low(7.5)) == st['n'] - 1      # only the first came from above


def test_refocus_at_each_tile(tmp_path):
    mr, store = FakeMoonraker(), sc.ScanStore(tmp_path)
    settings = sc.Settings(region=(20, 60, 30, 65), refocus=0.4, refocus_step=0.2, z=5.2)
    st = run(sc.Job('scan', mr, camera(), machine(), store, settings), 'scan')
    assert all(t['z'] == pytest.approx(5.0) for t in store.meta(st['scan'])['tiles'])


def test_store_keeps_the_newest(tmp_path):
    store = sc.ScanStore(tmp_path, keep=2)
    ids = []
    for i in range(3):
        ids.append(store.new({'kind': 'look'}))
    assert len(store.list()) == 2
    store.delete(store.list()[0]['id'])
    assert len(store.list()) == 1
    with pytest.raises(KeyError):
        store.dir('../etc')


def test_the_app_scans_with_the_camera_tool(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from plot import server
    import limn_cam.moonraker as mrmod
    fake = FakeMoonraker()
    monkeypatch.setattr(mrmod, 'Moonraker', lambda url: fake)
    client = TestClient(server.create_app(tmp_path / 'ws'))
    ws = client.app.state.ws
    ws.tags = {'41': {'pen': 'cam-u20', 'name': 'Camera U20', 'dx': 0, 'dy': 0, 'dz': 0.5}}
    st = client.get('/api/state').json()
    assert st['tools']['T0']['kind'] == 'camera' and st['tools']['T0']['draws'] is False
    cam = client.get('/api/camera').json()
    assert list(cam['cameras']) == ['T0'] and cam['cameras']['T0']['webcam'] == 'tethered_camera_tool'
    assert client.post('/api/camera/scan').status_code == 400                   # no region yet
    r = client.patch('/api/camera', json={'tool': 'T0', 'region': [60, 80, 20, 60], 'z': 5.0, 'settle': 0})
    assert r.json()['settings']['region'] == [20, 60, 60, 80]                    # put in order
    assert client.post('/api/camera/look', json={'x': 150, 'y': 90, 'z': 5}).status_code == 400   # the holders
    assert client.post('/api/camera/scan').status_code == 200
    for _ in range(500):
        job = client.get('/api/camera').json()['job']
        if job['done']:
            break
        time.sleep(0.01)
    assert job['error'] is None and job['i'] == job['n'] > 1
    sid = job['scan']
    meta = client.get(f'/api/captures/{sid}').json()
    first = meta['tiles'][0]['file']
    assert client.get(f'/api/captures/{sid}/file/{first}').headers['content-type'] == 'image/jpeg'
    assert client.get(f'/api/captures/{sid}/thumb/{first}').status_code == 200
    assert client.get(f'/api/captures/{sid}/mosaic').status_code == 200
    assert client.get(f'/api/captures/{sid}/zip').content[:2] == b'PK'
    assert client.delete(f'/api/captures/{sid}').json() == []
    assert client.get('/api/captures/nope').status_code == 404


def test_webcam_urls_go_to_the_web_server(monkeypatch):
    from limn_cam.moonraker import Moonraker
    monkeypatch.delenv('LIMN_WEBCAM_BASE', raising=False)
    assert Moonraker('http://127.0.0.1:7125').webcam_base() == 'http://127.0.0.1'   # on the Pi: nginx, not 7125
    assert Moonraker('https://limn.nb.malow.im').webcam_base() == 'https://limn.nb.malow.im'
    monkeypatch.setenv('LIMN_WEBCAM_BASE', 'http://pi:8080/')
    assert Moonraker('http://127.0.0.1:7125').webcam_base() == 'http://pi:8080'


def test_shift_and_calibrate():
    base = np.asarray(pattern(3, (960, 540)).filter(ImageFilter.GaussianBlur(1)))
    moved = np.roll(np.roll(base, -60, axis=1), 24, axis=0)          # the scene 60px left, 24px down
    dx, dy = sc.shift(jpeg(Image.fromarray(base)), jpeg(Image.fromarray(moved)))
    assert abs(dx + 60) < 2 and abs(dy - 24) < 2
    # A camera looking down, image x along +X and up along +Y, 100 px/mm: a 2mm move in X
    # moves the scene 200px left, in Y 200px down (the image's y runs down)
    cal = sc.calibrate((1920, 1080), (-200, 0), (0, 200), 2)
    assert cal['px_per_mm'] == 100 and cal['fov'] == (19.2, 10.8) and cal['turn'] == 0 and not cal['mirrored']
    assert sc.calibrate((1920, 1080), (0, -200), (200, 0), 2)['turn'] == 90
