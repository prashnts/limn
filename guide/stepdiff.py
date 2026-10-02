"""What changed between two or more STEP exports of Limn, design by design.

    python guide/stepdiff.py old.step [..] new.step

Designs are matched by name (Fusion's component or design name, without the
' v12' and '_1' Fusion adds), and compared by how many there are, where they
sit and their shape (step.Step.shape): ids change with every export, shapes only
when the part was edited. A design that vanished while another of the same shape
appeared is reported as renamed.
"""
import collections
import sys
from pathlib import Path

import step as stepfile
from build import clean


def designs(path):
    """{name: {'qty', 'where', 'shape', 'vendor', 'own'}} for one export."""
    st = stepfile.Step(stepfile.load(Path(path)))
    root = next(r for r in st.roots if r.children)
    out = {}

    def visit(part, mult, where):
        for c, n in part.children:
            name = clean(c.source or c.name)
            d = out.setdefault(name, {'qty': 0, 'where': set(), 'shape': None, 'vendor': c.vendor, 'pd': c.pd})
            d['qty'] += mult * n
            d['where'].add(where)
            if d['shape'] is None:
                d['shape'] = st.shape(c)
            if not c.vendor:
                visit(c, mult * n, name)
    visit(root, 1, clean(root.source or root.name))
    return out


def faces(shape):
    return sum(n for _, n in shape[1])


def describe(a, b):
    """How a design's shape changed, in words."""
    (ba, ka, xa), (bb, kb, xb) = a, b
    bits = []
    if ba != bb:
        bits.append(f'bodies {ba}→{bb}')
    if xa != xb and xa and xb:
        bits.append('size ' + '×'.join(f'{v:g}' for v in xa) + ' → ' + '×'.join(f'{v:g}' for v in xb) + ' mm')
    if ka != kb:
        bits.append(f'faces {faces(a)}→{faces(b)}')
    return ', '.join(bits) or 'same'


def diff(old, new):
    gone = {k: v for k, v in old.items() if k not in new}
    added = {k: v for k, v in new.items() if k not in old}
    renamed = []
    for k, v in list(added.items()):
        twin = next((g for g, gv in gone.items() if gv['shape'] == v['shape'] and faces(v['shape'])), None)
        if twin:
            renamed.append((twin, k))
            del gone[twin], added[k]
    changed = [(k, describe(old[k]['shape'], new[k]['shape'])) for k in sorted(old.keys() & new.keys(), key=str.lower)
               if old[k]['shape'] != new[k]['shape'] and new[k]['shape'][0]]
    qty = [(k, old[k]['qty'], new[k]['qty']) for k in sorted(old.keys() & new.keys(), key=str.lower) if old[k]['qty'] != new[k]['qty']]
    moved = [(k, old[k]['where'], new[k]['where']) for k in sorted(old.keys() & new.keys(), key=str.lower)
             if old[k]['where'] != new[k]['where']]
    return gone, added, renamed, changed, qty, moved


def report(names, versions):
    for (na, a), (nb, b) in zip(zip(names, versions), zip(names[1:], versions[1:])):
        gone, added, renamed, changed, qty, moved = diff(a, b)
        print(f'\n# {na} → {nb}\n')
        tag = lambda d: ' (bought)' if d['vendor'] else ''
        for title, rows in (
            ('Added', [f'{k}{tag(v)}' + (f' ×{v["qty"]}' if v['qty'] > 1 else '') + f'  in {", ".join(sorted(v["where"]))}' for k, v in sorted(added.items(), key=lambda kv: kv[0].lower())]),
            ('Removed', [f'{k}{tag(v)}' + (f' ×{v["qty"]}' if v['qty'] > 1 else '') + f'  from {", ".join(sorted(v["where"]))}' for k, v in sorted(gone.items(), key=lambda kv: kv[0].lower())]),
            ('Renamed (same shape)', [f'{a_} → {b_}' for a_, b_ in renamed]),
            ('Reshaped', [f'{k}: {d}' for k, d in changed]),
            ('Count', [f'{k}: {x} → {y}' for k, x, y in qty]),
            ('Moved', [f'{k}: {", ".join(sorted(x))} → {", ".join(sorted(y))}' for k, x, y in moved]),
        ):
            if rows:
                print(f'## {title} ({len(rows)})\n')
                print('\n'.join(f'- {r}' for r in rows) + '\n')


if __name__ == '__main__':
    paths = sys.argv[1:]
    report([Path(p).stem for p in paths], [designs(p) for p in paths])
