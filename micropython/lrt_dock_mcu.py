# Limn Resistive Touch Probe
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
import time
import select
import sys
import json
import binascii
import rp2
from machine import Pin, ADC, Timer, WDT
from neopixel import NeoPixel
from link import load_node, from_config, unpack_data, Guard, T_CMD, T_HELLO, T_LOG, T_DATA, T_OTA
from link import FSR_ID_LM, RTP_ID_LM, S_SAMPLE

wdt = WDT(timeout=3000)
NODE = load_node()
link = from_config(NODE)
npx = NeoPixel(Pin(16), 1)
PIN_PROBE_OUT = Pin(11, Pin.OUT, Pin.PULL_DOWN)
PIN_PWR_ON = Pin(8, Pin.OUT, Pin.PULL_DOWN)
PIN_PWR_OFF = Pin(7, Pin.OUT, Pin.PULL_DOWN)
ADC_DETECT = ADC(Pin(29, Pin.IN))

POWER_STATE = False
STALE_MS = 100         # forget a sensor's touches after this long

# Probe trigger, see micropython/STRATEGY.md
#   "uart":   pulse on touch samples arriving over UART (no diodes needed)
#   "detect": pulse on a bed node lifting DETECT, only while armed
TRIGGER = NODE.get('trigger', 'uart')
PROBE_PULSE_MS = 10    # BLTouch style pulse
PROBE_LOCKOUT_MS = 50  # after a pulse, ignore touches for this long
TOUCH_THRESHOLD = NODE.get('touch_threshold', 56000)
REMOVED_MS = 250       # DETECT must read "no bed" this long to count as removed

_enable_debug = True
_armed = False
TAG = "!LRT>>"
EMBLEM = "Limn Resistive Touch Probe v1"

# Commands from the host that are passed on to every node in the chain.
CHAIN_COMMANDS = ('calibrate()', 'debug_on()', 'debug_off()', 'reset()', 'ping()', 'disarm()', 'diag()')

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

def read_bed_id(val=None):
    if val is None:
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
    if kind == RTP_ID_LM:
        x, y, z = values
        values = [x, y, z >> 10]
    key = str(kind)
    _state[key] = values
    _last_pkt_at[key] = time.ticks_ms()

    if TRIGGER == 'uart' and state == S_SAMPLE and values:
        start_probe_pulse()

    out = dict(_state)
    out['hop'] = frame.hop
    teeprint("SMP", json.dumps(out))

def print_frame(hop, ftype, payload):
    '''Frames the host tools handle themselves (updates), as base64.'''
    b64 = binascii.b2a_base64(payload).decode().strip()
    teeprint("frame", json.dumps({'hop': hop, 'type': ftype, 'b64': b64}))

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
    elif frame.type == T_OTA:
        print_frame(frame.hop, frame.type, frame.payload)

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
        elif len(_cmd_buffer) < 1024:
            _cmd_buffer += ch
    return None

def send_frame(args):
    '''frame(<hop>,<type>,<base64 payload>): hop 0 is the Dock itself.'''
    hop, ftype, b64 = args.split(',')
    hop, ftype = int(hop), int(ftype)
    payload = binascii.a2b_base64(b64)
    if hop != 0:
        link.send_down(ftype, payload, hop)
    elif ftype == T_OTA:
        print_frame(0, T_OTA, link.handle_ota(payload))
        if link.ota.reset_pending:
            time.sleep_ms(100)      # let the reply reach the host
            import ota
            ota.reset()

def handle_host_command(cmd):
    global _enable_debug, _armed
    npx[0] = (80, 40, 10)
    npx.write()
    if cmd in CHAIN_COMMANDS or cmd.startswith('arm('):
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
    elif cmd.startswith('frame(') and cmd.endswith(')'):
        try:
            send_frame(cmd[6:-1])
        except (ValueError, TypeError) as e:
            teeprint("error", "bad frame: " + repr(e))
    elif cmd not in CHAIN_COMMANDS:
        teeprint("error", "unknown command " + cmd)


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
    global POWER_STATE, _bed_candidate, _bed_seen_at, _bed_missing_at
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
    clear_stale_state()

    cmd = read_host_command()
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
