# Limn cam - keeping scans: uploads to an S3 bucket (the NAS: OpenMediaVault's S3, MinIO, ..)
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# The scans are in RAM on the Pi (scan.capture_root()): a reboot loses them.
# A scan goes up as <prefix>/<scan id>/<file>, every file of its folder, the
# ones already up (same size, in its uploaded.json) skipped, meta.json last. Requests are
# signed here (AWS Signature V4, path-style URLs as MinIO wants them): no boto3
# on the Pi for a few PUTs.
#
# The settings (endpoint, bucket, keys) are kept in the workspace's nas.json,
# readable by its owner only, never in the repository.
import datetime
import hashlib
import hmac
import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit

import requests

EMPTY = hashlib.sha256(b'').hexdigest()
TYPES = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.tif': 'image/tiff', '.tiff': 'image/tiff',
         '.json': 'application/json', '.pto': 'text/plain', '.txt': 'text/plain'}


def _hmac(key, msg):
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def sign(method, url, headers, payload_hash, access_key, secret_key, region='us-east-1', now=None, service='s3'):
    '''The headers to send: `headers` plus host, x-amz-date, x-amz-content-sha256 and
    Authorization (AWS Signature V4; every header given is signed).'''
    now = now or datetime.datetime.now(datetime.timezone.utc)
    amz_date, day = now.strftime('%Y%m%dT%H%M%SZ'), now.strftime('%Y%m%d')
    u = urlsplit(url)
    h = {k.lower(): str(v).strip() for k, v in headers.items()}
    h.update({'host': u.netloc, 'x-amz-date': amz_date, 'x-amz-content-sha256': payload_hash})
    names = sorted(h)
    query = '&'.join(sorted(f'{quote(k, safe="-_.~")}={quote(v, safe="-_.~")}'
                            for k, _, v in (p.partition('=') for p in u.query.split('&') if p)))
    canonical = '\n'.join([method, quote(u.path or '/', safe='/-_.~'), query,
                           ''.join(f'{k}:{h[k]}\n' for k in names), ';'.join(names), payload_hash])
    scope = f'{day}/{region}/{service}/aws4_request'
    to_sign = '\n'.join(['AWS4-HMAC-SHA256', amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    key = _hmac(_hmac(_hmac(_hmac(('AWS4' + secret_key).encode(), day), region), service), 'aws4_request')
    sig = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    h['authorization'] = (f'AWS4-HMAC-SHA256 Credential={access_key}/{scope}, '
                          f'SignedHeaders={";".join(names)}, Signature={sig}')
    return h


@dataclass
class Settings:
    endpoint: str = ''              # https://nas.local:9000
    bucket: str = ''
    prefix: str = 'limn/scans'
    access_key: str = ''
    secret_key: str = ''
    region: str = 'us-east-1'       # MinIO takes any; AWS wants the bucket's
    auto: bool = False              # upload each scan when it is done

    @property
    def ready(self):
        return bool(self.endpoint and self.bucket and self.access_key and self.secret_key)

    def public(self):
        '''For the UI: the secret only as whether there is one.'''
        d = asdict(self)
        d['secret_key'] = bool(self.secret_key)
        d['ready'] = self.ready
        return d


def load_settings(path):
    path = Path(path)
    if not path.exists():
        return Settings()
    try:
        return Settings(**{k: v for k, v in json.loads(path.read_text()).items() if k in Settings.__dataclass_fields__})
    except (TypeError, ValueError):
        return Settings()


def save_settings(path, s):
    path = Path(path)
    path.write_text(json.dumps(asdict(s), indent=1))
    os.chmod(path, 0o600)


class Bucket:
    def __init__(self, s: Settings, timeout=60):
        if not s.ready:
            raise ValueError('the NAS needs an endpoint, a bucket and both keys')
        self.s = s
        self.timeout = timeout

    def url(self, key=''):
        return f'{self.s.endpoint.rstrip("/")}/{quote(self.s.bucket)}' + (f'/{quote(key, safe="/-_.~")}' if key else '')

    def request(self, method, key='', data=b'', headers=None, query=''):
        url = self.url(key) + (f'?{query}' if query else '')
        payload = hashlib.sha256(data).hexdigest() if data else EMPTY
        h = sign(method, url, headers or {}, payload, self.s.access_key, self.s.secret_key, self.s.region)
        h.pop('host')
        r = requests.request(method, url, data=data or None, headers=h, timeout=self.timeout)
        if r.status_code >= 300:
            msg = r.text.split('<Message>')[1].split('</Message>')[0] if '<Message>' in r.text else r.reason
            raise RuntimeError(f'{method} {key or self.s.bucket}: {r.status_code} {msg}')
        return r

    def put(self, key, data, content_type='application/octet-stream'):
        return self.request('PUT', key, data, {'content-type': content_type})

    def check(self):
        '''That the bucket is there and takes a file -> the key written.'''
        key = f'{self.s.prefix.strip("/")}/.limn-check'
        self.put(key, f'limn {time.strftime("%Y-%m-%d %H:%M:%S")}\n'.encode(), 'text/plain')
        return key


UPLOADED = 'uploaded.json'     # in the scan's folder: what is up, by size (not meta.json: stitches go by its time)


def uploaded(store, sid):
    '''{to, at, files: {name: size}} of a scan, {} if nothing went up.'''
    try:
        return json.loads((store.dir(sid) / UPLOADED).read_text())
    except (FileNotFoundError, ValueError):
        return {}


def up_to_date(store, sid):
    '''Every file of the scan is up as it is now.'''
    files = uploaded(store, sid).get('files', {})
    d = store.dir(sid)
    return bool(files) and all(files.get(p.name) == p.stat().st_size for p in d.iterdir()
                               if p.is_file() and not p.name.startswith('thumb-') and p.name != UPLOADED)


class Upload:
    '''One scan going up, in the background: `state` says how far.'''

    def __init__(self, store, sid, settings, bucket=None):
        self.store, self.sid, self.s = store, sid, settings
        self.bucket = bucket or Bucket(settings)
        self.state = {'scan': sid, 'i': 0, 'n': 0, 'mb': 0.0, 'done': False, 'error': None, 'started': time.time()}

    def files(self):
        d = self.store.dir(self.sid)
        return sorted((p for p in d.iterdir() if p.is_file() and not p.name.startswith('thumb-') and p.name != UPLOADED),
                      key=lambda p: (p.name == 'meta.json', p.name))      # meta.json last: a scan whose meta is up is whole

    def run(self):
        try:
            done = uploaded(self.store, self.sid).get('files', {})
            todo = [p for p in self.files() if p.name == 'meta.json' or done.get(p.name) != p.stat().st_size]
            self.state['n'] = len(todo)
            prefix = f'{self.s.prefix.strip("/")}/{self.sid}'
            for i, p in enumerate(todo):
                data = p.read_bytes()
                self.bucket.put(f'{prefix}/{p.name}', data, TYPES.get(p.suffix.lower(), 'application/octet-stream'))
                done[p.name] = len(data)
                self.state['i'], self.state['mb'] = i + 1, round(self.state['mb'] + len(data) / 1e6, 2)
                (self.store.dir(self.sid) / UPLOADED).write_text(json.dumps(
                    {'to': f's3://{self.s.bucket}/{prefix}/', 'at': time.time(), 'files': done}))
        except Exception as e:
            self.state['error'] = str(e)
        finally:
            self.state['done'], self.state['ended'] = True, time.time()

    def start(self):
        threading.Thread(target=self.run, daemon=True).start()
        return self
