# Limn - a map of an FSR sheet: which cell answers where (LRT_FSR_MAP)
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Fsr.map_sheet() touches the sheet spot by spot on a grid over the array: from
# above, down until a cell rises `rise` over its reading in the air, then a little
# deeper, every cell's rise there. Here, from those spots: each cell's centre
# (where it answers strongest), the array's origin and pitch fitted to them, the
# cells that never answer and those that answer far from where they should (a
# ribbon off by a pin, a cracked trace), the sheet's height. And a picture of it
# (SVG, no dependencies). Made after a sensor swap, to set beds.py by: the
# 2026-10-07 sheet was mapped by hand first, this is that, reproducible.
import json

import numpy as np


def strongest(cells, respond):
    '''(cell, rise) of the strongest cell answering at a spot, None under `respond`.'''
    if not cells:
        return None
    cell, rise = max(cells.items(), key=lambda kv: kv[1])
    return (tuple(cell), rise) if rise >= respond else None


def analyse(points, spec, pitch, respond=150, rows=4, cols=8):
    '''points: [{'xy': (x, y), 'touch': z or None, 'cells': {(row, col): rise}}], xy where the
    tip touched. spec: the array's config (origin, row_dir, col_dir). -> what the sheet is.'''
    row_dir, col_dir = np.asarray(spec['row_dir'], float), np.asarray(spec['col_dir'], float)
    hits = {}
    for p in points:
        s = strongest(p['cells'], respond)
        if s:
            hits.setdefault(s[0], []).append((np.asarray(p['xy'], float), s[1]))
    centres = {c: np.average([xy for xy, _ in v], axis=0, weights=[w for _, w in v]) for c, v in hits.items()}

    def fit(cells):
        # centre = O + pitch * ((col + 0.5) col_dir + (row + 0.5) row_dir): linear in Ox, Oy, pitch
        A, b = [], []
        for (r, c) in cells:
            v = (c + 0.5) * col_dir + (r + 0.5) * row_dir
            A += [[1, 0, v[0]], [0, 1, v[1]]]
            b += list(centres[(r, c)])
        sol, *_ = np.linalg.lstsq(np.array(A), np.array(b), rcond=None)
        return np.array(sol[:2]), float(sol[2])

    known = [c for c in centres if 0 <= c[0] < rows and 0 <= c[1] < cols]
    origin, fitted_pitch, far = None, None, []
    if len(known) >= 3:
        origin, fitted_pitch = fit(known)
        for _ in range(3):                  # the cells far from the fit out, fitted again
            off = {c: float(np.linalg.norm(centres[c] - (origin + fitted_pitch * ((c[1] + 0.5) * col_dir
                                                                                    + (c[0] + 0.5) * row_dir))))
                   for c in known}
            far = sorted(c for c, d in off.items() if d > 0.4 * pitch)
            good = [c for c in known if c not in far]
            if len(good) < 3:
                break
            origin, fitted_pitch = fit(good)
    touches = [p['touch'] for p in points if p['touch'] is not None]
    return {
        'centres': {c: centres[c].round(3).tolist() for c in sorted(centres)},
        'counts': {c: len(v) for c, v in sorted(hits.items())},
        'origin': origin.round(3).tolist() if origin is not None else None,
        'pitch': round(fitted_pitch, 3) if fitted_pitch else None,
        'silent': sorted((r, c) for r in range(rows) for c in range(cols) if (r, c) not in hits),
        'far': far,
        'touch': [round(min(touches), 3), round(max(touches), 3)] if touches else None,
        'spots': len(points), 'answered': sum(1 for p in points if strongest(p['cells'], respond)),
    }


def svg(points, result, spec, pitch, respond=150, step=1.25, rows=4, cols=8, title=''):
    '''The map as a picture: each spot the colour of the cell answering strongest (hue its
    column, darker a higher row), its name and rise; the configured cells dashed, the
    fitted ones solid.'''
    if not points:
        return '<svg xmlns="http://www.w3.org/2000/svg"/>'
    xs = [p['xy'][0] for p in points]; ys = [p['xy'][1] for p in points]
    x0, x1, y0, y1 = min(xs) - step, max(xs) + step, min(ys) - step, max(ys) + step
    k = 40 / step                           # px a mm
    W, H = (x1 - x0) * k + 20, (y1 - y0) * k + 60
    X = lambda x: 10 + (x - x0) * k
    Y = lambda y: 40 + (y1 - y) * k          # +Y up, as on the plotter seen from above
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" font-family="sans-serif" font-size="10">',
           f'<rect width="100%" height="100%" fill="white"/><text x="10" y="18" font-size="13" font-weight="bold">{title}</text>',
           f'<text x="10" y="32">origin {result.get("origin")} pitch {result.get("pitch")}; silent {len(result["silent"])}, '
           f'far {result["far"]}; touch z {result.get("touch")}</text>']
    for p in points:
        s = strongest(p['cells'], respond)
        x, y = X(p['xy'][0]) - step * k / 2, Y(p['xy'][1]) - step * k / 2
        if s:
            (r, c), rise = s
            hue, light = 360 * c / cols, 75 - 12 * r
            out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{step * k - 2:.1f}" height="{step * k - 2:.1f}" '
                       f'fill="hsl({hue:.0f},65%,{light}%)"/><text x="{x + 3:.1f}" y="{y + 13:.1f}" font-weight="bold">{r},{c}</text>'
                       f'<text x="{x + 3:.1f}" y="{y + 26:.1f}">{rise:.0f}</text>')
        else:
            out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{step * k - 2:.1f}" height="{step * k - 2:.1f}" fill="#eee"/>')
    row_dir, col_dir = np.asarray(spec['row_dir'], float), np.asarray(spec['col_dir'], float)

    def grid(origin, p, style):
        o = np.asarray(origin, float)
        for r in range(rows + 1):
            a, b = o + p * r * row_dir, o + p * (r * row_dir + cols * col_dir)
            out.append(f'<line x1="{X(a[0]):.1f}" y1="{Y(a[1]):.1f}" x2="{X(b[0]):.1f}" y2="{Y(b[1]):.1f}" {style}/>')
        for c in range(cols + 1):
            a, b = o + p * c * col_dir, o + p * (c * col_dir + rows * row_dir)
            out.append(f'<line x1="{X(a[0]):.1f}" y1="{Y(a[1]):.1f}" x2="{X(b[0]):.1f}" y2="{Y(b[1]):.1f}" {style}/>')
    grid(spec['origin'], pitch, 'stroke="#555" stroke-dasharray="4 3"')
    if result.get('origin') is not None:
        grid(result['origin'], result['pitch'], 'stroke="black" stroke-width="1.5"')
    out.append(f'<text x="10" y="{H - 8:.0f}">dashed: the cells as beds.py has them; solid: fitted to where they answer</text></svg>')
    return '\n'.join(out)


def to_json(points, result, meta):
    key = lambda c: f'{c[0]},{c[1]}'
    return json.dumps({
        'meta': meta,
        'result': {**result,
                   'centres': {key(c): v for c, v in result['centres'].items()},
                   'counts': {key(c): v for c, v in result['counts'].items()},
                   'silent': [list(c) for c in result['silent']], 'far': [list(c) for c in result['far']]},
        'points': [{'xy': list(p['xy']), 'touch': p['touch'], 'cells': {key(c): v for c, v in p['cells'].items()}}
                   for p in points]}, indent=1)
