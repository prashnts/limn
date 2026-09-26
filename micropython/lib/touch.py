# Limn Touch Line - tells the Dock about a touch over the DETECT line
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Each bed MCU has a Schottky diode from `touch_pin` (node.json) to the DETECT
# net. Raising the pin lifts DETECT above every bed ID, and the Dock turns that
# edge into the probe pulse. See micropython/STRATEGY.md.
#
# Without `touch_pin` (no diode fitted yet) the node never arms, and the RTP
# keeps measuring all the time instead of waiting in pen detect mode.
import time
from machine import Pin

HOLD_MS = 3     # long enough for the Dock's polling to see it


class TouchLine:

    def __init__(self, node):
        pin = node.get('touch_pin')
        self.pin = Pin(pin, Pin.OUT, value=0) if pin is not None else None
        self.role = node.get('role')
        self.armed = False
        self.latched = False    # fired for the current touch, waits for release
        self.raised_at = 0

    def command(self, cmd):
        '''Handles b'arm(<role>)' / b'disarm()'. Returns True if it was one.'''
        if cmd == b'disarm()':
            self.armed = False
        elif cmd.startswith(b'arm(') and cmd.endswith(b')'):
            self.armed = self.pin is not None and cmd[4:-1].decode() in (self.role, 'all')
        else:
            return False
        self.latched = False
        return True

    def fire(self, pin=None):
        '''A touch started. Safe to use as a hard IRQ handler: no allocation.'''
        if self.armed and not self.latched and self.pin:
            self.pin.value(1)
            self.raised_at = time.ticks_ms()
            self.latched = True

    def tick(self):
        '''Drops the line after HOLD_MS. Returns True while it is still up.'''
        if not (self.pin and self.pin.value()):
            return False
        if time.ticks_diff(time.ticks_ms(), self.raised_at) >= HOLD_MS:
            self.pin.value(0)
            return False
        return True

    def update(self, touching):
        '''Main loop: fires on a new touch, drops the line after HOLD_MS, and
        allows the next touch once this one is released.'''
        if touching:
            self.fire()
        if not self.tick() and not touching:
            self.latched = False
