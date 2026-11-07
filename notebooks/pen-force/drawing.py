# The drawn sheet next to the cell's force on every stroke (2026-11-07 runs).
# uv run --with numpy --with matplotlib --with pillow python drawing.py
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from PIL import Image, ImageOps
from ana import load

RUNS = ['pen-draw-20261107-121858.jsonl', 'pen-draw-20261107-122119.jsonl']
PHOTO = '/home/noop/limn-shot/IMG_7490.JPG'
CROP = (1440, 720, 3490, 2350)        # full-res px: the W, circles, dots and both blocks
INK, MUTED, SURF = '#0b0b0b', '#52514e', '#fcfcfb'
BLUE = LinearSegmentedColormap.from_list('seq', ['#cde2fb', '#86b6ef', '#3987e5', '#1c5cab', '#0d366b'])
plt.rcParams.update({'figure.facecolor': SURF, 'axes.facecolor': SURF, 'axes.edgecolor': MUTED,
                     'axes.labelcolor': INK, 'xtick.color': MUTED, 'ytick.color': MUTED, 'font.size': 9})


def painted(path):
    """Ink samples on the paper: (x, y, grams over the stroke's air pass) per stroke, last run wins."""
    meta, c, pos = load(path)
    t = np.array([x[0] for x in c]); g = np.array([x[1] for x in c])
    air, out = {}, {}
    for k in meta['marks']:
        sel = (t >= k['t0']) & (t <= k['t1'])
        P = [pos(x) for x in t[sel]]
        ok = np.array([p[0] is not None for p in P])
        if not ok.any():
            continue
        xyz = np.array([p[0] for p, o in zip(P, ok) if o]); gs = g[sel][ok]
        low = xyz[:, 2] < xyz[:, 2].min() + 0.35            # on the paper, not hopping
        if k['kind'] == 'air':
            air[k['label']] = np.median(gs[low]); continue
        out[k['label']] = (xyz[low, 0], xyz[low, 1], gs[low] - air.get(k['label'], 0))
    return out


strokes = {}
for r in RUNS:
    strokes.update(painted(r))

im = ImageOps.exif_transpose(Image.open(PHOTO)).crop(CROP)
fig, (a0, a1) = plt.subplots(1, 2, figsize=(9.6, 3.9), gridspec_kw={'width_ratios': [1, 1.12]})
a0.imshow(im); a0.set_axis_off(); a0.set_title('The sheet (phone photo)', color=INK)

for label, (x, y, gs) in strokes.items():
    sc = a1.scatter(-y, x, c=np.clip(gs, 0, 50), cmap=BLUE, vmin=0, vmax=50, s=5, lw=0)
for label, tx in (('zigzag p0.2 v40', 'W 0.2'), ('circle p0.3 v40', '0.3'), ('circle p0.2 v40', '0.2'),
                  ('circle p0.1 v40', '0.1'), ('dot p0.2 x52', 'dots 0.2')):
    x, y, _ = strokes[label]
    a1.annotate(tx, (-y.mean(), x.max() + 1.5), ha='center', color=MUTED, fontsize=8)
a1.annotate('X lines\npress 0.3 … 0.1', (-90, 7), ha='center', color=MUTED, fontsize=8)
a1.annotate('Y lines\npress 0.1 (bottom) … 0.3', (-65, 7), ha='center', color=MUTED, fontsize=8)
a1.set_aspect('equal'); a1.set_ylim(4, 62)
a1.set_xticks([-100, -90, -80, -70, -60, -50], ['100', '90', '80', '70', '60', '50'])
a1.set(xlabel='Y (mm)', ylabel='X (mm)'); a1.set_title('Force on each stroke, as photographed', color=INK)
for s in ('top', 'right'):
    a1.spines[s].set_visible(False)
cb = fig.colorbar(sc, ax=a1, fraction=0.04, pad=0.02); cb.set_label('force over the air pass (g)')
cb.outline.set_visible(False)
fig.tight_layout(); fig.savefig('drawing.png', dpi=160)
