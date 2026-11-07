# Pen force while drawing: LIT cell samples + Klipper's trapq, on one clock.
# Runs on the limn Pi next to ~/claude-cell (zcell.py: Lit, gcode).
import json, socket, sys, threading, time
sys.path.insert(0, '/home/pi/claude-cell')
from zcell import Lit, gcode

SOCK = '/home/pi/printer_data/comms/klippy.sock'


def mono():
    return time.clock_gettime(time.CLOCK_MONOTONIC_RAW)   # Klipper's reactor clock


class Klippy:
    """klippy.sock client: trapq segments (print time) + print time <-> monotonic."""

    def __init__(self):
        self.s = socket.socket(socket.AF_UNIX); self.s.connect(SOCK)
        self.segs, self.sync, self.replies, self._id = [], [], {}, 0
        threading.Thread(target=self._run, daemon=True).start()
        self.call('motion_report/dump_trapq', name='toolhead', response_template={'key': 'trapq'})

    def call(self, method, **params):
        self._id += 1
        self.s.sendall(json.dumps({'id': self._id, 'method': method, 'params': params}).encode() + b'\x03')
        return self._id

    def _run(self):
        buf = b''
        while True:
            buf += self.s.recv(65536)
            *msgs, buf = buf.split(b'\x03')
            for m in msgs:
                d = json.loads(m)
                if d.get('key') == 'trapq':
                    self.segs.extend(d['params']['data'])
                elif 'id' in d:
                    self.replies[d['id']] = d

    def clock(self):
        """(monotonic, print_time) pair from Klipper, via estimated_print_time."""
        i = self.call('objects/query', objects={'toolhead': ['estimated_print_time']})
        while i not in self.replies:
            time.sleep(0.002)
        r = self.replies.pop(i)['result']
        self.sync.append((r['eventtime'], r['status']['toolhead']['estimated_print_time']))
        return self.sync[-1]


class Rec:
    """Cell samples stamped on the monotonic clock; Lit keeps time.time() too."""

    def __init__(self, hz=100):
        self.lit, self.kl = Lit(), Klippy()
        time.sleep(2)
        self.lit.dock.send(f'rate({hz})')
        self.dt = time.time() - mono()      # wall -> monotonic, the Lit thread stamps wall time
        threading.Thread(target=self._clock, daemon=True).start()

    def _clock(self):
        while True:
            self.kl.clock(); time.sleep(1)

    def dump(self, path, t0, meta):
        with open(path, 'w') as f:
            f.write(json.dumps({'meta': meta, 'sync': self.kl.sync}) + '\n')
            for t, g, raw, fl in self.lit.samples:
                if t >= t0:
                    f.write(json.dumps(['c', round(t - self.dt, 4), round(g, 3), fl]) + '\n')
            for s in self.kl.segs:
                f.write(json.dumps(['q'] + s) + '\n')
