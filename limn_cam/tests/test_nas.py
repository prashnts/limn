# Uploading scans to an S3 bucket: the signature, and what goes up
import datetime

import pytest

from limn_cam import nas
from limn_cam.scan import ScanStore


def test_signature_is_aws_v4():
    # AWS's own example ("GET Object", Signature Version 4 docs)
    h = nas.sign('GET', 'https://examplebucket.s3.amazonaws.com/test.txt', {'Range': 'bytes=0-9'}, nas.EMPTY,
                 'AKIAIOSFODNN7EXAMPLE', 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY', 'us-east-1',
                 now=datetime.datetime(2013, 5, 24, tzinfo=datetime.timezone.utc))
    assert h['authorization'] == ('AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request, '
                                  'SignedHeaders=host;range;x-amz-content-sha256;x-amz-date, '
                                  'Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41')


class FakeS3:
    def __init__(self, fail_on=None):
        self.objects, self.fail_on = {}, fail_on

    def request(self, method, url, data=None, headers=None, timeout=None):
        assert headers['authorization'].startswith('AWS4-HMAC-SHA256 Credential=key/')
        r = type('R', (), {})()
        if self.fail_on and url.endswith(self.fail_on):
            r.status_code, r.reason, r.text = 503, 'Slow Down', '<Error><Message>busy</Message></Error>'
            return r
        self.objects[url] = data
        r.status_code, r.reason, r.text = 200, 'OK', ''
        return r


SETTINGS = nas.Settings(endpoint='http://nas:9000', bucket='scans', access_key='key', secret_key='secret')


def scan(tmp_path):
    store = ScanStore(tmp_path)
    sid = store.new({'kind': 'scan', 'fov': [15, 8]})
    store.add(sid, 'r00c00.jpg', b'a' * 10, {'x': 1, 'y': 2})
    store.add(sid, 'r00c01.jpg', b'b' * 20, {'x': 3, 'y': 2})
    (store.dir(sid) / 'thumb-320-r00c00.jpg').write_bytes(b'small')
    return store, sid


def test_a_scan_goes_up_once(tmp_path, monkeypatch):
    s3 = FakeS3()
    monkeypatch.setattr(nas.requests, 'request', s3.request)
    store, sid = scan(tmp_path)
    up = nas.Upload(store, sid, SETTINGS)
    up.run()
    assert up.state['error'] is None and up.state['i'] == up.state['n'] == 3
    keys = list(s3.objects)
    assert keys == [f'http://nas:9000/scans/limn/scans/{sid}/{f}' for f in ('r00c00.jpg', 'r00c01.jpg', 'meta.json')]
    assert nas.up_to_date(store, sid)
    # Again: only meta.json; a new file: that one too
    s3.objects.clear()
    store.add(sid, 'stitch-25.jpg', b'c' * 5, {})
    nas.Upload(store, sid, SETTINGS).run()
    assert [k.rsplit('/', 1)[1] for k in s3.objects] == ['stitch-25.jpg', 'meta.json']
    assert nas.uploaded(store, sid)['to'] == f's3://scans/limn/scans/{sid}/'


def test_a_failed_upload_says_why(tmp_path, monkeypatch):
    monkeypatch.setattr(nas.requests, 'request', FakeS3(fail_on='r00c01.jpg').request)
    store, sid = scan(tmp_path)
    up = nas.Upload(store, sid, SETTINGS)
    up.run()
    assert up.state['error'] == 'PUT limn/scans/%s/r00c01.jpg: 503 busy' % sid
    assert not nas.up_to_date(store, sid)


def test_settings_keep_the_secret(tmp_path):
    p = tmp_path / 'nas.json'
    nas.save_settings(p, SETTINGS)
    assert p.stat().st_mode & 0o077 == 0
    s = nas.load_settings(p)
    assert s.ready and s.public()['secret_key'] is True
    with pytest.raises(ValueError):
        nas.Bucket(nas.Settings())


def test_the_app_keeps_scans_on_the_nas(tmp_path, monkeypatch):
    import time
    from fastapi.testclient import TestClient
    from plot import server
    s3 = FakeS3()
    monkeypatch.setattr(nas.requests, 'request', s3.request)
    client = TestClient(server.create_app(tmp_path / 'ws'))
    assert client.post('/api/nas/check').status_code == 400                     # not set up
    st = client.put('/api/nas', json={'endpoint': 'http://nas:9000', 'bucket': 'scans', 'access_key': 'key',
                                      'secret_key': 'secret', 'auto': True}).json()
    assert st['settings']['secret_key'] is True and st['settings']['ready']
    assert client.put('/api/nas', json={'prefix': 'film', 'secret_key': ''}).json()['settings']['ready']   # kept
    assert client.post('/api/nas/check').json()['key'] == 'film/.limn-check'
    from limn_cam.scan import capture_root
    store = ScanStore(capture_root(client.app.state.ws.data))
    sid = store.new({'kind': 'scan'})
    store.add(sid, 'r00c00.jpg', b'a', {})
    assert client.post(f'/api/captures/{sid}/upload').status_code == 200
    for _ in range(100):
        if client.get('/api/nas').json()['uploads'][sid]['done']:
            break
        time.sleep(0.01)
    assert f'http://nas:9000/scans/film/{sid}/r00c00.jpg' in s3.objects
    assert client.get('/api/captures').json()[0]['uploaded'] == 'all'
