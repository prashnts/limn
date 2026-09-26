# Limn Resistive Touch Probe
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
import time
import select
import sys
import json
from machine import Pin, ADC, Timer, WDT
from neopixel import NeoPixel
from link import Link, open_uart, unpack_data, T_CMD, T_HELLO, T_LOG, T_DATA
from link import FSR_ID_LM, RTP_ID_LM, S_SAMPLE

wdt = WDT(timeout=3000)
link = Link(down=open_uart(0, tx=Pin(12), rx=Pin(13)))
npx = NeoPixel(Pin(16), 1)
PIN_PROBE_OUT = Pin(11, Pin.OUT, Pin.PULL_DOWN)
PIN_PWR_ON = Pin(8, Pin.OUT, Pin.PULL_DOWN)
PIN_PWR_OFF = Pin(7, Pin.OUT, Pin.PULL_DOWN)
ADC_DETECT = ADC(Pin(29, Pin.IN))

POWER_STATE = False
PROBE_PULSE_MS = 10    # BLTouch style pulse
STALE_MS = 100         # forget a sensor's touches after this long

_enable_debug = True
TAG = "!LRT>>"
EMBLEM = "Limn Resistive Touch Probe v1"

# Commands from the host that are passed on to every node in the chain.
CHAIN_COMMANDS = ('calibrate()', 'debug_on()', 'debug_off()', 'reset()', 'ping()')

# Keys are strings so that the JSON sent to klipper stays {"4": .., "5": ..}
_last_pkt_at = {
    str(FSR_ID_LM): 0,
    str(RTP_ID_LM): 0,
}
_state = {
    str(FSR_ID_LM): [],
    str(RTP_ID_LM): [],
}
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

def read_bed_id():
    val = ADC_DETECT.read_u16()
    if val > REMOVED_THRESHOLD:
        return 'NONE', None
    for spec in BEDS:
        if spec[2] <= val <= spec[3]:
            return spec[0], list(spec)
    return 'UNKNOWN', None


def teeprint(info, line):
    line = TAG + info + '>>' + line + ">>"
    print(line)

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


# Probe output
_probe_on_at = None

def start_probe_pulse():
    global _probe_on_at
    if _probe_on_at is None:
        PIN_PROBE_OUT.on()
        _probe_on_at = time.ticks_ms()

def end_probe_pulse():
    global _probe_on_at
    if _probe_on_at is not None and time.ticks_diff(time.ticks_ms(), _probe_on_at) >= PROBE_PULSE_MS:
        PIN_PROBE_OUT.off()
        _probe_on_at = None


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
    if kind == RTP_ID_LM:
        x, y, z = values
        values = [x, y, z >> 10]
    key = str(kind)
    _state[key] = values
    _last_pkt_at[key] = time.ticks_ms()

    if state == S_SAMPLE and values:
        start_probe_pulse()

    out = dict(_state)
    out['hop'] = frame.hop
    teeprint("SMP", json.dumps(out))

def on_chain_frame(frame):
    count_seq_gap(frame)
    npx[0] = ACT_COLOR
    npx.write()
    if frame.type == T_DATA:
        on_data(frame)
    elif frame.type == T_HELLO:
        role, emblem = (frame.payload.decode().split('>>', 1) + [''])[:2]
        teeprint("hello", json.dumps({'hop': frame.hop, 'role': role, 'emblem': emblem}))
    elif frame.type == T_LOG:
        teeprint("log", json.dumps({'hop': frame.hop, 'text': frame.payload.decode()}))

def clear_stale_state():
    now = time.ticks_ms()
    for key in _last_pkt_at:
        if time.ticks_diff(now, _last_pkt_at[key]) > STALE_MS:
            _state[key] = []


# Host -> dock
_poller = select.poll()
_poller.register(sys.stdin, select.POLLIN)
_cmd_buffer = ''

def read_host_command():
    '''Returns one complete command line, or None. Never blocks.'''
    global _cmd_buffer
    while _poller.poll(0):
        ch = sys.stdin.read(1)
        if ch in ('\r', '\n'):
            cmd, _cmd_buffer = _cmd_buffer.strip(), ''
            if cmd:
                return cmd
        elif len(_cmd_buffer) < 64:
            _cmd_buffer += ch
    return None

def handle_host_command(cmd):
    global _enable_debug
    npx[0] = (80, 40, 10)
    npx.write()
    if cmd in CHAIN_COMMANDS:
        link.send_down(T_CMD, cmd.encode())

    if cmd == 'power_on()':
        turn_on_power()
    elif cmd == 'power_off()':
        turn_off_power()
    elif cmd == 'read_bed_id()':
        teeprint("read_bed_id", json.dumps(list(read_bed_id())))
    elif cmd == 'debug_on()':
        _enable_debug = True
    elif cmd == 'debug_off()':
        _enable_debug = False
    elif cmd == 'ping()':
        ping(None)
    elif cmd == 'stats()':
        stats = link.stats()
        stats['seq_gaps'] = _seq_gaps
        teeprint("stats", json.dumps(stats))
    elif cmd not in CHAIN_COMMANDS:
        teeprint("error", "unknown command " + cmd)


# Bed detection
_bed_candidate = None
_bed_seen_at = 0

def check_bed():
    '''Powers the bed once the same bed id is read for BED_CONFIRM_MS.'''
    global POWER_STATE, _bed_candidate, _bed_seen_at
    bed_id = read_bed_id()

    if bed_id[1] and not POWER_STATE:
        if _bed_candidate != bed_id[0]:
            teeprint("bed_detected", json.dumps(list(bed_id)))
            _bed_candidate = bed_id[0]
            _bed_seen_at = time.ticks_ms()
        elif time.ticks_diff(time.ticks_ms(), _bed_seen_at) >= BED_CONFIRM_MS:
            turn_on_power()
            print("Probe detected and power turned on")
            POWER_STATE = True

    if not bed_id[1]:
        _bed_candidate = None
        if POWER_STATE:
            teeprint("bed_removed", json.dumps(list(bed_id)))
            turn_off_power()
            POWER_STATE = False


def on_boot():
    teeprint("booting", EMBLEM)
    turn_off_power()
    npx[0] = MCU_LED_COLOR
    npx.write()
    timer_hello.init(period=7141, mode=Timer.PERIODIC, callback=ping)
    timer_restore_led.init(period=1000, mode=Timer.PERIODIC, callback=restore_led)
    link.send_down(T_CMD, b'reset()')

on_boot()


while True:
    wdt.feed()

    for frame in link.poll():
        on_chain_frame(frame)
    clear_stale_state()
    end_probe_pulse()

    cmd = read_host_command()
    if cmd:
        handle_host_command(cmd)

    check_bed()

    npx[0] = (0, 0, 0) if not POWER_STATE else (0, 80, 20)
    npx.write()
