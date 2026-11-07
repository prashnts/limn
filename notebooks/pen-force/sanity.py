# No-tool sanity: K switch over the K travel (with the cell), then cell rest + Z sweep.
import json, statistics as st, sys, time
sys.path.insert(0, '/home/pi/claude-cell')
import penrec
from penrec import gcode


def k_switch(r):
    i = r.kl.call('query_endstops/status')
    while i not in r.kl.replies:
        time.sleep(0.002)
    return r.kl.replies.pop(i)['result'].get('manual_stepper axis_k') == 'TRIGGERED'   # 'open' is truthy too


def cell(r, secs=0.3):
    t = time.time(); time.sleep(secs)
    g = [s[1] for s in r.lit.samples if s[0] >= t]
    return st.mean(g)


def k_profile(r, step=0.5, span=16):
    gcode('MANUAL_STEPPER STEPPER=axis_k ENABLE=1 SET_POSITION=0'); time.sleep(0.5); r.lit.tare()
    out = []
    n = int(span / step)
    for p in [i * step for i in range(n + 1)] + [i * step for i in range(n, -1, -1)]:
        gcode(f'MANUAL_STEPPER STEPPER=axis_k MOVE={p} SPEED=5'); g = cell(r)
        out.append((p, k_switch(r), round(g, 2)))
    gcode('MANUAL_STEPPER STEPPER=axis_k ENABLE=0')
    last = None
    for i, (p, sw, g) in enumerate(out):
        leg = 'lock ' if i <= n else 'back '
        if sw != last or i in (0, n, len(out) - 1):
            print(f'  {leg} K {p:5.1f}  switch {"TRIG" if sw else "open"}  cell {g:+6.2f} g', flush=True)
        last = sw
    gs = [g for _, _, g in out]
    print(f'  cell over the K travel: {min(gs):+.2f}..{max(gs):+.2f} g', flush=True)
    return out


if __name__ == '__main__':
    r = penrec.Rec(hz=50)
    print('K profile (no homing needed)', flush=True)
    rows = k_profile(r)
    print('home', flush=True); gcode('G28\nG90\nG1 X60 Y80 F5000\nG1 Z2 F600\nM400')
    time.sleep(1); r.lit.tare()
    t = time.time(); time.sleep(10)
    g = [s[1] for s in r.lit.samples if s[0] >= t]
    print(f'rest Z2 10 s: n {len(g)} sd {st.pstdev(g):.2f} g, {min(g):+.2f}..{max(g):+.2f}', flush=True)
    sweep = []
    for z in [2, 3, 4, 5, 6, 7, 7.5, 7, 6, 5, 4, 3, 2, 1, 0, -1, -2, -2.5, -1, 0, 2]:
        gcode(f'G1 Z{z} F300\nM400'); sweep.append((z, round(cell(r, 0.6), 2)))
    print('Z sweep (g):', ' '.join(f'{z}:{g:+.1f}' for z, g in sweep), flush=True)
    json.dump({'k': rows, 'sweep': sweep}, open(f'/home/pi/claude-cell/sanity-{time.strftime("%Y%m%d-%H%M%S")}.json', 'w'))
