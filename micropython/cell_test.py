# Limn load cell bench test - how good is a cell: noise, drift, return to zero, hysteresis, creep
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
#   uv run micropython/cell_test.py --port /dev/ttyACM1
#   uv run micropython/cell_test.py --weights 7.5,16,24.5 --port /dev/ttyACM1
#   uv run micropython/cell_test.py --only presses --only wiggle
#
# Talks to LIT (or the plot bed) over USB like mcu.py, records its sample
# stream and walks through the steps, asking before each one. --weights are
# the total loads you can put on (eg. stacked coins: 1 EUR 7.5 g, 2 EUR 8.5 g).
# Without them the weights and creep steps are skipped, and grams are LIT's
# (the estimate until calibrate(<g>)). Prints a report and keeps the samples
# and the report in notebooks/cell-test/<time>.json, to compare cells.
import json
import time
import threading
import numpy as np
import typer

from pathlib import Path
from typing import Annotated

from mcu import Dock, find_port, PortOption, HERE
from link import LOAD_TARING, LOAD_CAL

STEPS = ('drift', 'presses', 'weights', 'creep', 'wiggle')
OUT = HERE.parent / 'notebooks' / 'cell-test'
RATE_HZ = 50
SETTLE_S = 4            # after a load goes on or off, before averaging
AVERAGE_S = 3
PRESS_G = 5.0           # above this, a press

app = typer.Typer()


class Recorder:
    '''Collects (t, grams, raw) from the stream in a thread; logs go to a list.'''

    def __init__(self, dock):
        self.dock = dock
        self.samples = []
        self.logs = []
        self.marks = []         # (label, start, end) of each recording
        self.calibrated = False
        self._stop = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        for kind, data in self.dock.lines():
            if self._stop:
                return
            if kind == 'log':
                self.logs.append(data.get('text', '') if isinstance(data, dict) else str(data))
            elif kind == 'data' and isinstance(data, dict) and data.get('kind') == 6:
                flags, mg, raw = data['values'][:3]
                if not flags & LOAD_TARING:
                    self.samples.append((time.monotonic(), mg / 1000, raw))
                self.calibrated = bool(flags & LOAD_CAL)

    def stop(self):
        self._stop = True

    def now(self):
        return time.monotonic()

    def window(self, t0, t1):
        '''Samples between two times as (t, grams) arrays, t from t0.'''
        s = [(t - t0, g) for t, g, _ in self.samples if t0 <= t < t1]
        if not s:
            return np.zeros(0), np.zeros(0)
        a = np.array(s)
        return a[:, 0], a[:, 1]

    def record(self, seconds, label=''):
        t0 = self.now()
        while self.now() - t0 < seconds:
            left = seconds - (self.now() - t0)
            g = self.samples[-1][1] if self.samples else float('nan')
            print(f"\r  {label} {left:5.1f} s left   {g:+8.2f} g   ", end='', flush=True)
            time.sleep(0.1)
        print('\r' + ' ' * 60 + '\r', end='')
        self.marks.append((label, t0, self.now()))
        return t0, self.now()

    def mean(self, seconds):
        t0, t1 = self.record(seconds, 'averaging')
        return float(np.mean(self.window(t0, t1)[1]))

    def wait_log(self, prefix, timeout=5):
        n = len(self.logs)
        end = self.now() + timeout
        while self.now() < end:
            for text in self.logs[n:]:
                if text.startswith(prefix):
                    return text
            time.sleep(0.05)
        return None


def ask(text):
    input(f"\n> {text} [Enter] ")

def tare(rec):
    rec.dock.send('tare()')
    if rec.wait_log('tare>>') is None:
        print('  (no tare>> reply, carrying on)')
    time.sleep(0.5)


# Steps: each returns a dict for the report
def step_drift(rec, seconds):
    ask(f"Drift: hands off the cell and the cable for {seconds} s")
    tare(rec)
    t0, t1 = rec.record(seconds, 'hands off')
    t, g = rec.window(t0, t1)
    slope = np.polyfit(t, g, 1)[0] * 60
    secs = np.floor(t).astype(int)
    means = np.array([g[secs == s].mean() for s in np.unique(secs)])
    return {'noise_rms_g': float(np.std(g - np.polyval(np.polyfit(t, g, 1), t))),
            'drift_g_per_min': float(slope),
            'p2p_1s_means_g': float(np.ptp(means)),
            'seconds': seconds}

def find_presses(t, g):
    '''(start, end, zero) of each press: the 0.1 s average rising past PRESS_G above
    the zero before it, until it falls back under half of that or 10 % of the peak
    (a zero that steps up after a hard press still ends it); presses closer than
    0.3 s are one. Between presses the zero follows the signal (~0.2 s), but not
    down into dips.'''
    gs = np.convolve(g, np.ones(5) / 5, mode='same')
    k = RATE_HZ // 10
    out, start, zero, peak = [], None, float(np.median(gs[:RATE_HZ // 2])), 0.0
    for i, v in enumerate(gs):
        if start is None:
            if v > zero + PRESS_G and v - gs[max(0, i - k)] > PRESS_G / 2:
                start, peak = t[i], v - zero
            elif v > zero - PRESS_G:
                zero += 0.1 * (v - zero)
        else:
            peak = max(peak, v - zero)
            if v < zero + max(PRESS_G / 2, 0.1 * peak):
                if out and start - out[-1][1] < 0.3:
                    start, _, zero = out.pop()
                out.append((start, t[i], zero))
                start = None
    if start is not None:
        out.append((start, t[-1], zero))
    return out

def quiet_zero(t, g, lo, hi):
    '''Median grams in [lo, hi), or None when that's under 0.5 s.'''
    sel = (t >= lo) & (t < hi)
    return float(np.median(g[sel])) if hi - lo >= 0.5 and sel.any() else None

def analyse_presses(t, g, stop):
    '''Presses before `stop` (seconds into t), the hands-off recovery after it.
    The zero between two presses only counts with >= 0.8 s between them
    (0.3 s off each edge).'''
    presses = [p for p in find_presses(t, g) if p[0] < stop]
    rows = []
    for i, (a, b, zero) in enumerate(presses):
        prev_end = presses[i - 1][1] if i else t[0]
        next_start = presses[i + 1][0] if i + 1 < len(presses) else stop
        before = quiet_zero(t, g, max(prev_end + 0.3, a - 1.3), a - 0.3)
        after = quiet_zero(t, g, b + 0.3, min(b + 1.3, next_start - 0.3))
        tail = (t >= b) & (t < min(b + 1, next_start))
        dip = float(smooth(g[tail]).min()) - zero if tail.sum() >= RATE_HZ // 5 else None
        rows.append({'at_s': float(a), 'peak_g': float(g[(t >= a) & (t <= b)].max()), 'held_s': float(b - a),
                     'undershoot_g': dip,
                     'zero_before_g': before, 'zero_after_g': after,
                     'shift_g': None if before is None or after is None else after - before})
    shifts = [r['shift_g'] for r in rows if r['shift_g'] is not None]
    first = presses[0][0] if presses else stop
    base = quiet_zero(t, g, max(t[0], first - 2), first - 0.3)
    last = presses[-1][1] if presses else stop
    recovery = {f'{s}s': quiet_zero(t, g, last + s - 0.5, last + s + 0.5) for s in (1, 3, 10)}
    dips = [r['undershoot_g'] for r in rows if r['undershoot_g'] is not None]
    out = {'presses': rows, 'n': len(rows), 'zero_before_first_g': base,
           'worst_undershoot_g': min(dips) if dips else None,
           'max_peak_g': max((r['peak_g'] for r in rows), default=None),
           'max_abs_shift_g': max(map(abs, shifts)) if shifts else None,
           'recovery_g': {k: None if v is None or base is None else v - base for k, v in recovery.items()}}
    if len(shifts) >= 3:
        peaks = [r['peak_g'] for r in rows if r['shift_g'] is not None]
        out['shift_vs_peak_corr'] = float(np.corrcoef(peaks, shifts)[0, 1])
    return out

def step_presses(rec, seconds):
    ask(f"Presses: with a tool (pencil eraser, not a finger), press ~10 times over {seconds} s, "
        "light to hard (up to a firm pen, ~50 g), ~1 s each with ~2 s off between")
    tare(rec)
    t0, t1 = rec.record(seconds, 'press')
    print('  stop pressing: hands off')
    rec.record(12, 'hands off')
    t, g = rec.window(t0, rec.now())
    return analyse_presses(t, g, t1 - t0)

def step_weights(rec, weights):
    ask("Weights: the cell empty")
    tare(rec)
    zero0 = rec.mean(AVERAGE_S)
    order = list(weights) + list(reversed(weights[:-1])) + [0.0]
    up, down = {}, {}
    seen = set()
    for w in order:
        going_up = w not in seen
        seen.add(w)
        ask(f"Put {w:g} g on in total" if w else "Take everything off")
        rec.record(SETTLE_S, 'settling')
        reading = rec.mean(AVERAGE_S)
        (up if going_up else down)[w] = reading
        print(f"  {w:g} g -> {reading:+.2f} g")
    xs = np.array([0.0] + list(weights))
    ys = np.array([zero0] + [up[w] for w in weights])
    scale = float(np.polyfit(xs, ys, 1)[0])
    fit = np.polyval(np.polyfit(xs, ys, 1), xs)
    hyst = {f'{w:g}': down[w] - up[w] for w in weights[:-1]}
    return {'zero_g': zero0, 'up_g': {f'{w:g}': v for w, v in up.items()},
            'down_g': {f'{w:g}': v for w, v in down.items()},
            'reads_per_true_g': scale,
            'nonlinearity_g': float(np.max(np.abs(ys - fit))),
            'hysteresis_g': hyst,
            'max_abs_hysteresis_g': max(map(abs, hyst.values())) if hyst else None,
            'return_to_zero_g': down.get(0.0, float('nan')) - zero0}

def step_creep(rec, weight, seconds):
    ask("Creep: the cell empty")
    tare(rec)
    zero0 = rec.mean(AVERAGE_S)
    ask(f"Put {weight:g} g on, then hands off for {seconds} s")
    t0, t1 = rec.record(seconds, 'loaded')
    t, g = rec.window(t0, t1)
    on_early = float(np.median(g[(t > 2) & (t < 4)]))
    on_late = float(np.median(g[t > t[-1] - 2]))
    ask(f"Take it off, then hands off for {seconds} s")
    t0, t1 = rec.record(seconds, 'unloaded')
    t, g = rec.window(t0, t1)
    off_early = float(np.median(g[(t > 2) & (t < 4)]))
    off_late = float(np.median(g[t > t[-1] - 2]))
    return {'weight_g': weight, 'seconds': seconds, 'zero_before_g': zero0,
            'loaded_at_3s_g': on_early, 'loaded_at_end_g': on_late, 'creep_loaded_g': on_late - on_early,
            'unloaded_at_3s_g': off_early - zero0, 'unloaded_at_end_g': off_late - zero0,
            'recovery_g': off_late - off_early}

def step_wiggle(rec, seconds):
    ask("Cable: hands off for 3 s, then wiggle and pull the cable (not the cell)")
    tare(rec)
    t0, t1 = rec.record(3, 'hands off')
    _, quiet = rec.window(t0, t1)
    print('  wiggle now')
    t0, t1 = rec.record(seconds, 'wiggle')
    _, g = rec.window(t0, t1)
    base = float(np.median(quiet))
    return {'max_dev_g': float(np.max(np.abs(smooth(g) - base))), 'quiet_p2p_g': float(np.ptp(smooth(quiet)))}

def smooth(g, n=RATE_HZ // 5):
    '''0.2 s moving average: single samples are noise, not the cable.'''
    return np.convolve(g, np.ones(n) / n, mode='valid') if len(g) >= n else g


# The report
def verdict(value, good, bad):
    if value is None or value != value:
        return '   '
    v = abs(value)
    return 'ok ' if v <= good else 'BAD' if v > bad else 'meh'

def report(res, calibrated):
    lines = [f"Cell test {res['time']}  (grams {'calibrated' if calibrated else 'from the 236 counts/g estimate'})"]
    def row(name, value, good, bad, unit='g'):
        txt = '-' if value is None else f'{value:+.2f} {unit}'
        lines.append(f"  {verdict(value, good, bad)} {name:<34} {txt:>12}   (good <= {good} {unit})")
    if 'drift' in res:
        d = res['drift']
        row('noise rms (one sample)', d['noise_rms_g'], 0.5, 1.5)
        row('drift, hands off', d['drift_g_per_min'], 0.5, 2, 'g/min')
        row('spread of 1 s means', d['p2p_1s_means_g'], 0.5, 2)
    if 'presses' in res:
        p = res['presses']
        lines.append(f"      presses found: {p['n']}")
        for r in p['presses']:
            sh = '-' if r['shift_g'] is None else f"{r['shift_g']:+.2f} g"
            us = '-' if r['undershoot_g'] is None else f"{r['undershoot_g']:+.1f} g"
            lines.append(f"        {r['at_s']:5.1f} s  peak {r['peak_g']:6.1f} g  held {r['held_s']:4.1f} s  "
                         f"dip after {us:>7}  zero shift {sh}")
        lines.append(f"      (zero shift '-': under 0.8 s between presses, can't tell)")
        row('worst dip within 1 s of a release', p['worst_undershoot_g'], 1, 2)
        row('worst zero shift after a press', p['max_abs_shift_g'], 0.5, 2)
        for k, v in p['recovery_g'].items():
            row(f'zero {k} after the last press', v, 0.5, 2)
        if 'shift_vs_peak_corr' in p:
            lines.append(f"      shift vs peak force correlation {p['shift_vs_peak_corr']:+.2f} "
                         "(near +1: harder presses move the zero more)")
    if 'weights' in res:
        w = res['weights']
        lines.append(f"      reads {w['reads_per_true_g']:.3f} g per true g "
                     f"(calibrate(<g>) fixes this)")
        row('non-linearity', w['nonlinearity_g'], 0.5, 2)
        row('worst hysteresis (down - up)', w['max_abs_hysteresis_g'], 1, 3)
        row('return to zero', w['return_to_zero_g'], 0.5, 2)
    if 'creep' in res:
        c = res['creep']
        row(f"creep under {c['weight_g']:g} g, {c['seconds']} s", c['creep_loaded_g'], 0.5, 2)
        row('zero 3 s after unloading', c['unloaded_at_3s_g'], 0.5, 2)
        row('zero at the end', c['unloaded_at_end_g'], 0.5, 2)
    if 'wiggle' in res:
        row('cable wiggle, worst', res['wiggle']['max_dev_g'], 0.5, 2)
    return '\n'.join(lines)


@app.command()
def main(
    weights: Annotated[str | None, typer.Option(help="Total loads in g, rising, eg. 7.5,16,24.5")] = None,
    only: Annotated[list[str] | None, typer.Option(help=f"Only these steps: {', '.join(STEPS)}")] = None,
    drift_s: int = 120,
    presses_s: int = 40,
    creep_s: int = 60,
    label: Annotated[str, typer.Option(help="A name for this cell/build, kept in the file")] = '',
    port: PortOption = None,
):
    '''Guided load cell test against LIT: prints a report, keeps the data.'''
    loads = sorted(float(x) for x in weights.split(',')) if weights else []
    steps = only or [s for s in STEPS if loads or s not in ('weights', 'creep')]
    for s in steps:
        if s not in STEPS:
            raise typer.BadParameter(f"unknown step {s}, choose from {', '.join(STEPS)}")
        if s in ('weights', 'creep') and not loads:
            raise typer.BadParameter(f"{s} needs --weights")
    dock = Dock.open(find_port(port))
    rec = Recorder(dock)
    dock.send('stream(on)')
    dock.send(f'rate({RATE_HZ})')
    time.sleep(1)
    if not rec.samples:
        raise SystemExit('no samples from the board: is it LIT, and not held by another program?')
    res = {'time': time.strftime('%Y-%m-%d %H:%M:%S'), 'label': label, 'steps': steps}
    try:
        for s in steps:
            print(f"\n== {s}")
            if s == 'drift':
                res[s] = step_drift(rec, drift_s)
            elif s == 'presses':
                res[s] = step_presses(rec, presses_s)
            elif s == 'weights':
                res[s] = step_weights(rec, loads)
            elif s == 'creep':
                res[s] = step_creep(rec, loads[-1], creep_s)
            elif s == 'wiggle':
                res[s] = step_wiggle(rec, 10)
    except KeyboardInterrupt:
        print('\n(stopped, reporting what ran)')
    finally:
        dock.send('rate(25)')
        rec.stop()
    res['calibrated'] = rec.calibrated
    text = report(res, rec.calibrated)
    print('\n' + text)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / (time.strftime('%Y%m%d-%H%M%S') + (f'-{label}' if label else '') + '.json')
    t_first = rec.samples[0][0] if rec.samples else 0
    res['samples'] = [[round(t - t_first, 3), round(g, 3), raw] for t, g, raw in rec.samples]
    res['marks'] = [[label, round(a - t_first, 3), round(b - t_first, 3)] for label, a, b in rec.marks]
    res['report'] = text
    path.write_text(json.dumps(res))
    print(f"\nkept in {path}")


if __name__ == '__main__':
    app()
