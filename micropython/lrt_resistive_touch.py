# Resistive Touch Panel - Z Probe
# 
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
import time
from machine import UART, Pin, ADC, reset
from neopixel import NeoPixel


PANEL_PINS = [28, 26, 27, 29]
XP, XM, YP, YM = PANEL_PINS

TOUCH_OUT_PIN = Pin(2, Pin.OUT, Pin.PULL_DOWN)

uart_in = UART(0, 115200, timeout=10)
uart_out = UART(1, 115200, timeout=10)
npx = NeoPixel(Pin(16), 1)

_enable_debug = True
TAG = ">>>RTP>>>"
EMBLEM = "Limn - Resistive Touch Alignment v1"


def get_points():
    # Referenced from https://github.com/adafruit/Adafruit_TouchScreen/blob/master/TouchScreen.cpp
    N_SAMPLES = 10
    ypin = ADC(Pin(YP, Pin.IN))
    ADC(Pin(YM, Pin.IN))
    Pin(XP, Pin.OUT).on()
    Pin(XM, Pin.OUT).off()
    time.sleep_ms(10)

    xsamples = []

    for _ in range(N_SAMPLES):
        val = ypin.read_u16()
        xsamples.append(val)
    
    x = 65535 - (sum(xsamples) / len(xsamples))

    xpin = ADC(Pin(XP, Pin.IN))
    xmin = ADC(Pin(XM, Pin.IN))
    Pin(YP, Pin.OUT).on()
    Pin(YM, Pin.OUT).off()

    ysamples = []

    for _ in range(N_SAMPLES):
        val = xpin.read_u16()
        ysamples.append(val)
    
    y = 65535 - (sum(ysamples) / len(ysamples))

    ypin = ADC(Pin(YP, Pin.IN))
    Pin(XP, Pin.OUT).off()
    Pin(YM, Pin.OUT).on()

    z1 = xmin.read_u16()
    z2 = ypin.read_u16()

    z = 65535 - z2 + z1

    return x, y, z

try:
    uart_in = UART(0, 115200, timeout=10)
    uart_out = UART(1, 115200, timeout=10)

    def teeprint(info, line):
        line = TAG + info + '>>>' + line + ">>>"
        if _enable_debug:
            print(line)
        uart_in.write((line + '\n').encode())

    teeprint("booting", EMBLEM)

    while True:
        cmd = uart_in.read()
        if cmd:
            if b'calibrate()' in cmd:
                uart_out.write(b'calibrate()\n')
            npx[0] = (80, 40, 10)
            npx.write()
        
        chain_data = uart_out.read()
        if chain_data:
            if _enable_debug:
                print(chain_data.decode())
            uart_in.write(chain_data)

        touch_point = get_points()
        has_touch = touch_point[2] > 5000

        if has_touch:
            teeprint('touch_point', f'{has_touch=},{touch_point=}')
            TOUCH_OUT_PIN.on()

        if has_touch or chain_data:
            npx[0] = (120, 0, 50)
            npx.write()

        time.sleep_ms(8)
        TOUCH_OUT_PIN.off()
        npx[0] = (10, 10, 8)
        npx.write()
except Exception:
    # Wait a few seconds and reset.
    npx[0] = (10, 240, 100)
    npx.write()     
    time.sleep(2)
    reset()
