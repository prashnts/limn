# Limn - the few things the calibration routines need from Klipper
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# rtp.py and fsr.py only talk to the printer through this, so that the tests
# can hand them a simulated one.
from contextlib import contextmanager

TRAVEL_SPEED = 50       # mm/s
JOG_SPEED = 2           # mm/s, z moves close to a sensor


class Machine:

    def __init__(self, printer, gcmd):
        self.printer = printer
        self.gcmd = gcmd
        self.reactor = printer.get_reactor()
        self.gcode = printer.lookup_object('gcode')
        self.probe_obj = printer.lookup_object('probe')
        self.toolhead = printer.lookup_object('toolhead')

    def now(self):
        return self.reactor.monotonic()

    def pause(self, seconds):
        '''Waits while Klipper keeps running (the Dock's lines keep arriving).'''
        self.reactor.pause(self.reactor.monotonic() + seconds)

    def position(self):
        return self.toolhead.get_position()[:3]

    def move(self, x=None, y=None, z=None, speed=TRAVEL_SPEED):
        '''Raw machine coordinates, no gcode offsets or mesh. Plain floats: the
        routines compute with numpy, and a numpy float in Klipper's position
        breaks its status JSON.'''
        self.toolhead.manual_move([None if v is None else float(v) for v in (x, y, z)], float(speed))

    def wait_moves(self):
        self.toolhead.wait_moves()

    def probe(self):
        '''One BLTouch probe here -> Klipper's probe result (test_x, test_y, test_z, ..).'''
        session = self.probe_obj.start_probe_session(self.gcmd)
        try:
            session.run_probe(self.gcmd)
            return session.pull_probed_results()[0]
        finally:
            session.end_probe_session()

    def probe_offsets(self):
        return self.probe_obj.get_offsets()

    def gcode_run(self, script):
        self.gcode.run_script_from_command(script)

    def say(self, msg):
        self.gcmd.respond_info(msg)


@contextmanager
def lifted_on_error(machine, z):
    '''Anything goes wrong inside: go up to `z` first, then report.'''
    try:
        yield
    except BaseException:
        machine.move(z=z, speed=JOG_SPEED * 5)
        machine.wait_moves()
        raise
