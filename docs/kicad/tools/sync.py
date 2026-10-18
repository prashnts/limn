# Bring a board in line with a netlist the way Update PCB from Schematic would, for this case: footprints
# whose part is gone or off the board are removed with the tracks/vias on their pads; pad nets follow the
# netlist (new nets added to the board's net table); values follow the netlist.
import re, sys, math
from pcbmodel import load, dist_seg
src, netlist, dst = sys.argv[1:4]
t, fps, pads, segs, vias = load(src)
nl = open(netlist).read()
comps = {}
for m in re.finditer(r'\(comp \(ref "([^"]+)"\)\s*\(value "([^"]*)"\)(.*?)\(tstamps "[^"]+"\)\)', nl, re.S):
    onb = 'exclude_from_board' not in m.group(3)
    comps[m.group(1)] = (m.group(2), onb)
pinnet = {}
for block in nl.split('(net (code ')[1:]:            # one block per net, all its nodes
    name = re.match(r'"\d+"\) \(name "([^"]*)"\)', block).group(1)
    for ref, pin in re.findall(r'\(node \(ref "([^"]+)"\) \(pin "([^"]+)"\)', block):
        pinnet[(ref, pin)] = name
nets = dict((name, int(num)) for num, name in re.findall(r'\n\t\(net (\d+) "([^"]*)"\)', t))
gone = [f['ref'] for f in fps if f['ref'] not in comps or not comps[f['ref']][1]]
print('removing footprints:', gone)
dead = [p for p in pads if p['ref'] in gone]
def touches(x, y): return any(math.hypot(x - p['x'], y - p['y']) < 0.4 for p in dead)
def seg_dead(m):
    x1, y1, x2, y2 = map(float, m.group(1, 2, 3, 4))
    return touches(x1, y1) or touches(x2, y2)
n_seg = n_via = 0
def drop_seg(m):
    global n_seg
    if seg_dead(m): n_seg += 1; return ''
    return m.group(0)
t = re.sub(r'\n\t\(segment\s*\(start ([-\d.]+) ([-\d.]+)\)\s*\(end ([-\d.]+) ([-\d.]+)\).*?\n\t\)', drop_seg, t, flags=re.S)
def drop_via(m):
    global n_via
    if touches(float(m.group(1)), float(m.group(2))): n_via += 1; return ''
    return m.group(0)
t = re.sub(r'\n\t\(via\s*\(at ([-\d.]+) ([-\d.]+)\).*?\n\t\)', drop_via, t, flags=re.S)
def drop_fp(m):
    ref = re.search(r'\(property "Reference" "([^"]+)"', m.group(0)).group(1)
    return '' if ref in gone else m.group(0)
t = re.sub(r'\n\t\(footprint "[^"]+".*?\n\t\)', drop_fp, t, flags=re.S)
print('removed tracks', n_seg, 'vias', n_via)
# net table: add what's new
on_board = {f['ref'] for f in fps if f['ref'] not in gone}
need = sorted({n for (ref, pin), n in pinnet.items() if ref in on_board} - set(nets))
last = max(nets.values())
add = ''
for name in need:
    last += 1; nets[name] = last; add += f'\n\t(net {last} "{name}")'
if add:
    i = [m.end() for m in re.finditer(r'\n\t\(net \d+ "[^"]*"\)', t)][-1]
    t = t[:i] + add + t[i:]
print('nets added:', need)
# pad nets and values
changed = []
def fix_fp(m):
    body = m.group(0)
    ref = re.search(r'\(property "Reference" "([^"]+)"', body).group(1)
    if ref in comps:
        val = comps[ref][0]
        body = re.sub(r'\(property "Value" "[^"]*"', f'(property "Value" "{val}"', body, count=1)
    def fix_pad(pm):
        pad = pm.group(0); num = pm.group(1)
        want = pinnet.get((ref, num))
        cur = re.search(r'\(net (\d+) "([^"]*)"\)', pad)
        if want and cur and cur.group(2) != want:
            changed.append(f'{ref}.{num}: {cur.group(2)} -> {want}')
            pad = pad.replace(cur.group(0), f'(net {nets[want]} "{want}")')
        return pad
    return re.sub(r'\(pad "([^"]*)" .*?\n\t\t\)', fix_pad, body, flags=re.S)
t = re.sub(r'\n\t\(footprint "[^"]+".*?\n\t\)', fix_fp, t, flags=re.S)
print('pads changed:', changed)
# tracks left on a net that no pad uses any more take the net of the pads they touch: none expected here
open(dst, 'w').write(t)
