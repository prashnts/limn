# Force Sensitive Resistor - Z+CoarseXY Alignment
# 
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
import time
import machine
from machine import Pin, ADC, Timer, WDT, reset
from neopixel import NeoPixel
from link import load_node, from_config, pack_fsr, Guard, T_CMD, T_HELLO, T_LOG, T_DATA
from link import S_CALIBRATING, S_CAL_FAILED, S_CALIBRATED, S_SAMPLE, S_MATRIX
from touch import TouchLine
from bridge import Bridge


wdt = WDT(timeout=5000)
NODE = load_node()
FSR_X = [10, 9, 12, 11, 8, 13, 14, 15]
FSR_Y = NODE.get('fsr_y', [29, 28, 27, 26])  # BED_3: [29, 28, 26, 27]
IO_X = [Pin(pin_x, Pin.OUT, value=0) for pin_x in FSR_X]
IO_Y = [Pin(pin_y, Pin.IN, Pin.PULL_DOWN) for pin_y in FSR_Y]
ADC_Y = [(pin_y, ADC(pin_y)) for pin_y in IO_Y]
# Each sense row needs a load to GND: the FSR cell and it make the divider the ADC
# reads. "fsr_load": ohms of the external resistor on each row (47k, notebooks/pinout.md).
# Without one the rows floated (2026-10: crosstalk up the columns, drift, row 3 hearing
# the head over the sheet), and row 3 was read x 0.8 to tame it.
FSR_LOAD = NODE.get('fsr_load')
ADC_DAMP_PIN = None if FSR_LOAD else IO_Y[3]   # no load: sense row 3 reads high, scaled by 0.8

# ADC() switches the pad's pull-down off. "fsr_pull_down": true in node.json
# turns it back on (~50k, loosely specified); not with an external load.
PADS_BANK0 = 0x4001C000
def _pad(pin_id):
    return PADS_BANK0 + 4 + 4 * pin_id

if NODE.get('fsr_pull_down') and not FSR_LOAD:
    for pin_id in FSR_Y:
        machine.mem32[_pad(pin_id)] = machine.mem32[_pad(pin_id)] | 0x4


_NX = len(FSR_X)
_NY = len(FSR_Y)
BASE   = None          # [row][col] dark baseline ADC
THRESH = None          # [row][col] absolute touch threshold ADC

K_SIGMA        = 18     # threshold = base + K_SIGMA*sigma (>= MIN_MARGIN)
MIN_MARGIN     = 820    # minimum absolute gap above baseline, ADC counts
MIN_STRENGTH   = 345    # strength(0..1000) a touch needs, on top of THRESH

DARK_MAX_GUARD = 5500  # dark-phase: global max below this => sheet untouched
DARK_POOL      = 50    # rolling matrices kept for dark stats (longer)
DARK_MIN_ITERS = 40    # must sample >= this many before considering done (longer)
DARK_STABLE    = 8     # stable windows required, not necessarily in a row (longer)
DARK_TOL       = 280   # global-max spread to call "stable" (tighter -> runs longer)
CAL_TIMEOUT    = 60    # safety: stop after N outer iters (WDT-friendly)

READ_MATRIX = []
for x, pin_x in enumerate(IO_X):
    for y, pin_y in enumerate(ADC_Y):
        READ_MATRIX.append((x, y, pin_x, pin_y))

link = from_config(NODE)
touch = TouchLine(NODE)
bridge = Bridge(link)     # only used when a host talks to this node over USB
npx = NeoPixel(Pin(16), 1)

_ADC_MAX = 65535
_adc_cutoff = 2000
_enable_debug = True
ROLE = "fsr"
EMBLEM = "Limn - FSR Alignment v2"

timer_hello = Timer(-1)
timer_restore_led = Timer(-1)
_hello_due = False
_matrix = False        # matrix(on): send every cell every frame, for the host's own thresholds
_inbox = []            # frames for this node, kept while busy calibrating

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

def send_matrix(values):
    cells = [(r, c, calculate_strength(r, c, v)) for r, row in enumerate(values) for c, v in enumerate(row)]
    link.send(T_DATA, pack_fsr(S_MATRIX, cells, limit=len(cells)))

def send_state(state, touch_coords=()):
    npx[0] = ACT_COLOR
    npx.write()
    touches = [(r, c, calculate_strength(r, c, v)) for r, c, v in touch_coords]
    link.send(T_DATA, pack_fsr(state, touches))

def hello():
    npx[0] = ACT_COLOR
    npx.write()
    link.send(T_HELLO, (ROLE + '>>' + EMBLEM).encode())

def log(text):
    if _enable_debug:
        print(text)
    link.send(T_LOG, text.encode())

def diag():
    log('diag>>fsr_load=%s' % (FSR_LOAD or 'none (rows float unless fsr_pull_down)'))
    for pin_id in FSR_Y:
        pad = machine.mem32[_pad(pin_id)]
        log('diag>>gpio%d pull_down=%d pull_up=%d input=%d' % (pin_id, pad >> 2 & 1, pad >> 3 & 1, pad >> 6 & 1))

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

    flat = [read_cell(*t) for t in READ_MATRIX]
    return [[v for x, y, v in flat if y == i] for i in range(_NY)]

def calculate_strength(row, col, v):
    if BASE is None:
        rng = _ADC_MAX - _adc_cutoff
        s = (v - _adc_cutoff) / rng if v > _adc_cutoff else 0
        return int(s * 1000)
    base = BASE[row][col]
    span = _ADC_MAX - base
    if span <= 0:
        return 0
    s = (v - base) / span * 1000.0
    return int(max(0, min(1000, s)))

def read_fsr():
    values = _read_raw()

    touch_coords = []
    for row_i, row in enumerate(values):
        for col_j, v in enumerate(row):
            if BASE is None:
                continue
            if v > THRESH[row_i][col_j] and calculate_strength(row_i, col_j, v) >= MIN_STRENGTH:
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
    global BASE, THRESH, _adc_cutoff
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
        send_state(S_CALIBRATING)
        _inbox.extend(link.poll())
        wdt.feed()
        iters += 1
        time.sleep_ms(40)

    if not done:
        log('calibration>>timed out: stable=%d max=%d (sheet touched?)' % (stable, max_adc))
        if BASE is not None:
            log('calibration>>keeping the previous baseline')
            send_state(S_CAL_FAILED)
            return

    base_med, base_sig = _pool_stats(pool)
    BASE   = [[int(base_med[r][c]) for c in range(_NX)] for r in range(_NY)]
    THRESH = [[int(BASE[r][c] + max(K_SIGMA * base_sig[r][c], MIN_MARGIN)) for c in range(_NX)]
              for r in range(_NY)]

    _adc_cutoff = max(max(r) for r in THRESH)   # keep sane global ref
    send_state(S_CALIBRATED if done else S_CAL_FAILED)

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

def on_hello_timer(t):
    # Only flag it: all UART writes happen in the main loop.
    global _hello_due
    _hello_due = True

def restore_led(t=None):
    npx[0] = MCU_LED_COLOR
    npx.write()

def handle(frame):
    global _enable_debug, _matrix
    if frame.type != T_CMD:
        return
    cmd = frame.payload
    if touch.command(cmd):
        pass
    elif cmd == b'calibrate()':
        calibrate_fsr()
    elif cmd == b'debug_on()':
        _enable_debug = True
    elif cmd == b'debug_off()':
        _enable_debug = False
    elif cmd == b'reset()':
        reset()
    elif cmd == b'ping()':
        hello()
    elif cmd == b'diag()':
        diag()
    elif cmd == b'matrix(on)':
        _matrix = True
    elif cmd == b'matrix(off)':
        _matrix = False
    npx[0] = LED_OFF
    npx.write()

def on_boot():
    hello()
    npx[0] = MCU_LED_COLOR
    npx.write()
    timer_hello.init(period=12345, mode=Timer.PERIODIC, callback=on_hello_timer)
    timer_restore_led.init(period=50, mode=Timer.PERIODIC, callback=restore_led)
    calibrate_fsr()

def step():
    global _hello_due
    _inbox.extend(link.poll())
    while _inbox:
        handle(_inbox.pop(0))

    cmd = bridge.read_command()
    if cmd:
        bridge.from_host(cmd, handle)

    if _hello_due:
        _hello_due = False
        hello()

    sensor_values, touch_coords = read_fsr()

    n_touches = len(touch_coords)
    has_touch = n_touches > 0
    touch.update(has_touch)

    if _matrix:
        send_matrix(sensor_values)
    elif has_touch:
        send_state(S_SAMPLE, touch_coords)
    if has_touch:
        if _enable_debug:
            _debug_preview(sensor_values, touch_coords)
        npx[0] = TOUCH_LED_COLOR
        npx.write()
    else:
        npx[0] = MCU_LED_COLOR
        npx.write()

    wdt.feed()

guard = Guard(log)
on_boot()

while True:
    try:
        step()
        guard.ok()
    except Exception as e:
        guard.error(e)
