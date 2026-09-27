# Limn - sensor samples, as they arrive from the Dock's `data` lines
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
from collections import deque, namedtuple

# Sensor kinds and states, as in micropython/lib/link.py
FSR = 4
RTP = 5
S_SAMPLE = 42
S_MATRIX = 43

Sample = namedtuple('Sample', ('t', 'hop', 'kind', 'state', 'values'))


class Samples:
    '''The recent samples of every node, plus a recording for probe runs.'''

    def __init__(self, keep=4000):
        self.recent = deque(maxlen=keep)
        self.recorded = []
        self.recording = False

    def add(self, sample):
        self.recent.append(sample)
        if self.recording:
            self.recorded.append(sample)

    def start(self):
        self.recorded = []
        self.recording = True

    def stop(self):
        self.recording = False
        recorded, self.recorded = self.recorded, []
        return recorded

    def since(self, t, hop=None, kind=None, state=None):
        return [s for s in self.recent
                if s.t >= t
                and (hop is None or s.hop == hop)
                and (kind is None or s.kind == kind)
                and (state is None or s.state == state)]

    def latest(self, hop, kind):
        for s in reversed(self.recent):
            if s.hop == hop and s.kind == kind:
                return s
        return None
