# Plot Bed - load cells under the bed: a touch line for Klipper, the force for the host
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Three half-bridge feet carry the bed (docs/load-cell.md). Two ADS1220s on one
# SPI bus:
#   - sum:  the feet's midpoints averaged by resistors, read continuously
#           (~330/s). It drives the touch line: the fast channel.
#   - feet: cycles the feet one conversion each (~20/s): load per foot, point
#           of pressure. Its 50/60 Hz filter makes it the quiet one.
# The sum is read in a hard IRQ on its DRDY (`_on_sum`), which also decides the
# touch and sets the line: USB prints and GC hold the main loop for 3-25 ms, an
# IRQ runs through them. The main loop drains the samples it left (tare, jobs,
# streaming) and does everything else. Feet SPI traffic masks the IRQ.
# The touch line goes to a Klipper endstop through an NPN (open collector):
# `touch_out` high = OK, low = touched. It also reads touched while taring,
# without samples, or with the RP2040 off, so a probe never starts blind.
#
# Commands (USB, or down the chain like the other nodes):
#   tare()  calibrate()  calibrate(<g>)  calibrate(<g>, <foot>)
#   threshold(<g>)  threshold(<g>, <release g>)  stream(on|off)  rate(<Hz>)
#   arm(plot_bed)  disarm()  diag()  ping()  reset()  debug_on()  debug_off()
#   stall(<ms>): a test, the main loop busy while the IRQ keeps the line going
import json
import time
from array import array
from machine import Pin, SPI, Timer, WDT, reset, disable_irq, enable_irq
from neopixel import NeoPixel
from link import load_node, from_config, pack_load, Guard, T_CMD, T_HELLO, T_LOG, T_DATA
from link import S_CALIBRATING, S_CAL_FAILED, S_CALIBRATED, S_SAMPLE
from link import LOAD_TOUCH, LOAD_ARMED, LOAD_CAL, LOAD_SUM_OK, LOAD_FEET_OK, LOAD_TARING
from bridge import Bridge, teeprint
from ads1220 import ADS1220


try:
    import micropython
    micropython.alloc_emergency_exception_buf(100)
except (ImportError, AttributeError):
    pass

wdt = WDT(timeout=5000)
NODE = load_node()
ROLE = NODE.get('role', 'plot_bed')
EMBLEM = 'Limn - Plot Bed v1'
CAL_FILE = 'cal.json'

# Grams before calibrate(<g>), rough: 10 g on one foot is ~4.6 µε, a half
# bridge gives 3.3 V x 2.08 x ε / 2 (~1.6 µV/g); a count at gain 128 with
# the 3.3 V reference is 2 x 3.3 V / 128 / 2^24 (~3.1 nV). The sum node is
# the mean of the midpoints: a third of a foot's signal per gram.
EST_FOOT = 510.0        # counts per gram
TAU_S = 5               # drift tracking time constant, while untouched
TARE_MS = 250           # arm(): sum only
TARE_ALL_MS = 700       # tare(): sum + every foot a few times
CAL_MS = 1500
NOISE_MS = 2000
MIN_FOOT_SAMPLES = 3
AVG = 4                 # sum samples averaged for the touch decision
RETRY_MS = 3000         # setup again of a chip that is missing or stalled
STALL_MS = 200          # no samples this long: a fault (flash writes stall ~50 ms)

_debug = False
_stream = True
_hello_due = False


def _now():
    return time.ticks_ms()

def _since(t):
    return time.ticks_diff(_now(), t)

def _shift(rate):
    '''Drift tracking as a shift: alpha = 1 / (rate x TAU_S) ~ 2^-shift.'''
    n, shift = rate * TAU_S, 0
    while (1 << shift + 1) <= n:
        shift += 1
    return shift


class Channel:
    '''One bridge reading: raw counts, a tare, counts per gram, the sign.
    The tare is kept x256 so the slow drift tracking keeps its fractions.'''

    def __init__(self, name, adc, mux, sign, k):
        self.name = name
        self.adc = adc
        self.mux = tuple(mux)
        self.sign = sign
        self.k = k
        self.raw = 0
        self.tare_q = None      # tare x 256, None until the first tare
        self.at = _now()        # last sample
        self.count = 0          # samples since the last diag()

    def sample(self, raw):
        self.raw = raw
        self.at = _now()
        self.count += 1

    def counts(self, raw=None):
        if self.tare_q is None:
            return 0
        raw = self.raw if raw is None else raw
        return self.sign * ((raw << 8) - self.tare_q) / 256

    def grams(self, raw=None):
        return self.counts(raw) / self.k

    def track(self, shift):
        if self.tare_q is not None:
            self.tare_q += ((self.raw << 8) - self.tare_q) >> shift


class Collect:
    '''Gathers samples for `ms` (and enough of each foot), then calls done(self).
    Sums are ints: MicroPython floats are 32 bit, too short for 24 bit counts.'''

    def __init__(self, ms, done, feet=True):
        self.t0 = _now()
        self.ms = ms
        self.done = done
        self.sum = [0, 0, 0]
        self.feet = [[0, 0, 0] for _ in FEET] if feet else []

    @staticmethod
    def add(acc, raw):
        acc[0] += 1
        acc[1] += raw
        acc[2] += raw * raw

    def finished(self):
        t = _since(self.t0)
        if t < self.ms:
            return False
        if t > 4 * self.ms + 3000:
            return True     # a chip went quiet: done with what there is
        return bool(_feet_fault) or all(acc[0] >= MIN_FOOT_SAMPLES for acc in self.feet)

    @staticmethod
    def mean(acc):
        return acc[1] // acc[0] if acc[0] else None

    @staticmethod
    def rms(acc):
        n, s, ss = acc
        if n < 2:
            return None
        return ((n * ss - s * s) / (n * (n - 1))) ** 0.5


# Hardware
spec = NODE['spi']
spi = SPI(spec['id'], baudrate=spec.get('baud', 1000000), polarity=0, phase=1,
          sck=Pin(spec['sck']), mosi=Pin(spec['mosi']), miso=Pin(spec['miso']))
SUM_SPEC = NODE['sum_adc']
FEET_SPEC = NODE['feet_adc']
VREF = NODE.get('vref_volts', 3.3)
sum_adc = ADS1220(spi, SUM_SPEC['cs'], SUM_SPEC['drdy'], sps=SUM_SPEC.get('sps', 330),
                  mux=tuple(SUM_SPEC['mux']), vref_volts=VREF, continuous=True)
feet_adc = ADS1220(spi, FEET_SPEC['cs'], FEET_SPEC['drdy'], sps=FEET_SPEC.get('sps', 20),
                   mux=tuple(FEET_SPEC['mux'][0]), vref_volts=VREF, continuous=False)

FEET = [Channel('foot%d' % (i + 1), feet_adc, mux, FEET_SPEC['sign'][i], EST_FOOT)
        for i, mux in enumerate(FEET_SPEC['mux'])]
SUM = Channel('sum', sum_adc, SUM_SPEC['mux'], SUM_SPEC.get('sign', -1), EST_FOOT / len(FEET))
SUM_SHIFT = _shift(sum_adc.sps)
FOOT_SHIFT = _shift(feet_adc.sps / len(FEET))

# GP high = the NPN conducts = the Klipper pin reads low = OK.
touch_out = Pin(NODE['touch_out'], Pin.OUT, value=0)
npx = NeoPixel(Pin(NODE.get('led', 16)), 1)
link = from_config(NODE)
bridge = Bridge(link)       # the host on USB, see lib/bridge.py

# GRB
LED_IDLE = (0x13, 0x9, 0x5)
LED_ACT = (0x0, 0x6D, 0x70)
LED_TOUCH = (0x91, 0x3A, 0x1B)
LED_FAULT = (0x0, 0x60, 0x0)

threshold_g = NODE.get('threshold_g', 5.0)
release_g = NODE.get('release_g', threshold_g * 0.7)
stream_ms = int(1000 / NODE.get('stream_hz', 25))
calibrated = False

touching = False
armed = False
job = None              # the Collect running, at most one
job_name = ''
_foot_i = 0
_sum_fault = 'not set up'   # why the sum channel is not usable, '' when it is
_feet_fault = 'not set up'
_setup_at = {}
_stream_at = 0
_line = None
_led = None
_loop_max = 0
_diag_at = _now()


def log(text):
    if _debug:
        print(text)
    link.send(T_LOG, text.encode())

def hello():
    link.send(T_HELLO, (ROLE + '>>' + EMBLEM).encode())

def host(kind, data):
    '''A line for the host on USB, once it talked to us (bridge.from_host).'''
    if link.tap:
        teeprint(kind, json.dumps(data))


# Calibration, kept across updates (mcu.py only sends the files it knows)
def load_cal():
    global calibrated
    try:
        with open(CAL_FILE) as fp:
            cal = json.load(fp)
    except (OSError, ValueError):
        return
    if len(cal.get('feet', [])) == len(FEET):
        for ch, k in zip(FEET, cal['feet']):
            ch.k = k
    if cal.get('sum'):
        SUM.k = cal['sum']
        calibrated = True

def save_cal():
    with open(CAL_FILE + '.new', 'w') as fp:
        json.dump({'sum': SUM.k, 'feet': [ch.k for ch in FEET]}, fp)
    import os
    try:
        os.remove(CAL_FILE)
    except OSError:
        pass
    os.rename(CAL_FILE + '.new', CAL_FILE)


# ADCs
def setup_sum():
    global _sum_fault
    _setup_at['sum'] = _now()
    sum_adc.drdy.irq(handler=None)
    state = disable_irq()
    try:
        ok, why = sum_adc.setup()
    finally:
        enable_irq(state)
    if ok:
        _iv[3] = 0          # refill the average
        sum_adc.drdy.irq(handler=_on_sum, trigger=Pin.IRQ_FALLING, hard=True)
        sum_adc.start()
        SUM.at = _now()
    fault = '' if ok else why
    if fault != _sum_fault:
        log('adc>>sum: ' + ('ok' if ok else why))
    _sum_fault = fault
    if ok and SUM.tare_q is None:
        start_job('tare', TARE_ALL_MS, tare_done)

def setup_feet():
    global _feet_fault, _foot_i
    _setup_at['feet'] = _now()
    state = disable_irq()
    try:
        ok, why = feet_adc.setup()
        if ok:
            _foot_i = 0
            feet_adc.set_mux(FEET[0].mux)
            feet_adc.start()
    finally:
        enable_irq(state)
    if ok:
        for ch in FEET:
            ch.at = _now()
    fault = '' if ok else why
    if fault != _feet_fault:
        log('adc>>feet: ' + ('ok' if ok else why))
    _feet_fault = fault
    if ok and not job and any(ch.tare_q is None for ch in FEET) and SUM.tare_q is not None:
        start_job('tare', TARE_ALL_MS, tare_done)

def check_adcs():
    '''A chip that stops delivering is a fault (and the touch line fails safe);
    a faulty or missing one is set up again every RETRY_MS.'''
    global _sum_fault, _feet_fault
    if not _sum_fault and _since(SUM.at) > max(STALL_MS, 20 * sum_adc.period_ms()):
        _sum_fault = 'no samples'
        log('adc>>sum: no samples for %d ms' % _since(SUM.at))
    if _sum_fault and _since(_setup_at.get('sum', 0)) > RETRY_MS:
        setup_sum()
    if not _feet_fault and _since(FEET[_foot_i].at) > 10 * feet_adc.period_ms() + STALL_MS:
        _feet_fault = 'no samples'
        log('adc>>feet: no samples for %d ms' % _since(FEET[_foot_i].at))
    if _feet_fault and _since(_setup_at.get('feet', 0)) > RETRY_MS:
        setup_feet()

# Shared with the IRQ: only ints in arrays, no allocation there.
RING = 64               # sum samples kept for the main loop (~190 ms at 330/s)
WRAP = 0x0FFFFFF        # sample counter wraps here (small ints only in the IRQ)
_ring = array('i', [0] * RING)
_avg = array('i', [0] * AVG)
# 0 count  1 avg index  2 avg sum  3 avg fill  4 tare  5 sign  6 on counts
# 7 off counts  8 hold (line touched whatever the force)  9 touching  10 edge
_iv = array('i', [0, 0, 0, 0, 0, SUM.sign, 1 << 28, 1 << 28, 1, 0, 0])
_read = 0               # next ring sample the main loop takes
_overruns = 0

def _on_sum(pin):
    '''Hard IRQ, DRDY of the sum ADC fell: read, average, decide, set the line.'''
    v = _iv
    raw = sum_adc.read()
    n = v[0]
    _ring[n % RING] = raw
    v[0] = (n + 1) & WRAP
    i = v[1]
    total = v[2] - _avg[i] + raw
    _avg[i] = raw
    v[2] = total
    v[1] = (i + 1) % AVG
    if v[3] < AVG:
        v[3] += 1
        return
    f = (total // AVG - v[4]) * v[5]
    was = v[9]
    now = 1 if f > (v[7] if was else v[6]) else 0
    v[9] = now
    if now != was:
        v[10] = 1
    touch_out(0 if now or v[8] else 1)

def sync_irq():
    '''Tare, thresholds in counts and the hold flag, for the IRQ.'''
    v = _iv
    v[4] = 0 if SUM.tare_q is None else SUM.tare_q >> 8
    v[6] = int(threshold_g * SUM.k)
    v[7] = int(release_g * SUM.k)
    v[8] = 1 if hold() else 0

def drain_sum():
    '''The samples the IRQ left: tare jobs, drift tracking, the stall check.'''
    global _read, _sum_fault, _overruns, touching
    n = _iv[0]
    behind = (n - _read) & WRAP
    if not behind:
        return
    if behind > RING:
        _overruns += behind - RING
        _read = (n - RING) & WRAP
    if _sum_fault == 'no samples':
        _sum_fault = ''
        log('adc>>sum: samples again')
        sync_irq()
    track = not _iv[9] and not armed and not job
    while _read != n:
        raw = _ring[_read % RING]
        _read = (_read + 1) & WRAP
        SUM.sample(raw)
        if job:
            Collect.add(job.sum, raw)
        if track and abs(SUM.grams(raw)) < release_g / 2:
            SUM.track(SUM_SHIFT)
    if track:
        _iv[4] = SUM.tare_q >> 8 if SUM.tare_q is not None else 0
    touching = bool(_iv[9])
    if _iv[10]:
        _iv[10] = 0
        send_sample()       # the edge right away, not at the next stream tick

def read_feet():
    global _foot_i, _feet_fault
    if _feet_fault and _feet_fault != 'no samples' or not feet_adc.ready():
        return
    if _feet_fault:
        _feet_fault = ''
        log('adc>>feet: samples again')
    i = _foot_i
    ch = FEET[i]
    nxt = (i + 1) % len(FEET)
    state = disable_irq()       # the bus is shared with the sum's IRQ
    try:
        raw = feet_adc.read()
        feet_adc.set_mux(FEET[nxt].mux)
        feet_adc.start()
    finally:
        enable_irq(state)
    _foot_i = nxt
    ch.sample(raw)
    if job and job.feet:
        Collect.add(job.feet[i], raw)
    if not touching and not armed and not job and abs(ch.grams()) < release_g / 2:
        ch.track(FOOT_SHIFT)


# The touch line
def hold():
    '''The line reads touched whatever the force: taring, no samples, no tare.'''
    return job_name.startswith('tare') or bool(_sum_fault) or SUM.tare_q is None

def line_touched():
    return bool(_iv[9]) or hold()

def update_line():
    '''The IRQ sets the line on every sample; this covers the hold changing
    and the times without samples.'''
    global _line
    h = 1 if hold() else 0
    if h != _iv[8]:
        _iv[8] = h
    touched = line_touched()
    if touched != _line:
        state = disable_irq()
        touch_out.value(0 if line_touched() else 1)
        enable_irq(state)
        _line = touched

def flags():
    f = 0
    if line_touched():
        f |= LOAD_TOUCH
    if armed:
        f |= LOAD_ARMED
    if calibrated:
        f |= LOAD_CAL
    if not _sum_fault:
        f |= LOAD_SUM_OK
    if not _feet_fault:
        f |= LOAD_FEET_OK
    if job_name.startswith('tare'):
        f |= LOAD_TARING
    return f

def send_sample(state=S_SAMPLE):
    global _stream_at
    _stream_at = _now()
    feet = [(int(ch.grams() * 1000), ch.raw) for ch in FEET]
    link.send(T_DATA, pack_load(state, flags(), int(SUM.grams() * 1000), SUM.raw, feet))


# Jobs: tare, calibrate, the noise check. One at a time, the loop keeps going.
def start_job(name, ms, done, feet=True):
    global job, job_name
    if job:
        log('%s>>busy with %s' % (name, job_name))
        return False
    job, job_name = Collect(ms, done, feet), name
    send_sample(S_CALIBRATING)
    return True

def stop_job():
    global job, job_name
    job, job_name = None, ''

def run_job():
    global job, job_name
    if job and job.finished():
        done, finished = job.done, job
        job, job_name = None, ''
        done(finished)

def _tare(c):
    if not c.sum[0]:
        log('tare>>failed: no sum samples')
        send_sample(S_CAL_FAILED)
        return False
    SUM.tare_q = (c.sum[1] << 8) // c.sum[0]
    for ch, acc in zip(FEET, c.feet):
        if acc[0]:
            ch.tare_q = (acc[1] << 8) // acc[0]
    return True

def tare_done(c):
    if _tare(c):
        log('tare>>sum %d, feet %s' % (SUM.tare_q >> 8, [None if ch.tare_q is None else ch.tare_q >> 8 for ch in FEET]))
        send_sample(S_CALIBRATED)

def arm_done(c):
    global armed
    armed = _tare(c)
    host('armed', {'hop': 0, 'role': ROLE, 'armed': armed})
    send_sample(S_CALIBRATED if armed else S_CAL_FAILED)

def calibrate(grams, foot=None):
    def done(c):
        global calibrated
        mean = Collect.mean(c.sum)
        if foot is None:
            if mean is None or SUM.tare_q is None:
                return fail('no sum samples, or no tare')
            k = SUM.counts(mean) / grams
            if k < EST_FOOT / len(FEET) / 20:
                return fail('%.1f counts/g on the sum: no weight, or the sign is wrong (sum_adc.sign)' % k)
            SUM.k = k
            # The feet with one common gain from the same weight, unless
            # weighed one by one: calibrate(<g>, <foot>) with it over each.
            total = sum(ch.counts(Collect.mean(acc)) for ch, acc in zip(FEET, c.feet) if acc[0])
            if not _feet_fault and total / grams > EST_FOOT / 20:
                for ch in FEET:
                    ch.k = total / grams
            calibrated = True
            log('calibrate>>sum %.1f counts/g, feet %s' % (SUM.k, ['%.1f' % ch.k for ch in FEET]))
        else:
            ch, acc = FEET[foot], c.feet[foot]
            if not acc[0] or ch.tare_q is None:
                return fail('no samples of foot %d, or no tare' % (foot + 1))
            k = ch.counts(Collect.mean(acc)) / grams
            if k < EST_FOOT / 20:
                return fail('%.1f counts/g on foot %d: no weight over it, or its sign is wrong' % (k, foot + 1))
            ch.k = k
            log('calibrate>>foot %d %.1f counts/g' % (foot + 1, k))
        save_cal()
        send_sample(S_CALIBRATED)

    def fail(why):
        log('calibrate>>failed: ' + why)
        send_sample(S_CAL_FAILED)

    if grams <= 0 or foot is not None and not 0 <= foot < len(FEET):
        return fail('calibrate(<grams>) or calibrate(<grams>, <foot 1..%d>)' % len(FEET))
    start_job('calibrate', CAL_MS, done)

def noise_done(c):
    def line(name, adc, ch, acc):
        rms = Collect.rms(acc)
        if rms is None:
            return '%s: no samples' % name
        return '%s: rms %.1f counts = %.3f uV = %.2f g (%d samples)' % (
            name, rms, adc.volts(rms) * 1e6, rms / ch.k, acc[0])
    log('diag>>noise ' + line('sum', sum_adc, SUM, c.sum))
    for ch, acc in zip(FEET, c.feet):
        log('diag>>noise ' + line(ch.name, feet_adc, ch, acc))

def diag():
    global _loop_max, _diag_at
    secs = max(_since(_diag_at), 1) / 1000
    for name, adc, fault, n in (('sum', sum_adc, _sum_fault, SUM.count),
                                ('feet', feet_adc, _feet_fault, sum(ch.count for ch in FEET))):
        regs = ' '.join('%02x' % b for b in adc.regs) if adc.regs else '-'
        log('diag>>%s adc: %s, regs %s, %d sps set, %.1f/s measured' % (name, fault or 'ok', regs, adc.sps, n / secs))
    log('diag>>tare sum %s feet %s' % (None if SUM.tare_q is None else SUM.tare_q >> 8,
                                       [None if ch.tare_q is None else ch.tare_q >> 8 for ch in FEET]))
    log('diag>>counts/g sum %.1f feet %s (%s)' % (SUM.k, ['%.1f' % ch.k for ch in FEET],
                                                 'calibrated' if calibrated else 'estimate'))
    log('diag>>threshold %.2f g, release %.2f g, armed %s, line %s, loop max %d ms' % (
        threshold_g, release_g, armed, 'touched' if line_touched() else 'ok', _loop_max))
    log('diag>>sum samples behind the IRQ ring: %d since boot' % _overruns)
    log('diag>>longest, us: ' + ', '.join('%s %d' % (n, v) for n, v in zip(SECTIONS, _sect)))
    for i in range(len(_sect)):
        _sect[i] = 0
    _loop_max, _diag_at = 0, _now()
    for ch in [SUM] + FEET:
        ch.count = 0
    start_job('noise', NOISE_MS, noise_done)


# Commands
def parse(cmd):
    '''b'calibrate(100, 2)' -> ('calibrate', ['100', '2'])'''
    i = cmd.find(b'(')
    if i < 0 or not cmd.endswith(b')'):
        return cmd.decode(), []
    inner = cmd[i + 1:-1].decode().strip()
    return cmd[:i].decode(), [a.strip() for a in inner.split(',')] if inner else []

def handle(frame):
    global _debug, _stream, stream_ms, threshold_g, release_g, armed
    if frame.type != T_CMD:
        return
    name, args = parse(frame.payload)
    if name == 'ping':
        hello()
    elif name == 'reset':
        reset()
    elif name == 'debug_on':
        _debug = True
    elif name == 'debug_off':
        _debug = False
    elif name == 'diag':
        diag()
    elif name == 'tare' or name == 'calibrate' and not args:
        start_job('tare', TARE_ALL_MS, tare_done)
    elif name == 'calibrate':
        calibrate(float(args[0]), int(args[1]) - 1 if len(args) > 1 else None)
    elif name == 'threshold' and args:
        threshold_g = float(args[0])
        release_g = float(args[1]) if len(args) > 1 else threshold_g * 0.7
        log('threshold>>%.2f g, release %.2f g' % (threshold_g, release_g))
    elif name == 'stream' and args:
        _stream = args[0] == 'on'
    elif name == 'rate' and args:
        stream_ms = max(10, int(1000 / float(args[0])))
    elif name == 'arm' and args:
        if args[0] in (ROLE, 'all'):
            armed = False
            start_job('tare_arm', TARE_MS, arm_done, feet=False)
    elif name == 'stall' and args:
        # A test: the main loop busy for <ms>; the touch line must keep working.
        t = _now()
        while _since(t) < int(args[0]):
            wdt.feed()
    elif name == 'disarm':
        armed = False
        if job_name == 'tare_arm':
            stop_job()
        host('armed', {'hop': 0, 'role': ROLE, 'armed': False})


def on_hello_timer(t):
    global _hello_due
    _hello_due = True

def set_led():
    global _led
    if _sum_fault:
        color = LED_FAULT
    elif job:
        color = LED_ACT
    elif line_touched():
        color = LED_TOUCH
    else:
        color = LED_IDLE
    if color != _led:
        npx[0] = color
        npx.write()
        _led = color

def on_boot():
    load_cal()
    hello()
    timer_hello.init(period=12345, mode=Timer.PERIODIC, callback=on_hello_timer)
    update_line()
    setup_sum()             # starts the first tare once it works
    setup_feet()

SECTIONS = ('host', 'adc', 'check', 'job', 'stream', 'led')
_sect = [0] * len(SECTIONS)     # longest of each part of step(), µs, since diag()

def _mark(i, t):
    now = time.ticks_us()
    d = time.ticks_diff(now, t)
    if d > _sect[i]:
        _sect[i] = d
    return now

def step():
    global _hello_due, _loop_max
    t0 = _now()
    t = time.ticks_us()
    for frame in link.poll():
        handle(frame)
    cmd = bridge.read_command()
    if cmd:
        bridge.from_host(cmd, handle)
    if _hello_due:
        _hello_due = False
        hello()
    t = _mark(0, t)

    drain_sum()
    read_feet()
    t = _mark(1, t)
    check_adcs()
    t = _mark(2, t)
    run_job()
    sync_irq()              # tare, thresholds, hold: cheap enough every loop
    update_line()
    t = _mark(3, t)

    if _stream and _since(_stream_at) >= stream_ms:
        send_sample()
    t = _mark(4, t)
    set_led()
    wdt.feed()
    _mark(5, t)
    _loop_max = max(_loop_max, _since(t0))


timer_hello = Timer(-1)
guard = Guard(log)
on_boot()

while True:
    try:
        step()
        guard.ok()
    except Exception as e:
        touch_out.value(0)  # touched until a step goes through again
        _line = None
        guard.error(e)
