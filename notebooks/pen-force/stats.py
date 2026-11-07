# Per ink stroke: steady force (minus the air pass), ripple, touchdown peak, wobble frequency.
import sys, statistics as st
import numpy as np
from ana import load


def strokes(path):
    meta, c, pos = load(path)
    t = np.array([x[0] for x in c]); g = np.array([x[1] for x in c])
    out, air = [], {}
    for k in meta['marks']:
        sel = (t >= k['t0']) & (t <= k['t1'])
        ts, gs = t[sel], g[sel]
        ps = [pos(x) for x in ts]
        z = np.array([p[0][2] if p[0] else np.nan for p in ps]); v = np.array([p[1] for p in ps])
        xy = np.array([p[0][:2] if p[0] else (np.nan, np.nan) for p in ps])
        if k['kind'] == 'air':
            air[k['label']] = (xy, gs, z); continue
        zdraw = np.nanmin(z)
        V = k['v'] or 0
        on = np.where((z < zdraw + 0.35) & ((v > 0.8 * V) if V else (v < 0.5)))[0]   # drawing, not hopping
        if len(on) < 10:
            continue
        a, b = on[0], on[-1]
        n = b - a; mid = slice(a + n // 5, b - n // 5)      # steady middle
        axy, ag, az = air[k['label']]
        aon = az < np.nanmin(az) + 0.35
        base = np.median(ag[aon]) if aon.any() else 0
        gm = gs[mid] - base
        f = np.fft.rfft(gm - gm.mean()); fr = np.fft.rfftfreq(len(gm), np.median(np.diff(ts)))
        fpk = fr[1:][np.argmax(abs(f[1:]))] if len(gm) > 20 else np.nan
        first = gs[a:a + 15] - base
        out.append(dict(label=k['label'], press=k['press'], v=k['v'], mean=gm.mean(), sd=gm.std(),
                        pp=np.ptp(gm), td=first.max() - gm.mean(), f=fpk, trend=np.polyfit(np.arange(len(gm)), gm, 1)[0] * 100 if len(gm) > 5 else 0))
    return out


if __name__ == '__main__':
    rows = [r for p in sys.argv[1:] for r in strokes(p)]
    seen = {}
    for r in rows:
        seen[r['label']] = r
    print(f'{"stroke":24s} {"mean g":>7s} {"sd":>5s} {"p-p":>6s} {"td+":>6s} {"f Hz":>5s} {"g/s":>6s}')
    for r in seen.values():
        print(f'{r["label"]:24s} {r["mean"]:7.1f} {r["sd"]:5.1f} {r["pp"]:6.1f} {r["td"]:6.1f} {r["f"]:5.1f} {r["trend"]:6.1f}')
