# Limn - the Pi's own I2C bus: the tool holders' MCP23017 and the PN532 tag reader
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Plain Linux i2c-dev, no extra packages (klippy-env has no blinka). Every
# transfer is one I2C_RDWR ioctl, one transaction on the bus, so other
# processes on the same bus can't slip in between a register write and its
# read. Nothing here knows about Klipper: waiting goes through `pause`.
import os
import fcntl
import ctypes

I2C_TIMEOUT = 0x0702    # in 10ms units
I2C_RDWR = 0x0707
I2C_M_RD = 0x0001


class _Msg(ctypes.Structure):
    _fields_ = [('addr', ctypes.c_uint16), ('flags', ctypes.c_uint16),
                ('len', ctypes.c_uint16), ('buf', ctypes.POINTER(ctypes.c_uint8))]


class _RdWr(ctypes.Structure):
    _fields_ = [('msgs', ctypes.POINTER(_Msg)), ('nmsgs', ctypes.c_uint32)]


class Bus:

    def __init__(self, number, timeout=0.02):
        self.path = f'/dev/i2c-{number}'
        self.timeout = timeout
        self.fd = None

    def open(self):
        if self.fd is None:
            self.fd = os.open(self.path, os.O_RDWR)
            fcntl.ioctl(self.fd, I2C_TIMEOUT, max(1, round(self.timeout * 100)))

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def transfer(self, addr, *parts):
        '''One transaction: each part is bytes to write or a count to read -> [bytes read].'''
        self.open()
        msgs = (_Msg * len(parts))()
        bufs = []
        for msg, part in zip(msgs, parts):
            if isinstance(part, int):
                buf = (ctypes.c_uint8 * part)()
                msg.flags, msg.len = I2C_M_RD, part
            else:
                buf = (ctypes.c_uint8 * len(part)).from_buffer_copy(bytes(part))
                msg.flags, msg.len = 0, len(part)
            msg.addr = addr
            msg.buf = ctypes.cast(buf, ctypes.POINTER(ctypes.c_uint8))
            bufs.append(buf)
        fcntl.ioctl(self.fd, I2C_RDWR, _RdWr(msgs, len(parts)))
        return [bytes(buf) for buf, part in zip(bufs, parts) if isinstance(part, int)]


class MCP23017:
    '''16 GPIOs, pin 0..7 on port A, 8..15 on port B (IOCON.BANK=0, the default).'''
    IODIR = 0x00
    GPPU = 0x0C
    GPIO = 0x12

    def __init__(self, bus, address=0x20):
        self.bus = bus
        self.address = address

    def read16(self, reg):
        a, b = self.bus.transfer(self.address, bytes([reg]), 2)[0]
        return a | b << 8

    def write16(self, reg, value):
        self.bus.transfer(self.address, bytes([reg, value & 0xFF, value >> 8]))

    def setup_inputs(self, mask):
        '''Pins in `mask` become inputs with pull-ups, the others are left alone.'''
        self.write16(self.IODIR, self.read16(self.IODIR) | mask)
        self.write16(self.GPPU, self.read16(self.GPPU) | mask)

    def read(self):
        return self.read16(self.GPIO)


# PN532, as in adafruit_pn532 (the frames of its user manual, section 6.2)
ACK = b'\x00\x00\xff\x00\xff\x00'
HOST_TO_PN532 = 0xD4
PN532_TO_HOST = 0xD5
POLL = 0.01

CMD_FIRMWARE_VERSION = 0x02
CMD_SAM_CONFIGURATION = 0x14
CMD_RF_CONFIGURATION = 0x32
CMD_IN_DATA_EXCHANGE = 0x40
CMD_IN_LIST_PASSIVE_TARGET = 0x4A
NTAG_READ = 0x30        # 4 pages, 16 bytes
NTAG_WRITE = 0xA2       # 1 page, 4 bytes


def build_frame(data):
    n = len(data)
    return bytes([0x00, 0x00, 0xFF, n, -n & 0xFF]) + bytes(data) + bytes([-sum(data) & 0xFF, 0x00])


def parse_frame(raw):
    '''-> the data of the frame in `raw` (leading 0x00s allowed).'''
    i = 0
    while i < len(raw) and raw[i] == 0x00:
        i += 1
    if i >= len(raw) - 2 or raw[i] != 0xFF:
        raise RuntimeError("PN532: no frame start")
    n, lcs = raw[i + 1], raw[i + 2]
    if (n + lcs) & 0xFF:
        raise RuntimeError("PN532: bad length checksum")
    data = raw[i + 3:i + 3 + n]
    if len(data) < n or (sum(data) + raw[i + 3 + n]) & 0xFF:
        raise RuntimeError("PN532: bad checksum")
    return bytes(data)


class PN532:

    def __init__(self, bus, address=0x24, pause=None):
        self.bus = bus
        self.address = address
        self.pause = pause

    def _ready(self, timeout):
        for _ in range(max(1, round(timeout / POLL))):
            try:
                if self.bus.transfer(self.address, 1)[0][0] == 0x01:
                    return True
            except OSError:
                pass            # it NAKs while busy
            self.pause(POLL)
        return False

    def _read(self, n):
        data = self.bus.transfer(self.address, n + 1)[0]
        if data[0] != 0x01:
            raise RuntimeError("PN532: not ready")
        return data[1:]

    def abort(self):
        '''An ACK from the host cancels the command in progress.'''
        try:
            self.bus.transfer(self.address, ACK)
        except OSError:
            pass

    def call(self, cmd, params=b'', length=0, timeout=1.0):
        '''Sends a command, waits for its ACK and its reply -> the reply's data.'''
        self.bus.transfer(self.address, build_frame(bytes([HOST_TO_PN532, cmd]) + bytes(params)))
        if not self._ready(timeout):
            raise TimeoutError(f"PN532: no ACK for 0x{cmd:02x}")
        if self._read(len(ACK)) != ACK:
            raise RuntimeError(f"PN532: bad ACK for 0x{cmd:02x}")
        if not self._ready(timeout):
            self.abort()
            raise TimeoutError(f"PN532: no reply to 0x{cmd:02x}")
        reply = parse_frame(self._read(length + 9))
        if reply[:2] != bytes([PN532_TO_HOST, cmd + 1]):
            raise RuntimeError(f"PN532: unexpected reply to 0x{cmd:02x}")
        return reply[2:]

    def begin(self, retries=0x10):
        '''Wakes it up, makes "no tag" come back after `retries` tries -> firmware version.'''
        try:
            self.call(CMD_SAM_CONFIGURATION, [0x01, 0x14, 0x01])
        except (OSError, TimeoutError, RuntimeError):
            self.call(CMD_SAM_CONFIGURATION, [0x01, 0x14, 0x01])    # the first one only woke it
        self.call(CMD_RF_CONFIGURATION, [0x05, 0xFF, 0x01, retries])
        return tuple(self.call(CMD_FIRMWARE_VERSION, length=4, timeout=0.5))

    def read_uid(self, timeout=1.0):
        '''The UID of the ISO14443A tag in the field, None when there is none.'''
        try:
            reply = self.call(CMD_IN_LIST_PASSIVE_TARGET, [0x01, 0x00], length=19, timeout=timeout)
        except TimeoutError:
            return None
        if not reply or reply[0] == 0:
            return None
        n = reply[5]            # Tg, SENS_RES(2), SEL_RES, NFCID length, NFCID
        return reply[6:6 + n]

    def ntag_read(self, page):
        '''Pages page..page+3, 16 bytes.'''
        reply = self.call(CMD_IN_DATA_EXCHANGE, [0x01, NTAG_READ, page], length=17)
        if not reply or reply[0] != 0x00:
            raise RuntimeError(f"PN532: could not read page {page}")
        return reply[1:17]

    def ntag_write(self, page, data):
        assert len(data) == 4
        reply = self.call(CMD_IN_DATA_EXCHANGE, [0x01, NTAG_WRITE, page, *data], length=1)
        if not reply or reply[0] != 0x00:
            raise RuntimeError(f"PN532: could not write page {page}")
