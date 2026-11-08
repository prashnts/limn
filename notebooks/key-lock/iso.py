# Isometric SVG of the tool plate from the STEP mesh: back view with the proposed lead-ins/detents, front view with the balls.
import json, math
M = json.load(open('/tmp/claude-1000/-home-noop-repo/e118dc02-237b-4f2a-b237-7d3407350e61/scratchpad/plate.json'))
CX, CZ, FLOOR = 73.68, 58.81, -48.5        # key axis (x, z), floor face y


def norm(v):
    n = math.sqrt(sum(a * a for a in v)) or 1e-12; return [a / n for a in v]


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def dot(a, b): return sum(x * y for x, y in zip(a, b))


class View:
    def __init__(self, eye, scale, ox, oy, centre):
        self.v = norm(eye)                                   # towards the viewer
        self.r = norm(cross([0, 0, 1], self.v)); self.u = cross(self.v, self.r)
        self.s, self.ox, self.oy, self.c = scale, ox, oy, centre
        self.light = norm([0.4, 0.8, 0.9]) if eye[1] > 0 else norm([0.4, -0.8, 0.9])

    def p(self, q):
        d = [q[i] - self.c[i] for i in range(3)]
        return self.ox + dot(d, self.r) * self.s, self.oy - dot(d, self.u) * self.s

    def depth(self, q): return dot(q, self.v)


def tris(body, xf=None):
    b = M[str(body)]; P = b['p']; I = b['i']
    pts = [P[k:k + 3] for k in range(0, len(P), 3)]
    if xf: pts = [xf(q) for q in pts]
    return [(pts[I[k]], pts[I[k + 1]], pts[I[k + 2]]) for k in range(0, len(I), 3)]


def rot_y(deg):                       # about the key axis (y), through (CX, CZ)
    a = math.radians(deg); c, s = math.cos(a), math.sin(a)
    return lambda q: [CX + (q[0] - CX) * c - (q[2] - CZ) * s, q[1], CZ + (q[0] - CX) * s + (q[2] - CZ) * c]


def shade(base, k):
    return '#%02x%02x%02x' % tuple(int(min(255, c * (0.45 + 0.55 * k))) for c in base)


def render(view, items):
    """items: (tri, rgb, opacity) -> svg polygons, painter-sorted, back faces culled."""
    out = []
    for t, rgb, op in items:
        n = norm(cross([t[1][i] - t[0][i] for i in range(3)], [t[2][i] - t[0][i] for i in range(3)]))
        if op == 0.9 and dot(n, view.v) < 0: n = [-a for a in n]
        if dot(n, view.v) <= 0: continue
        k = max(0.0, dot(n, view.light))
        out.append((sum(view.depth(q) for q in t) / 3, t, shade(rgb, k), op))
    out.sort(key=lambda e: e[0])
    svg = []
    for _, t, col, op in out:
        pts = ' '.join('%.1f,%.1f' % view.p(q) for q in t)
        o = '' if op == 1 else f' fill-opacity="{op}"'
        svg.append(f'<polygon points="{pts}" fill="{col}" stroke="{col}" stroke-width="0.6"{o}/>')
    return svg


def floor_cells():
    """Proposed floor: lead-in 0.8 -> 0 over 25-65 deg, detent at 90, in Q1 and Q3 (dowel turning +phi seen from the back)."""
    cells = []
    for q0 in (0, 180):
        for k in range(0, 40):
            a0, a1 = q0 + 22 + k * 2, q0 + 24 + k * 2
            if a1 > q0 + 100: break
            for j in range(9):
                r0, r1 = 2.6 + j * 0.5, 3.1 + j * 0.5
                am = math.radians((a0 + a1) / 2)
                if abs(r1 * math.sin(am)) < 2.4: continue          # still the slot
                a = a0 - q0
                if a < 65:   col = (214, 48, 49); d = 0.8 * (65 - a) / 40 + 0.02
                elif 84 <= a <= 96: col = (241, 196, 15); d = 0.17
                else: continue
                quad = [[CX + r * math.cos(math.radians(an)), FLOOR + 0.03, CZ + r * math.sin(math.radians(an))]
                        for r, an in ((r0, a0), (r1, a0), (r1, a1), (r0, a1))]
                shadek = 0.35 + 0.65 * (1 - d / 0.82) if a < 65 else 1
                for t in ((quad[0], quad[1], quad[2]), (quad[0], quad[2], quad[3])):
                    cells.append((t, tuple(int(c * (0.55 + 0.45 * shadek)) for c in col), 0.9))
    return cells


PLATE, STEEL, GHOST = (190, 208, 228), (150, 150, 155), (150, 150, 155)
centre = [CX, -48.3, CZ - 0.5]
# ---------- back view ----------
V = View([0.55, 1.0, 0.55], 15.5, 330, 400, centre)
items = [(t, PLATE, 1) for t in tris(1)]
fix = {}
for t in tris(7, rot_y(90)): pass
svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="760" viewBox="0 0 1120 760" font-family="Helvetica, Arial, sans-serif">',
       '<defs><style>.t{font-size:12.5px;fill:#222}.h{font-size:16px;font-weight:bold;fill:#111}.s{font-size:11px;fill:#555}'
       '.a{font-size:12.5px;fill:#b03a2e;font-weight:bold}.ld{stroke:#333;stroke-width:0.9;fill:none}</style>'
       '<marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0L10,5L0,10z" fill="#b03a2e"/></marker></defs>',
       '<rect width="1120" height="760" fill="#fff"/>',
       '<text class="h" x="20" y="28">Tool plate (Limn-Tool-Dock-Plate, v67 section): proposed lead-in + detent on the dowel floor</text>',
       '<text class="t" x="20" y="50">Back view (pocket side, the tool body side), dowel shown LOCKED. Rendered from the STEP mesh; red/yellow = new cuts.</text>']
svg += render(V, items)
svg += render(V, floor_cells())
svg += render(V, [(t, STEEL, 1) for t in tris(7, rot_y(90))])


def label(q, ty, s, cls='a'):
    x, y = V.p(q)
    left = x < V.ox
    tx = 30 if left else 610
    anchor = 'start'
    svg.append(f'<polyline class="ld" points="{x:.1f},{y:.1f} {tx:.1f},{ty + 4:.1f}"/>')
    svg.append(f'<text class="{cls}" x="{tx + (4 if anchor == "start" else -4):.1f}" y="{ty + 8:.1f}" text-anchor="{anchor}">{s}</text>')


def polar(r, deg, y=FLOOR):
    return [CX + r * math.cos(math.radians(deg)), y, CZ + r * math.sin(math.radians(deg))]


label(polar(5.2, 45), 175, 'lead-in: 0.8 deep at the slot edge → 0 at ~65°')
label(polar(5.2, 225), 560, 'lead-in, other dowel end')
label(polar(6.2, 90), 95, 'detent 0.15 at 90° (locked)')
label(polar(6.2, 270), 640, 'detent, other end')
label(polar(6.5, 180), 420, 'slot 14.5 x 4.5 (dowel enters level)', 't')
label(polar(4.6, 140), 250, 'floor (flat now): grease it', 't')
label(polar(7.05, 135, -45.0), 135, 'pocket r 7.1, 4.5 deep', 's')
label(polar(2.5, 100, -46.6), 300, 'dowel Ø2 x 14, locked', 't')
# turn arrow on the back of the pocket
arc = [V.p(polar(8.3, a, -44.0)) for a in range(8, 84, 4)]
svg.append('<polyline points="' + ' '.join('%.1f,%.1f' % p for p in arc) + '" fill="none" stroke="#b03a2e" stroke-width="2" marker-end="url(#ar)"/>')
x, y = arc[len(arc) // 2]; svg.append(f'<text class="a" x="30" y="455">lock turn shown; mirror</text>'); svg.append(f'<text class="a" x="30" y="470">if K turns the other way</text>')
svg.append('<text class="s" x="20" y="700">Leading edges only (the side the dowel turns onto); chamfer them. The ramp is helical: depth by angle, not by height, so the whole dowel climbs at once.</text>')
svg.append('<text class="s" x="20" y="716">Easiest in Fusion: a 0.8 x 40° helical/loft cut from the slot edge, or a sweep of a wedge around the key axis; detent = a Ø2 groove 0.15 deep along the 90° line.</text>')

# ---------- front view (head side) with the balls ----------
V2 = View([0.55, -1.0, 0.55], 6.5, 975, 520, centre)
items2 = [(t, PLATE, 1) for t in tris(1)] + [(t, STEEL, 1) for b in (0, 2, 3) for t in tris(b)]
svg.append('<text class="t" x="850" y="375">Front (head side): 3 M3 balls</text>')
svg += render(V2, items2)
for b, (tx, ty) in zip((0, 2, 3), ((1040, 400), (1060, 650), (880, 660))):
    P = M[str(b)]['p']; q = [sum(P[i::3]) / (len(P) // 3) for i in range(3)]
    x, y = V2.p(q)
    svg.append(f'<polyline class="ld" points="{x:.1f},{y:.1f} {tx:.1f},{ty:.1f}"/>')
svg.append('<text class="s" x="850" y="690">balls only seat the plate: all 3 equal</text>')
svg.append('<text class="s" x="850" y="705">protrusion (3.65), caliper depth rod</text>')
svg.append('</svg>')
open('/home/noop/repo/limn/notebooks/key-lock/plate-iso.svg', 'w').write('\n'.join(svg))
print(len(svg))
