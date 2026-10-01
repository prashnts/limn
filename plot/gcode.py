# Limn plot - writing G-code
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# G0 is a travel, G1 the tool working (or coming down to work): the preview
# tells them apart by that. Axes that don't change are left out. After a
# macro that moves the head the position is unknown until `at()` says where
# it is, and the next move has all its axes. `moves` keeps each move's start
# and end, None where it isn't known, for the checks of emit.py.
EPS = 5e-4


def num(v):
    s = f'{v:.3f}'.rstrip('0').rstrip('.')
    return '0' if s in ('', '-0') else s


class Writer:
    def __init__(self):
        self.lines = []
        self.x = self.y = self.z = None
        self.f = None
        self._up = None         # the last line is a G0 of z alone: (z, F) from before it
        self.moves = []         # ((x, y, z) from, (x, y, z) to) of each move line

    def comment(self, text):
        self.lines.append(f'; {text}')
        self._up = None

    def raw(self, text, moves=True):
        '''Lines as they are; `moves`: they may move the head.'''
        for line in text.strip('\n').splitlines():
            self.lines.append(line.rstrip())
        self._up = None
        if moves:
            self.x = self.y = self.z = None
            self.f = None

    def at(self, x=None, y=None, z=None):
        self.x, self.y, self.z = x, y, z

    def _move(self, cmd, x, y, z, f):
        zonly = cmd == 'G0' and x is None and y is None and z is not None
        start = (self.x, self.y, self.z)
        if zonly and self._up is not None:
            # A z move right after another: one move, from where the first started
            self.lines.pop()
            start = self.moves.pop()[0]
            self.z, self.f = self._up
        before = (self.z, self.f)
        words = []
        for axis, v in (('x', x), ('y', y), ('z', z)):
            if v is None:
                continue
            cur = getattr(self, axis)
            if cur is not None and abs(cur - v) < EPS:
                continue
            words.append(axis.upper() + num(v))
            setattr(self, axis, float(v))
        self._up = None
        if not words:
            return False
        if f is not None and f != self.f:
            words.append('F' + num(f))
            self.f = f
        self.lines.append(cmd + ' ' + ' '.join(words))
        self.moves.append((start, (self.x, self.y, self.z)))
        if zonly:
            self._up = before
        return True

    def rapid(self, x=None, y=None, z=None, f=None):
        return self._move('G0', x, y, z, f)

    def line(self, x=None, y=None, z=None, f=None):
        return self._move('G1', x, y, z, f)

    def text(self):
        return '\n'.join(self.lines) + '\n'
