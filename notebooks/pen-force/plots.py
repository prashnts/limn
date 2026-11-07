# Plots for README.md (pen force, 2026-11-07). uv run --with numpy --with matplotlib python plots.py
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from ana import load
from stats import strokes

RUN = ['pen-draw-20261107-121858.jsonl', 'pen-draw-20261107-122119.jsonl']
C = ['#2a78d6', '#eb6834', '#1baf7a']
INK, MUTED, SURF = '#0b0b0b', '#52514e', '#fcfcfb'
plt.rcParams.update({'figure.facecolor': SURF, 'axes.facecolor': SURF, 'axes.edgecolor': MUTED,
                     'axes.labelcolor': INK, 'xtick.color': MUTED, 'ytick.color': MUTED, 'font.size': 9,
                     'axes.spines.top': False, 'axes.spines.right': False, 'axes.grid': True,
                     'grid.color': '#e4e3df', 'grid.linewidth': 0.6, 'legend.frameon': False})


def trace(path, label):
    meta, c, pos = load(path)
    k = next(m for m in meta['marks'] if m['label'] == label and m['kind'] == 'ink')
    a = next(m for m in meta['marks'] if m['label'] == label and m['kind'] == 'air')
    t = np.array([x[0] for x in c]); g = np.array([x[1] for x in c])
    base = np.median(g[(t >= a['t0']) & (t <= a['t1'])])
    sel = (t >= k['t0']) & (t <= k['t1'])
    return t[sel] - k['t0'], g[sel] - base


# 1: one stroke per press (Y+ at 40 mm/s): touchdown, stroke, lift
fig, ax = plt.subplots(figsize=(6.4, 2.6))
for i, p in enumerate((0.1, 0.2, 0.3)):
    tt, gg = trace(RUN[0], f'yline p{p} v40 +')
    ax.plot(tt, gg, color=C[i], lw=1.4, label=f'press {p} mm')
ax.set(xlabel='time in the stroke (s)', ylabel='force (g)', title='One Y+ stroke at 40 mm/s')
ax.legend(loc='upper left'); fig.tight_layout(); fig.savefig('trace.png', dpi=160)

# 2: steady force by press and direction
rows = {r['label']: r for p in RUN for r in strokes(p)}
fig, axs = plt.subplots(1, 2, figsize=(6.4, 2.6), sharey=True)
for ax, axis in zip(axs, ('xline', 'yline')):
    for j, (d, col) in enumerate((('+', C[0]), ('-', C[1]))):
        for v, mk in zip((10, 40, 100), 'o^s'):
            ps = [0.1, 0.2, 0.3]
            ms = [rows[f'{axis} p{p} v{v} {d}']['mean'] for p in ps]
            ax.plot([p + (j - 0.5) * 0.012 for p in ps], ms, mk, color=col, ms=5,
                    label=f'{d} {v} mm/s')
    ax.set(xlabel='press past contact (mm)', title=f'{axis[0].upper()} lines', xticks=[0.1, 0.2, 0.3])
axs[0].set_ylabel('steady force (g)')
h, l = axs[1].get_legend_handles_labels()
fig.legend(h, l, loc='center right', fontsize=7, title='dir, speed', title_fontsize=7)
fig.tight_layout(rect=(0, 0, 0.8, 1)); fig.savefig('press.png', dpi=160)

# 3: force around the press-0.3 circle against heading
meta, c, pos = load(RUN[1])
t = np.array([x[0] for x in c]); g = np.array([x[1] for x in c])
k = next(m for m in meta['marks'] if m['label'] == 'circle p0.3 v40' and m['kind'] == 'ink')
a = next(m for m in meta['marks'] if m['label'] == 'circle p0.3 v40' and m['kind'] == 'air')
base = np.median(g[(t >= a['t0']) & (t <= a['t1'])])
sel = (t >= k['t0']) & (t <= k['t1']); P = [pos(x) for x in t[sel]]
ok = np.array([p[0] is not None and p[1] > 30 for p in P])
xy = np.array([p[0][:2] for p, o in zip(P, ok) if o]); gs = g[sel][ok] - base
d = np.gradient(xy, axis=0); th = np.degrees(np.arctan2(d[:, 1], d[:, 0])) % 360
fig, ax = plt.subplots(figsize=(6.4, 2.4))
ax.plot(th, gs, 'o', color=C[0], ms=3, alpha=0.7)
A = np.c_[np.ones_like(th), np.cos(np.radians(th)), np.sin(np.radians(th))]
f = np.linalg.lstsq(A, gs, rcond=None)[0]; hh = np.linspace(0, 360, 200)
ax.plot(hh, f[0] + f[1] * np.cos(np.radians(hh)) + f[2] * np.sin(np.radians(hh)), color=INK, lw=1)
ax.set(xlabel='heading (deg, 0 = +X, 90 = +Y)', ylabel='force (g)', xticks=range(0, 361, 90),
       title='Circle, press 0.3, 40 mm/s: force against heading')
fig.tight_layout(); fig.savefig('heading.png', dpi=160)

# 4: line width from the photo against speed
px_mm = 39.6   # measured pitch: 1.2 mm = 47.5 px
W = {0.2: {'x': [19, 19, 15, 14, 10, 9], 'y': [19, 20, 14, 14, 11, 9]},
     0.3: {'x': [20, 19, 18, 15, 13, 11], 'y': [20, 21, 16, 16, 13, 11]}}
fig, ax = plt.subplots(figsize=(6.4, 2.4))
for i, p in enumerate(W):
    w = np.array(W[p]['x'] + W[p]['y']).reshape(2, 3, 2).mean(axis=(0, 2)) / px_mm
    ax.plot([10, 40, 100], w, '-o', color=C[i + 1], lw=1.4, ms=5, label=f'press {p}')
ax.set(xscale='log', xticks=[10, 40, 100], xticklabels=['10', '40', '100'], xlabel='speed (mm/s)',
       ylabel='line width (mm)', title='Line width (phone photo) against speed', ylim=(0, 0.6))
ax.legend(); fig.tight_layout(); fig.savefig('width.png', dpi=160)
