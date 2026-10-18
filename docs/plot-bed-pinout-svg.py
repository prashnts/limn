"""Generate limn/docs/plot-bed-pinout.svg: the plot bed's SparkFun Pro Micro RP2040,
top view, every header pin with what it does.

    python3 docs/plot-bed-pinout-svg.py docs/plot-bed-pinout.svg

The functions come from micropython/nodes/plot_bed.json, so the drawing follows
the firmware's pins. The header order is SparkFun's Pro Micro footprint as
Zephyr maps it (boards/sparkfun/pro_micro_rp2040/sparkfun_pro_micro_connector.dtsi):
check it against the board's silkscreen before soldering.
"""
import sys
import json
from pathlib import Path

NODE = json.loads((Path(__file__).resolve().parent.parent / 'micropython/nodes/plot_bed.json').read_text())

W, H = 1180, 800
out = []
INK, MUTE, FILL, ACC = "#1d1d1f", "#8a8a8e", "#f5f4ef", "#0b6e69"
TOUCH, PWR, GND_C, FREE = "#b5541b", "#b3261e", "#1d1d1f", "#9a9aa0"
PCB, PAD = "#c62828", "#d9b54a"

# Top view, USB-C up. Header pins from the USB end down.
LEFT = [0, 1, 'GND', 'GND', 2, 3, 4, 5, 6, 7, 8, 9]
RIGHT = ['RAW', 'GND', 'RST', '3V3', 29, 28, 27, 26, 22, 20, 23, 21]
SILK = {0: 'TX', 1: 'RX', 26: 'A0', 27: 'A1', 28: 'A2', 29: 'A3',
        22: 'SCK', 20: 'CIPO', 23: 'COPI', 21: 'CS'}


def e(s):
    out.append(s)


def text(x, y, s, size=12, anchor="start", c=INK, w="normal", italic=False):
    st = ' font-style="italic"' if italic else ""
    e(f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}" fill="{c}" font-weight="{w}"{st}>{s}</text>')


def functions():
    '''GPIO -> (what, detail, colour), from node.json; the rest are free.'''
    f = {}
    spi = NODE['spi']
    f[spi['sck']] = ('SPI%d SCK' % spi['id'], 'both ADS1220 SCLK', ACC)
    f[spi['mosi']] = ('SPI%d COPI' % spi['id'], 'both DIN', ACC)
    f[spi['miso']] = ('SPI%d CIPO' % spi['id'], 'both DOUT/DRDY (shared)', ACC)
    feet, total = NODE['feet_adc'], NODE['sum_adc']
    f[feet['cs']] = ('CS1', 'ADS #1 (feet) CS', ACC)
    f[feet['drdy']] = ('DRDY1', 'ADS #1 (feet) DRDY', ACC)
    f[total['cs']] = ('CS2', 'ADS #2 (sum) CS', ACC)
    f[total['drdy']] = ('DRDY2', 'ADS #2 (sum) DRDY: the touch IRQ', ACC)
    f[NODE['touch_out']] = ('TOUCH', '4.7 k → NPN → Melzi endstop', TOUCH)
    free = {0: ('UART0 TX', 'free: a sensor up/down the chain'), 1: ('UART0 RX', 'free'),
            4: ('UART1 TX', 'free: the other direction'), 5: ('UART1 RX', 'free'),
            2: ('I2C1 SDA', 'free'), 3: ('I2C1 SCL', 'free'),
            26: ('ADC0', 'free: break-beam, XY sensor'), 27: ('ADC1', 'free'),
            28: ('ADC2', 'free'), 29: ('ADC3', 'free')}
    for gp, (what, detail) in free.items():
        f.setdefault(gp, (what, detail, FREE))
    return f


POWER = {'GND': ('GND', 'the NPN emitter; one wire to the AGND star', GND_C),
         'RAW': ('RAW', '5 V in: not used (USB powers it)', MUTE),
         'RST': ('RST', 'reset, active low', MUTE),
         '3V3': ('3V3', 'AVDD_A: bridges, REFP0, AVDD (47 µF + 100 nF)', PWR)}

e(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
  'font-family="Inter, Helvetica, Arial, sans-serif">')
e(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')
text(40, 44, "Plot bed MCU: SparkFun Pro Micro RP2040", 20, w="bold")
text(40, 66, "top view, USB-C up · functions from micropython/nodes/plot_bed.json · "
     "header order: SparkFun's Pro Micro footprint (check the silkscreen); parts on the board placed roughly", 11.5, c=MUTE)

# The board: 0.7 x 1.3 in, rows 0.6 in apart, 0.1 in pitch
S = 40 / 2.54           # px per mm: one pitch = 40 px
bw, bh = 17.8 * S, 33.0 * S
cx, by = W / 2, 120
bx = cx - bw / 2
e(f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="10" fill="{PCB}" stroke="#7f1d1d" stroke-width="1.6"/>')
# USB-C, the RP2040, the buttons
e(f'<rect x="{cx-36}" y="{by-14}" width="72" height="34" rx="9" fill="#c9c9cc" stroke="#6d6d72" stroke-width="1.4"/>')
text(cx, by + 8, "USB-C", 10, "middle", INK, "bold")
e(f'<rect x="{cx-38}" y="{by+190}" width="76" height="76" rx="3" fill="#2b2b2e"/>')
text(cx, by + 232, "RP2040", 11, "middle", "#e8e8ea", "bold")
for dx, nm in ((-46, "BOOT"), (46, "RESET")):
    e(f'<rect x="{cx+dx-16}" y="{by+62}" width="32" height="20" rx="3" fill="#e8e8ea" stroke="#6d6d72"/>')
    text(cx + dx, by + 98, nm, 8.5, "middle", "#fde7e7")
e(f'<circle cx="{cx}" cy="{by+135}" r="9" fill="#f1f1f1" stroke="#6d6d72"/>')
text(cx, by + 160, "LED GP25", 8.5, "middle", "#fde7e7")
e(f'<rect x="{cx-30}" y="{by+bh-58}" width="60" height="30" rx="3" fill="#f2f2f2" stroke="#6d6d72"/>')
text(cx, by + bh - 39, "Qwiic", 9.5, "middle", INK, "bold")
text(cx, by + bh - 12, "GP16 SDA · GP17 SCL", 8.5, "middle", "#fde7e7")

FUN = functions()
row = 15.24 * S
lx, rx = cx - row / 2, cx + row / 2
py0 = by + 2.6 * S + 12


def pin(x, y, key, side):
    if isinstance(key, int):
        what, detail, c = FUN[key]
        name = 'GP%d' % key
        silk = SILK.get(key, str(key))
    else:
        what, detail, c = POWER[key]
        name, silk = key, key
        if key == 'GND' and side == 'L':
            detail = 'any GND'
    e(f'<circle cx="{x}" cy="{y}" r="9" fill="{PAD}" stroke="#7a5d10" stroke-width="1.2"/>')
    e(f'<circle cx="{x}" cy="{y}" r="4" fill="#ffffff"/>')
    # silkscreen inside the board
    sx = x + 16 if side == 'L' else x - 16
    text(sx, y + 4, silk, 9.5, "start" if side == 'L' else "end", "#ffffff", "bold")
    # callout outside
    x1 = x - 14 if side == 'L' else x + 14
    x2 = x - 70 if side == 'L' else x + 70
    e(f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="{c}" stroke-width="1.4"/>')
    anchor = "end" if side == 'L' else "start"
    tx = x2 - 6 if side == 'L' else x2 + 6
    strong = c not in (FREE, MUTE)
    label = f'{name}  {what}' if isinstance(key, int) else name
    if side == 'L':
        text(tx, y - 1, label, 12.5, anchor, c, "bold" if strong else "normal")
    else:
        text(tx, y - 1, label, 12.5, anchor, c, "bold" if strong else "normal")
    text(tx, y + 13, detail, 10, anchor, MUTE if not strong else INK)


for i, key in enumerate(LEFT):
    pin(lx, py0 + i * 40, key, 'L')
for i, key in enumerate(RIGHT):
    pin(rx, py0 + i * 40, key, 'R')

# The ADC + touch group: one end of the board
gy0, gy1 = py0 + 8 * 40 - 18, py0 + 11 * 40 + 18
for x in (lx, rx):
    e(f'<rect x="{x-15}" y="{gy0}" width="30" height="{gy1-gy0}" rx="8" fill="none" stroke="{ACC}" '
      'stroke-width="1.6" stroke-dasharray="5 4"/>')
text(cx, gy1 + 34, "the ADCs + TOUCH: the 8 pins at the far end from USB", 11, "middle", ACC, "bold")

# Legend and notes
ny = by + bh + 70
for i, (c, s) in enumerate(((ACC, "ADS1220 bus"), (TOUCH, "touch line"), (PWR, "3V3 → the analog rail"),
                            (FREE, "free"))):
    x = 60 + i * 190
    e(f'<line x1="{x}" y1="{ny}" x2="{x+26}" y2="{ny}" stroke="{c}" stroke-width="3"/>')
    text(x + 34, ny + 4, s, 11.5)
text(60, ny + 32, "Not on the headers: Qwiic = I2C0 on GP16/17 (the holders' MCP23017 + PN532, later?), "
     "WS2812 on GP25, BOOT + RESET (hold BOOT, tap RESET: the RPI-RP2 drive).", 10.5, c=MUTE)
text(60, ny + 48, "GP10-15 and GP18/19/24 aren't brought out. Klipper fallback: spi_bus spi0_gpio20_gpio23_gpio22, "
     "cs gpio%d, data_ready gpio%d (ADS #2)." % (NODE['sum_adc']['cs'], NODE['sum_adc']['drdy']), 10.5, c=MUTE)

e("</svg>")
open(sys.argv[1], "w").write("\n".join(out))
