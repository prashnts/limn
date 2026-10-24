# Limn Touch Line - tells Klipper about a touch: BED_PROBE, or the Dock's DETECT
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# `probe_pin` (node.json, the bed's first node on LIT): the pogo's BED_PROBE,
# high = OK, pulled low for HOLD_MS on a touch. On LIT it sits in series with
# the head's touch line (Q952), so it reaches Klipper's probe pin in hardware.
# Nodes further down have no pogo: the first node relays their touches (a
# sample frame from below while something is armed) on its own BED_PROBE.
#
# `touch_pin` (the Dock, lrt_dock_mcu.py): a Schottky diode from the pin to the
# DETECT net. Raising the pin lifts DETECT above every bed ID, and the Dock
# turns that edge into the probe pulse. See micropython/STRATEGY.md.
#
# Without either the node never arms, and the RTP keeps measuring all the time
# instead of waiting in pen detect mode.
import time
from machine import Pin

HOLD_MS = 3     # long enough for the Dock's polling to see it
PROBE_HOLD_MS = 10  # BED_PROBE: like the Dock's pulse, Klipper samples it directly

T_DATA = 4      # link.T_DATA, S_SAMPLE: not imported, the RTP's IRQ path stays small
S_SAMPLE = 42


class TouchLine:

    def __init__(self, node):
        probe = node.get('probe_pin')
        pin = probe if probe is not None else node.get('touch_pin')
        self.on = 0 if probe is not None else 1     # the level that says "touched"
        self.hold_ms = PROBE_HOLD_MS if probe is not None else HOLD_MS
        self.pin = Pin(pin, Pin.OUT, value=1 - self.on) if pin is not None else None
        self.role = node.get('role')
        self.armed = False
        self.relaying = False   # something below is armed: their touches go out on our pin
        self.latched = False    # fired for the current touch, waits for release
        self.raised_at = 0

    def command(self, cmd):
        '''Handles b'arm(<role>)' / b'disarm()'. Returns True if it was one.'''
        if cmd == b'disarm()':
            self.armed = self.relaying = False
        elif cmd.startswith(b'arm(') and cmd.endswith(b')'):
            role = cmd[4:-1].decode()
            self.armed = self.pin is not None and role in (self.role, 'all')
            self.relaying = self.pin is not None and self.on == 0 and role != self.role
        else:
            return False
        self.latched = False
        return True

    def _up(self):
        return self.pin.value() == self.on

    def fire(self, pin=None):
        '''A touch started. Safe to use as a hard IRQ handler: no allocation.'''
        if self.armed and not self.latched and self.pin:
            self.pin.value(self.on)
            self.raised_at = time.ticks_ms()
            self.latched = True

    def relay(self, frame):
        '''link.below: a touch sample from a node below, while it is armed.'''
        if (self.relaying and frame.type == T_DATA and len(frame.payload) > 1
                and frame.payload[1] == S_SAMPLE and not self._up()):
            self.pin.value(self.on)
            self.raised_at = time.ticks_ms()

    def tick(self):
        '''Drops the line after its hold time. Returns True while it is still up.'''
        if not (self.pin and self._up()):
            return False
        if time.ticks_diff(time.ticks_ms(), self.raised_at) >= self.hold_ms:
            self.pin.value(1 - self.on)
            return False
        return True

    def update(self, touching):
        '''Main loop: fires on a new touch, drops the line after its hold time,
        and allows the next touch once this one is released.'''
        if touching:
            self.fire()
        if not self.tick() and not touching:
            self.latched = False
