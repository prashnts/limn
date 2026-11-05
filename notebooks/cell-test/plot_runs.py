"""Head load cell: cell-now.png (11-03 on the plotter), cell-runs.png (all runs)."""
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).parent
PI = HERE / '20261103-pi'
BLUE, ORANGE, AQUA, YELLOW = '#2a78d6', '#eb6834', '#1baf7a', '#eda100'
INK, MUTED, GRID = '#0b0b0b', '#898781', '#e1e0d9'


def run(name: str) -> dict:
    return json.loads((HERE / f'{name}.json').read_text())


def rows(name: str) -> list[dict]:
    return [json.loads(line) for line in (PI / f'{name}.jsonl').open()]


def press_trace(name: str) -> tuple[np.ndarray, np.ndarray]:
    d = run(name)
    t0, t1 = next(m[1:] for m in d['marks'] if m[0] == 'press')
    s = np.array(d['samples'], float)
    s = s[(s[:, 0] >= t0 - 2) & (s[:, 0] <= t1 + 12)]
    return s[:, 0] - t0, s[:, 1] - np.median(s[s[:, 0] < t0, 1])


def style(ax, title: str, xlabel: str, ylabel: str):
    ax.set_title(title, loc='left', fontsize=10, color=INK)
    ax.set_xlabel(xlabel, color=MUTED)
    ax.set_ylabel(ylabel, color=MUTED)
    ax.grid(color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    ax.tick_params(colors=MUTED, labelsize=8)
    for side in ('top', 'right'):
        ax.spines[side].set_visible(False)
    for side in ('left', 'bottom'):
        ax.spines[side].set_color(GRID)


def noise(ax):
    rest = np.array([g for _, g in rows('rest-20261103-181503')[0]['rest']])
    runs = [
        ('v1 bench 10-24', run('20261024-204813-v1-printed-clamp')['drift']),
        ('v2 bench 10-25', run('20261025-001803-v2-printed-clamp')['drift']),
        ('v2 on plotter, 50 Hz 10-25', run('20261025-111818-v2-printed-clamp')['drift']),
        ('new print, desk 11-01', run('20261101-142342-new-print-desk')['drift']),
        ('plotter, FFC 11-01', run('20261101-174938-on-plotter-ffc')['drift']),
    ]
    labels = [r[0] for r in runs] + ['plotter, Pi Z0 11-03']
    vals = [r[1]['noise_rms_g'] for r in runs] + [rest.std()]
    y = np.arange(len(vals))[::-1]
    ax.barh(y, vals, color=BLUE, height=0.6)
    for yi, v in zip(y, vals):
        ax.text(v + 0.05, yi, f'{v:.2f}', va='center', fontsize=8, color=INK)
    ax.set_yticks(y, labels, fontsize=8)
    ax.set_xlim(0, 3.6)
    style(ax, 'A  Hands-off noise (before 11-01: 236 counts/g estimate)', 'g rms', '')


def presses(ax):
    for name, label, c in (('20261024-204813-v1-printed-clamp', 'Al v1, gauges at fixed end: dips below 0 after each release', BLUE),
                           ('20261025-001803-v2-printed-clamp', 'Al v2, flipped: zero steps up and stays', ORANGE)):
        t, g = press_trace(name)
        ax.plot(t, g, color=c, lw=1, label=label)
    ax.axhline(0, color=MUTED, lw=0.8)
    ax.set_ylim(-8, 12)
    ax.legend(fontsize=8, frameon=False, loc='lower right')
    style(ax, 'B  Finger presses on the bench, zoomed on zero (peaks 6-230 g off-scale)',
          's', 'g vs zero before')


def zsweep(ax):
    for name, label, c in (('fine-20261103-181022', 'before wire fix (a cable caught)', ORANGE),
                           ('fine-20261103-221613', 'after wire fix', BLUE),
                           ('low-20261103-222047', None, BLUE)):
        pts = {}
        for r in rows(name):
            pts.setdefault(r['label'].split()[1], []).append((r['z'], r['g']))
        for i, (direction, p) in enumerate(sorted(pts.items())):
            z, g = np.array(sorted(p)).T
            ax.plot(z, g, color=c, lw=1.5, ls='-' if direction == 'up' else '--',
                    label=label if (i == 1 and label) else None)
    ax.axhspan(-1, 1, color=GRID, alpha=0.6, lw=0)
    ax.legend(fontsize=8, frameon=False, loc='lower left', title='solid: Z going up, dashed: Z going down',
              title_fontsize=7)
    style(ax, 'C  Z travel with nothing touching (should read 0)', 'Z (mm)', 'g')


def paper(ax):
    rs = [r for r in rows('tool-20261103-223751') if r.get('label') in ('ldown', 'lup', 'lend')]
    for lab, c, txt in (('ldown', BLUE, 'Z stepping down 50 µm: tip loads the paper'),
                         ('lup', ORANGE, 'Z stepping back up: unloading')):
        p = np.array([(r['z'], r['rel']) for r in rs if r['label'] == lab])
        ax.plot(p[:, 0], p[:, 1], 'o-', color=c, lw=2, ms=4, label=txt)
    ax.axvline(3.888, color=MUTED, lw=0.8, ls=':')
    ax.text(3.885, 35, 'contact 3.888', fontsize=7, color=MUTED)
    ax.invert_xaxis()
    ax.legend(fontsize=8, frameon=False, loc='upper left')
    style(ax, 'C  Tip force vs Z, pointing tool on paper', 'Z (mm), down →',
          'g on the tip')


def rest(ax):
    r = np.array(rows('rest-20261103-181503')[0]['rest'])
    t, g = r[:, 0] - r[0, 0], r[:, 1] - r[:, 1].mean()
    ax.plot(t, g, color=BLUE, lw=0.8)
    ax.set_ylim(-1.5, 1.5)
    ax.text(0.02, 0.92, f'sd {g.std():.2f} g, {len(g) / t[-1]:.0f} readings/s',
            transform=ax.transAxes, fontsize=8, color=INK)
    style(ax, 'A  Parked at Z0, nothing touching: noise (pre wire fix; after: sd 0.15 g)', 's', 'g (mean removed)')


def repeats(ax):
    rs = [r for r in rows('tool-20261103-223751') if str(r.get('label')).startswith('rep')]
    zs = [r['z2'] for r in rows('tool-20261103-223751') if r.get('ev') == 'rep']
    for i in range(5):
        p = np.array([(r['z'], r['rel']) for r in rs if r['label'] == f'rep{i}'])
        ax.plot(p[:, 0], p[:, 1], color=BLUE, lw=1, alpha=0.4 + 0.12 * i)
    ax.axhline(3, color=MUTED, lw=0.8, ls=':')
    ax.text(0.02, 0.92, f'one line per approach (5), Z down in 20 µm steps;\n3 g reached at Z {min(zs):.2f}-{max(zs):.2f}',
            transform=ax.transAxes, fontsize=8, color=INK)
    ax.invert_xaxis()
    style(ax, 'B  Touching the paper 5 times: same contact Z?', 'Z (mm), down →',
          'g on the tip')


def hold(ax):
    h = np.array([(r['t'], r['rel']) for r in rows('tool-20261103-223751') if r.get('label') == 'hold'])
    ax.plot(h[:, 0] - h[0, 0] + 2, h[:, 1], 'o-', color=BLUE, lw=2, ms=4)
    ax.set_ylim(25, 31)
    ax.text(0.98, 0.92, f'{h[0, 1]:.1f} → {h[-1, 1]:.1f} g, flat after ~18 s',
            transform=ax.transAxes, ha='right', fontsize=8, color=INK)
    style(ax, 'D  Z held still at 3.738 on paper: does the force sag?', 's',
          'g on the tip')


def save(panels, title: str, out: str):
    fig, axs = plt.subplots(2, 2, figsize=(11, 7.5), facecolor='#fcfcfb')
    for f, ax in zip(panels, axs.flat):
        ax.set_facecolor('#fcfcfb')
        f(ax)
    fig.suptitle(title, x=0.01, ha='left', color=INK)
    fig.tight_layout()
    fig.savefig(HERE / out, dpi=130)


save((noise, presses, zsweep, paper), 'limn head load cell, runs 2026-10-24 → 11-03', 'cell-runs.png')
save((rest, repeats, paper, hold), 'limn head load cell on the plotter, 2026-11-03', 'cell-now.png')


def evolution():
    """Key numbers per stage; None = not measured. Values from the runs above + TODO.md."""
    stages = ['Al v1\nbench\n10-24', 'Al v2\nbench\n10-25', 'Al v2\nplotter\n10-25',
              'printed\ndesk\n11-01', 'printed\nplotter\n11-01', 'printed\nplotter\n11-03']
    panels = [
        ('Hands-off noise, g rms (log)', [0.58, 1.03, 3.04, 1.42, 0.11, 0.15], True,
         {2: '50 Hz, then 0.2\nafter LIT fix'}),
        ('Zero error after presses, g', [3, 6, None, None, 0, None], False,
         {0: 'dips', 1: 'ratchets', 4: 'returns\n(±100 g)'}),
        ('Worst pull from motion/cables, g (log)', [2.0, 2.4, 90, None, None, 1], True,
         {0: 'wiggle', 1: 'wiggle', 2: 'XY drag', 5: 'Z travel\n(80 before\nwire fix)'}),
    ]
    fig, axs = plt.subplots(1, 3, figsize=(13, 4.2), facecolor='#fcfcfb')
    x = np.arange(len(stages))
    for ax, (title, vals, log, notes) in zip(axs, panels):
        ax.set_facecolor('#fcfcfb')
        ax.axvspan(2.5, 5.5, color=GRID, alpha=0.35, lw=0)
        pts = [(i, v) for i, v in enumerate(vals) if v is not None]
        xi, vi = np.array(pts).T
        ax.plot(xi, vi, ':', color=BLUE, lw=1.2)  # dotted across stages not measured
        for (a, va), (b, vb) in zip(pts, pts[1:]):
            if b == a + 1:
                ax.plot([a, b], [va, vb], color=BLUE, lw=2)
        ax.plot(xi, vi, 'o', color=BLUE, ms=7)
        for i, v in pts:
            note = f'{v:g}' + (f'\n{notes[i]}' if i in notes else '')
            ax.annotate(note, (i, v), xytext=(0, 9), textcoords='offset points',
                        ha='center', fontsize=7, color=INK)
        if log:
            ax.set_yscale('log')
            ax.set_ylim(0.05, 600)
        else:
            ax.set_ylim(-1, 9)
        ax.set_xticks(x, stages, fontsize=7)
        ax.set_xlim(-0.5, 5.5)
        style(ax, title, '', '')
    axs[0].text(4, 0.07, 'one-piece printed', ha='center', fontsize=8, color=MUTED)
    fig.suptitle('limn head load cell: aluminium strips → one-piece printed', x=0.01,
                 ha='left', color=INK)
    fig.tight_layout()
    fig.savefig(HERE / 'cell-evolution.png', dpi=130)


evolution()
