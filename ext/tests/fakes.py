# Stand-ins for Klipper and the Dock, for the ext tests.
import os
import sys
from collections import namedtuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

ProbeResult = namedtuple('ProbeResult', ('bed_x', 'bed_y', 'bed_z', 'test_x', 'test_y', 'test_z'))


class FakeReactor:
    '''Time only moves in pause(), running the timers that are due.'''
    NOW = 0.0
    NEVER = 9e99

    def __init__(self):
        self.t = 0.0
        self.timers = {}

    def monotonic(self):
        return self.t

    def register_timer(self, callback, waketime):
        self.timers[callback] = waketime
        return callback

    def unregister_timer(self, timer):
        self.timers.pop(timer, None)

    def pause(self, until):
        while self.t < until:
            self.t = min(until, self.t + 0.01)
            for callback, when in list(self.timers.items()):
                if when <= self.t and callback in self.timers:
                    self.timers[callback] = callback(self.t)


class FakeDock:
    '''Records what the routines send; `matrix` tracks FSR matrix mode per hop.'''

    def __init__(self):
        self.sent = []
        self.matrix = set()
        self.connected = True

    def send(self, cmd):
        if not self.connected:
            raise ConnectionError("Dock not connected")
        self.sent.append(cmd)

    def send_to(self, hop, cmd):
        self.send(f'{hop}:{cmd}')
        if cmd == 'matrix(on)':
            self.matrix.add(hop)
        elif cmd == 'matrix(off)':
            self.matrix.discard(hop)


class FakeBus:
    """The Pi's I2C bus: each address answers with a fake device, the others NAK."""

    def __init__(self, *devices):
        self.devices = {d.address: d for d in devices}

    def transfer(self, addr, *parts):
        dev = self.devices.get(addr)
        if dev is None or dev.fail:
            raise OSError(121, 'Remote I/O error')
        reads = []
        for part in parts:
            if isinstance(part, int):
                reads.append(bytes(dev.read(part)))
            else:
                dev.write(bytes(part))
        return reads


class FakeMCP23017:
    """Registers with auto-increment; `low` holds the pins pulled low (tools in their holders)."""
    address = 0x20

    def __init__(self, low=()):
        self.regs = bytearray(0x16)
        self.regs[0x00] = self.regs[0x01] = 0xFF    # IODIR: all inputs after power up
        self.low = set(low)
        self.ptr = 0
        self.fail = False

    def write(self, data):
        self.ptr = data[0]
        for b in data[1:]:
            self.regs[self.ptr] = b
            self.ptr += 1

    def read(self, n):
        gpio = 0xFFFF & ~sum(1 << p for p in self.low)
        self.regs[0x12], self.regs[0x13] = gpio & 0xFF, gpio >> 8
        out = self.regs[self.ptr:self.ptr + n]
        self.ptr += n
        return out


class FakePN532:
    """Frames in, ACK and reply frames out, like the chip; `pages` is the NTAG in the field."""
    address = 0x24
    ACK = b'\x00\x00\xff\x00\xff\x00'

    def __init__(self, pages=None, uid=b'\x04\x11\x22\x33\x44\x55\x66'):
        self.pages = pages          # page -> 4 bytes, None: no tag in the field
        self.uid = uid
        self.queue = []
        self.fail = False
        self.mute = False           # never replies, only ACKs
        self.writes = []
        self.aborted = 0

    @staticmethod
    def frame(data):
        n = len(data)
        return bytes([0, 0, 0xFF, n, (0x100 - n) & 0xFF]) + bytes(data) + bytes([(0x100 - sum(data)) & 0xFF, 0])

    def write(self, data):
        if data == self.ACK:
            self.queue = []
            self.aborted += 1
            return
        n = data[3]
        body = data[5:5 + n]
        assert body[0] == 0xD4 and (sum(body) + data[5 + n]) & 0xFF == 0, data
        self.queue = [self.ACK]
        reply = self.reply(body[1], body[2:])
        if not self.mute:
            self.queue.append(self.frame(bytes([0xD5, body[1] + 1]) + bytes(reply)))

    def reply(self, cmd, params):
        if cmd == 0x02:
            return [0x32, 1, 6, 7]
        if cmd in (0x14, 0x32):
            return []
        if cmd == 0x4A:
            if self.pages is None:
                return [0]
            return [1, 1, 0x00, 0x44, 0x00, len(self.uid), *self.uid]
        if cmd == 0x40 and self.pages is not None:
            op, page = params[1], params[2]
            if op == 0x30:
                return [0] + [b for p in range(page, page + 4) for b in self.pages.get(p, bytes(4))]
            if op == 0xA2:
                self.pages[page] = bytes(params[3:7])
                self.writes.append(page)
                return [0]
        return [0x01]

    def read(self, n):
        if not self.queue:
            return bytes(n)
        if n == 1:
            return b'\x01'
        out = (b'\x01' + self.queue.pop(0)).ljust(n, b'\x00')
        return out[:n]


def run_tests(module_globals):
    tests = [(name, fn) for name, fn in module_globals.items() if name.startswith('test_')]
    for name, fn in tests:
        fn()
        print('ok', name)
    print(len(tests), 'passed')
