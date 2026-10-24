# Limn Half Wire - a UART on one open-drain wire (PIO + DMA), for lib/link.py
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# The pogo's BED_DATA: LIT (GP0) <-> the bed's first node (GP0), 4k7 pull-up on
# LIT's side. Either end pulls the line low or lets go (pindirs, the pin's
# output stays 0), so nothing fights. 8N1, LSB first, like a UART.
#
# RX: a PIO program on the pin, its FIFO emptied by DMA into a ring (2 KiB),
# so a main loop held for 25 ms (USB prints, GC) loses nothing. TX: DMA into
# a second state machine. Each side hears its own bytes: write() counts them
# and the reads drop them. Who talks when is lib/link.py's HalfPort.
#
# Same face as machine.UART for link.Port: any(), read(n), write(data), txdone().
import time
import uctypes
import rp2
from machine import Pin

PIO1_BASE = 0x50300000      # state machines 4-7: PIO0 is left to the apps
TXF = 0x010
RXF = 0x020
DREQ_PIO1_TX0 = 8
DREQ_PIO1_RX0 = 12
RING_BITS = 11              # 2 KiB
RING = 1 << RING_BITS
COUNT = 0x7FFFFFFF          # bytes before the RX DMA is set up again


@rp2.asm_pio(out_shiftdir=rp2.PIO.SHIFT_RIGHT, side_pindir=True, sideset_init=rp2.PIO.IN_HIGH)
def _tx():
    # Fed inverted bytes: pindir 1 = drive low = a 0 bit.
    pull()                  .side(0) [7]    # idle and stop bit: let go
    set(x, 7)               .side(1) [7]    # start bit: low
    label('bit')
    out(pindirs, 1)                  [6]
    jmp(x_dec, 'bit')

@rp2.asm_pio(in_shiftdir=rp2.PIO.SHIFT_RIGHT)
def _rx():
    label('start')
    wait(0, pin, 0)                         # start bit
    set(x, 7)                        [10]   # to the middle of bit 0
    label('bit')
    in_(pins, 1)
    jmp(x_dec, 'bit')                [6]
    jmp(pin, 'stop')
    wait(1, pin, 0)                         # no stop bit (a break, the other side unpowered): drop it
    jmp('start')
    label('stop')
    push(block)                             # the byte in bits 31-24


class HalfWire:

    def __init__(self, pin, baud=115200, sm=4):
        self.pin = Pin(pin, Pin.IN, Pin.PULL_UP)    # the bed's end, undocked: no 4k7 there
        self.bit_us = 1000000 / baud
        n = sm - 4
        self.tx_sm = rp2.StateMachine(sm, _tx, freq=8 * baud, sideset_base=self.pin, out_base=self.pin,
                                      set_base=self.pin)
        self.tx_sm.exec('set(pins, 0)')     # the output latch low, for good: only pindirs change
        self.tx_sm.exec('set(pindirs, 0)')
        self.rx_sm = rp2.StateMachine(sm + 1, _rx, freq=8 * baud, in_base=self.pin, jmp_pin=self.pin)
        self.txf = PIO1_BASE + TXF + 4 * n
        self.rxf = PIO1_BASE + RXF + 4 * (n + 1)
        self.dreq_tx = DREQ_PIO1_TX0 + n
        self.dreq_rx = DREQ_PIO1_RX0 + n + 1

        # The RX ring must sit on a RING boundary for the DMA's address wrap.
        self._mem = bytearray(2 * RING)
        at = uctypes.addressof(self._mem)
        self._off = ((at + RING - 1) & ~(RING - 1)) - at
        self._ring = memoryview(self._mem)[self._off:self._off + RING]
        self.rx_dma = rp2.DMA()
        self.tx_dma = rp2.DMA()
        self._tx_buf = None         # kept alive while the DMA reads it
        self._tx_end = time.ticks_us()
        self._skip = 0              # our own bytes still to come back
        self.overruns = 0
        self._start_rx()
        self.tx_sm.active(1)
        self.rx_sm.active(1)

    def _start_rx(self):
        self.rx_dma.active(0)
        self._got = 0               # bytes taken out of the ring
        ctrl = self.rx_dma.pack_ctrl(size=0, inc_read=False, inc_write=True, ring_size=RING_BITS,
                                     ring_sel=True, treq_sel=self.dreq_rx)
        self.rx_dma.config(read=self.rxf + 3, write=uctypes.addressof(self._mem) + self._off,
                           count=COUNT, ctrl=ctrl, trigger=True)

    def _arrived(self):
        return COUNT - self.rx_dma.count

    def any(self):
        n = self._arrived() - self._got
        if n > RING:
            self.overruns += 1
            self._got = self._arrived() - RING
            n = RING
        drop = min(n, self._skip)
        if drop:
            self._got += drop
            self._skip -= drop
            n -= drop
        return n

    def read(self, n):
        n = min(n, self.any())
        if not n:
            return b''
        i = self._got & (RING - 1)
        if i + n <= RING:
            out = bytes(self._ring[i:i + n])
        else:
            out = bytes(self._ring[i:]) + bytes(self._ring[:i + n - RING])
        self._got += n
        if self._got > COUNT - (1 << 24):   # days of traffic: start the ring over
            self._start_rx()
        return out

    def write(self, data):
        '''Starts sending all of `data`, returns at once. Only call when txdone().'''
        self.any()                  # what came in before is real data: count the echo from here
        self._skip += len(data)
        self._tx_buf = bytes(b ^ 0xFF for b in data)
        ctrl = self.tx_dma.pack_ctrl(size=0, inc_read=True, inc_write=False, treq_sel=self.dreq_tx)
        self.tx_dma.config(read=self._tx_buf, write=self.txf, count=len(data), ctrl=ctrl, trigger=True)
        self._tx_end = time.ticks_add(time.ticks_us(), int((len(data) * 10 + 2) * self.bit_us))
        return len(data)

    def txdone(self):
        return (not self.tx_dma.active() and self.tx_sm.tx_fifo() == 0
                and time.ticks_diff(time.ticks_us(), self._tx_end) >= 0)
