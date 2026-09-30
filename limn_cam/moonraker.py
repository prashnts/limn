# Limn cam - the plotter through Moonraker: G-code, files, webcam shots
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# A proxy in front of Moonraker may drop a request after a minute while
# Klipper carries on with it: `run` waits for Klipper to be idle instead.
import os
import time
from urllib.parse import urlsplit

import requests

IDLE = ('Ready', 'Idle')


class Moonraker:
    def __init__(self, url, timeout=10):
        self.url = url.rstrip('/')
        self.timeout = timeout

    def get(self, path, **params):
        r = requests.get(self.url + path, params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()['result']

    def query(self, **objects):
        return self.get('/printer/objects/query', **objects)['status']

    def state(self):
        st = self.query(print_stats='state', idle_timeout='state')
        return st['print_stats']['state'], st['idle_timeout']['state']

    def busy(self):
        printing, idle = self.state()
        return printing in ('printing', 'paused') or idle not in IDLE

    def wait_idle(self, timeout=3600, settle=3):
        '''Until Klipper is idle `settle` looks in a row (it is idle for a moment
        between the lines of a script).'''
        end, quiet = time.monotonic() + timeout, 0
        while time.monotonic() < end:
            quiet = 0 if self.busy() else quiet + 1
            if quiet >= settle:
                return
            time.sleep(2)
        raise TimeoutError(f'Klipper still busy after {timeout}s')

    def run(self, script, timeout=3600):
        '''G-code, until done. Errors come back as RuntimeError.'''
        try:
            r = requests.post(self.url + '/printer/gcode/script', json={'script': script}, timeout=55)
            if r.status_code == 400:
                raise RuntimeError(r.json()['error']['message'])
            if r.status_code not in (200, 502, 504):
                r.raise_for_status()
        except requests.Timeout:
            pass
        self.wait_idle(timeout)

    def gcode(self, script, timeout=120):
        '''G-code, back once Klipper has run it (the moves too, with an M400 in it).
        A proxy that gives up first (502/504): then until Klipper is idle.'''
        try:
            r = requests.post(self.url + '/printer/gcode/script', json={'script': script}, timeout=min(timeout, 58))
        except requests.Timeout:
            self.wait_idle(timeout)
            return
        if r.status_code == 200:
            return
        if r.status_code == 400:
            try:
                msg = r.json()['error']['message']
            except Exception:
                msg = r.text[:200]
            raise RuntimeError(msg)
        if r.status_code in (502, 504):
            self.wait_idle(timeout)
            return
        r.raise_for_status()

    def print_file(self, name, text, timeout=7200):
        '''Uploads and starts it, waits until it is over -> its end state.'''
        r = requests.post(self.url + '/server/files/upload', files={'file': (name, text.encode(), 'text/plain')},
                          data={'print': 'true'}, timeout=60)
        r.raise_for_status()
        end = time.monotonic() + timeout
        time.sleep(3)
        while time.monotonic() < end:
            state = self.query(print_stats='state,message')['print_stats']
            if state['state'] not in ('printing', 'paused'):
                return state
            time.sleep(3)
        raise TimeoutError(f'{name} still printing after {timeout}s')

    def webcams(self):
        return {w['name']: w for w in self.get('/server/webcams/list')['webcams']}

    def webcam_base(self):
        '''Where a webcam's relative URL (/webcam/..) lives: the web server in front
        (nginx, port 80), not Moonraker's own port. LIMN_WEBCAM_BASE says otherwise.'''
        if os.environ.get('LIMN_WEBCAM_BASE'):
            return os.environ['LIMN_WEBCAM_BASE'].rstrip('/')
        u = urlsplit(self.url)
        return f'{u.scheme}://{u.hostname}'

    def snapshot(self, camera):
        '''JPEG bytes from a webcam, by its name in Moonraker (or a snapshot URL).'''
        url = camera if '/' in camera else self.webcams()[camera]['snapshot_url']
        if url.startswith('/'):
            url = self.webcam_base() + url
        r = requests.get(url, timeout=self.timeout)
        r.raise_for_status()
        return r.content
