# Force Sensitive Resistor - XY Alignment
# 
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
import time
import uctypes
import binascii
from machine import UART, Pin, ADC, Timer, WDT, reset
from neopixel import NeoPixel


wdt = WDT(timeout=5000)
FSR_X = [10, 9, 12, 11, 8, 13, 14, 15]
FSR_Y = [29, 28, 26, 27]
IO_X = [Pin(pin_x, Pin.OUT, value=0) for pin_x in FSR_X]
ADC_Y = [ADC(Pin(pin_y, Pin.IN, Pin.PULL_DOWN)) for pin_y in FSR_Y]

uart_in = UART(0, 115200)
npx = NeoPixel(Pin(16), 1)

_ADC_MAX = 39000
_adc_cutoff = 2000
_enable_debug = True
TAG = "!FSR>>"
EMBLEM = "Limn - FSR Alignment v1"

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
    return sorted(arr)[len(arr) // 2]

def teeprint(info, line):
    line = line.strip()
    line = TAG + info + '>>' + line + ">>\n"
    if _enable_debug:
        print(line)
    uart_in.write((line).encode())

def read_fsr():
    evenvalues = []
    oddvalues = []
    even_io_x = IO_X[::2]
    odd_io_x = IO_X[1::2]
    SAMPLES = 5

    def read_row(x_io_pin):
        rows = []
        x_io_pin.on()
        for i, y_pin in enumerate(ADC_Y):
            factor = 1.0
            if FSR_Y[i] == 29:
                factor = 1.18
            val = [y_pin.read_u16() for _ in range(SAMPLES)]
            val = sorted(val)[SAMPLES // 2]
            val = int(val * factor)
            rows.append(val)
        x_io_pin.off()
        return rows

    for pin_x in even_io_x:
        evenvalues.append(read_row(pin_x))
    for pin_x in odd_io_x:
        oddvalues.append(read_row(pin_x))

    values = list(zip(*[val for pair in zip(evenvalues, oddvalues) for val in pair]))
    touch_coords = [(x, y, v) for x, row in enumerate(values) for y, v in enumerate(row) if v > _adc_cutoff]
    touch_coords.sort(key=lambda t: t[2], reverse=True)

    return values, touch_coords

def calibrate_fsr():
    global _adc_cutoff
    max_samples = 10
    prev_max = 0
    prev_samples = []
    prev_variances = []
    tolerance = 500
    npx[0] = ACT_COLOR
    npx.write()
    while True:
        values, touch_coords = read_fsr()
        max_adc = max(max(row) for row in values)
        if max_adc > prev_max + tolerance:
            prev_max = max_adc
        if len(prev_samples) > max_samples:
            prev_samples.pop(0)
        prev_samples.append(max_adc)
        variance = sum((max_adc - s) ** 2 for s in prev_samples) ** 0.5 / len(prev_samples)
        prev_variances.append(variance)

        if len(prev_variances) > max_samples * 10 and sum(prev_variances) / len(prev_variances) < tolerance:
            break
        if _enable_debug:
            _debug_preview(values)
        teeprint('CLB', pack_state(touch_coords, 12))
        wdt.feed()
    _adc_cutoff = int(max(max(prev_samples) * 1.6, _ADC_MAX))


def _debug_preview(values):
    preview = '+-' * len(FSR_X) + '+'
    max_value = max(max(row) for row in values)
    mean_value = sum(sum(row) for row in values) / (len(FSR_X) * len(FSR_Y))

    def _ch(v):
        if v <= _adc_cutoff:
            return ' '
        elif v == max_value:
            return '*'
        elif v > mean_value:
            return 'x'
        else:
            return '.'

    for row in values:
        row = [row[len(row) - 1 - i] for i in range(len(row))]
        preview += '\n|' + '|'.join([_ch(v) for v in row]) + '|'
    preview += '\n' + '+-' * len(FSR_X) + '+\n'
    print(preview)

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
        pkt.touches[i].v = int(v / 1024)
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
            _debug_preview(sensor_values)
        npx[0] = TOUCH_LED_COLOR
        npx.write()
    else:
        npx[0] = MCU_LED_COLOR
        npx.write()

    wdt.feed()

    
