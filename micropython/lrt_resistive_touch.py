# Resistive Touch Panel - Z Probe
# 
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
import time
from machine import Pin, ADC, reset, Timer, WDT
from neopixel import NeoPixel
from link import load_node, from_config, pack_rtp, Guard, T_CMD, T_HELLO, T_LOG, T_DATA, S_SAMPLE
from touch import TouchLine


wdt = WDT(timeout=3000)
NODE = load_node()
PANEL_PINS = NODE.get('panel_pins', [28, 26, 27, 29])
XP, XM, YP, YM = PANEL_PINS
N_SAMPLES = 10
SETTLE_US = 1000       # after every drive change; was 10ms for X only
TOUCH_Z = 5000
MAX_SPREAD = NODE.get('max_spread', 4000)   # samples of one read further apart: not settled

npx = NeoPixel(Pin(16), 1)
link = from_config(NODE)
touch = TouchLine(NODE)
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


def _sense(pin_id):
    return ADC(Pin(pin_id, Pin.IN))

def _drive(pin_id, value):
    Pin(pin_id, Pin.OUT, value=value)

def _settled(samples):
    '''Median, and how far apart the middle samples are.'''
    samples = sorted(samples)
    quarter = len(samples) // 4
    return samples[len(samples) // 2], samples[-quarter - 1] - samples[quarter]

def release_panel():
    # Nothing driven between reads: no current through a pressed panel.
    for pin_id in PANEL_PINS:
        Pin(pin_id, Pin.IN)

def get_points():
    '''-> x, y, z, spread. A large spread means the pen was landing or
    lifting during the read.'''
    # Referenced from https://github.com/adafruit/Adafruit_TouchScreen/blob/master/TouchScreen.cpp
    # X: drive the X plate, read the position off the Y plate.
    ypin = _sense(YP)
    _sense(YM)
    _drive(XP, 1)
    _drive(XM, 0)
    time.sleep_us(SETTLE_US)
    x, x_spread = _settled([ypin.read_u16() for _ in range(N_SAMPLES)])
    x = 65535 - x

    # Y: drive the Y plate, read the X plate.
    xpin = _sense(XP)
    xmin = _sense(XM)
    _drive(YP, 1)
    _drive(YM, 0)
    time.sleep_us(SETTLE_US)
    y, y_spread = _settled([xpin.read_u16() for _ in range(N_SAMPLES)])
    y = 65535 - y

    # Z (pressure): X+ low, Y- high, read X- and Y+.
    ypin = _sense(YP)
    _drive(XP, 0)
    _drive(YM, 1)
    time.sleep_us(SETTLE_US)
    z1 = xmin.read_u16()
    z2 = ypin.read_u16()
    z = 65535 - z2 + z1
    release_panel()

    return x, y, z, max(x_spread, y_spread)

def pen_detect_on():
    '''Y plate grounded, X plate pulled up: a touch pulls X+ low and fires
    the touch line straight from the IRQ.'''
    _sense(XM)
    _sense(YP)
    _drive(YM, 0)
    pin = Pin(XP, Pin.IN, Pin.PULL_UP)
    pin.irq(touch.fire, Pin.IRQ_FALLING, hard=True)

def pen_detect_off():
    # Measuring toggles X+, which must not look like a touch.
    Pin(XP).irq(handler=None)

def pen_is_down():
    return Pin(XP).value() == 0

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
    if touch.command(cmd):
        pass
    elif cmd == b'debug_on()':
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

def log(text):
    if _enable_debug:
        print(text)
    link.send(T_LOG, text.encode())

def on_boot():
    hello()
    npx[0] = MCU_LED_COLOR
    npx.write()
    timer_hello.init(period=12141, mode=Timer.PERIODIC, callback=on_hello_timer)
    timer_restore_led.init(period=100, mode=Timer.PERIODIC, callback=restore_led)

has_touch = False
detecting = False
rejected = 0            # touching, but not settled: not sent

def step():
    global _hello_due, has_touch, detecting, rejected
    relayed = link.down.stats['rx'] if link.down else 0
    for frame in link.poll():
        handle(frame)
    relayed = link.down and link.down.stats['rx'] != relayed

    if _hello_due:
        _hello_due = False
        hello()
        if rejected:
            log('rtp>>%d touch samples not settled (spread > %d), not sent' % (rejected, MAX_SPREAD))
            rejected = 0

    if touch.armed and not has_touch:
        # Idle while armed: wait in pen detect mode, only measure once touched.
        # Only lifting the pen re-arms the line, a light contact does not.
        if not detecting:
            pen_detect_on()
            detecting = True
        down = pen_is_down()
        touch.update(down)
        if not (down or touch.latched):
            wdt.feed()
            return
    if detecting:
        pen_detect_off()
        detecting = False

    x, y, z, spread = get_points()
    has_touch = z > TOUCH_Z
    if touch.armed:
        if has_touch:
            touch.fire()
        touch.tick()
    else:
        touch.update(has_touch)

    if has_touch and spread > MAX_SPREAD:
        rejected += 1
        if _enable_debug:
            print('not settled', x, y, z, spread)
    elif has_touch:
        link.send(T_DATA, pack_rtp(S_SAMPLE, x, y, z))
        if _enable_debug:
            print('SMP', x, y, z, spread)

    if has_touch:
        npx[0] = TOUCH_LED_COLOR
        npx.write()
    elif relayed:
        npx[0] = FSR_MCU_LED_COLOR
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
