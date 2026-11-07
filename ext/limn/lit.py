# Limn - LIT, the head's load cell board, on its own USB serial
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# LIT (micropython/limn_lit.py) streams `data` lines of kind 6: [flags, milligrams, raw, ..],
# + = pushing the pen up. It answers tare() / threshold() with `log` lines and arm(lit) with
# an `armed` line. Its touch line (an NPN into a Klipper endstop) is what a probe uses; this
# file is the host side: the force for the UI, tare / arm / threshold, the debug lines, and the
# force log (each sample with where the toolhead was, from Klipper's trapq).
import collections
import json
import os
import time

from .dock import Dock

READ_INTERVAL = 0.01    # s: samples are stamped when read
KIND_LOAD = 6
TOUCH, ARMED, CAL, SUM_OK, TARING = 0x01, 0x02, 0x04, 0x08, 0x20   # micropython/lib/link.py LOAD_*
STREAM_HZ = 25          # LIT's own default
LOG_HZ = 100            # while a log runs (one mains period averaged per sample: ~25 Hz of bandwidth)
RECENT = 2.0            # s of samples kept for the UI and the debug lines
REPLY_TIMEOUT = 3.0


class Lit:

    def __init__(self, reactor, port, say, log_dir='~/printer_data/logs/limn-cell'):
        self.reactor = reactor
        self.say = say
        self.link = Dock(reactor, port, say=say, interval=READ_INTERVAL, name='LIT')
        self.link.on('data', self._on_data)
        self.link.on('log', self._on_log)
        self.link.on('armed', self._on_armed)
        self.log_dir = os.path.expanduser(log_dir)
        self.recent = collections.deque()       # (eventtime, grams, flags)
        self.flags = 0
        self.grams = None
        self.at = 0.0
        self.armed_reply = None
        self.logs = collections.deque(maxlen=20)        # LIT's own log lines, the last few
        self.nlogs = 0                                  #   and how many came in all
        self.debug_every = 0.0
        self.debug_timer = None
        self.log = None             # the force log while one runs: {'file', 'path', 'n', 'where'}

    # -- the stream -------------------------------------------------------

    def connect(self):
        return self.link.connect()

    def _on_data(self, data):
        if not isinstance(data, dict) or data.get('kind') != KIND_LOAD or data.get('hop', 0) != 0:
            return
        flags, mg = data['values'][0], data['values'][1]
        now = self.reactor.monotonic()
        self.flags, self.grams, self.at = flags, mg / 1000.0, now
        self.recent.append((now, self.grams, flags))
        while self.recent and self.recent[0][0] < now - RECENT:
            self.recent.popleft()
        if self.log:
            self._log_sample(now, self.grams, flags)

    def _on_log(self, data):
        text = data.get('text', '') if isinstance(data, dict) else str(data)
        self.logs.append(text)
        self.nlogs += 1

    def _on_armed(self, data):
        self.armed_reply = bool(data.get('armed')) if isinstance(data, dict) else False

    def mean(self, seconds=0.25):
        '''Mean grams over the last `seconds` (not while taring); None without samples.'''
        since = self.reactor.monotonic() - seconds
        g = [s[1] for s in self.recent if s[0] >= since and not s[2] & TARING]
        return sum(g) / len(g) if g else None

    # -- commands to LIT --------------------------------------------------

    def _wait_log(self, cmd, prefix, timeout=REPLY_TIMEOUT):
        '''Sends cmd, waits (letting Klipper run) for LIT's `prefix>>..` log line, returns its text.'''
        n0 = self.nlogs
        self.link.send(cmd)
        end = self.reactor.monotonic() + timeout
        while True:
            new = min(self.nlogs - n0, len(self.logs))
            for text in list(self.logs)[len(self.logs) - new:]:
                if text.startswith(prefix + '>>'):
                    return text[len(prefix) + 2:]
            now = self.reactor.monotonic()
            if now >= end:
                raise TimeoutError(f"LIT: no {prefix} reply to {cmd}")
            self.reactor.pause(now + READ_INTERVAL)

    def tare(self):
        reply = self._wait_log('tare()', 'tare')
        if reply.startswith('failed'):
            raise RuntimeError(f"LIT tare {reply}")
        return reply

    def arm(self, timeout=REPLY_TIMEOUT):
        '''Tare, then arm the touch line (LIT does both: arm(lit)). False: not armed.'''
        self.armed_reply = None
        self.link.send('arm(lit)')
        end = self.reactor.monotonic() + timeout
        while self.armed_reply is None:
            now = self.reactor.monotonic()
            if now >= end:
                raise TimeoutError("LIT: no armed reply")
            self.reactor.pause(now + READ_INTERVAL)
        return self.armed_reply

    def threshold(self, grams, release=None):
        cmd = f'threshold({grams})' if release is None else f'threshold({grams},{release})'
        return self._wait_log(cmd, 'threshold')

    def rate(self, hz):
        self.link.send(f'rate({hz})')

    # -- debug lines ------------------------------------------------------

    def debug(self, every):
        '''Every `every` s a console line with the force; 0: off.'''
        self.debug_every = every
        if self.debug_timer:
            self.reactor.unregister_timer(self.debug_timer)
            self.debug_timer = None
        if every > 0:
            self.debug_timer = self.reactor.register_timer(self._debug_line, self.reactor.NOW)

    def _debug_line(self, eventtime):
        g = self.mean(min(self.debug_every, 0.5))
        if g is None:
            self.say("[LIT] no samples")
        else:
            lo = min(s[1] for s in self.recent if s[0] >= eventtime - self.debug_every)
            hi = max(s[1] for s in self.recent if s[0] >= eventtime - self.debug_every)
            self.say(f"[LIT] {g:+7.2f} g  ({lo:+.1f}..{hi:+.1f}){self._flag_text()}")
        return eventtime + self.debug_every

    def _flag_text(self):
        f = self.flags
        return ''.join(t for bit, t in ((TOUCH, ' TOUCH'), (ARMED, ' armed'), (TARING, ' taring')) if f & bit) + \
            ('' if f & SUM_OK else ' ADC-FAULT')

    # -- the force log ----------------------------------------------------

    def log_start(self, name, where):
        '''Each sample to <log_dir>/<name>.jsonl with `where(eventtime)` -> (x, y, z, v) or None.'''
        if self.log:
            self.log_stop()
        os.makedirs(self.log_dir, exist_ok=True)
        path = os.path.join(self.log_dir, f'{name}.jsonl')
        f = open(path, 'w')
        f.write(json.dumps({'started': time.time(), 'monotonic': self.reactor.monotonic(),
                            'row': ['t', 'g', 'flags', 'x', 'y', 'z', 'v']}) + '\n')
        self.log = {'file': f, 'path': path, 'n': 0, 'where': where}
        self.rate(LOG_HZ)
        return path

    def _log_sample(self, now, grams, flags):
        log = self.log
        pos = log['where'](now)
        row = [round(now, 4), round(grams, 3), flags] + ([round(v, 4) for v in pos] if pos else [None] * 4)
        log['file'].write(json.dumps(row) + '\n')
        log['n'] += 1

    def log_stop(self):
        log, self.log = self.log, None
        if not log:
            return None
        log['file'].close()
        self.rate(STREAM_HZ)
        return log['path'], log['n']

    def status(self, eventtime):
        g = self.mean()
        return {
            'connected': self.link.connected,
            'grams': None if g is None else round(g, 2),
            'age': round(eventtime - self.at, 2) if self.at else None,
            'touch': bool(self.flags & TOUCH),
            'armed': bool(self.flags & ARMED),
            'calibrated': bool(self.flags & CAL),
            'adc_ok': bool(self.flags & SUM_OK),
            'debug': self.debug_every,
            'logging': self.log['path'] if self.log else None,
        }
