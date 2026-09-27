# Limn Resistive Touch Probe
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
import time
import json
import random
import rp2
from machine import Pin, ADC, Timer, WDT
from neopixel import NeoPixel
from link import load_node, from_config, unpack_data, Guard, T_CMD, T_DATA
from link import S_SAMPLE
from bridge import Bridge, teeprint

wdt = WDT(timeout=3000)
NODE = load_node()
link = from_config(NODE)
bridge = Bridge(link)
npx = NeoPixel(Pin(16), 1)
PIN_PROBE_OUT = Pin(11, Pin.OUT, Pin.PULL_DOWN)
PIN_PWR_ON = Pin(8, Pin.OUT, Pin.PULL_DOWN)
PIN_PWR_OFF = Pin(7, Pin.OUT, Pin.PULL_DOWN)
ADC_DETECT = ADC(Pin(29, Pin.IN))

POWER_STATE = False

# Probe trigger, see micropython/STRATEGY.md
#   "uart":   pulse on touch samples arriving over UART (no diodes needed)
#   "detect": pulse on a bed node lifting DETECT, only while armed
TRIGGER = NODE.get('trigger', 'uart')
PROBE_PULSE_MS = 10    # BLTouch style pulse
PROBE_LOCKOUT_MS = 50  # after a pulse, ignore touches for this long
TOUCH_THRESHOLD = NODE.get('touch_threshold', 56000)
REMOVED_MS = 250       # DETECT must read "no bed" this long to count as removed

# Klipper remembers meshes and test marks per placement of a bed. `placed` counts
# the beds placed and removed since boot; a new BOOT_ID says the count started
# over, and that the bed may have moved while the Dock was off.
BOOT_ID = '%08x' % random.getrandbits(32)
_placed = 0

_enable_debug = True
_armed = False
EMBLEM = "Limn Resistive Touch Probe v1"

# Commands only the Dock handles. Everything else is also passed on to every
# node in the chain.
DOCK_COMMANDS = ('power_on()', 'power_off()', 'read_bed_id()', 'stats()')

_last_seq = {}         # hop -> last seq seen
_seq_gaps = {}         # hop -> frames missed (replaced by newer data, or damaged)

BEDS = [
    # Reference Resistor, ADC Min, ADC Max
    ('BED_1', 2200,  10000, 13500),
    ('BED_2', 4700,  18000, 24000),
    ('BED_3', 10000, 28000, 36000),
    ('BED_4', 15000, 37000, 42000),
    ('BED_5', 22000, 43000, 47500),
    ('BED_6', 33000, 48000, 53000),
]
REMOVED_THRESHOLD = 55000
BED_CONFIRM_MS = 1000

def read_bed_id(val=None):
    if val is None:
        val = ADC_DETECT.read_u16()
    if val > REMOVED_THRESHOLD:
        return 'NONE', None
    for spec in BEDS:
        if spec[2] <= val <= spec[3]:
            return spec[0], list(spec)
    return 'UNKNOWN', None


def placement():
    return {'boot': BOOT_ID, 'placed': _placed, 'powered': POWER_STATE}


def log(text):
    teeprint("log", json.dumps({'hop': 0, 'text': text}))

def _pulse_power_pin(pin):
    pin.on()
    time.sleep_ms(100)
    pin.off()

def turn_on_power():
    _pulse_power_pin(PIN_PWR_ON)
    teeprint("power", "turned on")

def turn_off_power():
    _pulse_power_pin(PIN_PWR_OFF)
    teeprint("power", "turned off")


timer_hello = Timer(-1)
timer_restore_led = Timer(-1)

# GRB
MCU_LED_COLOR = (0x46, 0, 0x70)
ACT_COLOR = (0x0, 0x6D, 0x70)
LED_OFF = (0x0, 0x0, 0x0)
TOUCH_LED_COLOR = (0x94, 0x12, 0x2F)

def ping(t):
    teeprint("ping", f"t={time.ticks_ms()}")
    # GRB
    npx[0] = ACT_COLOR
    npx.write()

def restore_led(t=None):
    npx[0] = MCU_LED_COLOR
    npx.write()


# Probe output: the pulse is timed by a PIO state machine, so it is exact and
# the loop keeps running meanwhile. One cycle = 10us.
@rp2.asm_pio(set_init=rp2.PIO.OUT_LOW)
def _probe_pulse():
    pull(block)
    mov(x, osr)
    set(pins, 1)
    label('hold')
    jmp(x_dec, 'hold')
    set(pins, 0)

probe_sm = rp2.StateMachine(0, _probe_pulse, freq=100000, set_base=PIN_PROBE_OUT)
probe_sm.active(1)
_last_pulse_at = None

def start_probe_pulse():
    global _last_pulse_at
    now = time.ticks_ms()
    if _last_pulse_at is not None and time.ticks_diff(now, _last_pulse_at) < PROBE_PULSE_MS + PROBE_LOCKOUT_MS:
        return
    probe_sm.put(PROBE_PULSE_MS * 100 - 1)
    _last_pulse_at = now


# Chain -> host
def count_seq_gap(frame):
    last = _last_seq.get(frame.hop)
    if last is not None:
        gap = (frame.seq - last - 1) & 0xFF
        _seq_gaps[frame.hop] = _seq_gaps.get(frame.hop, 0) + gap
    _last_seq[frame.hop] = frame.seq

def on_data(frame):
    sample = unpack_data(frame.payload)
    if sample is None:
        teeprint("error", "malformed data from hop %d" % frame.hop)
        return
    kind, state, values = sample
    if TRIGGER == 'uart' and state == S_SAMPLE and values:
        start_probe_pulse()
    bridge.show(frame)

def on_chain_frame(frame):
    count_seq_gap(frame)
    npx[0] = ACT_COLOR
    npx.write()
    if frame.type == T_DATA:
        on_data(frame)
    else:
        bridge.show(frame)

# Host -> dock
def handle_host_command(cmd):
    global _enable_debug, _armed
    npx[0] = (80, 40, 10)
    npx.write()
    if cmd.startswith('frame('):
        bridge.command(cmd)
        return
    if cmd not in DOCK_COMMANDS:
        link.send_down(T_CMD, cmd.encode())

    if cmd == 'power_on()':
        turn_on_power()
    elif cmd == 'power_off()':
        turn_off_power()
    elif cmd == 'read_bed_id()':
        teeprint("read_bed_id", json.dumps(list(read_bed_id()) + [placement()]))
    elif cmd == 'debug_on()':
        _enable_debug = True
    elif cmd == 'debug_off()':
        _enable_debug = False
    elif cmd == 'ping()':
        ping(None)
    elif cmd.startswith('arm('):
        _armed = True
        teeprint("armed", cmd[4:-1])
    elif cmd == 'disarm()':
        _armed = False
        teeprint("armed", "")
    elif cmd == 'stats()':
        stats = link.stats()
        stats['seq_gaps'] = _seq_gaps
        stats['trigger'] = TRIGGER
        stats['armed'] = _armed
        teeprint("stats", json.dumps(stats))


# Touch (trigger "detect") and bed detection share the DETECT line.
_detect_high = False

def check_touch(val):
    global _detect_high
    high = val > TOUCH_THRESHOLD
    if high and not _detect_high and TRIGGER == 'detect' and _armed:
        start_probe_pulse()
    _detect_high = high

_bed_candidate = None
_bed_seen_at = 0
_bed_missing_at = None

def check_bed(val):
    '''Powers the bed once the same bed id is read for BED_CONFIRM_MS, and cuts
    power once it reads missing for REMOVED_MS (a touch lifts it briefly).'''
    global POWER_STATE, _bed_candidate, _bed_seen_at, _bed_missing_at, _placed
    bed_id = read_bed_id(val)
    now = time.ticks_ms()

    if bed_id[1]:
        _bed_missing_at = None
        if not POWER_STATE:
            if _bed_candidate != bed_id[0]:
                teeprint("bed_detected", json.dumps(list(bed_id)))
                _bed_candidate = bed_id[0]
                _bed_seen_at = now
            elif time.ticks_diff(now, _bed_seen_at) >= BED_CONFIRM_MS:
                turn_on_power()
                print("Probe detected and power turned on")
                POWER_STATE = True
                _placed += 1
        return

    _bed_candidate = None
    if not POWER_STATE:
        return
    if _bed_missing_at is None:
        _bed_missing_at = now
    elif time.ticks_diff(now, _bed_missing_at) >= REMOVED_MS:
        teeprint("bed_removed", json.dumps(list(bed_id)))
        turn_off_power()
        POWER_STATE = False
        _placed += 1
        _bed_missing_at = None


def on_boot():
    teeprint("booting", EMBLEM)
    turn_off_power()
    npx[0] = MCU_LED_COLOR
    npx.write()
    timer_hello.init(period=7141, mode=Timer.PERIODIC, callback=ping)
    timer_restore_led.init(period=1000, mode=Timer.PERIODIC, callback=restore_led)
    link.send_down(T_CMD, b'reset()')

def step():
    wdt.feed()

    detect = ADC_DETECT.read_u16()
    check_touch(detect)

    for frame in link.poll():
        on_chain_frame(frame)

    cmd = bridge.read_command()
    if cmd:
        handle_host_command(cmd)

    check_bed(detect)

    npx[0] = (0, 0, 0) if not POWER_STATE else (0, 80, 20)
    npx.write()

guard = Guard(log)
on_boot()

while True:
    try:
        step()
        guard.ok()
    except Exception as e:
        guard.error(e)
