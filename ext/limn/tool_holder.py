# Limn - the tool holder: which holders have their tool, and the tools' tags
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Each holder has a switch on the MCP23017 (low = tool in the holder), the
# PN532 reads the tag of the tool on the carriage. Both are on the Pi's I2C.
# A timer watches the holders and tells the listeners of `change` what moved;
# changes nobody `expect`ed are `manual`: someone's hand was on the holders.
from dataclasses import dataclass

from .i2c import MCP23017, PN532

INTERVAL = 0.2          # s between two looks at the holders
SETTLE = 2              # equal reads before a new state counts
SAMPLE_GAP = 0.02       # s between the reads of `sample`
EXPECT_WINDOW = 120     # s an expected change stays expected
ANY = 'any'             # expect(): any change, until forget()

PAGE_DX, PAGE_NAME = 6, 11      # dx, dy, dz on pages 6, 7, 8; the name on 11..15
PAGE_FLAGS = 9                  # REFERENCE: the reference tool, anything else: not
REFERENCE, NOT_REFERENCE = b'LREF', bytes(4)
NAME_LEN = 20
# Format 2 fits the smallest tags too (NTAG210 / Ultralight: user pages 4..15, 5x10mm
# ones among them): the pen, a key into the pen library (plot/profiles/pens.toml),
# on 4..5, 8 characters; the colour on 10: R G B and FORMAT_2 (FORMAT_2_NO_COLOR: none).
# Page 10 goes last: a tag written halfway stays format 1. Without it: format 1, no pen,
# no colour. One read covers 4 pages: 4, 8, 12 read the whole tag.
PAGE_PEN, PAGE_COLOR = 4, 10
FORMAT_2, FORMAT_2_NO_COLOR = 0xC2, 0xC0
PEN_LEN = 8
PEN_CHARS = set('abcdefghijklmnopqrstuvwxyz0123456789-_.')


def parse_pins(text):
    '''"15:41, 14:42" -> {15: 41, 14: 42}, MCP23017 pin -> tool.'''
    pins = {}
    for item in text.split(','):
        pin, _, tool = item.strip().partition(':')
        pins[int(pin)] = int(tool)
    return pins


def decode_holders(gpio, pins):
    return frozenset(tool for pin, tool in pins.items() if not gpio >> pin & 1)


def encode_num(x):
    '''-> 4 bytes: sign, integer part, hundredths, 0.'''
    whole, frac = divmod(round(abs(x) * 100), 100)
    if whole > 255:
        raise ValueError(f"{x} does not fit on a tag")
    return bytes([1 if x < 0 else 0, whole, frac, 0])


def decode_num(b):
    return round((-1 if b[0] == 1 else 1) * (b[1] + b[2] / 100), 2)


def encode_name(name):
    return name.encode()[:NAME_LEN].ljust(NAME_LEN)


def decode_name(b):
    return b.decode(errors='ignore').strip('\x00 ') or '<unknown>'


def encode_color(color):
    '''"#rrggbb" -> page 10, None / "" -> none (still format 2).'''
    if not color:
        return bytes([0, 0, 0, FORMAT_2_NO_COLOR])
    c = color.lstrip('#')
    try:
        rgb = bytes.fromhex(c)
    except ValueError:
        rgb = b''
    if len(rgb) != 3:
        raise ValueError(f"colour {color!r}: give it as #rrggbb")
    return rgb + bytes([FORMAT_2])


def decode_color(b):
    return '#' + bytes(b[:3]).hex() if b[3] == FORMAT_2 else None


def encode_pen(pen):
    pen = (pen or '').strip().lower()
    if len(pen) > PEN_LEN or not set(pen) <= PEN_CHARS:
        raise ValueError(f"pen {pen!r}: up to {PEN_LEN} of a-z 0-9 - _ .")
    return pen.encode().ljust(PEN_LEN, b'\x00')


def decode_pen(b):
    return bytes(b).rstrip(b'\x00').decode(errors='ignore') or None


@dataclass
class Tag:
    uid: str
    dx: float
    dy: float
    dz: float
    name: str
    reference: bool = False
    pen: str | None = None      # format 2: the pen library's key
    color: str | None = None    # format 2: #rrggbb


class ToolHolder:

    def __init__(self, reactor, bus, pins, address=0x20, tag_address=0x24, say=None,
                 interval=INTERVAL, settle=SETTLE):
        self.reactor = reactor
        self.pins = pins
        self.mcp = MCP23017(bus, address)
        self.nfc = PN532(bus, tag_address, pause=self._pause)
        self.say = say or (lambda msg: None)
        self.interval = interval
        self.settle = settle
        self.listeners = {}         # kind -> [callback(...)]
        self.timer = None
        self.ok = False             # the MCP23017 answers and is set up
        self.nfc_ready = False
        self.occupied = None        # frozenset of tools, once settled
        self.changed_at = 0.0
        self.expected = {}          # tool -> (occupied, until)
        self._pending = None
        self._count = 0

    @property
    def tools(self):
        return frozenset(self.pins.values())

    def on(self, kind, callback):
        self.listeners.setdefault(kind, []).append(callback)

    def _emit(self, kind, *args):
        for callback in self.listeners.get(kind, ()):
            callback(*args)

    def _pause(self, seconds):
        self.reactor.pause(self.reactor.monotonic() + seconds)

    # Holders
    def start(self):
        if self.timer is None:
            self.timer = self.reactor.register_timer(self._tick, self.reactor.NOW)

    def stop(self):
        if self.timer is not None:
            self.reactor.unregister_timer(self.timer)
            self.timer = None

    def read(self):
        '''The holders with their tool, now. Raises OSError.'''
        try:
            if not self.ok:
                self.mcp.setup_inputs(sum(1 << pin for pin in self.pins))
                self.ok = True
                self._emit('status', True)
            return decode_holders(self.mcp.read(), self.pins)
        except OSError:
            if self.ok:
                self.ok = False
                self.say("[Tool holder] lost the MCP23017")
                self._emit('status', False)
            raise

    def sample(self):
        '''The holders with their tool, read until `settle` reads agree.'''
        last, same = None, 0
        for _ in range(10):
            state = self.read()
            same = same + 1 if state == last else 1
            last = state
            if same >= self.settle:
                return state
            self._pause(SAMPLE_GAP)
        raise RuntimeError("tool holder readings do not settle")

    def expect(self, tool, occupied, window=EXPECT_WINDOW):
        '''The next change of `tool`'s holder to `occupied` is ours, not a hand's.'''
        self.expected[tool] = (occupied, self.reactor.monotonic() + window)

    def quiet(self, tool, window=EXPECT_WINDOW):
        '''Every change of `tool`'s holder is ours until forget(): going in and out of it.'''
        self.expected[tool] = (ANY, self.reactor.monotonic() + window)

    def forget(self, tool):
        self.expected.pop(tool, None)

    def resync(self):
        '''Takes the holders as they are now, telling nobody (after a quiet() move).'''
        state = self.sample()
        self.occupied, self._pending = state, None
        return state

    def busy(self):
        '''One of our own tool changes is on its way.'''
        now = self.reactor.monotonic()
        return any(until > now for _, until in self.expected.values())

    def _was_expected(self, tool, occupied, now):
        want, until = self.expected.get(tool, (None, 0))
        if until <= now or want not in (occupied, ANY):
            return False
        if want != ANY:
            del self.expected[tool]
        return True

    def _tick(self, eventtime):
        try:
            state = self.read()
        except OSError:
            return eventtime + self.interval * 5
        self._update(state, eventtime)
        return eventtime + self.interval

    def _update(self, state, now):
        if state == self.occupied:
            self._pending = None
            return
        if state != self._pending:
            self._pending, self._count = state, 0
        self._count += 1
        if self._count < self.settle:
            return
        old, self.occupied, self._pending = self.occupied, state, None
        self.changed_at = now
        if old is None:
            self._emit('ready', state)
            return
        added, removed = state - old, old - state
        manual = frozenset(t for t in added if not self._was_expected(t, True, now)) \
            | frozenset(t for t in removed if not self._was_expected(t, False, now))
        self._emit('change', state, added, removed, manual)

    # Tags
    def _begin_nfc(self):
        if not self.nfc_ready:
            ic, ver, rev, _ = self.nfc.begin()
            self.nfc_ready = True
            self.say(f"[Tag] PN532 firmware {ver}.{rev}")

    def _tag_io(self, fn):
        try:
            self._begin_nfc()
            return fn()
        except (OSError, TimeoutError, RuntimeError):
            self.nfc_ready = False
            raise

    def begin_tag_reader(self):
        self._tag_io(lambda: None)

    def read_tag(self, timeout=0.5):
        '''The tag of the tool over the reader, None when there is none.'''
        return self._tag_io(lambda: self._read_tag(timeout))

    def _read_tag(self, timeout):
        uid = self.nfc.read_uid(timeout)
        if uid is None:
            return None
        data = bytes(self.nfc.ntag_read(4)) + bytes(self.nfc.ntag_read(8)) + bytes(self.nfc.ntag_read(12))
        page = lambda p, n=1: data[(p - 4) * 4:(p - 4 + n) * 4]
        nums = page(PAGE_DX, 4)
        pen = color = None
        if page(PAGE_COLOR)[3] in (FORMAT_2, FORMAT_2_NO_COLOR):
            pen = decode_pen(page(PAGE_PEN, 2))
            color = decode_color(page(PAGE_COLOR))
        return Tag(uid.hex(), decode_num(nums[0:4]), decode_num(nums[4:8]),
                   decode_num(nums[8:12]), decode_name(page(PAGE_NAME, 5)), bytes(nums[12:16]) == REFERENCE,
                   pen, color)

    def write_tag(self, dx=None, dy=None, dz=None, name=None, reference=None, pen=None, color=None,
                  timeout=0.5):
        '''Writes the given fields only, reads the tag back -> Tag. pen / color: "" clears.'''
        if pen is not None:
            encode_pen(pen)
        if color is not None:
            encode_color(color)
        return self._tag_io(lambda: self._write_tag(dx, dy, dz, name, reference, pen, color, timeout))

    def _write_tag(self, dx, dy, dz, name, reference, pen, color, timeout):
        if self.nfc.read_uid(timeout) is None:
            raise RuntimeError("no tag on the reader")
        if pen is not None or color is not None:
            # Format 2 from here: a format 1 tag gets the mark, and no pen or colour but these
            old = self._read_tag(timeout)
            if old is None:
                raise RuntimeError("no tag on the reader")
            pen = (old.pen or '') if pen is None else pen
            color = (old.color or '') if color is None else color
            data = encode_pen(pen)
            for i in range(0, PEN_LEN, 4):
                self.nfc.ntag_write(PAGE_PEN + i // 4, data[i:i + 4])
            self.nfc.ntag_write(PAGE_COLOR, encode_color(color))       # last: now it is format 2
        for i, value in enumerate((dx, dy, dz)):
            if value is not None:
                self.nfc.ntag_write(PAGE_DX + i, encode_num(value))
        if name is not None:
            data = encode_name(name)
            for i in range(0, NAME_LEN, 4):
                self.nfc.ntag_write(PAGE_NAME + i // 4, data[i:i + 4])
        if reference is not None:
            self.nfc.ntag_write(PAGE_FLAGS, REFERENCE if reference else NOT_REFERENCE)
        tag = self._read_tag(timeout)
        wrote = {'dx': dx, 'dy': dy, 'dz': dz}
        if tag is None or any(v is not None and abs(getattr(tag, k) - v) > 0.006 for k, v in wrote.items()) \
                or (name is not None and tag.name != decode_name(encode_name(name))) \
                or (reference is not None and tag.reference != bool(reference)) \
                or (pen is not None and (tag.pen or '') != pen.strip().lower()) \
                or (color is not None and (tag.color or '') != (color.lower() if color else '')):
            raise RuntimeError(f"the tag reads back differently: {tag}")
        return tag
