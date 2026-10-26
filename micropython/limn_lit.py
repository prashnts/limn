# Limn LIT - the plot bed board: the head's load cell, the touch line, the bed dock
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# LIT (lit, bed in French) is the board at the back of the frame (KiCad sheet
# *Plot bed board*, docs/kicad): a Pro Micro RP2040 and one ADS1220.
#   - the cell: the full bridge in the toolchanger connector (CAT6, AIN0-AIN1),
#     read continuously (~330/s) in a hard IRQ on DRDY, which decides the touch
#     and sets the line: USB prints and GC hold the main loop for 3-25 ms, an
#     IRQ runs through them. The main loop drains the samples it left (tare,
#     jobs, streaming) and does everything else.
#   - the bed dock (what the Dock MCU did, lrt_dock_mcu.py stays as it was):
#     the bed's ID resistor on BED_DETECT, its power through a Pololu switch
#     (BED_EN, a level: on while high), its trigger on BED_PROBE (high = OK).
#     Q952 puts BED_PROBE in series with the touch line in hardware; GP1 only
#     reports it. BED_DATA (GP0): the chain to the bed's nodes on one wire,
#     half duplex ("down": {"pin": 0}, lib/halfwire.py), LIT takes the lead;
#     no turns while the bed is off.
#   - +5V_SW (SW_5V_EN): the LEDs and extras, off until sw5v(on).
#   - the tool's ID on GP26 against R957 (10k), read with GP27 (R958) off.
# The touch line goes to a Klipper endstop through an NPN (open collector):
# `touch_out` high = OK, low = touched. It also reads touched while taring,
# without samples, or with the RP2040 off, so a probe never starts blind.
#
# Commands (USB, or down the chain like the other nodes):
#   tare()  calibrate()  calibrate(<g>)  threshold(<g>)  threshold(<g>, <release g>)
#   stream(on|off)  rate(<Hz>)  arm(lit)  disarm()  diag()  ping()  reset()
#   flip(): the cell's sign the other way (kept in cal.json); + must be the bed
#   pushing the pen up, the touch line only fires on +
#   debug_on()  debug_off()  power_on()  power_off()  read_bed_id()  sw5v(on|off)
#   tool()  stall(<ms>): a test, the main loop busy while the IRQ keeps the line going
import json
import random
import time
from array import array
from machine import ADC, Pin, SPI, Timer, WDT, reset, disable_irq, enable_irq
from neopixel import NeoPixel
from link import load_node, from_config, pack_load, Guard, T_CMD, T_HELLO, T_LOG, T_DATA
from link import S_CALIBRATING, S_CAL_FAILED, S_CALIBRATED, S_SAMPLE
from link import LOAD_TOUCH, LOAD_ARMED, LOAD_CAL, LOAD_SUM_OK, LOAD_TARING
from bridge import Bridge, teeprint
from ads1220 import ADS1220


try:
    import micropython
    micropython.alloc_emergency_exception_buf(100)
except (ImportError, AttributeError):
    pass

wdt = WDT(timeout=5000)
NODE = load_node()
ROLE = NODE.get('role', 'lit')
EMBLEM = 'Limn - LIT v1'
CAL_FILE = 'cal.json'

# Grams before calibrate(<g>), rough: the strips give ~29 µV per 40 g
# (TODO.md, the connector's cell), ~0.73 µV/g; a count at gain 128 with the
# 3.3 V reference is 2 x 3.3 V / 128 / 2^24 (~3.1 nV).
EST_CELL = 236.0        # counts per gram
TAU_S = 5               # drift tracking time constant, while untouched
TARE_MS = 240           # arm(): whole mains periods
TARE_ALL_MS = 700       # tare()
CAL_MS = 1500
NOISE_MS = 2000
RETRY_MS = 3000         # setup again of a chip that is missing or stalled
STALL_MS = 200          # no samples this long: a fault (flash writes stall ~50 ms)

# The bed's ID resistor against R966 (10k to 3V3): the Dock's table.
BEDS = [
    # name, resistor, ADC min, ADC max
    ('BED_1', 2200,  10000, 13500),
    ('BED_2', 4700,  18000, 24000),
    ('BED_3', 10000, 28000, 36000),
    ('BED_4', 15000, 37000, 42000),
    ('BED_5', 22000, 43000, 47500),
    ('BED_6', 33000, 48000, 53000),
]
NO_BED = 55000
BED_CONFIRM_MS = 1000   # the same bed this long: power it
REMOVED_MS = 250        # "no bed" this long: cut its power
BED_READ_MS = 20
NO_TOOL = 60000         # GP26 over this: open, no tool

# Klipper remembers meshes and test marks per placement of a bed. `placed` counts
# the beds placed and removed since boot; a new BOOT_ID says the count started over.
BOOT_ID = '%08x' % random.getrandbits(32)

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
    '''Gathers samples for `ms`, then calls done(self).
    Sums are ints: MicroPython floats are 32 bit, too short for 24 bit counts.'''

    def __init__(self, ms, done):
        self.t0 = _now()
        self.ms = ms
        self.done = done
        self.acc = [0, 0, 0]

    def add(self, raw):
        acc = self.acc
        acc[0] += 1
        acc[1] += raw
        acc[2] += raw * raw

    def finished(self):
        return _since(self.t0) >= self.ms

    def mean(self):
        n, s, _ = self.acc
        return s // n if n else None

    def rms(self):
        n, s, ss = self.acc
        if n < 2:
            return None
        return ((n * ss - s * s) / (n * (n - 1))) ** 0.5


# Hardware
spec = NODE['spi']
spi = SPI(spec['id'], baudrate=spec.get('baud', 1000000), polarity=0, phase=1,
          sck=Pin(spec['sck']), mosi=Pin(spec['mosi']), miso=Pin(spec['miso']))
CELL_SPEC = NODE['cell_adc']
VREF = NODE.get('vref_volts', 3.3)
adc = ADS1220(spi, CELL_SPEC['cs'], CELL_SPEC['drdy'], sps=CELL_SPEC.get('sps', 330),
              mux=tuple(CELL_SPEC['mux']), vref_volts=VREF, continuous=True)
CELL = Channel('cell', adc, CELL_SPEC['mux'], CELL_SPEC.get('sign', -1), EST_CELL)
SHIFT = _shift(adc.sps)
# Samples averaged for the touch decision and the stream: one mains period
# (20 ms, 12 at 600/s) cancels the 50 Hz the frame picks up (~2 g rms, 2026-10-25).
AVG = CELL_SPEC.get('avg', max(1, adc.sps // 50))

# GP high = the NPN conducts = the Klipper pin reads low = OK.
touch_out = Pin(NODE['touch_out'], Pin.OUT, value=0)
bed_en = Pin(NODE['bed_en'], Pin.OUT, value=0)
sw_5v = Pin(NODE['sw_5v'], Pin.OUT, value=0)
bed_probe = Pin(NODE['bed_probe'], Pin.IN)      # R970 pulls it up: OK with no bed
bed_detect = ADC(Pin(NODE['bed_detect']))
tool_pu = Pin(NODE['tool_pu'], Pin.IN)          # high only for the tool's link, later
tool_id = ADC(Pin(NODE['tool_id']))
npx = NeoPixel(Pin(NODE.get('led', 25)), 1)
link = from_config(NODE)
if link.down:
    link.down.active = False    # the bed's off: nobody to give the turn to
bridge = Bridge(link)       # the host on USB, see lib/bridge.py

# GRB
LED_IDLE = (0x13, 0x9, 0x5)
LED_BED = (0x30, 0x0, 0x10)
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
_fault = 'not set up'   # why the ADC is not usable, '' when it is
_setup_at = 0
_stream_at = 0
_line = None
_led = None
_loop_max = 0
_diag_at = _now()

bed_power = False
placed = 0
_bed_candidate = None
_bed_seen_at = 0
_bed_missing_at = None
_bed_read_at = 0
_probe_ok = None


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
    if cal.get('cell'):
        CELL.k = cal['cell']
        calibrated = True
    if cal.get('sign'):
        CELL.sign = cal['sign']

def save_cal():
    with open(CAL_FILE + '.new', 'w') as fp:
        json.dump({'cell': CELL.k if calibrated else None, 'sign': CELL.sign}, fp)
    import os
    try:
        os.remove(CAL_FILE)
    except OSError:
        pass
    os.rename(CAL_FILE + '.new', CAL_FILE)


# The ADC
def setup_adc():
    global _fault, _setup_at
    _setup_at = _now()
    adc.drdy.irq(handler=None)
    state = disable_irq()
    try:
        ok, why = adc.setup()
    finally:
        enable_irq(state)
    if ok:
        _iv[3] = 0          # refill the average
        adc.drdy.irq(handler=_on_sample, trigger=Pin.IRQ_FALLING, hard=True)
        adc.start()
        CELL.at = _now()
    fault = '' if ok else why
    if fault != _fault:
        log('adc>>' + ('ok' if ok else why))
    _fault = fault
    if ok and CELL.tare_q is None:
        start_job('tare', TARE_ALL_MS, tare_done)

def check_adc():
    '''A chip that stops delivering is a fault (and the touch line fails safe);
    a faulty or missing one is set up again every RETRY_MS.'''
    global _fault
    if not _fault and _since(CELL.at) > max(STALL_MS, 20 * adc.period_ms()):
        _fault = 'no samples'
        log('adc>>no samples for %d ms' % _since(CELL.at))
    if _fault and _since(_setup_at) > RETRY_MS:
        setup_adc()

# Shared with the IRQ: only ints in arrays, no allocation there.
RING = 128              # samples kept for the main loop (~210 ms at 600/s)
WRAP = 0x0FFFFFF        # sample counter wraps here (small ints only in the IRQ)
_ring = array('i', [0] * RING)
_avg = array('i', [0] * AVG)
# 0 count  1 avg index  2 avg sum  3 avg fill  4 tare  5 sign  6 on counts
# 7 off counts  8 hold (line touched whatever the force)  9 touching  10 edge
_iv = array('i', [0, 0, 0, 0, 0, CELL.sign, 1 << 28, 1 << 28, 1, 0, 0])
_read = 0               # next ring sample the main loop takes
_overruns = 0

def _on_sample(pin):
    '''Hard IRQ, DRDY fell: read, average, decide, set the line.'''
    v = _iv
    raw = adc.read()
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
    v[4] = 0 if CELL.tare_q is None else CELL.tare_q >> 8
    v[5] = CELL.sign
    v[6] = int(threshold_g * CELL.k)
    v[7] = int(release_g * CELL.k)
    v[8] = 1 if hold() else 0

def drain():
    '''The samples the IRQ left: tare jobs, drift tracking, the stall check.'''
    global _read, _fault, _overruns, touching
    n = _iv[0]
    behind = (n - _read) & WRAP
    if not behind:
        return
    if behind > RING:
        _overruns += behind - RING
        _read = (n - RING) & WRAP
    if _fault == 'no samples':
        _fault = ''
        log('adc>>samples again')
        sync_irq()
    track = not _iv[9] and not armed and not job and abs(CELL.grams(average())) < release_g / 2
    while _read != n:
        raw = _ring[_read % RING]
        _read = (_read + 1) & WRAP
        CELL.sample(raw)
        if job:
            job.add(raw)
        if track:
            CELL.track(SHIFT)
    if track:
        _iv[4] = CELL.tare_q >> 8 if CELL.tare_q is not None else 0
    touching = bool(_iv[9])
    if _iv[10]:
        _iv[10] = 0
        send_sample()       # the edge right away, not at the next stream tick


def average():
    '''The IRQ's average of the last AVG samples (the last one until it filled).'''
    return _iv[2] // AVG if _iv[3] >= AVG else CELL.raw


# The touch line
def hold():
    '''The line reads touched whatever the force: taring, no samples, no tare.'''
    return job_name.startswith('tare') or bool(_fault) or CELL.tare_q is None

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
    if not _fault:
        f |= LOAD_SUM_OK
    if job_name.startswith('tare'):
        f |= LOAD_TARING
    return f

def send_sample(state=S_SAMPLE):
    global _stream_at
    _stream_at = _now()
    raw = average()
    link.send(T_DATA, pack_load(state, flags(), int(CELL.grams(raw) * 1000), raw, []))


# Jobs: tare, calibrate, the noise check. One at a time, the loop keeps going.
def start_job(name, ms, done):
    global job, job_name
    if job:
        log('%s>>busy with %s' % (name, job_name))
        return False
    job, job_name = Collect(ms, done), name
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
    mean = c.mean()
    if mean is None:
        log('tare>>failed: no samples')
        send_sample(S_CAL_FAILED)
        return False
    CELL.tare_q = (c.acc[1] << 8) // c.acc[0]
    return True

def tare_done(c):
    if _tare(c):
        log('tare>>%d' % (CELL.tare_q >> 8))
        send_sample(S_CALIBRATED)

def arm_done(c):
    global armed
    armed = _tare(c)
    host('armed', {'hop': 0, 'role': ROLE, 'armed': armed})
    send_sample(S_CALIBRATED if armed else S_CAL_FAILED)

def calibrate(grams):
    def done(c):
        global calibrated
        mean = c.mean()
        if mean is None or CELL.tare_q is None:
            return fail('no samples, or no tare')
        k = CELL.counts(mean) / grams
        if k < EST_CELL / 20:
            return fail('%.1f counts/g: no weight, or the sign is wrong (flip())' % k)
        CELL.k = k
        calibrated = True
        log('calibrate>>%.1f counts/g' % k)
        save_cal()
        send_sample(S_CALIBRATED)

    def fail(why):
        log('calibrate>>failed: ' + why)
        send_sample(S_CAL_FAILED)

    if grams <= 0:
        return fail('calibrate(<grams>)')
    start_job('calibrate', CAL_MS, done)

def noise_done(c):
    rms = c.rms()
    if rms is None:
        log('diag>>noise: no samples')
        return
    log('diag>>noise rms %.1f counts = %.3f uV = %.2f g (%d samples)' % (
        rms, adc.volts(rms) * 1e6, rms / CELL.k, c.acc[0]))


# The bed dock
def read_bed_id(val=None):
    if val is None:
        val = bed_detect.read_u16()
    if val > NO_BED:
        return 'NONE', None
    for spec in BEDS:
        if spec[2] <= val <= spec[3]:
            return spec[0], list(spec)
    return 'UNKNOWN', None

def placement():
    return {'boot': BOOT_ID, 'placed': placed, 'powered': bed_power}

def power(on, why=''):
    global bed_power
    bed_en.value(1 if on else 0)
    bed_power = on
    if link.down:
        link.down.active = on
    log('bed>>power %s%s' % ('on' if on else 'off', why))
    host('power', {'hop': 0, 'on': on})

def check_bed():
    '''Powers the bed once the same bed id is read for BED_CONFIRM_MS, and cuts
    power once it reads missing for REMOVED_MS.'''
    global _bed_candidate, _bed_seen_at, _bed_missing_at, _bed_read_at, placed
    if _since(_bed_read_at) < BED_READ_MS:
        return
    _bed_read_at = _now()
    bed_id = read_bed_id()
    if bed_id[1]:
        _bed_missing_at = None
        if not bed_power:
            if _bed_candidate != bed_id[0]:
                host('bed_detected', list(bed_id))
                _bed_candidate = bed_id[0]
                _bed_seen_at = _now()
            elif _since(_bed_seen_at) >= BED_CONFIRM_MS:
                placed += 1
                power(True, ', ' + bed_id[0])
        return
    _bed_candidate = None
    if not bed_power:
        return
    if _bed_missing_at is None:
        _bed_missing_at = _now()
    elif _since(_bed_missing_at) >= REMOVED_MS:
        host('bed_removed', list(bed_id))
        placed += 1
        _bed_missing_at = None
        power(False, ', removed')

def check_probe():
    '''BED_PROBE: the bed's trigger, already in series with the touch line.'''
    global _probe_ok
    ok = bool(bed_probe.value())
    if ok != _probe_ok:
        _probe_ok = ok
        host('bed_probe', {'hop': 0, 'ok': ok})
        if _debug:
            log('bed>>probe ' + ('ok' if ok else 'triggered'))

def tool():
    val = tool_id.read_u16()
    kind = 'none' if val > NO_TOOL else 'passive' if val < 2000 else 'id'
    host('tool', {'hop': 0, 'adc': val, 'kind': kind})
    return val, kind


def diag():
    global _loop_max, _diag_at
    secs = max(_since(_diag_at), 1) / 1000
    regs = ' '.join('%02x' % b for b in adc.regs) if adc.regs else '-'
    log('diag>>adc: %s, regs %s, %d sps set, %.1f/s measured' % (_fault or 'ok', regs, adc.sps, CELL.count / secs))
    log('diag>>tare %s, %.1f counts/g (%s)' % (None if CELL.tare_q is None else CELL.tare_q >> 8, CELL.k,
                                             'calibrated' if calibrated else 'estimate'))
    log('diag>>threshold %.2f g, release %.2f g, armed %s, line %s, loop max %d ms' % (
        threshold_g, release_g, armed, 'touched' if line_touched() else 'ok', _loop_max))
    log('diag>>samples behind the IRQ ring: %d since boot' % _overruns)
    log('diag>>bed %s (adc %d), power %s, probe %s; +5V_SW %s; tool %s (adc %d)' % (
        read_bed_id()[0], bed_detect.read_u16(), bed_power, 'ok' if bed_probe.value() else 'triggered',
        'on' if sw_5v.value() else 'off', tool()[1], tool_id.read_u16()))
    log('diag>>bed link: %s' % json.dumps(link.stats()))
    log('diag>>longest, us: ' + ', '.join('%s %d' % (n, v) for n, v in zip(SECTIONS, _sect)))
    for i in range(len(_sect)):
        _sect[i] = 0
    _loop_max, _diag_at = 0, _now()
    CELL.count = 0
    start_job('noise', NOISE_MS, noise_done)


# Commands
def parse(cmd):
    '''b'calibrate(100)' -> ('calibrate', ['100'])'''
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
        calibrate(float(args[0]))
    elif name == 'threshold' and args:
        threshold_g = float(args[0])
        release_g = float(args[1]) if len(args) > 1 else threshold_g * 0.7
        log('threshold>>%.2f g, release %.2f g' % (threshold_g, release_g))
    elif name == 'flip':
        CELL.sign = -CELL.sign
        _iv[5] = CELL.sign
        save_cal()
        log('flip>>sign %d' % CELL.sign)
    elif name == 'stream' and args:
        _stream = args[0] == 'on'
    elif name == 'rate' and args:
        stream_ms = max(10, int(1000 / float(args[0])))
    elif name == 'arm' and args:
        if args[0] in (ROLE, 'all'):
            armed = False
            start_job('tare_arm', TARE_MS, arm_done)
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
    elif name == 'power_on':
        power(True, ', by hand')
    elif name == 'power_off':
        power(False, ', by hand')
    elif name == 'read_bed_id':
        host('read_bed_id', list(read_bed_id()) + [placement()])
    elif name == 'sw5v' and args:
        sw_5v.value(1 if args[0] == 'on' else 0)
        log('sw5v>>' + ('on' if sw_5v.value() else 'off'))
    elif name == 'tool':
        val, kind = tool()
        log('tool>>%s (adc %d)' % (kind, val))


def on_hello_timer(t):
    global _hello_due
    _hello_due = True

def set_led():
    global _led
    if _fault:
        color = LED_FAULT
    elif job:
        color = LED_ACT
    elif line_touched():
        color = LED_TOUCH
    elif bed_power:
        color = LED_BED
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
    setup_adc()             # starts the first tare once it works

SECTIONS = ('host', 'adc', 'check', 'job', 'bed', 'stream', 'led')
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

    drain()
    t = _mark(1, t)
    check_adc()
    t = _mark(2, t)
    run_job()
    sync_irq()              # tare, thresholds, hold: cheap enough every loop
    update_line()
    t = _mark(3, t)
    check_bed()
    check_probe()
    t = _mark(4, t)

    if _stream and _since(_stream_at) >= stream_ms:
        send_sample()
    t = _mark(5, t)
    set_led()
    wdt.feed()
    _mark(6, t)
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
