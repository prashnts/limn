# A perfboard router for the plot head board: bare traces between neighbouring holes (F.Cu, short),
# insulated 30 AWG wires for the rest (B.Cu, straight, a via where a wire lands on an SMD pad).
# Keeps everything already on the board. GND follows the star plan (the Pro Micro's GND pins).
import re, math, sys, uuid, collections
from pcbmodel import load, islands, dist_seg, on_layer

SRC, DST = sys.argv[1], sys.argv[2]
X0, Y0, P, NI, NJ = 50.8, 50.8, 2.54, 38, 17
MAXBARE = 3                       # holes a bare trace may run (steps)
POWER = {'+5V_TOOL_IN', '+5V_TOOL', 'Net-(U953-VOUT)'}
t, fps, pads, segs, vias = load(SRC)
netnum = {name: num for num, name in re.findall(r'\n\t\(net (\d+) "([^"]*)"\)', t)}
short = lambda n: n.split('/')[-1]

def node_of(x, y, tol=0.7):
    i, j = round((x - X0) / P), round((y - Y0) / P)
    if 0 <= i < NI and 0 <= j < NJ and math.hypot(x - (X0 + i*P), y - (Y0 + j*P)) < tol:
        return (i, j)
def xy(n): return (round(X0 + n[0]*P, 3), round(Y0 + n[1]*P, 3))

# who owns each hole on the top side (bare traces run on F.Cu)
owner = {}
def claim(n, net):
    if n is None: return
    if owner.get(n, net) != net: owner[n] = '#conflict'
    else: owner[n] = net
for p in pads:
    if p['kind'] == 'thru_hole' or p['side'] == 'F.Cu':
        if p['kind'] == 'smd' and p['ref'] == 'U952': continue
        n = node_of(p['x'], p['y'], tol=1.3 if p['kind'] == 'smd' else 0.7)
        claim(n, p['net'] or '#nc')
for s in segs:
    if s['layer'] != 'F.Cu': continue
    for i in range(NI):
        for j in range(NJ):
            if dist_seg(*xy((i, j)), s) < 0.9: claim((i, j), s['net'])
for f in fps:                     # under a module on the top side: no bare traces
    if f['side'] == 'F.Cu' and f['box'] and f['ref'] in ('U951', 'U953'):
        x1, y1, x2, y2 = f['box']
        for i in range(NI):
            for j in range(NJ):
                x, y = xy((i, j))
                if x1 < x < x2 and y1 < y < y2 and (i, j) not in owner: owner[(i, j)] = '#body'

def gap_free(a, b, net):
    '''No other net's top copper in the gap between two neighbouring holes.'''
    mx, my = (xy(a)[0] + xy(b)[0]) / 2, (xy(a)[1] + xy(b)[1]) / 2
    for s in segs + new_segs:
        if s['layer'] == 'F.Cu' and s['net'] != net and dist_seg(mx, my, s) < 0.7: return False
    for p in pads:
        if p['net'] != net and (p['kind'] == 'thru_hole' or p['side'] == 'F.Cu') and not (p['kind'] == 'smd' and p['ref'] == 'U952'):
            if math.hypot(mx - p['x'], my - p['y']) < 1.0: return False
    return True

def nodes_of(group, net):
    out = set()
    for p in group['pads']:
        if p['kind'] == 'smd' and p['ref'] == 'U952': continue
        n = node_of(p['x'], p['y'], tol=1.3 if p['kind'] == 'smd' else 0.7)
        if n and owner.get(n) == net: out.add(n)
    for s in group['segs']:
        if s['layer'] == 'F.Cu':
            for n, o in owner.items():
                if o == net and dist_seg(*xy(n), s) < 0.9: out.add(n)
    return out

def bare(A, B, net):
    src, dst = nodes_of(A, net), nodes_of(B, net)
    if not src or not dst: return None
    prev, frontier = {n: None for n in src}, list(src)
    for _ in range(MAXBARE):
        nxt = []
        for n in frontier:
            for d in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                m = (n[0] + d[0], n[1] + d[1])
                if m in prev or not (0 <= m[0] < NI and 0 <= m[1] < NJ): continue
                if owner.get(m, net) != net or not gap_free(n, m, net): continue
                prev[m] = n
                if m in dst:
                    path = [m]
                    while prev[path[-1]] is not None: path.append(prev[path[-1]])
                    return path[::-1]
                nxt.append(m)
        frontier = nxt
    return None

new_segs, new_vias, report = [], [], []
def add_seg(a, b, layer, net, w):
    new_segs.append(dict(x1=a[0], y1=a[1], x2=b[0], y2=b[1], w=w, layer=layer, net=net))

def join(A, B, net, why='', power=None):
    '''Join two islands of a net: a bare trace if a short one fits, else an insulated wire.'''
    power = net in POWER if power is None else power
    path = bare(A, B, net)
    if path:
        for a, b in zip(path, path[1:]):
            add_seg(xy(a), xy(b), 'F.Cu', net, 1.2 if power else 0.8)
            owner[a] = owner[b] = net
        for end in (path[0], path[-1]):          # an SMD pad beside its hole: the solder joint to it
            for p in A['pads'] + B['pads']:
                if p['kind'] == 'smd' and node_of(p['x'], p['y'], tol=1.3) == end and math.hypot(p['x'] - xy(end)[0], p['y'] - xy(end)[1]) > 0.3:
                    add_seg(xy(end), (p['x'], p['y']), 'F.Cu', net, 0.8)
        report.append((short(net), 'bare', len(path) - 1, why))
        return
    best = None
    for pa in A['pads']:
        for pb in B['pads']:
            if (pa['kind'] == 'smd' and pa['ref'] == 'U952') or (pb['kind'] == 'smd' and pb['ref'] == 'U952'): continue
            d = math.hypot(pa['x'] - pb['x'], pa['y'] - pb['y']) + (1.0 if pa['kind'] == 'smd' else 0) + (1.0 if pb['kind'] == 'smd' else 0)
            if best is None or d < best[0]: best = (d, pa, pb)
    _, pa, pb = best
    add_seg((pa['x'], pa['y']), (pb['x'], pb['y']), 'B.Cu', net, 1.0 if power else 0.5)   # power: 26 AWG, signals: 30 AWG
    for p in (pa, pb):
        if p['kind'] == 'smd':
            new_vias.append(dict(x=p['x'], y=p['y'], net=net))
    report.append((short(net), 'wire', round(math.hypot(pa['x'] - pb['x'], pa['y'] - pb['y']), 1), f"{pa['name']} - {pb['name']} {why}"))

def merged(groups):
    return {'pads': [p for g in groups for p in g['pads']], 'segs': [s for g in groups for s in g['segs']]}

def connect_all(net, groups, why=''):
    groups = list(groups)
    while len(groups) > 1:
        best = None
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                d = min(math.hypot(a['x'] - b['x'], a['y'] - b['y']) for a in groups[i]['pads'] for b in groups[j]['pads'])
                if best is None or d < best[0]: best = (d, i, j)
        _, i, j = best
        join(groups[i], groups[j], net, why)
        g = merged([groups[i], groups[j]])
        groups = [x for k, x in enumerate(groups) if k not in (i, j)] + [g]
    return groups[0] if groups else None

# --- the tool's 5 V in: J958 straight to the switch's VIN (not through the debug jumper's pad)
isl5 = islands(pads, segs, vias, '+5V_TOOL_IN')
g58 = [g for g in isl5 if any(p['name'] == 'J958.1' for p in g['pads'])]
gvin = [g for g in isl5 if any(p['name'] == 'U953.1' for p in g['pads'])]
if g58 and gvin and g58[0] is not gvin[0]:
    only = lambda g, n: {'pads': [p for p in g['pads'] if p['name'] == n], 'segs': []}
    join(only(g58[0], 'J958.1'), only(gvin[0], 'U953.1'), '+5V_TOOL_IN', '(5 V in -> switch VIN)')
    segs.extend(new_segs[-1:])          # count it before the general pass

# --- every net but GND: join its islands, nearest first
for net in sorted(set(p['net'] for p in pads)):
    if not net or net.startswith('unconnected') or net == 'GND': continue
    isl = islands(pads, segs, vias, net)
    if len(isl) > 1: connect_all(net, isl)

# --- GND, the star: analog island, top rail, power ground, each to the Pro Micro's GND pins
isl = islands(pads, segs, vias, 'GND')
def has(g, *names): return any(p['name'] in names for p in g['pads'])
analog = [g for g in isl if has(g, 'U951.9', 'U951.12')][0]
toprail = [g for g in isl if has(g, 'J953.2', 'R955.2')][0]
pm = {n: [g for g in isl if has(g, n)][0] for n in ('U952.3', 'U952.4', 'U952.14')}
POWER_GND = {'J955.6', 'J955.7', 'J955.8', 'J958.2', 'J957.3', 'U953.3'}
def grp(name): return [g for g in isl if has(g, name)][0]
used = [analog, toprail] + list(pm.values()) + [grp(n) for n in POWER_GND]
rest = [g for g in isl if not any(g is x for x in used)]
for g in rest:                    # the analog side's caps and the QRE's cap: to their own island
    names = {p['name'] for p in g['pads']}
    target = analog if names & {'C951.2', 'C952.2', 'D951.1'} else toprail
    join(g, target, 'GND', '(to the analog island)' if target is analog else '(to the top rail)')
    target['pads'] += g['pads']; target['segs'] += g['segs']
# power ground, explicit: the tool's 2 A returns J955 -> J958 (the 5 V in); the switch's GND there too
def once(a, b, why, power=False):
    if a is not b: join(a, b, 'GND', why, power=power)
j955 = grp('J955.6')
for n in ('J955.7', 'J955.8', 'J957.3'):
    once(grp(n), j955, '(CAT6 #2 GND, USB GND)'); j955 = merged([j955, grp(n)]) if grp(n) is not j955 else j955
once(j955, grp('J958.2'), '(tool return -> J958 GND)', power=True)
once(grp('U953.3'), grp('J958.2'), '(switch GND)')
once(grp('J958.2'), pm['U952.14'], '(power ground -> the star)')
if pm['U952.3'] is not pm['U952.4']:
    join(pm['U952.3'], pm['U952.4'], 'GND', '(Pro Micro GND pins)')
if toprail is not pm['U952.3'] and toprail is not pm['U952.4']:
    join(toprail, pm['U952.3'], 'GND', '(top rail -> the star)')

# --- write
def seg_txt(s):
    return (f'\t(segment\n\t\t(start {s["x1"]:.4g} {s["y1"]:.4g})\n\t\t(end {s["x2"]:.4g} {s["y2"]:.4g})\n'
            f'\t\t(width {s["w"]})\n\t\t(layer "{s["layer"]}")\n\t\t(net {netnum[s["net"]]})\n\t\t(uuid "{uuid.uuid4()}")\n\t)\n')
def via_txt(v):
    return (f'\t(via\n\t\t(at {v["x"]:.4g} {v["y"]:.4g})\n\t\t(size 0.6)\n\t\t(drill 0.3)\n\t\t(layers "F.Cu" "B.Cu")\n'
            f'\t\t(net {netnum[v["net"]]})\n\t\t(uuid "{uuid.uuid4()}")\n\t)\n')
i = t.rindex('\n\t(embedded_fonts')
out = t[:i + 1] + ''.join(seg_txt(s) for s in new_segs) + ''.join(via_txt(v) for v in new_vias) + t[i + 1:]
open(DST, 'w').write(out)
for r in report: print(*r)
print('segments', len(new_segs), 'vias', len(new_vias), 'conflicting holes', [k for k, v in owner.items() if v == '#conflict'][:10])
