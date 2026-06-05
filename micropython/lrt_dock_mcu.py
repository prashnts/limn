# Limn Resistive Touch Probe
# 
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
import time
import select
import sys
from machine import UART, Pin, ADC, Timer, WDT, reset
from neopixel import NeoPixel

wdt = WDT(timeout=3000)
uart_out = UART(0, 115200, timeout=10, tx=Pin(12), rx=Pin(13))
npx = NeoPixel(Pin(16), 1)
PIN_PROBE_OUT = Pin(11, Pin.OUT, Pin.PULL_DOWN)
PIN_PWR_ON = Pin(8, Pin.OUT, Pin.PULL_DOWN)
PIN_PWR_OFF = Pin(7, Pin.OUT, Pin.PULL_DOWN)
ADC_DETECT = ADC(Pin(29, Pin.IN))  

POWER_STATE = False

_enable_debug = True
_is_probing = False
_probe_id = 0
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

def turn_off_power():
    global POWER_STATE
    _pulse_power_pin(PIN_PWR_OFF)
    teeprint("power", "turned off")

def cb_probe_off(t):
    PIN_PROBE_OUT.off()
    teeprint("probe", "turned off")

def cb_clear_probe(pid):
    def _cb(t, pid=pid):
        if pid == _probe_id:
            _probe_id = 0
    return _cb


timer_hello = Timer(-1)
timer_restore_led = Timer(-1)
timer_end_probing = Timer(-1)

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
    # time.sleep_ms(500)
    # restore_led()

def restore_led(t=None):
    npx[0] = MCU_LED_COLOR
    npx.write()

def on_boot():
    teeprint("booting", EMBLEM)
    turn_off_power()
    npx[0] = MCU_LED_COLOR
    npx.write()
    timer_hello.init(period=7141, mode=Timer.PERIODIC, callback=ping)
    timer_restore_led.init(period=1000, mode=Timer.PERIODIC, callback=restore_led)
    uart_out.write(b'reset()\n')

on_boot()


in_buffer = sys.stdin.buffer
probe_on_at = None

while True:
    wdt.feed()
    try:
        _c = select.select([uart_out], [], [], 0.01)
        if _c[0]:
            chain_data = uart_out.readline()
            if b'"has_touch": true' in chain_data:
                if probe_on_at is None:
                    PIN_PROBE_OUT.on()
                    probe_on_at = time.ticks_ms()
            npx[0] = ACT_COLOR
            npx.write()
            print(chain_data.decode())

    except Exception:
        teeprint("error", "failed to read from uart_out")
    
    if probe_on_at is not None and time.ticks_ms() - probe_on_at > 5:
        PIN_PROBE_OUT.off()
        probe_on_at = None
    
    if _is_probing:
        continue

    _c = select.select([in_buffer], [], [], 0.01)
    if _c[0]:
        chars = ''
        while True:
            print("Waiting for command...")
            chr = in_buffer.read(1)
            wdt.feed()
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
        if 'debug_on()' in cmd:
            uart_out.write(b'debug_on()\n')
            _enable_debug = True
        if 'debug_off()' in cmd:
            uart_out.write(b'debug_off()\n')
            _enable_debug = False
        if 'reset()' in cmd:
            uart_out.write(b'reset()\n')
            reset()
        if 'begin_probe()' in cmd:
            _is_probing = True
            _probe_id += 1
            timer_hello.init(period=12000, mode=Timer.ONE_SHOT, callback=cb_clear_probe(_probe_id))
            teeprint("probe", f"started with id {_probe_id}")
        if 'end_probe()' in cmd:
            _is_probing = False


    detect_value = ADC_DETECT.read_u16()

    if detect_value > 32000 and detect_value < 33000 and not POWER_STATE:
        teeprint("probe_detected", f"{detect_value=}")
        time.sleep(1)
        detect_value = ADC_DETECT.read_u16()
        if detect_value > 32000 and detect_value < 33000:
            turn_on_power()
            print("Probe detected and power turned on")
            POWER_STATE = True
    elif detect_value > 55000 and POWER_STATE:
        teeprint("probe_removed", f"{detect_value=}")
        turn_off_power()
        POWER_STATE = False

    npx[0] = (0, 0, 0) if not POWER_STATE else (0, 80, 20)
    npx.write()

    
