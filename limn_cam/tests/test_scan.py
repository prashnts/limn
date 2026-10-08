# Scanning with the camera tool: tiles, focus by height, the store, the jobs, the app
import math
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
        ids.append(store.new({'kind': 'scan'}))
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


def test_a_drawn_cross_and_the_camera_offset():
    from PIL import ImageDraw
    im = Image.new('L', (960, 540), 235)
    d = ImageDraw.Draw(im)
    d.line([(600, 180), (720, 180)], fill=40, width=5)            # a + at (660, 180)
    d.line([(660, 120), (660, 240)], fill=40, width=5)
    u, v = sc.cross_centre(jpeg(im.filter(ImageFilter.GaussianBlur(1))))
    assert abs(u - 660) < 3 and abs(v - 180) < 3
    assert sc.cross_centre(jpeg(Image.new('L', (960, 540), 235))) is None
    # turn 0: image x is +X, image y down is -Y; turn 180: the other way round
    assert sc.px_to_mm(100, 50, 100, 0) == pytest.approx((1.0, -0.5))
    assert sc.px_to_mm(100, 50, 100, 180) == pytest.approx((-1.0, 0.5))


def test_the_camera_offset_is_taken_off_when_it_moves(tmp_path):
    mr, store = FakeMoonraker(), sc.ScanStore(tmp_path)
    cam = camera().model_copy(update={'center': (2.0, -1.0)})
    job = sc.Job('look', mr, cam, machine(), store, sc.Settings())
    st = run(job, 'look', 40, 90, 7.5)
    assert st['error'] is None and (mr.x, mr.y) == (38.0, 91.0)
    assert store.meta(st['scan'])['tiles'][0]['x'] == 40


def test_store_stays_under_its_size(tmp_path):
    store = sc.ScanStore(tmp_path, max_mb=1)
    for i in range(4):
        sid = store.new({'kind': 'scan'})
        store.add(sid, 't.jpg', b'x' * 400_000, {})
    assert len(store.list()) == 3           # the oldest went: 4 x 0.4 MB > 1 MB, but the newest always stays
    assert store.size() < 1.3e6


def test_captures_in_ram_where_there_is_some(tmp_path, monkeypatch):
    monkeypatch.delenv('LIMN_CAPTURES')
    root = sc.capture_root(tmp_path)
    assert root == (sc.Path('/dev/shm/limn-captures') if sc.Path('/dev/shm').is_dir() else tmp_path / 'captures')


def test_corners_are_shot_on_the_region_corners(tmp_path):
    mr, store = FakeMoonraker(), sc.ScanStore(tmp_path)
    st = run(sc.Job('checking the corners', mr, camera(), machine(), store, sc.Settings(region=(20, 60, 56, 84))), 'corners')
    assert st['error'] is None and st['i'] == st['n'] == 4
    meta = store.meta(st['scan'])
    assert meta['kind'] == 'corners'
    assert [(t['corner'], t['x'], t['y']) for t in meta['tiles']] == [('tl', 20, 84), ('tr', 56, 84), ('br', 56, 60), ('bl', 20, 60)]
    assert all(t['z'] == pytest.approx(5.0) for t in meta['tiles'])


def fixed_camera():
    from plot.tools import REGISTRY
    return REGISTRY['camera'](id='endoscope', name='Endoscope', webcam='http://laptop:4240/snapshot.jpg?flip=1',
                              fov=(35.5, 35.1), turn=44.6, settle=0.0, fixed=True)


def test_a_fixed_camera_moves_z_only_over_the_paper(tmp_path):
    '''The endoscope: on the carriage for good, no tool picked up. No z asked: Z never moved. A z: only over the
    paper (draw_area), lifted to clear_z before leaving it; never down elsewhere.'''
    m = machine()
    px0, py0, px1, py1 = m.draw_area
    mr, store = FakeMoonraker(), sc.ScanStore(tmp_path)
    st = run(sc.Job('scan', mr, fixed_camera(), m, store, sc.Settings(region=(20, 60, 80, 100), refocus=0.4)), 'scan')
    assert st['error'] is None and st['i'] == st['n'] > 1
    lines = [l for s in mr.scripts for l in s.splitlines()]
    assert not any('Z' in l for l in lines if l.startswith('G1')) and not any(l.startswith('T0') for l in lines)
    assert all(t['z'] is None and t['curve'] is None for t in store.meta(st['scan'])['tiles'])
    # with a z, across the paper's edge: down only over it
    mr = FakeMoonraker()
    region = (px1 - 30, py0 + 10, px1 + 30, py0 + 40)
    st = run(sc.Job('scan', mr, fixed_camera(), m, store, sc.Settings(region=region, z=6.0)), 'scan')
    assert st['error'] is None
    tiles = store.meta(st['scan'])['tiles']
    assert all((t['z'] is not None) == (px0 <= t['x'] <= px1 and py0 <= t['y'] <= py1) for t in tiles)
    assert any(t['z'] is None for t in tiles) and any(t['z'] == 6.0 for t in tiles)
    z, low = None, []
    for l in (l for s in mr.scripts for l in s.splitlines() if l.startswith('G1')):
        vals = {v[0]: float(v[1:]) for v in l.split()[1:] if v[0] in 'XYZ'}
        z = vals.get('Z', z)
        if 'X' in vals and z is not None and z < 7.5 and not (px0 <= vals['X'] <= px1 and py0 <= vals['Y'] <= py1):
            low.append(l)
    assert low == []                                                            # never low off the paper
    st = run(sc.Job('focus', mr, fixed_camera(), m, store, sc.Settings()), 'focus', px1 + 20, py0 + 10)
    assert 'only over the paper' in st['error']


def test_the_app_has_the_endoscope_once_its_url_is_set(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from plot import server
    import limn_cam.moonraker as mrmod
    fake = FakeMoonraker()
    monkeypatch.setattr(mrmod, 'Moonraker', lambda url: fake)
    client = TestClient(server.create_app(tmp_path / 'ws'))
    assert 'endoscope' not in client.get('/api/camera').json()['cameras']
    assert client.put('/api/settings', json={'endoscope_url': 'not a url'}).status_code == 400
    client.put('/api/settings', json={'endoscope_url': 'http://laptop:4240/snapshot.jpg?flip=1'})
    w = client.get('/api/webcams').json()['webcams']
    assert {'name': 'endoscope', 'snapshot_url': 'http://laptop:4240/snapshot.jpg?flip=1',
            'stream_url': 'http://laptop:4240/stream.mjpg?flip=1'}.items() <= next(c for c in w if c['name'] == 'endoscope').items()
    cam = client.get('/api/camera').json()['cameras']['endoscope']
    assert cam['fixed'] and cam['webcam'] == 'http://laptop:4240/snapshot.jpg?flip=1' and cam['fov'] == [35.5, 35.1]
    client.patch('/api/camera', json={'tool': 'endoscope', 'region': [20, 60, 60, 90], 'settle': 0})
    assert client.post('/api/camera/scan').status_code == 200                   # no holder needed
    for _ in range(500):
        job = client.get('/api/camera').json()['job']
        if job['done']:
            break
        time.sleep(0.01)
    assert job['error'] is None and job['i'] == job['n'] > 0


def test_coverage_is_inside_the_turned_shot():
    '''A turned shot's tiles leave no gaps: its footprint is the largest upright rectangle inside it.'''
    assert sc.coverage((16, 9), 0) == (16, 9) and sc.coverage((16, 9), 90) == (9, 16)
    w, h = sc.coverage((35.5, 35.5), 45)
    assert w == pytest.approx(35.5 / 2 ** 0.5) and h == pytest.approx(35.5 / 2 ** 0.5)
    for turn in (10, 30, 44.6, 60, -179.2):
        fx, fy = sc.coverage((16, 9), turn)
        c, s = math.cos(math.radians(turn)), math.sin(math.radians(turn))
        for cx, cy in ((fx / 2, fy / 2), (-fx / 2, fy / 2)):        # its corners lie within the turned shot
            u, v = cx * c + cy * s, -cx * s + cy * c
            assert abs(u) <= 8 + 1e-6 and abs(v) <= 4.5 + 1e-6


def test_a_look_is_gone_at_the_next_capture(tmp_path):
    from limn_cam.scan import ScanStore
    store = ScanStore(tmp_path)
    store.new({'kind': 'look'})
    scan = store.new({'kind': 'scan'})
    assert [c['id'] for c in store.list()] == [scan]
    store.new({'kind': 'look'})
    store.new({'kind': 'focus'})
    assert sorted(c['kind'] for c in store.list()) == ['focus', 'scan']


class Optics(FakeMoonraker):
    '''A camera docked by hand whose shots are made: the bed (paper with a little texture, the cross of
    MARK_SVG at `mark`) seen `ppm` px a mm, turned `turn`, its middle `center` mm from the tool point,
    sharpest at z 6.'''

    def __init__(self, mark, ppm=40.0, turn=30.0, center=(1.5, -1.0), size=(480, 360)):
        super().__init__()
        self.mark, self.ppm, self.turn, self.center, self.size = mark, ppm, turn, center, size
        rng = np.random.default_rng(7)
        self.res, self.span = 0.05, 40.0                # the bed around the mark, mm a cell, mm across
        n = int(self.span / self.res)
        g = (np.arange(n) * self.res - self.span / 2)
        X, Y = np.meshgrid(g, g)
        bed = 225 + 20 * np.kron(rng.random((n // 4, n // 4)), np.ones((4, 4)))[:n, :n]     # paper: 0.2 mm grain
        bed[(np.abs(Y) < 0.2) & (np.abs(X) < 5)] = 30
        bed[(np.abs(X) < 0.2) & (np.abs(Y) < 5)] = 30
        self.bed = bed

    def snapshot(self, camera):
        w, h = self.size
        U, V = np.meshgrid(np.arange(w) - w / 2, np.arange(h) - h / 2)
        t = math.radians(self.turn)
        wx = (U * math.cos(t) + V * math.sin(t)) / self.ppm         # sc.px_to_mm, for the whole picture
        wy = (U * math.sin(t) - V * math.cos(t)) / self.ppm
        bx = self.x + self.center[0] + wx - self.mark[0] + self.span / 2
        by = self.y + self.center[1] + wy - self.mark[1] + self.span / 2
        i = np.clip((by / self.res).astype(int), 0, self.bed.shape[0] - 1)
        j = np.clip((bx / self.res).astype(int), 0, self.bed.shape[1] - 1)
        im = Image.fromarray(self.bed[i, j].astype(np.uint8))
        return jpeg(im.filter(ImageFilter.GaussianBlur(abs(self.z - 6.0) * 4 + 0.3)))


def manual_camera(**kw):
    from plot.tools import REGISTRY
    return REGISTRY['camera'](**{'id': 'manual', 'name': 'Pi camera', 'webcam': 'http://picam:4250/capture.jpg',
                                 'pen': 'picam', 'settle': 0.0, 'fixed': True, **kw})


def test_calibrating_a_camera_docked_by_hand_on_the_cross(tmp_path):
    mark = (50.0, 100.0)
    mr, store = Optics(mark), sc.ScanStore(tmp_path)
    job = sc.Job('calibrating the camera', mr, manual_camera(), machine(), store, sc.Settings(sweep=(5.0, 7.0, 0.25)))
    st = run(job, 'calibrate', *mark, True)
    assert st['error'] is None, st['error']
    k = st['result']['calibration']
    assert k['pen'] == 'picam' and k['focus_z'] == pytest.approx(6.0)
    assert k['px_per_mm'] == pytest.approx(40, rel=0.03) and k['turn'] == pytest.approx(30, abs=1)
    assert k['fov'] == pytest.approx([12, 9], rel=0.03) and k['steps'][1] > k['steps'][0]
    assert k['center'] == pytest.approx([1.5, -1.0], abs=0.1) and k['residual'] < 0.1
    assert 'LAZY_HOME' in mr.scripts[0] and not any('T0' in s or 'DOCK' in s for s in mr.scripts)   # never a tool change
    assert store.meta(st['scan'])['kind'] == 'calibrate'
    # Without the cross in sight (its center too far off): said so, nothing measured
    far = Optics(mark, center=(15.0, 0.0))
    st = run(sc.Job('calibrating the camera', far, manual_camera(), machine(), sc.ScanStore(tmp_path / 'b'),
                    sc.Settings(sweep=(5.0, 7.0, 0.5))), 'calibrate', *mark, True)
    assert 'no cross in sight' in st['error'] and st['result'] is None


def test_the_app_places_the_cross_calibrates_and_saves_into_the_pen(tmp_path, monkeypatch):
    import shutil
    from fastapi.testclient import TestClient
    from plot import profile, server
    import limn_cam.moonraker as mrmod
    pens = tmp_path / 'pens.toml'
    shutil.copy(profile.PENS, pens)
    monkeypatch.setattr(profile, 'PENS', pens)
    fake = Optics((50.0, 100.0))
    monkeypatch.setattr(mrmod, 'Moonraker', lambda url: fake)
    client = TestClient(server.create_app(tmp_path / 'ws'))
    ws = client.app.state.ws
    ws.tags = {'90': {'pen': 'picam', 'name': 'Pi camera'}}        # docked by hand
    assert client.post('/api/camera/calibrate').status_code == 400   # no cross, no spot
    st = client.post('/api/camera/mark', json={'x': 50, 'y': 100}).json()
    assert [o['id'] for o in st['job']['objects']] == ['camera-mark']
    assert client.post('/api/camera/mark', json={'x': 50, 'y': 100}).json()['job']['objects'][0]['placement']['x'] == 44
    cam = client.get('/api/camera').json()
    assert list(cam['cameras']) == ['manual'] and cam['mark'] == [50, 100]
    client.patch('/api/camera', json={'tool': 'manual', 'settle': 0, 'sweep': [5.0, 7.0, 0.25]})
    assert client.post('/api/camera/calibration').status_code == 400        # nothing measured yet
    assert client.post('/api/camera/calibrate').status_code == 200
    for _ in range(1000):
        job = client.get('/api/camera').json()['job']
        if job['done']:
            break
        time.sleep(0.01)
    assert job['error'] is None, job['error']
    r = client.post('/api/camera/calibration').json()
    assert r['pen'] == 'picam'
    saved = profile.load_pens()['picam']
    assert saved['fov'] == pytest.approx([12, 9], rel=0.03) and saved['center'] == pytest.approx([1.5, -1.0], abs=0.1)
    assert saved['webcam'] == 'http://limn-picam.local:4250/capture.jpg' and saved['z_min'] == 5.0
    assert '# Docked by hand (DOCK_MANUAL)' in pens.read_text()             # its comments stay
    assert r['camera']['cameras']['manual']['fov'] == saved['fov']          # used from now on
