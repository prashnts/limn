# Limn ADS1220 - 24 bit bridge ADC over SPI
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Several chips share one SPI bus (SPI mode 1), each with its own CS and DRDY:
# DOUT goes Hi-Z while CS is high. Register layout as in the datasheet
# (SBAS501) and Klipper's klippy/extras/ads1220.py. See docs/load-cell.md.
#
#   adc = ADS1220(spi, cs=13, drdy=14, sps=20, mux=(0, 3))
#   adc.start()
#   if adc.ready():
#       counts = adc.read()
from machine import Pin

CMD_RESET = 0x06
CMD_START = 0x08
CMD_RREG  = 0x20
CMD_WREG  = 0x40

# (AINp, AINn) -> MUX[3:0]; 'avss' as AINn for single ended
MUX = {(0, 1): 0x0, (0, 2): 0x1, (0, 3): 0x2, (1, 2): 0x3, (1, 3): 0x4,
       (2, 3): 0x5, (1, 0): 0x6, (3, 2): 0x7,
       (0, 'avss'): 0x8, (1, 'avss'): 0x9, (2, 'avss'): 0xA, (3, 'avss'): 0xB}
GAINS = (1, 2, 4, 8, 16, 32, 64, 128)
SPS_NORMAL = (20, 45, 90, 175, 330, 600, 1000)
SPS_TURBO  = (40, 90, 180, 350, 660, 1200, 2000)
VREFS = {'internal': 0, 'REF0': 1, 'REF1': 2, 'AVDD': 3}

FULL = 1 << 23


class ADS1220:

    def __init__(self, spi, cs, drdy, gain=128, sps=20, mux=(0, 1), vref='REF0',
                 vref_volts=3.3, continuous=True, turbo=False):
        self.spi = spi
        self.cs = Pin(cs, Pin.OUT, value=1)
        self.drdy = Pin(drdy, Pin.IN, Pin.PULL_UP)
        self.gain = gain
        self.sps = sps
        self.mux = mux
        self.vref = vref
        self.vref_volts = 2.048 if vref == 'internal' else vref_volts
        self.continuous = continuous
        self.turbo = turbo
        self.ok = False         # found and configured, see setup()
        self.regs = None        # what the chip read back
        self._buf = bytearray(3)
        self._cmd = bytearray(1)

    def _command(self, cmd):
        self._cmd[0] = cmd
        self.cs(0)
        self.spi.write(self._cmd)
        self.cs(1)

    def write_regs(self, first, values):
        self.cs(0)
        self.spi.write(bytes([CMD_WREG | first << 2 | len(values) - 1]) + bytes(values))
        self.cs(1)

    def read_regs(self, first=0, n=4):
        out = bytearray(n)
        self.cs(0)
        self.spi.write(bytes([CMD_RREG | first << 2 | n - 1]))
        self.spi.readinto(out, 0)
        self.cs(1)
        return bytes(out)

    def config(self):
        '''The four configuration registers for the current settings.'''
        rates = SPS_TURBO if self.turbo else SPS_NORMAL
        if self.sps not in rates:
            raise ValueError('sps %s not in %s' % (self.sps, rates))
        # The 50/60 Hz FIR only works at 20 SPS (normal mode).
        notch = 1 if self.sps == 20 and not self.turbo else 0
        bypass = 1 if self.mux[1] == 'avss' and self.gain <= 4 else 0
        return bytes([
            MUX[self.mux] << 4 | GAINS.index(self.gain) << 1 | bypass,
            rates.index(self.sps) << 5 | (2 if self.turbo else 0) << 3 | (1 if self.continuous else 0) << 2,
            VREFS[self.vref] << 6 | notch << 4,
            0x00,               # DRDYM off: DOUT is shared, DRDY has its own pin
        ])

    def setup(self):
        '''Resets and configures the chip. Returns (ok, reason). A missing chip
        reads back the wrong registers (all 0 or all 1).'''
        self._command(CMD_RESET)
        _wait_us(100)       # 50 µs + 32 clocks; may run with IRQs off, so no sleep
        after_reset = self.read_regs()
        want = self.config()
        self.write_regs(0, want)
        self.regs = self.read_regs()
        if after_reset != b'\x00\x00\x00\x00':
            self.ok = False
            return False, 'reset state %s' % _hex(after_reset)
        self.ok = self.regs == want
        return self.ok, '' if self.ok else 'registers %s, wanted %s' % (_hex(self.regs), _hex(want))

    def start(self):
        '''Starts conversions (continuous), or one conversion (single shot).'''
        self._command(CMD_START)

    def set_mux(self, mux):
        '''Switches the input pair. The next conversion is fully settled
        (the filter restarts), so a single shot after this is good to use.'''
        self.mux = mux
        self.write_regs(0, self.config()[:1])

    def ready(self):
        return not self.drdy.value()

    def read(self):
        '''The last conversion as signed counts (-2^23 .. 2^23 - 1).'''
        self.cs(0)
        self.spi.readinto(self._buf, 0)
        self.cs(1)
        b = self._buf
        v = b[0] << 16 | b[1] << 8 | b[2]
        return v - (1 << 24) if v & 0x800000 else v

    def volts(self, counts):
        return counts * self.vref_volts / self.gain / FULL

    def period_ms(self):
        return 1000 / self.sps


def _hex(data):
    return ' '.join('%02x' % b for b in data)

def _wait_us(us):
    '''Busy wait. time.sleep_ms() with interrupts disabled never returns on the
    RP2040 (it waits for an interrupt): the board hung until the watchdog.'''
    import time
    try:
        t = time.ticks_us()
        while time.ticks_diff(time.ticks_us(), t) < us:
            pass
    except AttributeError:
        time.sleep(us / 1e6)
