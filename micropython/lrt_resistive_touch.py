# Resistive Touch Panel - Z Probe
# 
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
import time
from machine import Pin, ADC, reset, Timer, WDT
from neopixel import NeoPixel
from link import Link, open_uart, pack_rtp, T_CMD, T_HELLO, T_DATA, S_SAMPLE


wdt = WDT(timeout=3000)
PANEL_PINS = [28, 26, 27, 29]
XP, XM, YP, YM = PANEL_PINS

npx = NeoPixel(Pin(16), 1)
link = Link(up=open_uart(0), down=open_uart(1))
timer_hello = Timer(-1)
timer_restore_led = Timer(-1)
_hello_due = False

_enable_debug = True
ROLE = "rtp"
EMBLEM = "Limn - Resistive Touch Alignment v1"

# GRB
MCU_LED_COLOR = (0x0F, 0, 0x18)
ACT_COLOR = (0x0, 0x6D, 0x20)
LED_OFF = (0x0, 0x0, 0x0)
TOUCH_LED_COLOR = (0x46, 0, 0x70)
FSR_MCU_LED_COLOR = (0x91, 0x0A, 0x0B)


def median(arr):
    return sorted(arr)[len(arr) // 2]

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
    
    x = 65535 - (median(xsamples))

    xpin = ADC(Pin(XP, Pin.IN))
    xmin = ADC(Pin(XM, Pin.IN))
    Pin(YP, Pin.OUT).on()
    Pin(YM, Pin.OUT).off()

    ysamples = []

    for _ in range(N_SAMPLES):
        val = xpin.read_u16()
        ysamples.append(val)
    
    y = 65535 - (median(ysamples))

    ypin = ADC(Pin(YP, Pin.IN))
    Pin(XP, Pin.OUT).off()
    Pin(YM, Pin.OUT).on()

    z1 = xmin.read_u16()
    z2 = ypin.read_u16()

    z = 65535 - z2 + z1

    return x, y, z

def hello():
    npx[0] = ACT_COLOR
    npx.write()
    link.send(T_HELLO, (ROLE + '>>' + EMBLEM).encode())

def on_hello_timer(t):
    # Only flag it: all UART writes happen in the main loop.
    global _hello_due
    _hello_due = True

def restore_led(t=None):
    npx[0] = MCU_LED_COLOR
    npx.write()

def handle(frame):
    # Broadcast commands (eg. calibrate()) are already forwarded down by link.
    global _enable_debug
    if frame.type != T_CMD:
        return
    cmd = frame.payload
    if cmd == b'debug_on()':
        _enable_debug = True
    elif cmd == b'debug_off()':
        _enable_debug = False
    elif cmd == b'reset()':
        link.flush()   # let the reset reach the nodes below first
        reset()
    elif cmd == b'ping()':
        hello()
    npx[0] = LED_OFF
    npx.write()

def on_boot():
    hello()
    npx[0] = MCU_LED_COLOR
    npx.write()
    timer_hello.init(period=12141, mode=Timer.PERIODIC, callback=on_hello_timer)
    timer_restore_led.init(period=100, mode=Timer.PERIODIC, callback=restore_led)

on_boot()

while True:
    relayed = link.down.stats['rx']
    for frame in link.poll():
        handle(frame)
    relayed = link.down.stats['rx'] != relayed

    if _hello_due:
        _hello_due = False
        hello()

    touch_point = get_points()
    has_touch = touch_point[2] > 5000

    if has_touch:
        link.send(T_DATA, pack_rtp(S_SAMPLE, *touch_point))
        if _enable_debug:
            print('SMP', touch_point)
        npx[0] = TOUCH_LED_COLOR
        npx.write()
    elif relayed:
        npx[0] = FSR_MCU_LED_COLOR
        npx.write()
    else:
        npx[0] = MCU_LED_COLOR
        npx.write()

    wdt.feed()
