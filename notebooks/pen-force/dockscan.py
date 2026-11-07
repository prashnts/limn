# Dock calibration with the carried tool going into its own, empty holder.
# dockscan.py x <T> <dy0> <dy1> <step> [z]   X profiles over a Y range
#             z <T> <x> <dy> <z0> <z1> <step>  Z ladder at a depth
import json, sys, time, urllib.request
sys.path.insert(0, '/home/pi/claude-cell')
import penrec
from penrec import gcode

MOON = 'http://127.0.0.1:7125'
OUT = '/home/pi/claude-cell/dock'
STAMP = time.strftime('%Y%m%d-%H%M%S')
LIMIT_G = 150


def query(obj):
    with urllib.request.urlopen(f'{MOON}/printer/objects/query?{obj}', timeout=5) as r:
        return json.load(r)['result']['status']


def holder_occupied(t):
    return t in (query('limn')['limn']['tool_holder']['occupied'] or [])


def dock_vars(t):
    d = query('gcode_macro%20_DOCK_HOME')['gcode_macro _DOCK_HOME']
    return {k: d[f'tool_{t}_{k}'] for k in ('x', 'y', 'z', 'dx', 'dy', 'dz')}


def mean_g(r, secs=0.25):
    t = time.time(); time.sleep(secs)
    g = [s[1] for s in r.lit.samples if s[0] >= t]
    return sum(g) / len(g)


def out_of_dock(d, y, z):
    gcode(f'G90\nG1 X{d["x"]} Y{y:.3f} Z{z:.3f} F1500\nG1 Z9.2 F600\nM400')


def x_profile(r, t, d, y, z, x0, x1, step=0.5, f=300, log=None):
    """In along X from x0 to x1 in `step` pieces: force + holder switch; back out."""
    gcode(f'G90\nG1 Z9.2 F600\nG1 X{d["x"]} Y{y:.3f} F5000\nG1 Z{z:.3f} F600\nG1 X{x0} F3000\nM400')
    time.sleep(0.4); r.lit.tare(); rows, x = [], x0
    try:
        while x < x1 - 1e-6:
            x = round(min(x1, x + step), 3)
            gcode(f'G1 X{x} F{f}\nM400'); g = mean_g(r)
            occ = holder_occupied(t)
            rows.append((x, round(g, 2), occ))
            print(f'  y {y:7.2f} z {z:5.2f} x {x:7.2f} {g:+7.1f} g{"  H" if occ else ""}', flush=True)
            if abs(g) > LIMIT_G:
                print('  limit', flush=True); break
    finally:
        out_of_dock(d, y, z)
        gcode('G90\nG1 X60 Y80 F5000\nG28 X\nG28 Y\nM400')    # a stall loses X steps
    if log:
        log.write(json.dumps({'kind': 'x', 'y': y, 'z': z, 'rows': rows}) + '\n'); log.flush()
    return rows


def z_ladder(r, t, d, x, y, z0, z1, step, log=None):
    gcode(f'G90\nG1 Z9.2 F600\nG1 X{d["x"]} Y{y:.3f} F5000\nG1 Z{z0:.3f} F600\nM400')
    gcode(f'G1 X{x} F300\nM400'); time.sleep(0.4)
    rows, z = [], z0
    base = mean_g(r, 0.6)
    try:
        n = int(round(abs(z1 - z0) / step))
        for i in range(n + 1):
            z = round(z0 + (z1 - z0) * i / n, 3)
            gcode(f'G1 Z{z} F60\nM400'); g = mean_g(r, 0.3) - base
            rows.append((z, round(g, 2), holder_occupied(t)))
            print(f'  x {x:7.2f} y {y:7.2f} z {z:6.3f} {g:+7.1f} g{"  H" if rows[-1][2] else ""}', flush=True)
            if abs(g) > LIMIT_G:
                print('  limit', flush=True); break
    finally:
        gcode(f'G1 Z{z0:.3f} F60\nM400'); out_of_dock(d, y, z0)
    if log:
        log.write(json.dumps({'kind': 'z', 'x': x, 'y': y, 'base': base, 'rows': rows}) + '\n'); log.flush()
    return rows


if __name__ == '__main__':
    what, t = sys.argv[1], int(sys.argv[2]); a = [float(v) for v in sys.argv[3:]]
    r = penrec.Rec(hz=50); d = dock_vars(t); print('dock', d, flush=True)
    log = open(f'{OUT}scan-{what}-{t}-{STAMP}.jsonl', 'w')
    x_end = d['x'] + d['dx']
    if what == 'x':
        dy0, dy1, step = a[:3]; z = a[3] if len(a) > 3 else d['z']
        n = int(round((dy1 - dy0) / step))
        for i in range(n + 1):
            x_profile(r, t, d, d['y'] + dy0 + i * step, z, x_end - 14, min(179.5, x_end + 1.5), log=log)
    elif what == 'xz':
        dy, z0, z1, step = a
        n = int(round((z1 - z0) / step))
        for i in range(n + 1):
            x_profile(r, t, d, d['y'] + dy, round(z0 + i * step, 3), x_end - 14, min(179.5, x_end + 1.5), log=log)
    elif what == 'z':
        x, dy, z0, z1, step = a
        z_ladder(r, t, d, x, d['y'] + dy, z0, z1, step, log=log)
