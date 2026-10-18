"""limn/docs/load-cell-perfboard.svg: the bed load-cell front end on 2.54 mm perfboard.

Top view (parts, insulated jumpers) and the bottom view mirrored (bare wire, solder side).
Checks the layout and prints problems: two nets in one hole, bottom wires of two nets
crossing, a part's leads under another lying part. Usage: python3 this.py out.svg
"""
import sys

COLS, ROWS = 40, 26
P = 17  # px per hole
INK, MUTE, ACC = "#1d1d1f", "#8a8a8e", "#0b6e69"
NET_C = {"AVDD_A": "#c0392b", "AGND": "#3a3a3c", "DGND": "#6b4f2a", "MC": "#d4800b", "S": "#7d3c98",
         "TOUCH": "#1f6fb2", "GP6": "#1f6fb2"}
SIG_C = "#0b6e69"


def ncol(net):
    return NET_C.get(net, SIG_C)


# ---------- the layout ----------
parts = []   # ref, kind, pins [(c, r, net)], value, lying (body over the holes between)
bottom = []  # net, [(c, r), ...]  bare wire on the solder side
top = []     # net, (c, r), (c, r)  insulated jumper on the parts side
pads = []    # (c, r, text)  where a wire to a module / the Pro Micro lands


def part(ref, kind, pins, value="", lying=True):
    parts.append(dict(ref=ref, kind=kind, pins=pins, value=value, lying=lying))


def bw(net, *pts):
    bottom.append((net, list(pts)))


# rails
bw("AVDD_A", (0, 1), (0, 16)); bw("AVDD_A", (0, 1), (18, 1))
bw("AGND", (3, 4), (3, 24)); bw("AGND", (3, 24), (18, 24))

# feet connectors: EXC+, mid, EXC-
feet = [(2, "J1", "M1"), (7, "J2", "M2"), (12, "J3", "M3")]
chans = []  # (row, raw, filtered)
for r0, ref, m in feet:
    part(ref, "J", [(1, r0, "AVDD_A"), (1, r0 + 1, m + "r"), (1, r0 + 2, "AGND")], "foot " + m[1])
    bw("AVDD_A", (1, r0), (0, r0))
    bw("AGND", (1, r0 + 2), (6, r0 + 2))      # EXC- to the bus, on to the 4.7 nF
    bw(m + "r", (1, r0 + 1), (2, r0 + 1))
    chans.append((r0 + 1, m + "r", m))
# completion pair, lying along column 1
part("R4", "R", [(1, 16, "AVDD_A"), (1, 19, "MCr")], "350 match")
part("R5", "R", [(1, 20, "MCr"), (1, 23, "AGND")], "350 match")
bw("AVDD_A", (0, 16), (1, 16)); bw("MCr", (1, 19), (1, 20)); bw("MCr", (1, 20), (2, 20))
bw("AGND", (1, 23), (3, 23)); bw("AGND", (3, 21), (6, 21))
chans.append((20, "MCr", "MC"))

# RC per channel: 1 k over the AGND bus, 4.7 nF to the stub below, node at columns 6-7
for i, (row, raw, f) in enumerate(chans):
    part(f"R{6+i}", "R", [(2, row, raw), (6, row, f)], "1k")
    part(f"C{1+i}", "C", [(6, row, f), (6, row + 1, "AGND")], "4n7", lying=False)
    bw(f, (6, row), (7, row))
    if f != "MC":
        bw(f, (7, row), (7, row - 1))
        part(f"C{5+i}", "C", [(7, row - 1, f), (8, row - 1, "MC")], "47n", lying=False)
        top.append((f, (7, row), (9, row)))     # hop over the MC bus
        bw(f, (9, row), (11, row))
        pads.append((10, row, f"#1 AIN{i}"))
        part(f"R{10+i}", "R", [(11, row, f), (15, row, "S")], "47k")
bw("MC", (7, 20), (8, 20)); bw("MC", (8, 2), (8, 20)); bw("MC", (8, 20), (15, 20))
pads.append((11, 20, "#1 AIN3")); pads.append((13, 20, "#2 AIN1"))
# S: the sum
bw("S", (15, 2), (15, 18)); pads.append((15, 2, "#2 AIN0"))
part("C8", "C", [(15, 18, "S"), (15, 20, "MC")], "10n")
bw("S", (15, 17), (16, 17))
part("C9", "C", [(16, 17, "S"), (16, 19, "AGND")], "1n")
bw("AGND", (16, 19), (16, 24))
for c, t in ((10, "Pro Micro 3V3"), (12, "#1 AVDD"), (14, "#1 REFP0"), (16, "#2 AVDD"), (18, "#2 REFP0")):
    pads.append((c, 1, t))
for c, t in ((8, "Pro Micro GND"), (10, "#1 GND"), (12, "#1 REFN0"), (14, "#2 GND"), (18, "#2 REFN0")):
    pads.append((c, 24, t))

# touch: NPN open collector (BC547 pin order C-B-E, flat face toward you)
part("R13", "R", [(23, 3, "GP6"), (23, 7, "B")], "4k7")
pads.append((23, 3, "Pro Micro GP6"))
part("Q1", "Q", [(22, 8, "TOUCH"), (23, 8, "B"), (24, 8, "DGND")], "NPN", lying=False)
part("R14", "R", [(23, 9, "B"), (23, 13, "DGND")], "100k")
bw("B", (23, 7), (23, 8)); bw("B", (23, 8), (23, 9))
bw("DGND", (24, 8), (24, 13)); bw("DGND", (23, 13), (27, 13))
bw("TOUCH", (22, 8), (22, 6), (27, 6))
part("J5", "J", [(27, 6, "TOUCH"), (27, 7, "DGND")], "to Melzi")
bw("DGND", (27, 7), (27, 13))
pads.append((25, 13, "Pro Micro GND"))

zones = [  # c0, r0, c1, r1, title, sub
    (29, 1, 37, 14, "Pro Micro RP2040", "upright, USB to the top edge"),
    (20, 15, 29, 25, "ADS1220 module #1", "feet, cycled"),
    (30, 15, 39, 25, "ADS1220 module #2", "sum: touch"),
]

pads.sort(key=lambda p: (p[1], p[0]))

# ---------- checks ----------
problems = []


def seg_holes(a, b):
    (c0, r0), (c1, r1) = a, b
    if c0 != c1 and r0 != r1:
        problems.append(f"diagonal wire {a}-{b}")
        return []
    n = max(abs(c1 - c0), abs(r1 - r0))
    dc, dr = (c1 > c0) - (c1 < c0), (r1 > r0) - (r1 < r0)
    return [(c0 + k * dc, r0 + k * dr) for k in range(n + 1)]


hole = {}
def claim(h, net, why):
    if not (0 <= h[0] < COLS and 0 <= h[1] < ROWS):
        problems.append(f"{why} off the board at {h}")
    old = hole.setdefault(h, (net, why))
    if old[0] != net:
        problems.append(f"hole {h}: {old[1]} ({old[0]}) vs {why} ({net})")


for p in parts:
    for c, r, n in p["pins"]:
        claim((c, r), n, p["ref"])
for net, pts in bottom:
    for a, b in zip(pts, pts[1:]):
        for h in seg_holes(a, b):
            claim(h, net, f"wire {net}")
for net, a, b in top:
    claim(a, net, f"jumper {net}"); claim(b, net, f"jumper {net}")
# lying parts: nothing else may put a lead in the holes under the body
for p in parts:
    if p["lying"] and len(p["pins"]) == 2:
        (c0, r0, _), (c1, r1, _) = p["pins"]
        under = seg_holes((c0, r0), (c1, r1))[1:-1]
        for q in parts:
            if q is p:
                continue
            for c, r, _ in q["pins"]:
                if (c, r) in under:
                    problems.append(f"{q['ref']} lead under {p['ref']} at {(c, r)}")
for c0, r0, c1, r1, t, _ in zones:
    for (c, r) in hole:
        if c0 <= c <= c1 and r0 <= r <= r1:
            problems.append(f"{t} zone has {hole[(c, r)]} at {(c, r)}")

# ---------- drawing ----------
out = []
e = out.append
MX, TOPY, GAP = 40, 110, 90
BW, BH = COLS * P, ROWS * P
W = MX * 2 + BW
H = TOPY + 2 * BH + GAP + 330


def T(x, y, s, size=11, anchor="start", c=INK, w="normal"):
    e(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" text-anchor="{anchor}" fill="{c}" font-weight="{w}">{s}</text>')


def board(oy, mirror, title, sub):
    def xy(c, r):
        cc = COLS - 1 - c if mirror else c
        return MX + cc * P + P / 2, oy + r * P + P / 2
    T(MX, oy - 28, title, 15, w="bold"); T(MX, oy - 12, sub, 11, c=MUTE)
    e(f'<rect x="{MX-6}" y="{oy-6}" width="{BW+12}" height="{BH+12}" rx="6" fill="#efe3c4" stroke="#b9a77a"/>')
    for c in range(COLS):
        for r in range(ROWS):
            x, y = xy(c, r)
            e(f'<circle cx="{x}" cy="{y}" r="2.6" fill="#fff" stroke="#c9b68a" stroke-width="1"/>')
    for c in range(0, COLS, 5):
        x, _ = xy(c, 0); T(x, oy - 9 + BH + 28, str(c), 8.5, "middle", MUTE)
    for r in range(0, ROWS, 5):
        x, y = xy(0, r); T(x + (14 if mirror else -14), y + 3, str(r), 8.5, "middle", MUTE)
    return xy


def draw_top(xy):
    for c0, r0, c1, r1, t, sub in zones:
        (xa, ya), (xb, yb) = xy(c0, r0), xy(c1, r1)
        e(f'<rect x="{xa-7}" y="{ya-7}" width="{xb-xa+14}" height="{yb-ya+14}" rx="5" fill="#ffffff88" '
          f'stroke="{MUTE}" stroke-dasharray="5 4"/>')
        T((xa + xb) / 2, (ya + yb) / 2 - 4, t, 11.5, "middle", INK, "bold")
        T((xa + xb) / 2, (ya + yb) / 2 + 11, sub, 10, "middle", MUTE)
        T((xa + xb) / 2, (ya + yb) / 2 + 25, "wire by label", 9.5, "middle", MUTE)
    for net, pts in bottom:  # ghost of the bottom wiring
        d = " ".join(f"{xy(*p)[0]},{xy(*p)[1]}" for p in pts)
        e(f'<polyline points="{d}" fill="none" stroke="{ncol(net)}" stroke-opacity="0.18" stroke-width="3"/>')
    for p in parts:
        k, pins = p["kind"], p["pins"]
        pts = [xy(c, r) for c, r, _ in pins]
        for x, y in pts:
            e(f'<circle cx="{x}" cy="{y}" r="3.6" fill="#9a9a9a"/>')
        (x0, y0), (x1, y1) = pts[0], pts[-1]
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        vert = abs(x1 - x0) < 1
        if k == "R":
            e(f'<line x1="{x0}" y1="{y0}" x2="{x1}" y2="{y1}" stroke="#777" stroke-width="1.6"/>')
            L = min(abs(x1 - x0) + abs(y1 - y0) - 16, 34)
            w_, h_ = (9, L) if vert else (L, 9)
            e(f'<rect x="{mx-w_/2}" y="{my-h_/2}" width="{w_}" height="{h_}" rx="4" fill="#e9d3a3" stroke="#8a6d3b"/>')
            lx, ly = (mx + 8, my + 3) if vert else (mx, my - 8)
            T(lx, ly, f'{p["ref"]} {p["value"]}', 8.5, "start" if vert else "middle", INK)
        elif k == "C":
            e(f'<line x1="{x0}" y1="{y0}" x2="{x1}" y2="{y1}" stroke="#777" stroke-width="1.6"/>')
            e(f'<ellipse cx="{mx}" cy="{my}" rx="{5 if vert else 7}" ry="{7 if vert else 5}" fill="#4b7bd1" stroke="#23458a"/>')
            T(mx + 9, my + 3, p["value"], 8, "start", "#23458a")
        elif k == "J":
            xs = [x for x, _ in pts]; ys = [y for _, y in pts]
            e(f'<rect x="{min(xs)-7}" y="{min(ys)-8}" width="{max(xs)-min(xs)+14}" height="{max(ys)-min(ys)+16}" '
              'rx="2" fill="#2d6a4f" fill-opacity="0.85"/>')
            for x, y in pts:
                e(f'<circle cx="{x}" cy="{y}" r="3" fill="#d9d9d9"/>')
            right = pins[0][0] > COLS / 2
            T(min(xs) - 10 if right else max(xs) + 10, min(ys) - 2, p["ref"], 9, "end" if right else "start", INK, "bold")
        elif k == "Q":
            e(f'<path d="M{x0-6},{y0+4} L{x1+6},{y1+4} A{(x1-x0)/2+6},{(x1-x0)/2+6} 0 0 0 {x0-6},{y0+4} Z" '
              'fill="#333" fill-opacity="0.85"/>')
            for (x, y), lab in zip(pts, "CBE"):
                e(f'<circle cx="{x}" cy="{y}" r="3" fill="#d9d9d9"/>')
                T(x, y + 15, lab, 8.5, "middle", INK, "bold")
            T(x1 + 10, y1 - 10, "Q1 NPN", 9, "start", INK, "bold")
    for net, a, b in top:
        (x0, y0), (x1, y1) = xy(*a), xy(*b)
        e(f'<path d="M{x0},{y0} Q{(x0+x1)/2},{y0-14} {x1},{y1}" fill="none" stroke="#fff" stroke-width="5"/>')
        e(f'<path d="M{x0},{y0} Q{(x0+x1)/2},{y0-14} {x1},{y1}" fill="none" stroke="{ncol(net)}" stroke-width="2.4"/>')
    for c, r, t in pads:
        x, y = xy(c, r)
        e(f'<circle cx="{x}" cy="{y}" r="5" fill="none" stroke="{ACC}" stroke-width="1.8"/>')


def draw_bottom(xy):
    for net, pts in bottom:
        d = " ".join(f"{xy(*p)[0]},{xy(*p)[1]}" for p in pts)
        e(f'<polyline points="{d}" fill="none" stroke="{ncol(net)}" stroke-width="4.2" stroke-linecap="round" '
          'stroke-linejoin="round"/>')
    for p in parts:
        for c, r, _ in p["pins"]:
            x, y = xy(c, r)
            e(f'<circle cx="{x}" cy="{y}" r="4" fill="#b8b8b8" stroke="#555"/>')
    for net, a, b in top:
        for h in (a, b):
            x, y = xy(*h)
            e(f'<circle cx="{x}" cy="{y}" r="4" fill="#fff" stroke="{ncol(net)}" stroke-width="2"/>')
    for i, (c, r, t) in enumerate(pads):
        x, y = xy(c, r)
        e(f'<circle cx="{x}" cy="{y}" r="5.5" fill="none" stroke="{ACC}" stroke-width="1.8"/>')
        T(x + 6, y - 7, str(i + 1), 8.5, "start", ACC, "bold")


e(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
  'font-family="Inter, Helvetica, Arial, sans-serif">')
e(f'<rect width="{W}" height="{H}" fill="#fff"/>')
T(MX, 34, "limn bed load cells: perfboard", 18, w="bold")
T(MX, 54, f"2026-10-15 · 2.54 mm perfboard, {COLS} × {ROWS} holes ({COLS*2.54:.0f} × {ROWS*2.54:.0f} mm) · "
  "front end + touch stage laid out; modules and Pro Micro by label", 11, c=MUTE)

xy = board(TOPY, False, "Top (parts side)", "parts, insulated jumpers (arcs); bottom wiring ghosted; teal rings = a wire to a module / the Pro Micro")
draw_top(xy)
# pad labels on the top view
for i, (c, r, t) in enumerate(pads):
    x, y = xy(c, r)
    T(x + 6, y - 6, str(i + 1), 8.5, "start", ACC, "bold")

oy2 = TOPY + BH + GAP
xy2 = board(oy2, True, "Bottom (solder side), mirrored", "bare tinned wire; grey = a part's lead; white ring = a jumper's end; read it with the board flipped left-right")
draw_bottom(xy2)

# legend
ly = oy2 + BH + 50
for i, (net, lab) in enumerate((("AVDD_A", "AVDD_A (Pro Micro 3V3)"), ("AGND", "AGND"), ("MC", "MC (completion, filtered)"),
                                ("S", "S (sum)"), ("M1", "M1-M3 / raw mids"), ("TOUCH", "touch, GP6"), ("DGND", "DGND (touch only)"))):
    x = MX + (i % 4) * 190; y = ly + (i // 4) * 20
    e(f'<line x1="{x}" y1="{y}" x2="{x+26}" y2="{y}" stroke="{ncol(net)}" stroke-width="4.2"/>')
    T(x + 32, y + 4, lab, 10.5)
ty0 = ly + 58
T(MX, ty0, "Wires to the modules and the Pro Micro (teal rings, numbered):", 11, w="bold")
for i, (c, r, t) in enumerate(pads):
    T(MX + (i % 4) * 175, ty0 + 18 + (i // 4) * 15, f"{i+1}  {t}", 10, c=ACC)
ly = ty0 + 18 + ((len(pads) + 3) // 4) * 15
T(MX, ly + 6, "J1-J3: foot, top to bottom EXC+ (top gauge), mid, EXC− · J5: TOUCH, GND to the Melzi · R4/R5 completion pair", 10, c=MUTE)
T(MX, ly + 22, "R6-R9 1 k · C1-C4 4.7 nF · C5-C7 47 nF · R10-R12 47 k · C8 10 nF · C9 1 nF · R13 4.7 k · R14 100 k", 10, c=MUTE)
T(MX, ly + 38, "Q1: BC547 legs C-B-E with the flat face toward you; a 2N3904 is E-B-C: turn it round.", 10, c=MUTE)
T(MX, ly + 54, "Hops: the 47 nF caps sit on the MC bus, so M1-M3 jump over it on top (insulated wire).", 10, c=MUTE)
e("</svg>")

if problems:
    print("PROBLEMS:"); [print(" ", p) for p in problems]
else:
    print("layout ok:", len(parts), "parts,", len(bottom), "bottom wires,", len(top), "jumpers")
open(sys.argv[1], "w").write("\n".join(out))
