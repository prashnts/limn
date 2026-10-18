# Read a KiCad 9 board: pads (absolute), tracks, vias; connectivity islands per net.
import re, math, collections

def load(path):
    t = open(path).read()
    netnames = dict(re.findall(r'\n\t\(net (\d+) "([^"]*)"\)', t))
    def nname(num, name): return name if name is not None else netnames.get(num, num)
    fps, pads = [], []
    for m in re.finditer(r'\n\t\(footprint "([^"]+)"(.*?)\n\t\)', t, re.S):
        body = m.group(2)
        fx, fy, fr = re.search(r'\n\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', body).groups()
        fx, fy, fr = float(fx), float(fy), float(fr or 0)
        ref = re.search(r'\(property "Reference" "([^"]+)"', body).group(1)
        side = re.search(r'\n\t\t\(layer "([^"]+)"\)', body).group(1)
        a = math.radians(-fr)
        cy = re.search(r'\(fp_rect\s*\(start ([-\d.]+) ([-\d.]+)\)\s*\(end ([-\d.]+) ([-\d.]+)\).*?\(layer "[FB]\.CrtYd"\)', body, re.S)
        box = None
        if cy:
            xs, ys = [], []
            for px, py in ((float(cy.group(1)), float(cy.group(2))), (float(cy.group(3)), float(cy.group(4))),
                           (float(cy.group(1)), float(cy.group(4))), (float(cy.group(3)), float(cy.group(2)))):
                xs.append(fx + px*math.cos(a) - py*math.sin(a)); ys.append(fy + px*math.sin(a) + py*math.cos(a))
            box = (min(xs), min(ys), max(xs), max(ys))
        fps.append(dict(ref=ref, lib=m.group(1), x=fx, y=fy, rot=fr, side=side, box=box))
        for p in re.finditer(r'\(pad "([^"]*)" (\w+) (\w+)\s*\(at ([-\d.]+) ([-\d.]+)(?: [-\d.]+)?\)(.*?)\n\t\t\)', body, re.S):
            px, py = float(p.group(4)), float(p.group(5))
            x = fx + px*math.cos(a) - py*math.sin(a); y = fy + px*math.sin(a) + py*math.cos(a)
            net = re.search(r'\(net (?:(\d+) )?"([^"]*)"\)', p.group(6))
            size = re.search(r'\(size ([-\d.]+) ([-\d.]+)\)', p.group(6))
            pads.append(dict(id=len(pads), name=f'{ref}.{p.group(1)}', ref=ref, kind=p.group(2), x=round(x, 3), y=round(y, 3),
                             net=net.group(2) if net else '', side=side, size=(float(size.group(1)), float(size.group(2)))))
    segs = []
    for m in re.finditer(r'\n\t\(segment\s*\(start ([-\d.]+) ([-\d.]+)\)\s*\(end ([-\d.]+) ([-\d.]+)\)\s*\(width ([-\d.]+)\)\s*\(layer "([^"]+)"\)\s*(?:\(locked yes\)\s*)?\(net (?:(\d+)|"([^"]*)")\)', t):
        segs.append(dict(x1=float(m.group(1)), y1=float(m.group(2)), x2=float(m.group(3)), y2=float(m.group(4)),
                         w=float(m.group(5)), layer=m.group(6), net=nname(m.group(7), m.group(8))))
    vias = []
    for m in re.finditer(r'\n\t\(via\s*\(at ([-\d.]+) ([-\d.]+)\).*?\(net (?:(\d+)|"([^"]*)")\)', t, re.S):
        vias.append(dict(x=float(m.group(1)), y=float(m.group(2)), net=nname(m.group(3), m.group(4))))
    return t, fps, pads, segs, vias


def dist_seg(px, py, s):
    x1, y1, x2, y2 = s['x1'], s['y1'], s['x2'], s['y2']
    dx, dy = x2 - x1, y2 - y1; L = dx*dx + dy*dy
    k = 0 if L == 0 else max(0, min(1, ((px-x1)*dx + (py-y1)*dy) / L))
    return math.hypot(px - (x1 + k*dx), py - (y1 + k*dy))


def on_layer(pad, layer):
    return pad['kind'] == 'thru_hole' or pad['side'] == layer


def islands(pads, segs, vias, net):
    '''Groups of this net's pads already joined by its copper (tracks on matching layers, vias).'''
    P = [p for p in pads if p['net'] == net]
    S = [s for s in segs if s['net'] == net]
    V = [v for v in vias if v['net'] == net]
    par = {}
    def f(x):
        while par.setdefault(x, x) != x: x = par[x]
        return x
    def u(a, b): par[f(a)] = f(b)
    for i, s in enumerate(S):
        for j in range(i+1, len(S)):
            s2 = S[j]
            ends = ((s['x1'], s['y1']), (s['x2'], s['y2'])); ends2 = ((s2['x1'], s2['y1']), (s2['x2'], s2['y2']))
            touch = any(dist_seg(x, y, s2) < 0.3 for x, y in ends) or any(dist_seg(x, y, s) < 0.3 for x, y in ends2)
            if touch and (s['layer'] == s2['layer'] or any(dist_seg(v['x'], v['y'], s) < 0.3 and dist_seg(v['x'], v['y'], s2) < 0.3 for v in V)):
                u(('s', i), ('s', j))
    for k, v in enumerate(V):               # a via joins what touches it, on either layer (and a pad it sits in)
        for i, s in enumerate(S):
            if dist_seg(v['x'], v['y'], s) < 0.3: u(('v', k), ('s', i))
        for p in P:
            if math.hypot(v['x'] - p['x'], v['y'] - p['y']) < max(0.3, min(p['size']) / 2): u(('v', k), ('p', p['id']))
    for p in P:
        for i, s in enumerate(S):
            if on_layer(p, s['layer']) and dist_seg(p['x'], p['y'], s) < max(0.3, min(p['size']) / 2):
                u(('p', p['id']), ('s', i))
        f(('p', p['id']))
    groups = collections.defaultdict(lambda: {'pads': [], 'segs': []})
    for p in P:
        groups[f(('p', p['id']))]['pads'].append(p)
    for i, s in enumerate(S):
        r = f(('s', i))
        if r in groups:
            groups[r]['segs'].append(s)
    return list(groups.values())
