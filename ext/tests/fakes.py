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


def run_tests(module_globals):
    tests = [(name, fn) for name, fn in module_globals.items() if name.startswith('test_')]
    for name, fn in tests:
        fn()
        print('ok', name)
    print(len(tests), 'passed')
