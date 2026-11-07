# Pen on paper with the head cell. pen.py contact | draw <plane.json>
import json, statistics as st, sys, time
sys.path.insert(0, '/home/pi/claude-cell')
import penrec
from penrec import gcode

OUT = '/home/pi/claude-cell/pen'
STAMP = time.strftime('%Y%m%d-%H%M%S')
POINTS = [(35, 76), (15, 55), (15, 97), (52, 55), (52, 97)]


def at(r, secs):
    t = time.time(); time.sleep(secs)
    g = [s[1] for s in r.lit.samples if s[0] >= t and not s[3] & 0x20]
    return st.mean(g)


def z_to(z, f=120):
    gcode(f'G90\nG1 Z{z:.3f} F{f}\nM400')


def contact(r, x, y, start, step, stop_g=12, log=None):
    """Down from `start` until +stop_g; contact = the 2 g crossing (interpolated)."""
    gcode(f'G90\nG1 Z{start + 1:.3f} F600\nG1 X{x} Y{y} F6000\nM400'); z_to(start)
    ref = at(r, 0.8); z, prev, rows = start, (start, 0.0), []
    while z > -3:
        z = round(z - step, 3); z_to(z, 60); g = at(r, 0.3) - ref
        rows.append((z, round(g, 2)))
        if g >= stop_g:
            break
        prev = (z, g) if g < 2 else prev
    z_to(start)
    # The knee: the last step before a rise of > 0.35 g/step that keeps rising
    zc = next((rows[i - 1][0] for i in range(1, len(rows) - 1)
               if rows[i][1] - rows[i - 1][1] > 0.35 and rows[i + 1][1] > rows[i][1]), None)
    if zc is None:
        return None, rows
    if log:
        log.write(json.dumps({'x': x, 'y': y, 'zc': zc, 'rows': rows}) + '\n'); log.flush()
    return zc, rows


def fit_plane(pts):
    """z = a + b x + c y, least squares (3x3 normal equations)."""
    n = len(pts); sx = sum(p[0] for p in pts); sy = sum(p[1] for p in pts)
    sxx = sum(p[0] ** 2 for p in pts); syy = sum(p[1] ** 2 for p in pts)
    sxy = sum(p[0] * p[1] for p in pts)
    sz = sum(p[2] for p in pts); sxz = sum(p[0] * p[2] for p in pts); syz = sum(p[1] * p[2] for p in pts)
    m = [[n, sx, sy, sz], [sx, sxx, sxy, sxz], [sy, sxy, syy, syz]]
    for i in range(3):
        for j in range(i + 1, 3):
            k = m[j][i] / m[i][i]
            m[j] = [a - k * b for a, b in zip(m[j], m[i])]
    c = m[2][3] / m[2][2]; b = (m[1][3] - m[1][2] * c) / m[1][1]
    a = (m[0][3] - m[0][1] * b - m[0][2] * c) / m[0][0]
    return a, b, c


if __name__ == '__main__':
    r = penrec.Rec(hz=50)
    if sys.argv[1] == 'contact':
        log = open(f'{OUT}-contact-{STAMP}.jsonl', 'w')
        zc, rows = contact(r, *POINTS[0], start=float(sys.argv[2]) if len(sys.argv) > 2 else 4, step=0.1, log=log)
        print('coarse', zc, rows[-6:], flush=True)
        if zc is None:
            raise SystemExit('no contact')
        pts = []
        for x, y in POINTS:
            zs = [contact(r, x, y, zc + 0.4, 0.02, stop_g=6, log=log)[0] for _ in range(2)]
            print(f'({x},{y}) contact {zs}', flush=True)
            pts.append((x, y, st.mean(zs)))
        a, b, c = fit_plane(pts)
        res = [p[2] - (a + b * p[0] + c * p[1]) for p in pts]
        print(f'plane a {a:.3f} b {b * 1000:.2f}/m c {c * 1000:.2f}/m res', [round(v, 3) for v in res])
        json.dump({'a': a, 'b': b, 'c': c, 'pts': pts}, open(f'{OUT}-plane.json', 'w'))
        z_to(zc + 3, 600)


# The test sheet, X 14-54, Y 53-100 (blank on the 2026-11-07 sheet)
PRESSES, SPEEDS, HOP, AIR = (0.1, 0.2, 0.3), (10, 40, 100), 1.0, 0.6


def patterns():
    """(label, press, speed mm/s, [(x, y, hold s)]) per stroke."""
    out, i = [], 0
    for p in PRESSES:
        for v in SPEEDS:
            for d in (1, -1):
                x, y = 14 + 1.2 * i, 80 + 1.2 * i
                ys, xs = (55, 75)[::d], (14, 34)[::d]
                out.append((f'yline p{p} v{v} {"+-"[d < 0]}', p, v, [(x, ys[0], 0), (x, ys[1], 0)]))
                out.append((f'xline p{p} v{v} {"+-"[d < 0]}', p, v, [(xs[0], y, 0), (xs[1], y, 0)]))
                i += 1
    from math import cos, sin, pi
    for p, yc in zip(PRESSES, (60, 71, 82)):
        out.append((f'circle p{p} v40', p, 40,
                    [(46 + 4 * cos(2 * pi * k / 48), yc + 4 * sin(2 * pi * k / 48), 0) for k in range(49)]))
    out.append(('zigzag p0.2 v40', 0.2, 40, [(39 if k % 2 else 53, 88 + 2 * k, 0) for k in range(6)]))
    for x in (40, 44, 48, 52):
        out.append((f'dot p0.2 x{x}', 0.2, 0, [(x, 53, 1.0)]))
    return out


def stroke_gcode(plane, pts, dz, v):
    """Hop over, down at 5 mm/s, along in <= 1 mm pieces on the paper's plane, up."""
    a, b, c = plane['a'], plane['b'], plane['c']
    zp = lambda x, y: a + b * x + c * y
    x0, y0, _ = pts[0]
    g = [f'G1 Z{zp(x0, y0) + HOP:.3f} F300', f'G1 X{x0:.3f} Y{y0:.3f} F6000',
         f'G1 Z{zp(x0, y0) + dz:.3f} F300']
    for (xa, ya, _), (xb, yb, hold) in zip(pts, pts[1:]):
        n = max(1, int(((xb - xa) ** 2 + (yb - ya) ** 2) ** 0.5))
        for k in range(1, n + 1):
            x, y = xa + (xb - xa) * k / n, ya + (yb - ya) * k / n
            g.append(f'G1 X{x:.3f} Y{y:.3f} Z{zp(x, y) + dz:.3f} F{v * 60}')
    if pts[-1][2]:
        g.append(f'G4 P{int(pts[-1][2] * 1000)}')
    xe, ye, _ = pts[-1]
    g += [f'G1 Z{zp(xe, ye) + HOP:.3f} F300', 'M400']
    return 'G90\n' + '\n'.join(g)


def draw(r, plane, only=None, start=0):
    marks, t0 = [], time.time()
    a, b, c = plane['a'], plane['b'], plane['c']
    gcode(f'G90\nG1 Z{a + b * 30 + c * 75 + 3:.3f} F600\nG1 X30 Y75 F6000\nM400')
    gcode(f'G1 Z{a + b * 30 + c * 75 + HOP:.3f} F300\nM400'); time.sleep(1); r.lit.tare()
    try:
        for label, p, v, pts in patterns()[start:]:
            if only and only not in label:
                continue
            for kind, dz in (('air', AIR), ('ink', -p)):
                s = penrec.mono(); gcode(stroke_gcode(plane, pts, dz, v or 10))
                marks.append({'label': label, 'kind': kind, 'press': p, 'v': v, 't0': s, 't1': penrec.mono(),
                              'pts': pts})
                g = [x[1] for x in r.lit.samples if marks[-1]['t0'] <= x[0] - r.dt <= marks[-1]['t1']]
                end, peak = sum(g[-5:]) / 5, max(g)
                print(f'{label:22s} {kind} peak {peak:6.1f} end {end:5.1f}', flush=True)
                if peak > 120 or end > 2 or kind == 'air' and peak > 5:
                    print('STOP: the tool moved or presses too hard', flush=True)
                    return
    finally:
        gcode(f'G90\nG1 Z{a + b * 30 + c * 75 + 4:.3f} F600\nM400')
        path = f'{OUT}-draw-{STAMP}.jsonl'
        r.dump(path, t0, {'plane': plane, 'marks': marks})
        print(path)


if __name__ == '__main__' and sys.argv[1] == 'draw':
    draw(r, json.load(open(sys.argv[2])), sys.argv[3] if len(sys.argv) > 3 else None)
