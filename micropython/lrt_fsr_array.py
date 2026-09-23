# Force Sensitive Resistor - Z+CoarseXY Alignment
# 
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
import time
import uctypes
import binascii
import random
from machine import UART, Pin, ADC, Timer, WDT, reset
from neopixel import NeoPixel


wdt = WDT(timeout=5000)
FSR_X = [10, 9, 12, 11, 8, 13, 14, 15]
# FSR_Y = [29, 28, 26, 27]  # BED_3
FSR_Y = [29, 28, 27, 26]  # BED_4
IO_X = [Pin(pin_x, Pin.OUT, value=0) for pin_x in FSR_X]
IO_Y = [Pin(pin_y, Pin.IN, Pin.PULL_DOWN) for pin_y in FSR_Y]
ADC_Y = [(pin_y, ADC(pin_y)) for pin_y in IO_Y]
ADC_DAMP_PIN = IO_Y[3]


_NX = len(FSR_X)
_NY = len(FSR_Y)
BASE   = None          # [row][col] dark baseline ADC
FULL   = None          # [row][col] full-scale ADC per cell (best-effort)
THRESH = None          # [row][col] absolute touch threshold ADC
_streak= None          # [row][col] consecutive frames above threshold

K_SIGMA        = 18     # threshold = base + K_SIGMA*sigma (>= MIN_MARGIN)
MIN_MARGIN     = 820    # minimum absolute gap above baseline, ADC counts
STRONG_MIN     = 345    # strength(0..1000)
CONFIRM_FRAMES = 10

DARK_MAX_GUARD = 5500  # dark-phase: global max below this => sheet untouched
DARK_POOL      = 50    # rolling matrices kept for dark stats (longer)
DARK_MIN_ITERS = 40    # must sample >= this many before considering done (longer)
DARK_STABLE    = 8     # consecutive stable windows required (longer)
DARK_TOL       = 280   # global-max spread to call "stable" (tighter -> runs longer)
CAL_TIMEOUT    = 60    # safety: stop after N outer iters (WDT-friendly)

_min_strength  = 200    # GLOBAL force floor, 0..1000. Set via fsr_set_param(min_strength=N)

READ_MATRIX = []
for x, pin_x in enumerate(IO_X):
    for y, pin_y in enumerate(ADC_Y):
        READ_MATRIX.append((x, y, pin_x, pin_y))

uart_in = UART(0, 115200)
npx = NeoPixel(Pin(16), 1)

_ADC_MAX = 65535
_adc_cutoff = 2000
_enable_debug = True
TAG = "!FSR>>"
EMBLEM = "Limn - FSR Alignment v2"

timer_hello = Timer(-1)
timer_restore_led = Timer(-1)

ID_LM = 0x4
T_COORD = {
    'x': 0 | uctypes.UINT8,
    'y': 1 | uctypes.UINT8,
    'v': 2 | uctypes.UINT8,
}
PACKET = {
    'id': 0 | uctypes.UINT8,
    'n': 1 | uctypes.UINT8,
    'state': 2 | uctypes.UINT8,
    'touches': (3 | uctypes.ARRAY, 8, T_COORD),
}

# GRB
MCU_LED_COLOR = (0x13, 0x9, 0x5)  # #091305
ACT_COLOR = (0x0, 0x6D, 0x70)
LED_OFF = (0x0, 0x0, 0x0)
TOUCH_LED_COLOR = (0x91, 0x3A, 0x1B) #3A911B



def median(arr):
    arr = sorted(arr)
    if len(arr) % 2 == 1:
        return arr[len(arr) // 2]
    else:
        mid = len(arr) // 2
        return (arr[mid - 1] + arr[mid]) // 2

def random_shuffle(arr):
    arr = arr[:]
    shuffled = []
    while True:
        if not arr:
            break
        ix = random.randint(0, len(arr) - 1)
        shuffled.append(arr.pop(ix))
    return shuffled

def teeprint(info, line):
    npx[0] = ACT_COLOR
    npx.write()
    line = line.strip()
    line = TAG + info + '>>' + line + ">>\n"
    if _enable_debug:
        print(line)
    uart_in.write((line).encode())

def _read_raw():
    SAMPLES = 9

    def read_cell(x, y, pin_x, pin_y):
        io_y, adc_y = pin_y
        base_val = median([adc_y.read_u16() for _ in range(SAMPLES)])
        pin_x.value(1)
        time.sleep_us(40)
        factor = .8 if io_y == ADC_DAMP_PIN else 1.0
        val = median([adc_y.read_u16() for _ in range(SAMPLES)])
        pin_x.value(0)
        time.sleep_us(40)
        val = val - base_val if val > base_val else 0
        return (x, y, int(val * factor))

    # read_matrix = random_shuffle(READ_MATRIX)
    read_matrix = READ_MATRIX
    flat = [read_cell(*t) for t in read_matrix]
    flat.sort(key=lambda t: (t[0], t[1]))
    return [[v for x, y, v in flat if y == i] for i in range(_NY)]

def calculate_strength(row, col, v):
    if BASE is None:
        rng = _ADC_MAX - _adc_cutoff
        s = (v - _adc_cutoff) / rng if v > _adc_cutoff else 0
        return int(s * 1000)
    base = BASE[row][col]
    full = FULL[row][col] if FULL else _ADC_MAX
    span = full - base
    if span <= 0:
        return 0
    s = (v - base) / span * 1000.0
    return int(max(0, min(1000, s)))

def read_fsr():
    global _streak
    if _streak is None:
        _streak = [[0] * _NX for _ in range(_NY)]
    values = _read_raw()

    touch_coords = []
    for row_i, row in enumerate(values):
        for col_j, v in enumerate(row):
            if BASE is not None:
                thr = THRESH[row_i][col_j]
                s   = calculate_strength(row_i, col_j, v)
            else:
                thr, s = _adc_cutoff, 0
            if v > thr:
                _streak[row_i][col_j] += 1
            else:
                _streak[row_i][col_j] = 0
            st = _streak[row_i][col_j]
            # or st >= CONFIRM_FRAMES
            if v > thr and s >= _min_strength and (s >= STRONG_MIN):
                touch_coords.append((row_i, col_j, v))

    touch_coords.sort(key=lambda t: calculate_strength(t[0], t[1], t[2]), reverse=True)
    return values, touch_coords

def _robust(arr):
    m = median(arr)
    mad = median([abs(a - m) for a in arr]) or 1
    return m, (1.4826 * mad + 1e-3)

def _pool_stats(pool):
    med, sig = [[0]*_NX for _ in range(_NY)], [[0]*_NX for _ in range(_NY)]
    for row_i in range(_NY):
        for col_j in range(_NX):
            m, s = _robust([mat[row_i][col_j] for mat in pool])
            med[row_i][col_j], sig[row_i][col_j] = m, s
    return med, sig

def calibrate_fsr():
    global BASE, THRESH, _streak, _adc_cutoff
    npx[0] = ACT_COLOR
    npx.write()

    pool = []
    iters = 0
    stable = 0
    while True:
        vals = _read_raw()
        pool.append(vals)
        if len(pool) > DARK_POOL:
            pool.pop(0)

        window_max = [max(max(r) for r in m) for m in pool]
        spread = max(window_max) - min(window_max)
        stable += 1 if spread < DARK_TOL else 0

        max_adc = max(max(r) for r in vals)
        done = (iters >= DARK_MIN_ITERS and stable >= DARK_STABLE and max_adc < DARK_MAX_GUARD)
        if done or iters > CAL_TIMEOUT:
            break

        if _enable_debug:
            _debug_preview(vals)
        teeprint('CLB', pack_state([], 12))   # calibrating (still dark)
        wdt.feed()
        iters += 1
        time.sleep_ms(40)

    base_med, base_sig = _pool_stats(pool)
    BASE   = [[int(base_med[r][c]) for c in range(_NX)] for r in range(_NY)]
    THRESH = [[int(BASE[r][c] + max(K_SIGMA * base_sig[r][c], MIN_MARGIN)) for c in range(_NX)]
              for r in range(_NY)]

    _streak = [[0] * _NX for _ in range(_NY)]
    _adc_cutoff = max(max(r) for r in THRESH)   # keep sane global ref
    teeprint('CLB', pack_state([], 14))          # calibrated done

def _debug_preview(values, touch_coords=None):
    max_value = max(max(row) for row in values)

    def _ch(v, r, c):
        s = calculate_strength(r, c, v)
        def value_map():
            if v == max_value:
                return '█'
            if s <= 0:
                return ' '
            if s < 10:
                return '•'
            if s < 100:
                return '●'
            if s < 200:
                return '◉'
            if s < 300:
                return '◼︎'
            return '#'
        base = value_map()
        if touch_coords and (r, c, v) in touch_coords:
            color = 41 + touch_coords.index((r, c, v))
            return f'\033[{color}m {base} \033[0m'
        return f'\033[90m {base} \033[0m'

    preview = '  ┌' + '───┬' * (len(FSR_X) - 1) + '───┐'
    for r, row in enumerate(values):
        chars = [_ch(row[c], r, c) for c in range(len(row))][::-1]
        preview += f'\n{FSR_Y[r]}├' + '┼'.join(chars) + '│'
    preview += '\n  └' + '───┴' * (len(FSR_X) - 1) + '───┘\n'
    preview += '    ' + '  '.join([str(x).center(2) for x in FSR_X])
    print(preview)
    if touch_coords is not None:
        print("Touch Coords:", touch_coords)

def pack_state(touch_coords, state):
    candidates = touch_coords[:8]
    _alloc = b'\0' * (uctypes.sizeof(PACKET))
    pkt = uctypes.struct(uctypes.addressof(_alloc), PACKET)
    pkt.id = ID_LM
    pkt.state = state
    pkt.n = len(candidates)
    for i, (x, y, v) in enumerate(candidates):
        pkt.touches[i].x = x
        pkt.touches[i].y = y
        pkt.touches[i].v = calculate_strength(x, y, v)
    return binascii.b2a_base64(pkt).decode().strip()

def unpack_state(encoded):
    decoded = binascii.a2b_base64(encoded.strip())
    pkt = uctypes.struct(uctypes.addressof(decoded), PACKET)
    return pkt


def ping(t):
    teeprint("PING", pack_state([], 10))
    npx[0] = ACT_COLOR
    npx.write()

def restore_led(t=None):
    npx[0] = MCU_LED_COLOR
    npx.write()

def on_boot():
    teeprint("BOOT", EMBLEM)
    npx[0] = MCU_LED_COLOR
    npx.write()
    timer_hello.init(period=12345, mode=Timer.PERIODIC, callback=ping)
    timer_restore_led.init(period=50, mode=Timer.PERIODIC, callback=restore_led)
    calibrate_fsr()

on_boot()

while True:
    cmd = uart_in.readline()
    if cmd:
        if b'calibrate()' in cmd:
            calibrate_fsr()
        if b'debug_on()' in cmd:
            _enable_debug = True
        if b'debug_off()' in cmd:
            _enable_debug = False
        if b'reset()' in cmd:
            reset()
        if b'ping()' in cmd:
            ping(None)
        npx[0] = LED_OFF
        npx.write()

    sensor_values, touch_coords = read_fsr()

    n_touches = len(touch_coords)
    has_touch = n_touches > 0

    if has_touch:        
        teeprint('SMP', pack_state(touch_coords, 42))
        if _enable_debug:
            _debug_preview(sensor_values, touch_coords)
        npx[0] = TOUCH_LED_COLOR
        npx.write()
    else:
        npx[0] = MCU_LED_COLOR
        npx.write()

    wdt.feed()

    
