# Runs one MCU's installed files on CPython with a fake `machine`, used by
# tests/test_chain.py. Not meant to be run by hand.
#
#   UARTs   -> socket pairs handed over by the test (--uart ID:FD)
#   DETECT  -> a file per node in the sim folder while its touch pin is high
#   touches -> the test creates sim/stim_rtp or sim/stim_fsr
#   reset() -> the process restarts itself, keeping the sockets
import os
import sys
import json
import time
import types
import socket
import argparse
import threading
import traceback
import runpy

parser = argparse.ArgumentParser()
parser.add_argument('--name')
parser.add_argument('--root')
parser.add_argument('--sim')
parser.add_argument('--uart', action='append', default=[])
args = parser.parse_args()
ARGV = list(sys.argv)       # runpy replaces sys.argv[0] later

NAME, ROOT, SIM = args.name, args.root, args.sim
UART_FDS = {int(i): int(fd) for i, fd in (u.split(':') for u in args.uart)}
NODE = json.load(open(os.path.join(ROOT, 'node.json')))
ROLE = NODE['role']
XP, XM, YP, YM = NODE.get('panel_pins', [28, 26, 27, 29])
sys.dont_write_bytecode = True

time.sleep_ms = lambda ms: time.sleep(ms / 1000)
time.sleep_us = lambda us: None
time.ticks_ms = lambda: int(time.monotonic() * 1000)
time.ticks_diff = lambda a, b: a - b
sys.print_exception = lambda e: traceback.print_exception(e)

def sim_path(name):
    return os.path.join(SIM, name)

def stim(name):
    return os.path.exists(sim_path('stim_' + name))


# machine
machine = types.ModuleType('machine')
pins = {}       # id -> [mode, value]
irqs = {}       # id -> handler

class Pin:
    IN, OUT = 0, 1
    PULL_UP, PULL_DOWN = 1, 2
    IRQ_FALLING, IRQ_RISING = 4, 8

    def __init__(self, id, mode=None, pull=None, value=None):
        self.id = id
        if mode is not None:
            pins[id] = [mode, 0]
            if mode == Pin.OUT:
                self.value(value or 0)

    def value(self, v=None):
        mode, current = pins.get(self.id, [Pin.IN, 0])
        if v is None:
            if mode == Pin.OUT:
                return current
            if ROLE == 'rtp' and self.id == XP:
                return 0 if stim('rtp') else 1
            return 0
        pins[self.id] = [mode, v]
        if self.id == NODE.get('touch_pin'):
            path = sim_path('detect_' + NAME)
            if v:
                open(path, 'w').close()
            elif os.path.exists(path):
                os.remove(path)

    def on(self):
        self.value(1)

    def off(self):
        self.value(0)

    def irq(self, handler=None, trigger=None, hard=False):
        if handler:
            irqs[self.id] = handler
        else:
            irqs.pop(self.id, None)

class ADC:
    def __init__(self, pin):
        self.pin = pin.id

    def read_u16(self):
        if ROLE == 'dock':
            touched = any(f.startswith('detect_') for f in os.listdir(SIM))
            return 59000 if touched else 40000      # BED_4
        if ROLE == 'rtp':
            if stim('rtp'):
                return 30000
            return {YP: 65535, XM: 0}.get(self.pin, 30000)
        if ROLE == 'fsr':
            if stim('fsr') and self.pin == 28 and pins.get(12, [0, 0])[1]:
                return 60000
            return 100
        return 0

class UART:
    def __init__(self, id, baud=115200, **kw):
        self.sock = socket.socket(fileno=os.dup(UART_FDS[id]))
        self.sock.setblocking(False)
        self.buf = b''

    def _fill(self):
        try:
            while True:
                data = self.sock.recv(4096)
                if not data:
                    return
                self.buf += data
        except BlockingIOError:
            pass

    def any(self):
        self._fill()
        return len(self.buf)

    def read(self, n):
        self._fill()
        data, self.buf = self.buf[:n], self.buf[n:]
        return data

    def write(self, data):
        self.sock.setblocking(True)
        self.sock.sendall(data)
        self.sock.setblocking(False)
        return len(data)

    def txdone(self):
        return True

class Timer:
    PERIODIC, ONE_SHOT = 1, 0

    def __init__(self, id=-1):
        self._stop = None

    def init(self, period=1000, mode=1, callback=None):
        self.deinit()
        stop = self._stop = threading.Event()
        def run():
            while not stop.wait(period / 1000):
                callback(self)
                if mode == Timer.ONE_SHOT:
                    return
        threading.Thread(target=run, daemon=True).start()

    def deinit(self):
        if self._stop:
            self._stop.set()

class WDT:
    def __init__(self, timeout=0):
        pass

    def feed(self):
        time.sleep(0.0002)

def reset():
    sys.stdout.flush()
    os.execv(sys.executable, [sys.executable, '-u'] + ARGV)

machine.Pin, machine.ADC, machine.UART, machine.Timer, machine.WDT = Pin, ADC, UART, Timer, WDT
machine.reset = reset

class Mem32(dict):
    '''Pad registers read as after ADC(): input and pulls off.'''
    def __missing__(self, addr):
        return 0
machine.mem32 = Mem32()
machine.unique_id = lambda: NAME.encode().ljust(8, b'\0')[:8]
sys.modules['machine'] = machine

neopixel = types.ModuleType('neopixel')
class NeoPixel(list):
    def __init__(self, pin, n):
        super().__init__([(0, 0, 0)] * n)
    def write(self):
        pass
neopixel.NeoPixel = NeoPixel
sys.modules['neopixel'] = neopixel

rp2 = types.ModuleType('rp2')
class PIO:
    OUT_LOW = 0
class StateMachine:
    def __init__(self, *a, **kw):
        pass
    def active(self, on):
        pass
    def put(self, cycles):
        with open(sim_path('pulses'), 'a') as fp:
            fp.write('%.3f %d\n' % (time.time(), cycles))
rp2.PIO, rp2.StateMachine = PIO, StateMachine
rp2.asm_pio = lambda **kw: (lambda fn: fn)
sys.modules['rp2'] = rp2


# A hard IRQ on the pen-down edge.
def watch_irqs():
    was = False
    while True:
        now = ROLE == 'rtp' and stim('rtp')
        if now and not was and XP in irqs and pins.get(XP, [Pin.IN])[0] == Pin.IN:
            irqs[XP](Pin(XP))
        was = now
        time.sleep(0.001)
threading.Thread(target=watch_irqs, daemon=True).start()


class Stdin:
    '''Unbuffered, so select.poll() on it tells the truth.'''
    def fileno(self):
        return 0
    def read(self, n):
        return os.read(0, n).decode()
sys.stdin = Stdin()

os.chdir(ROOT)
sys.path[:0] = [os.path.join(ROOT, 'lib'), ROOT]
runpy.run_path('main.py', run_name='__main__')
