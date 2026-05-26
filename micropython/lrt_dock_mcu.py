# Limn Resistive Touch Probe
# 
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
import time
import select
import sys
from machine import UART, Pin, ADC, Timer, WDT
from neopixel import NeoPixel

wdt = WDT(timeout=1000)
uart_out = UART(0, 115200, timeout=0, tx=Pin(12), rx=Pin(13))
npx = NeoPixel(Pin(16), 1)
PIN_PROBE_OUT = Pin(11, Pin.OUT, Pin.PULL_DOWN)
PIN_PWR_ON = Pin(8, Pin.OUT, Pin.PULL_DOWN)
PIN_PWR_OFF = Pin(7, Pin.OUT, Pin.PULL_DOWN)
ADC_DETECT = ADC(Pin(29, Pin.IN))  

POWER_STATE = False

_enable_debug = True
TAG = ">>>LRT>>>"
EMBLEM = "Limn Resistive Touch Probe v1"

def teeprint(info, line):
    line = TAG + info + '>>>' + line + ">>>"
    if _enable_debug:
        print(line)

def _pulse_power_pin(pin):
    pin.on()
    time.sleep_ms(100)
    pin.off()

def turn_on_power():
    global POWER_STATE
    _pulse_power_pin(PIN_PWR_ON)
    teeprint("power", "turned on")
    POWER_STATE = True

def turn_off_power():
    global POWER_STATE
    _pulse_power_pin(PIN_PWR_OFF)
    teeprint("power", "turned off")
    POWER_STATE = False

def ping(t):
    teeprint("ping", f"t={time.ticks_ms()}")
    npx[0] = (0, 80, 20)
    npx.write()
    time.sleep_ms(100)
    npx[0] = (0, 0, 0)
    npx.write()

def cb_probe_off(t):
    PIN_PROBE_OUT.off()
    teeprint("probe", "turned off")


teeprint("booting", EMBLEM)

timer_hello = Timer(-1)
timer_hello.init(period=5000, mode=Timer.PERIODIC, callback=ping)
timer_pulse_probe = Timer(-1)

touch_detected_at = 0

turn_off_power()

while True:
    _c = select.select([sys.stdin.buffer], [], [], 0.01)
    if _c[0]:
        chars = ''
        while True:
            print("Waiting for command...")
            chr = sys.stdin.buffer.read(1)
            if chr == b'\r' or chr == b'\n':
                break
            chars += chr.decode()
        cmd = chars.strip()
        print(f"Received command: {cmd}")

        npx[0] = (80, 40, 10)
        npx.write()
        if 'power_on()' in cmd:
            turn_on_power()
        if 'power_off()' in cmd:
            turn_off_power()

    try:
        chain_data = uart_out.readline()
        if chain_data:
            npx[0] = (120, 0, 50)
            npx.write()
            print(chain_data.decode())

            if b'has_touch=True' in chain_data:
                PIN_PROBE_OUT.on()
                time.sleep_ms(8)
                PIN_PROBE_OUT.off()
    except Exception:
        teeprint("error", "failed to read from uart_out")

    detect_value = ADC_DETECT.read_u16()
    teeprint("detect_value", f"{detect_value=}")

    if detect_value > 32000 and detect_value < 33000 and not POWER_STATE:
        teeprint("probe_detected", f"{detect_value=}")
        time.sleep(1)
        detect_value = ADC_DETECT.read_u16()
        if detect_value > 32000 and detect_value < 33000:
            turn_on_power()
    if detect_value > 55000 and POWER_STATE:
        teeprint("probe_removed", f"{detect_value=}")
        turn_off_power()

    npx[0] = (0, 0, 0) if not POWER_STATE else (0, 80, 20)
    npx.write()
    wdt.feed()

    
