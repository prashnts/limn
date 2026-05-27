# Resistive Touch Panel - Z Probe
# 
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
import time
import json
from machine import UART, Pin, ADC, reset, Timer, WDT
from neopixel import NeoPixel


wdt = WDT(timeout=3000)
PANEL_PINS = [28, 26, 27, 29]
XP, XM, YP, YM = PANEL_PINS

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

uart_in = UART(0, 115200, timeout=10)
uart_out = UART(1, 115200, timeout=10)
timer_hello = Timer(-1)
timer_restore_led = Timer(-1)

# GRB
MCU_LED_COLOR = (0x46, 0, 0x70)
ACT_COLOR = (0x0, 0x6D, 0x70)
LED_OFF = (0x0, 0x0, 0x0)
TOUCH_LED_COLOR = (0x94, 0x12, 0x2F)


def teeprint(info, line):
    line = TAG + info + '>>>' + line + ">>>"
    if _enable_debug:
        print(line)
    uart_in.write((line + '\n').encode())


def ping(t):
    teeprint("ping", f"t={time.ticks_ms()}")
    # GRB
    npx[0] = ACT_COLOR
    npx.write()
    time.sleep_ms(500)
    restore_led()

def restore_led(t=None):
    npx[0] = MCU_LED_COLOR
    npx.write()

def on_boot():
    teeprint("booting", EMBLEM)
    npx[0] = MCU_LED_COLOR
    npx.write()
    timer_hello.init(period=7141, mode=Timer.PERIODIC, callback=ping)
    timer_restore_led.init(period=100, mode=Timer.PERIODIC, callback=restore_led)
    uart_out.write(b'reset()\n')

on_boot()

while True:
    cmd = uart_in.read()
    if cmd:
        if b'calibrate()' in cmd:
            uart_out.write(b'calibrate()\n')
        if b'debug_on()' in cmd:
            uart_out.write(b'debug_on()\n')
            _enable_debug = True
        if b'debug_off()' in cmd:
            uart_out.write(b'debug_off()\n')
            _enable_debug = False
        if b'reset()' in cmd:
            uart_out.write(b'reset()\n')
            reset()
        npx[0] = LED_OFF
        npx.write()
    
    chain_data = None
    if uart_out.any():
        chain_data = uart_out.readline()
        if chain_data:
            print(chain_data.decode())
            uart_in.write(chain_data)

    touch_point = get_points()
    has_touch = touch_point[2] > 5000

    if has_touch:
        payload = {
            'has_touch': has_touch,
            'coord': touch_point,
        }
        teeprint('touch_point', json.dumps(payload))
        npx[0] = TOUCH_LED_COLOR
        npx.write()
    elif chain_data:
        npx[0] = ACT_COLOR
        npx.write()
    else:
        npx[0] = MCU_LED_COLOR
        npx.write()

    wdt.feed()
