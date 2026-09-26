# Limn - the Dock's USB serial, inside Klipper's reactor
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# The Dock prints `!LRT>>kind>>json>>` lines and takes command lines, see
# micropython/STRATEGY.md. This file knows nothing about calibration: it hands
# every line to the listeners of its kind.
import json
import base64
import logging

READ_INTERVAL = 0.05
T_CMD = 2       # frame type of a command, as in micropython/lib/link.py


def parse_line(line):
    '''`!LRT>>kind>>body>>` -> (kind, data), data is json when it parses.'''
    line = line.strip()
    if not line.startswith('!LRT>>'):
        return None
    kind, _, body = line[len('!LRT>>'):].partition('>>')
    if body.endswith('>>'):
        body = body[:-2]
    try:
        return kind, json.loads(body)
    except ValueError:
        return kind, body


class Lines:
    '''Splits a byte stream into text lines.'''

    def __init__(self):
        self.buffer = b''

    def feed(self, data):
        self.buffer += data
        *lines, self.buffer = self.buffer.split(b'\n')
        return [l.decode('utf-8', errors='ignore').strip() for l in lines]


class Dock:

    def __init__(self, reactor, port, baud=115200, say=None):
        self.reactor = reactor
        self.port = port
        self.baud = baud
        self.say = say or logging.info
        self.serial = None
        self.timer = None
        self.lines = Lines()
        self.listeners = {}         # kind -> [callback(data)]
        self._replies = {}          # kind -> data, while a request waits for it

    def on(self, kind, callback):
        self.listeners.setdefault(kind, []).append(callback)

    @property
    def connected(self):
        return self.serial is not None

    def connect(self):
        if self.serial:
            return True
        import serial
        try:
            self.serial = serial.Serial(self.port, self.baud, timeout=0, write_timeout=0)
        except (OSError, serial.SerialException) as e:
            self.say(f"[LRT] Unable to connect to the Dock: {e}")
            return False
        self.lines = Lines()
        if self.timer:
            self.reactor.unregister_timer(self.timer)
        self.timer = self.reactor.register_timer(self._read, self.reactor.NOW)
        self.say("[LRT] Connected")
        return True

    def disconnect(self):
        if self.timer:
            self.reactor.unregister_timer(self.timer)
            self.timer = None
        if self.serial:
            self.serial.close()
            self.serial = None
            self.say("[LRT] Disconnected")

    def send(self, cmd):
        if not self.connect():
            raise ConnectionError("Dock not connected")
        try:
            self.serial.write((cmd.strip() + '\r\n').encode())
        except Exception as e:
            logging.exception("[LRT] write failed")
            self.disconnect()
            raise ConnectionError(f"Dock write failed: {e}")

    def send_to(self, hop, cmd):
        '''A command for one node only.'''
        b64 = base64.b64encode(cmd.encode()).decode()
        self.send(f'frame({hop},{T_CMD},{b64})')

    def request(self, cmd, kind, timeout=3.0):
        '''Sends `cmd` and waits (letting Klipper run) for the next `kind` line.'''
        self._replies[kind] = None
        self.send(cmd)
        end = self.reactor.monotonic() + timeout
        while self._replies[kind] is None:
            now = self.reactor.monotonic()
            if now >= end:
                del self._replies[kind]
                raise TimeoutError(f"no {kind} reply to {cmd}")
            self.reactor.pause(now + READ_INTERVAL)
        return self._replies.pop(kind)

    def handle_line(self, line):
        parsed = parse_line(line)
        if parsed is None:
            return
        kind, data = parsed
        if kind in self._replies:
            self._replies[kind] = data
        for callback in self.listeners.get(kind, ()):
            callback(data)

    def _read(self, eventtime):
        try:
            data = self.serial.read(self.serial.in_waiting or 1)
        except Exception:
            logging.exception("[LRT] read failed")
            self.say("[LRT] ERROR - Unable to communicate with the Dock.")
            self.serial.close()
            self.serial = None
            return self.reactor.NEVER
        for line in self.lines.feed(data):
            self.handle_line(line)
        return eventtime + READ_INTERVAL
