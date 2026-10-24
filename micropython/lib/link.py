# Limn Chain Link - frames, routing and queues shared by all MCUs
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# The MCUs are wired as a chain: Dock (or LIT) <-> node 1 <-> node 2 <-> ...
# Every node has an `up` UART (towards the Dock) and optionally a `down` UART.
# A segment on one wire (the pogo's BED_DATA, lib/halfwire.py) is half duplex:
# HalfPort below takes turns with a token.
# See micropython/STRATEGY.md for the wire format.
#
# This file also runs on CPython so that it can be tested on a PC:
#   python3 micropython/tests/test_link.py
import json
import struct
import time
import binascii
from collections import namedtuple


BAUD = 115200

# Frame types
T_HELLO = 1     # up:   node announces itself, payload b'<role>>><emblem>'
T_CMD   = 2     # down: command text, eg. b'calibrate()'
T_LOG   = 3     # up:   text for humans
T_DATA  = 4     # up:   sensor sample, see pack_fsr() / pack_rtp()
T_OTA   = 5     # both: firmware update request / reply, see lib/ota.py
T_TOKEN = 6     # one wire only: the turn to talk, never leaves the HalfPort

# Downstream frames carry the number of hops left to the target.
# Upstream frames carry the number of hops travelled, which the Dock reads as
# the position of the node that sent it. Sending down to that same number
# reaches the same node.
BROADCAST = 0xFF
MAX_HOP   = 0xFE

# SLIP framing
END     = b'\xc0'
ESC     = b'\xdb'
ESC_END = b'\xdb\xdc'
ESC_ESC = b'\xdb\xdd'

MAX_FRAME   = 1024  # encoded bytes; anything longer without an END is noise
TX_BATCH    = 128   # bytes handed to the UART per pump, keeps priorities useful
CONTROL_MAX = 32    # queued frames per priority before dropping the oldest
BULK_MAX    = 8
POLL_MS     = 5     # half duplex: the upper side's empty turns, at most this often
TOKEN_MS    = 150   # half duplex: silence this long and the upper side takes the turn back

# Priorities
P_CONTROL = 0       # commands, hello: sent first
P_LATEST  = 1       # sensor data: only the newest frame per source is kept
P_BULK    = 2       # logs: sent last, dropped first

Frame = namedtuple('Frame', ('type', 'hop', 'seq', 'payload'))


try:
    _crc32 = binascii.crc32
except AttributeError:
    def _crc32(data):
        crc = 0xFFFFFFFF
        for b in data:
            crc ^= b
            for _ in range(8):
                crc = (crc >> 1) ^ (0xEDB88320 if crc & 1 else 0)
        return crc ^ 0xFFFFFFFF

try:
    _sleep_ms = time.sleep_ms
    _ticks_ms = time.ticks_ms
    _ticks_diff = time.ticks_diff
except AttributeError:
    _sleep_ms = lambda ms: time.sleep(ms / 1000)
    _ticks_ms = lambda: int(time.monotonic() * 1000)
    _ticks_diff = lambda a, b: a - b


def encode(ftype, hop, seq, payload=b''):
    body = struct.pack('<BBB', ftype, hop, seq) + payload
    body += struct.pack('<I', _crc32(body) & 0xFFFFFFFF)
    # Leading END flushes whatever noise the receiver has buffered.
    return END + body.replace(ESC, ESC_ESC).replace(END, ESC_END) + END

def decode(raw):
    '''Bytes between two ENDs -> Frame, or None when damaged.'''
    body = raw.replace(ESC_END, END).replace(ESC_ESC, ESC)
    if len(body) < 7:
        return None
    crc = struct.unpack('<I', body[-4:])[0]
    if _crc32(body[:-4]) & 0xFFFFFFFF != crc:
        return None
    return Frame(body[0], body[1], body[2], body[3:-4])

def open_uart(uart_id, baud=BAUD, **pins):
    from machine import UART
    return UART(uart_id, baud, txbuf=1024, rxbuf=2048, **pins)

def load_node(root=''):
    '''This MCU's node.json: role, app, UARTs and pins. See micropython/nodes/.'''
    with open(root + 'node.json') as fp:
        return json.load(fp)

def from_config(node):
    '''Link with the UARTs described in node.json, eg.
    "up": {"id": 0}, "down": {"id": 0, "tx": 12, "rx": 13}, or one wire:
    "up": {"pin": 0} (half duplex, the lower side), "down": {"pin": 0} (the upper side)'''
    def port(key):
        spec = node.get(key)
        if not spec:
            return None
        baud = spec.get('baud', node.get('baud', BAUD))
        if 'pin' in spec:
            from halfwire import HalfWire
            return HalfPort(HalfWire(spec['pin'], baud), upper=key == 'down')
        from machine import Pin
        pins = {k: Pin(spec[k]) for k in ('tx', 'rx') if k in spec}
        return open_uart(spec['id'], baud, **pins)
    return Link(up=port('up'), down=port('down'))


class Port:
    '''One UART of a node: splits incoming bytes into frames, writes queued
    frames out by priority without ever blocking.'''

    def __init__(self, uart):
        self.uart = uart
        self._rx = b''
        self._tx = b''
        self._control = []
        self._latest = {}
        self._bulk = []
        self.stats = {'rx': 0, 'tx': 0, 'bad': 0, 'drop': 0}

    def frames(self):
        n = self.uart.any()
        if n:
            self._rx += self.uart.read(n) or b''

        frames = []
        while True:
            i = self._rx.find(END)
            if i < 0:
                break
            raw, self._rx = self._rx[:i], self._rx[i + 1:]
            if not raw:
                continue
            frame = decode(raw)
            if frame is None:
                self.stats['bad'] += 1
                continue
            self.stats['rx'] += 1
            frames.append(frame)

        if len(self._rx) > MAX_FRAME:
            self._rx = b''
            self.stats['bad'] += 1
        return frames

    def queue(self, frame, prio=P_CONTROL, key=None):
        if prio == P_LATEST:
            if key in self._latest:
                self.stats['drop'] += 1
            self._latest[key] = frame
            return
        queue, limit = (self._bulk, BULK_MAX) if prio == P_BULK else (self._control, CONTROL_MAX)
        if len(queue) >= limit:
            queue.pop(0)
            self.stats['drop'] += 1
        queue.append(frame)

    def busy(self):
        return bool(self._tx or self._control or self._latest or self._bulk
                    or not self.uart.txdone())

    def _next(self):
        if self._control:
            return self._control.pop(0)
        for key in self._latest:
            return self._latest.pop(key)
        if self._bulk:
            return self._bulk.pop(0)
        return None

    def _batch(self):
        batch = b''
        while len(batch) < TX_BATCH:
            frame = self._next()
            if frame is None:
                break
            batch += frame
            self.stats['tx'] += 1
        return batch

    def pump(self):
        if self._tx:
            # Finish a partial write before anything else.
            n = self.uart.write(self._tx) or 0
            self._tx = self._tx[n:]
            return
        if not self.uart.txdone():
            return
        batch = self._batch()
        if batch:
            n = self.uart.write(batch) or 0
            self._tx = batch[n:]


TOKEN = encode(T_TOKEN, 0, 0)

class HalfPort(Port):
    '''A Port on one wire: one side talks at a time. The upper side (towards
    the host) sends what it has and a token; the lower side answers with one
    batch and the token back, and never talks without it. A lost token: the
    upper side takes the turn back after TOKEN_MS of silence. `active` False
    (the upper side's bed is off): no turns at all, the queue waits.'''

    def __init__(self, wire, upper):
        super().__init__(wire)
        self.upper = upper
        self.active = True
        self.mine = upper           # our turn
        self._seen = _ticks_ms()    # the token, or bytes, last
        self.stats['lost'] = 0

    def frames(self):
        if self.uart.any():
            self._seen = _ticks_ms()
        out = []
        for f in super().frames():
            if f.type == T_TOKEN:
                self.stats['rx'] -= 1
                self.mine = True
            else:
                out.append(f)
        return out

    def _pending(self):
        return bool(self._control or self._latest or self._bulk)

    def pump(self):
        if not self.uart.txdone():
            return
        if self.upper:
            if not self.active:
                return
            if not self.mine:
                if _ticks_diff(_ticks_ms(), self._seen) < TOKEN_MS:
                    return
                self.stats['lost'] += 1
                self.mine = True
            if not self._pending() and _ticks_diff(_ticks_ms(), self._seen) < POLL_MS:
                return
        elif not self.mine:
            return
        self.uart.write(self._batch() + TOKEN)
        self.mine = False
        self._seen = _ticks_ms()


def _priority(ftype, hop, payload):
    if ftype == T_DATA:
        return P_LATEST, (hop, payload[0] if payload else 0)
    if ftype == T_LOG:
        return P_BULK, None
    return P_CONTROL, None


class Link:
    '''Routes frames for one node. Only the Dock has no `up` UART.'''

    def __init__(self, up=None, down=None, root=''):
        self.up = up if isinstance(up, Port) else Port(up) if up else None
        self.down = down if isinstance(down, Port) else Port(down) if down else None
        self.root = root        # where files live, only differs in tests
        self.quiet = False      # set during updates: no sensor data or logs
        self.ota = None
        self.tap = None         # tap(frame): sees frames from below and our own, for a USB host
        self.below = None       # below(frame): sees frames from below, eg. touch.relay
        self._seq = 0

    def poll(self):
        '''Moves traffic along the chain, returns frames meant for this node.'''
        mine = []
        if self.down:
            for f in self.down.frames():
                hop = min(f.hop + 1, MAX_HOP)
                if self.tap:
                    self.tap(Frame(f.type, hop, f.seq, f.payload))
                if self.below:
                    self.below(Frame(f.type, hop, f.seq, f.payload))
                if self.up:
                    self.up.queue(encode(f.type, hop, f.seq, f.payload),
                                  *_priority(f.type, hop, f.payload))
                else:
                    mine.append(Frame(f.type, hop, f.seq, f.payload))

        if self.up:
            for f in self.up.frames():
                if f.hop == BROADCAST:
                    self._forward_down(f, BROADCAST)
                elif f.hop > 1:
                    self._forward_down(f, f.hop - 1)
                    continue
                if f.type == T_OTA:
                    self.send(T_OTA, self.handle_ota(f.payload))
                    self.after_ota()
                else:
                    mine.append(f)

        self.pump()
        return mine

    def handle_ota(self, payload):
        '''Runs an update request meant for this node, returns the reply.'''
        if self.ota is None:
            import ota
            self.ota = ota.Receiver(self)
        return self.ota.handle(payload)

    def after_ota(self):
        '''Resets once the reply to a commit is on the wire.'''
        if self.ota and self.ota.reset_pending:
            self.flush()
            import ota
            ota.reset()

    def _forward_down(self, f, hop):
        if self.down:
            self.down.queue(encode(f.type, hop, f.seq, f.payload))

    def _next_seq(self):
        self._seq = (self._seq + 1) & 0xFF
        return self._seq

    def send(self, ftype, payload=b''):
        '''Sends a frame from this node towards the Dock.'''
        if self.quiet and ftype in (T_DATA, T_LOG):
            return
        seq = self._next_seq()
        if self.tap:
            self.tap(Frame(ftype, 0, seq, payload))
        if self.up:
            self.up.queue(encode(ftype, 0, seq, payload), *_priority(ftype, 0, payload))

    def send_down(self, ftype, payload=b'', hop=BROADCAST):
        '''Sends a frame to the node `hop` positions below, or to all.'''
        if self.down:
            self.down.queue(encode(ftype, hop, self._next_seq(), payload))

    def pump(self):
        if self.up:
            self.up.pump()
        if self.down:
            self.down.pump()

    def busy(self):
        return any(p.busy() for p in (self.up, self.down) if p)

    def flush(self, timeout_ms=200):
        '''Blocks until everything queued is on the wire, eg. before reset().'''
        for _ in range(timeout_ms):
            self.pump()
            if not self.busy():
                return
            _sleep_ms(1)

    def stats(self):
        return {name: p.stats for name, p in (('up', self.up), ('down', self.down)) if p}


class Guard:
    '''Keeps a main loop going through an occasional error: reports it with
    `log(text)` and carries on. After `limit` errors in a row it re-raises, and
    main.py falls back to the rescue loop, which still takes updates.

        while True:
            try:
                step()
                guard.ok()
            except Exception as e:
                guard.error(e)
    '''

    def __init__(self, log, limit=20):
        self.log = log
        self.limit = limit
        self.errors = 0
        self.total = 0

    def ok(self):
        self.errors = 0

    def error(self, e):
        self.errors += 1
        self.total += 1
        try:
            import sys
            sys.print_exception(e)
        except AttributeError:
            print(repr(e))
        self.log('error>>' + repr(e))
        if self.errors >= self.limit:
            raise e


# Sensor payloads, carried in T_DATA frames.
FSR_ID_LM = 0x4
RTP_ID_LM = 0x5

S_CALIBRATING = 12
S_CAL_FAILED  = 13      # kept the previous baseline (or a doubtful one), see the log
S_CALIBRATED  = 14
S_SAMPLE      = 42
S_MATRIX      = 43      # FSR matrix mode: every cell, touched or not

FSR_MAX_TOUCHES = 8

def pack_fsr(state, touches, limit=FSR_MAX_TOUCHES):
    '''touches: [(row, col, strength 0..1000)], strongest first.'''
    touches = touches[:limit]
    out = struct.pack('<BBB', FSR_ID_LM, state, len(touches))
    for row, col, strength in touches:
        out += struct.pack('<BBH', row, col, strength)
    return out

def pack_rtp(state, x, y, z):
    return struct.pack('<BBHHI', RTP_ID_LM, state, x, y, z)

LOAD_ID_LM = 0x6

# Plot bed flags
LOAD_TOUCH   = 0x01     # the touch line says touched (or failed safe)
LOAD_ARMED   = 0x02
LOAD_CAL     = 0x04     # grams come from a calibration, not the estimate
LOAD_SUM_OK  = 0x08     # the sum ADC delivers samples
LOAD_FEET_OK = 0x10     # the feet ADC delivers samples
LOAD_TARING  = 0x20

def pack_load(state, flags, sum_mg, sum_raw, feet):
    '''Plot bed: sum and per foot load. feet: [(mg, raw counts)].'''
    out = struct.pack('<BBBBii', LOAD_ID_LM, state, flags, len(feet), sum_mg, sum_raw)
    for mg, raw in feet:
        out += struct.pack('<ii', mg, raw)
    return out

def unpack_data(payload):
    '''T_DATA payload -> (kind, state, values), or None when malformed.
    FSR values: [[row, col, strength], ...], RTP values: [x, y, z],
    plot bed values: [flags, sum_mg, sum_raw, [[mg, raw], ...per foot]].'''
    if len(payload) < 2:
        return None
    kind, state = payload[0], payload[1]
    if kind == LOAD_ID_LM and len(payload) >= 12:
        flags, n = payload[2], payload[3]
        if len(payload) != 12 + 8 * n:
            return None
        sum_mg, sum_raw = struct.unpack_from('<ii', payload, 4)
        feet = [list(struct.unpack_from('<ii', payload, 12 + 8 * i)) for i in range(n)]
        return kind, state, [flags, sum_mg, sum_raw, feet]
    if kind == FSR_ID_LM and len(payload) >= 3:
        n = payload[2]
        if len(payload) != 3 + 4 * n:
            return None
        return kind, state, [list(struct.unpack_from('<BBH', payload, 3 + 4 * i)) for i in range(n)]
    if kind == RTP_ID_LM and len(payload) == 10:
        return kind, state, list(struct.unpack_from('<HHI', payload, 2))
    return None
