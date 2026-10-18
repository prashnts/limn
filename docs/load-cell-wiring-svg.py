"""Generate limn/docs/load-cell-wiring.svg (ADS1220 x2 + RP2040 bed load cells)."""
import sys

W, H = 1440, 940
out = []
INK, MUTE, FILL, ACC = "#1d1d1f", "#8a8a8e", "#f5f4ef", "#0b6e69"


def e(s):
    out.append(s)


def wire(*pts, c=INK, dash=False):
    d = " ".join(f"{x},{y}" for x, y in pts)
    da = ' stroke-dasharray="5 4"' if dash else ""
    e(f'<polyline points="{d}" fill="none" stroke="{c}" stroke-width="1.6"{da}/>')


def dot(x, y):
    e(f'<circle cx="{x}" cy="{y}" r="3.2" fill="{INK}"/>')


def text(x, y, s, size=12, anchor="start", c=INK, w="normal", italic=False):
    st = ' font-style="italic"' if italic else ""
    e(f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}" fill="{c}" font-weight="{w}"{st}>{s}</text>')


def res_h(x1, x2, y, label=None, lab_dy=-11, c=INK):
    m = (x1 + x2) / 2
    wire((x1, y), (m - 18, y), c=c)
    wire((m + 18, y), (x2, y), c=c)
    e(f'<rect x="{m-18}" y="{y-6}" width="36" height="12" fill="#fff" stroke="{c}" stroke-width="1.6"/>')
    if label:
        text(m, y + lab_dy, label, 10.5, "middle", c)


def res_v(x, y1, y2, label=None):
    m = (y1 + y2) / 2
    wire((x, y1), (x, m - 18))
    wire((x, m + 18), (x, y2))
    e(f'<rect x="{x-6}" y="{m-18}" width="12" height="36" fill="#fff" stroke="{INK}" stroke-width="1.6"/>')
    if label:
        text(x + 11, m + 4, label, 10.5)


def cap_v(x, y1, y2, label=None):
    m = (y1 + y2) / 2
    wire((x, y1), (x, m - 4))
    wire((x, m + 4), (x, y2))
    e(f'<line x1="{x-10}" y1="{m-4}" x2="{x+10}" y2="{m-4}" stroke="{INK}" stroke-width="2.2"/>')
    e(f'<line x1="{x-10}" y1="{m+4}" x2="{x+10}" y2="{m+4}" stroke="{INK}" stroke-width="2.2"/>')
    if label:
        text(x + 13, m + 4, label, 10.5)


def gnd(x, y, label="AGND"):
    wire((x, y), (x, y + 8))
    for i, hw in enumerate((10, 6.5, 3)):
        yy = y + 8 + i * 4
        e(f'<line x1="{x-hw}" y1="{yy}" x2="{x+hw}" y2="{yy}" stroke="{INK}" stroke-width="1.6"/>')
    if label:
        text(x, y + 34, label, 9, "middle", MUTE)


def flag(x, y, s, side="up", c=ACC):
    """Net label; side = direction the wire leaves from (x, y)."""
    if side == "up":
        wire((x, y), (x, y - 10))
        text(x, y - 14, s, 11, "middle", c, "bold")
    elif side == "right":
        wire((x, y), (x + 10, y))
        text(x + 14, y + 4, s, 11, "start", c, "bold")
    elif side == "left":
        wire((x, y), (x - 10, y))
        text(x - 14, y + 4, s, 11, "end", c, "bold")


def rc(x, y):
    e(f'<rect x="{x}" y="{y-9}" width="34" height="18" rx="3" fill="#fff" stroke="{INK}" stroke-width="1.4"/>')
    text(x + 17, y + 4, "RC", 10, "middle")


def chip(x, y, w, h, title, sub):
    e(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4" fill="{FILL}" stroke="{INK}" stroke-width="1.8"/>')
    text(x + w / 2, y + h / 2 - 4, title, 13, "middle", INK, "bold")
    text(x + w / 2, y + h / 2 + 13, sub, 10.5, "middle", MUTE)


def pin(side, x, y, name, num=None, c=INK, stub=0):
    """Pin label inside the chip edge at (x, y)."""
    if side == "L":
        text(x + 6, y + 4, name, 10.5, "start", c)
        if num:
            text(x - 4, y - 4, num, 9, "end", MUTE)
    elif side == "R":
        text(x - 6, y + 4, name, 10.5, "end", c)
        if num:
            text(x + 4, y - 4, num, 9, "start", MUTE)
    elif side == "T":
        text(x, y + 15, name, 10, "middle", c)
        if num:
            text(x + 4, y - 4, num, 9, "start", MUTE)
    elif side == "B":
        text(x, y - 7, name, 10, "middle", c)
        if num:
            text(x + 4, y + 12, num, 9, "start", MUTE)


e(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
  'font-family="Inter, Helvetica, Arial, sans-serif">')
e(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')
text(24, 34, "limn bed load cells: 3 feet, 2 × ADS1220, RP2040", 18, w="bold")
text(24, 54, "2026-10-15 · plan, not yet built · pin numbers = the ADS1220 chip; the module\'s header uses the same names", 11, c=MUTE)

# ---------- supply: the Pro Micro's 3V3, ratiometric ----------
py = 110
flag(150, py, "+3V3 (Pro Micro 3V3 pin)", "left")
wire((150, py), (330, py))
dot(210, py); cap_v(210, py, py + 45, "47 µ"); gnd(210, py + 45, None)
dot(270, py); cap_v(270, py, py + 45, "100 n"); gnd(270, py + 45, None)
flag(330, py, "AVDD_A", "right")
text(430, py - 4, "AVDD_A = the Pro Micro's 3V3: bridge excitation, REFP0, AVDD (= DVDD, 0 Ω on the module)", 11, c=MUTE)
text(430, py + 12, "ratiometric: the excitation is the reference, so its noise and drift cancel", 11, c=MUTE)
text(430, py + 28, "option if the noise test asks: an LDO module from VBUS feeding AVDD_A instead", 11, c=MUTE, italic=True)


def cap_h(x1, x2, y, label=None):
    m = (x1 + x2) / 2
    wire((x1, y), (m - 4, y)); wire((m + 4, y), (x2, y))
    e(f'<line x1="{m-4}" y1="{y-9}" x2="{m-4}" y2="{y+9}" stroke="{INK}" stroke-width="2.2"/>')
    e(f'<line x1="{m+4}" y1="{y-9}" x2="{m+4}" y2="{y+9}" stroke="{INK}" stroke-width="2.2"/>')
    if label:
        text(m, y - 13, label, 10, "middle")


# ---------- bridges ----------
rows = [240, 310, 380, 450]
names = ["Foot 1 · top middle", "Foot 2 · bottom left", "Foot 3 · bottom right", "Completion pair · on the board"]
flag(90, 215, "AVDD_A")
wire((90, 215), (90, rows[-1]))
wire((320, rows[0]), (320, 480))
gnd(320, 480)
taps = []
for i, (y, n) in enumerate(zip(rows, names)):
    on_bar = i < 3
    if on_bar:
        e(f'<rect x="102" y="{y-36}" width="206" height="46" rx="5" fill="none" stroke="{MUTE}" '
          'stroke-width="1.2" stroke-dasharray="4 3"/>')
    text(108, y - 24, n + ("  (on the bar)" if on_bar else ""), 10.5, c=ACC if on_bar else INK, w="bold")
    if i < 3:
        dot(90, y)
    if i:
        dot(320, y)
    wire((90, y), (110, y))
    res_h(110, 190, y, "BF350 top" if on_bar else "350 Ω matched")
    res_h(220, 300, y, "BF350 bottom" if on_bar else "350 Ω matched")
    wire((190, y), (220, y)); wire((300, y), (320, y))
    dot(205, y)
    ty = y + 22
    wire((205, y), (205, ty), (335, ty))
    taps.append(ty)
    text(214, ty - 4, ["M1", "M2", "M3", "MC"][i], 10, c=ACC, w="bold")

# ---------- RC filters ----------
MCX = 548  # filtered MC bus
ax, aw = 580, 160
for i, ty in enumerate(taps):
    res_h(335, 395, ty, "1 k" if i == 0 else None)
    wire((395, ty), (ax, ty))
    dot(410, ty); cap_v(410, ty, ty + 26, "4.7 n" if i == 0 else None); gnd(410, ty + 26, None)
    if i < 3:
        dot(490, ty)
        wire((490, ty), (490, ty + 22), (500, ty + 22))
        cap_h(500, 536, ty + 22, "47 n" if i == 0 else None)
        wire((536, ty + 22), (MCX, ty + 22)); dot(MCX, ty + 22)
wire((MCX, taps[0] + 22), (MCX, 720), (ax, 720)); dot(MCX, taps[3])

# ---------- ADS #1: feet, cycled ----------
chip(ax, 210, aw, 290, "ADS1220 #1", "feet, cycled")
ains = [("AIN0", "11"), ("AIN1", "10"), ("AIN2", "7"), ("AIN3", "6")]
for ty, (nm, num) in zip(taps, ains):
    pin("L", ax, ty, nm, num)


def ads_power(ytop, ybot):
    for px, nm, num in ((630, "REFP0", "9"), (690, "AVDD", "12")):
        flag(px, ytop, "AVDD_A")
        pin("T", px, ytop, nm, num)
    for px, nm, num in ((630, "REFN0", "8"), (690, "AVSS", "5")):
        wire((px, ybot), (px, ybot + 12))
        gnd(px, ybot + 12)
        pin("B", px, ybot, nm, num)


ads_power(210, 500)


def ads_digital(rows_y):
    sclk, din, dout, cs, drdy, dvdd, clk, dg = rows_y
    for y, nm, num in ((sclk, "SCLK", "1"), (din, "DIN", "16"), (dout, "DOUT/DRDY", "15"),
                       (cs, "CS", "2"), (drdy, "DRDY", "14"), (dvdd, "DVDD", "13"),
                       (clk, "CLK", "3"), (dg, "DGND", "4")):
        pin("R", ax + aw, y, nm, num, c=MUTE if nm == "CLK" else INK)
    flag(ax + aw, dvdd, "AVDD_A", "right")
    text(ax + aw + 6, clk + 4, "nc (10 k to GND", 9, c=MUTE)
    text(ax + aw + 6, clk + 14, "on the module)", 9, c=MUTE)
    wire((ax + aw, dg), (765, dg))
    gnd(765, dg, None)


A1 = (240, 270, 300, 330, 360, 410, 440, 470)
ads_digital(A1)

# ---------- summing network (from the filtered nodes) + ADS #2 ----------
sum_y = [620, 650, 680]
bx = [470, 458, 446]
SX = 530
for ty, x, y in zip(taps[:3], bx, sum_y):
    dot(x, ty)
    wire((x, ty), (x, y), (476, y))
    res_h(476, 522, y, "3 × 47 k" if y == 620 else None)
    wire((522, y), (SX, y))
wire((SX, 620), (SX, 690)); dot(SX, 650); dot(SX, 680)
text(SX + 4, 645, "S", 10, "start", ACC, "bold")
cap_v(SX, 690, 716, None); gnd(SX, 716, None)
text(SX - 14, 708, "1 n", 10, "end")
wire((SX, 650), (ax, 650))
dot(568, 650); dot(568, 720); cap_v(568, 650, 720, None)
text(568, 736, "10 n", 9.5, "middle")

chip(ax, 590, aw, 260, "ADS1220 #2", "fixed sum: touch")
for y, nm, num in ((650, "AIN0", "11"), (720, "AIN1", "10")):
    pin("L", ax, y, nm, num)
for y, nm, num in ((780, "AIN2", "7"), (815, "AIN3", "6")):
    pin("L", ax, y, nm, num, c=MUTE)
    wire((ax - 16, y), (ax, y), c=MUTE)
    text(ax - 20, y + 4, "nc", 9.5, "end", MUTE)
ads_power(590, 850)
A2 = (620, 650, 680, 710, 740, 780, 805, 830)
ads_digital(A2)

# ---------- SPI bus ----------
rp_x, rp_w, rp_y, rp_h = 980, 170, 190, 380
bus = {"SCLK": 800, "MOSI": 815, "MISO": 830}
for (k, i) in (("SCLK", 0), ("MOSI", 1), ("MISO", 2)):
    x = bus[k]
    wire((ax + aw, A1[i]), (x, A1[i]))
    wire((ax + aw, A2[i]), (x, A2[i]), (x, A1[i]))
    dot(x, A1[i])
chip(rp_x, rp_y, rp_w, rp_h, "", "")
rp_pins = [  # y, gpio, function, from-point path start
    (240, "GP22", "SPI0 SCK", [(bus["SCLK"], 240)]),
    (270, "GP23", "SPI0 TX (COPI)", [(bus["MOSI"], 270)]),
    (300, "GP20", "SPI0 RX (CIPO)", [(bus["MISO"], 300)]),
    (330, "GP21", "CS1", [(ax + aw, 330)]),
    (360, "GP9", "DRDY1", [(ax + aw, 360)]),
    (400, "GP8", "CS2", [(ax + aw, 710), (860, 710), (860, 400)]),
    (430, "GP7", "DRDY2", [(ax + aw, 740), (875, 740), (875, 430)]),
]
for y, gp, fn, path in rp_pins:
    wire(*path, (rp_x, y))
    pin("L", rp_x, y, f"{gp}  {fn}")
text(890, 222, "24 Ω series on the module", 9.5, "middle", MUTE)

text(rp_x + rp_w / 2, rp_y + rp_h - 64, "RP2040", 13, "middle", w="bold")
text(rp_x + rp_w / 2, rp_y + rp_h - 48, "SparkFun Pro Micro", 10.5, "middle", MUTE)
text(rp_x + rp_w / 2, rp_y + rp_h - 34, "custom firmware", 10.5, "middle", MUTE)
for px, nm, fl in ((1010, "VBUS", "VBUS 5 V"), (1110, "3V3", "+3V3")):
    flag(px, rp_y, fl)
    pin("T", px, rp_y, nm)
wire((1065, rp_y + rp_h), (1065, rp_y + rp_h + 10)); gnd(1065, rp_y + rp_h + 10, "DGND")
pin("B", 1065, rp_y + rp_h, "GND")
# USB
wire((rp_x + rp_w, 530), (1200, 530))
text(1206, 534, "USB → Pi 4 (data + VBUS)", 11, c=ACC, w="bold")
pin("R", rp_x + rp_w, 530, "USB")

# reserved: break-beam
for y, nm in ((380, "GP0/1  UART0 free"), (410, "GP4/5  UART1 free"), (440, "Qwiic 16/17, 2/3, 26-29")):
    pin("R", rp_x + rp_w, y, nm, c=MUTE)
    wire((rp_x + rp_w, y), (rp_x + rp_w + 14, y), c=MUTE)
text(rp_x + rp_w + 20, 414, "beam, XY sensor,", 10, c=MUTE, italic=True)
text(rp_x + rp_w + 20, 428, "later", 10, c=MUTE, italic=True)

# ---------- touch line: one NPN, open collector ----------
ty = 330
pin("R", rp_x + rp_w, ty, "GP6  TOUCH")
res_h(rp_x + rp_w, 1205, ty, "4.7 k")
wire((1205, ty), (1222, ty)); dot(1195, ty)
res_v(1195, ty, ty + 60); gnd(1195, ty + 60, None)
text(1185, ty + 35, "100 k", 10.5, "end")
qx = 1222  # base bar
e(f'<circle cx="{qx+10}" cy="{ty}" r="19" fill="none" stroke="{INK}" stroke-width="1.4"/>')
e(f'<line x1="{qx}" y1="{ty-12}" x2="{qx}" y2="{ty+12}" stroke="{INK}" stroke-width="2.4"/>')
wire((qx, ty - 6), (qx + 16, ty - 16), (qx + 16, ty - 50))
wire((qx, ty + 6), (qx + 16, ty + 16), (qx + 16, ty + 40))
e(f'<polygon points="{qx+16},{ty+16} {qx+6},{ty+14} {qx+11},{ty+8}" fill="{INK}"/>')
gnd(qx + 16, ty + 40, None)
text(qx + 34, ty + 4, "NPN", 10, c=INK, w="bold")
text(qx + 34, ty + 17, "BC547 / 2N3904", 9, c=MUTE)
wire((qx + 16, ty - 50), (1330, ty - 50))
text(1262, ty - 56, "wire", 9.5, "middle", MUTE)
# at the Melzi
e(f'<rect x="1300" y="{ty-130}" width="128" height="104" rx="5" fill="none" stroke="{MUTE}" '
  'stroke-width="1.2" stroke-dasharray="4 3"/>')
text(1306, ty - 116, "at the Melzi", 10.5, c=ACC, w="bold")
flag(1345, ty - 84, "5 V", "up", c=INK)
res_v(1345, ty - 84, ty - 50, None); text(1356, ty - 63, "10 k", 10.5)
dot(1345, ty - 50)
wire((1330, ty - 50), (1385, ty - 50))
text(1388, ty - 46, "", 10)
text(1306, ty - 34, "endstop pin →", 10, c=ACC)
text(1180, 470, "TOUCH: GP6 high = OK, Melzi pin low", 10.5, c=INK, w="bold")
text(1180, 485, "touch, dead MCU or cut wire: pulled", 10, c=MUTE)
text(1180, 498, "high = triggered, Klipper won't probe", 10, c=MUTE)
text(1180, 511, "no 5 V reaches the RP2040", 10, c=MUTE)

# ---------- grounds ----------
gx, gy = 1000, 700
text(gx, gy - 20, "Grounds: one star on the front-end board", 11, w="bold")
text(gx, gy, "the module joins its AGND and DGND (0 Ω);", 10.5, c=MUTE)
text(gx, gy + 15, "the Pro Micro's GND reaches the star by one wire;", 10.5, c=MUTE)
text(gx, gy + 30, "the NPN's emitter by its own wire to the Pro Micro's GND", 10.5, c=MUTE)
text(gx, gy + 60, "RC: 1 kΩ + 4.7 nF to AGND per input, 47 nF Mx–MC;", 10.5, c=MUTE)
text(gx, gy + 75, "S: the 47 ks are its R, 1 nF to AGND, 10 nF S–MC", 10.5, c=MUTE)
text(gx, gy + 90, "Gauge wires: 32 AWG twisted triples (EXC+, mid, EXC−) per foot", 10.5, c=MUTE)

e("</svg>")
open(sys.argv[1], "w").write("\n".join(out))
