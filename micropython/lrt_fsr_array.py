# Force Sensitive Resistor - XY Alignment
# 
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
import time
from machine import UART, Pin, ADC
from neopixel import NeoPixel


FSR_X = [10, 9, 12, 11, 8, 13, 14, 15]
FSR_Y = [29, 28, 26, 27]
IO_X = [Pin(pin_x, Pin.OUT, value=0) for pin_x in FSR_X]
ADC_Y = [ADC(Pin(pin_y, Pin.IN, Pin.PULL_DOWN)) for pin_y in FSR_Y]

uart_in = UART(0, 115200, timeout=10)
uart_out = UART(1, 115200, timeout=10) # not used
npx = NeoPixel(Pin(16), 1)

_adc_cutoff = 2000
_adc_calibs = [2000 for _ in FSR_Y]
_enable_debug = True
TAG = ">>>FSR>>>"
EMBLEM = "Limn - FSR Alignment v1"

def teeprint(info, line):
    line = TAG + info + '>>>' + line + ">>>"
    if _enable_debug:
        print(line)
    uart_in.write((line + '\n').encode())

def read_fsr():
    evenvalues = []
    oddvalues = []
    even_io_x = IO_X[::2]
    odd_io_x = IO_X[1::2]

    def read_row(x_io_pin):
        rows = []
        for y_pin in ADC_Y:
            x_io_pin.on()
            rows.append(y_pin.read_u16())
            x_io_pin.off()
        return rows

    for pin_x in even_io_x:
        evenvalues.append(read_row(pin_x))

    for pin_x in odd_io_x:
        oddvalues.append(read_row(pin_x))

    values = list(zip(*[val for pair in zip(evenvalues, oddvalues) for val in pair]))

    touch_coords = [(x, y) for x, row in enumerate(values) for y, v in enumerate(row) if v > _adc_cutoff]

    return values, touch_coords

def calibrate_fsr():
    global _adc_cutoff
    max_samples = 10
    prev_max = 0
    prev_samples = []
    prev_variances = []
    tolerance = 500
    npx[0] = (0, 200, 0)
    npx.write()
    while True:
        values, _ = read_fsr()
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
        teeprint("calibrating...", f"{max_adc=},{variance=}")
    _adc_cutoff = max(prev_samples) * 1.2
    teeprint("ADC calibration complete", f"{_adc_cutoff=}")


def _debug_preview(values):
    preview = '+-' * len(FSR_X) + '+'
    for row in values:
        row = [row[len(row) - 1 - i] for i in range(len(row))]
        preview += '\n|' + '|'.join([' ' if v <= _adc_cutoff else '*' for v in row]) + '|'
    preview += '\n' + '+-' * len(FSR_X) + '+\n'
    print(preview)



teeprint("booting", EMBLEM)
calibrate_fsr()

while True:
    cmd = uart_in.readline()
    if cmd:
        npx[0] = (80, 40, 10)
        npx.write()
        if b'calibrate()' in cmd:
            calibrate_fsr()

    chain_data = uart_out.readline()
    if chain_data:
        if _enable_debug:
            print(chain_data.decode())
        uart_in.write(chain_data)


    sensor_values, touch_coords = read_fsr()

    max_value = max(max(row) for row in sensor_values)
    has_touch = max_value > _adc_cutoff
    n_touches = len(touch_coords)

    if n_touches != 0:
        teeprint('sample', f'{n_touches=},{touch_coords=},{max_value=}')
        if _enable_debug:
            _debug_preview(sensor_values)
    if has_touch:
        c_red = min(255, n_touches * 10)
        c_green = min(128, max_value // 256)
        c_blue = min(128, sum(sum(pt) for pt in touch_coords) * 2)
        npx[0] = (c_blue, c_red, c_green)
        npx.write()

    time.sleep_ms(5)
    npx[0] = (10, 10, 8)
    npx.write()

    
