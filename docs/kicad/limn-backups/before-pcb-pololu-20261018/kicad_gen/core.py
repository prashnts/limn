# Limn KiCad generator - the s-expression writer and one Sheet's drawing tools
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# The recipe of limn_endoscope/kicad/gen_teensy_sheet.py, grown into a library: KiCad's own library
# symbols copied in (or boards drawn as blocks), parts placed on the 1.27 mm grid, wires with 45°
# corners (the user's preference), labels on pin ends, enclosures around groups. Lessons:
#   - a wire joins another only at its ends: split long wires at every T (wire() takes a path);
#   - power symbols name their net by their Value, so '+5V_LED' on a +5V symbol is its own rail;
#   - every rail with a power_in pin needs one power_out or PWR_FLAG somewhere in the design.
import re
import uuid
from pathlib import Path

LIBS = Path('/usr/share/kicad/symbols')
GRID = 1.27


class Q(str):
    '''A quoted string.'''


def parse(text):
    tokens = re.findall(r'\(|\)|"(?:\\.|[^"\\])*"|[^\s()]+', text)
    stack = [[]]
    for t in tokens:
        if t == '(':
            stack.append([])
        elif t == ')':
            x = stack.pop()
            stack[-1].append(x)
        else:
            stack[-1].append(Q(t[1:-1].replace('\\"', '"').replace('\\\\', '\\')) if t.startswith('"') else t)
    return stack[0][0]


def dump(x, ind=0):
    if isinstance(x, list):
        if all(not isinstance(c, list) for c in x):
            return '(' + ' '.join(dump(c) for c in x) + ')'
        out = '(' + ' '.join(dump(c) for c in x if not isinstance(c, list))
        for c in x:
            if isinstance(c, list):
                out += '\n' + '\t' * (ind + 1) + dump(c, ind + 1)
        return out + '\n' + '\t' * ind + ')'
    if isinstance(x, Q):
        return '"' + str(x).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n') + '"'
    return str(x)


def find(node, name):
    return [c for c in node if isinstance(c, list) and c and c[0] == name]


def u():
    return Q(str(uuid.uuid4()))


def num(v):
    return f'{v:.3f}'.rstrip('0').rstrip('.') if isinstance(v, float) else str(v)


def g(v):
    '''Snap to the grid.'''
    return round(round(v / GRID) * GRID, 3)


def font(hide=False, justify=None, size=1.27, bold=False, italic=False):
    f = ['font', ['size', num(size), num(size)]]
    if bold:
        f.append(['bold', 'yes'])
    if italic:
        f.append(['italic', 'yes'])
    e = ['effects', f]
    if justify:
        e.append(['justify'] + justify.split())
    if hide:
        e.append(['hide', 'yes'])
    return e


# ---------------------------------------------------------------- library symbols
_lib_cache = {}


def kicad_symbol(lib, name):
    '''A symbol from KiCad's libraries, renamed lib:name; `extends` flattened.'''
    if lib not in _lib_cache:
        _lib_cache[lib] = {str(s[1]): s for s in find(parse((LIBS / f'{lib}.kicad_sym').read_text()), 'symbol')}
    syms = _lib_cache[lib]
    sym = [list(c) if isinstance(c, list) else c for c in syms[name]]
    ext = find(sym, 'extends')
    if ext:
        base = [list(c) if isinstance(c, list) else c for c in syms[str(ext[0][1])]]
        props = {str(p[1]): p for p in find(sym, 'property')}
        out = [c for c in base if not (isinstance(c, list) and c[0] == 'property')]
        out[1] = Q(name)
        merged = [props.get(str(p[1]), p) for p in find(base, 'property')]
        out[2:2] = merged
        for sub in find(out, 'symbol'):        # units are named after the symbol
            sub[1] = Q(str(sub[1]).replace(str(ext[0][1]), name, 1))
        sym = out
    sym[1] = Q(f'{lib}:{name}')
    return sym


def pin(kind, x, y, ang, name, number, length=2.54, hide_name=False):
    eff = font(hide=hide_name)
    return ['pin', kind, 'line', ['at', num(x), num(y), str(ang)], ['length', num(length)],
            ['name', Q(name), eff], ['number', Q(number), font()]]


def block(name, desc, left=(), right=(), top=(), bottom=(), width=None, ref='U', value=None):
    '''A board drawn as a box. Each side: [(pin name, kind, number?), ...] or None for a gap.
    Returns (lib symbol, half width, half height). Pin numbers default to the order given.'''
    def norm(side):
        out = []
        for p in side:
            out.append(None if p is None else (p + (None,))[:3] if len(p) == 2 else p)
        return out
    left, right, top, bottom = norm(left), norm(right), norm(top), norm(bottom)
    rows = max(len(left), len(right), 1)
    longest = max([len(p[0]) for p in left + right + top + bottom if p] + [4])
    cols = max(len(top), len(bottom), 0)
    w = width or max(g((longest * 1.27 * 2 + 6) / 2), g(cols * 5.08 / 2 + 2.54), 7.62)
    vertical = max([len(p[0]) for p in top + bottom if p] + [0]) * 1.0 + (2.54 if top or bottom else 0)
    h = g(rows * 2.54 / 2 + 1.27 + vertical)
    pins, n = [], [0]

    def nextnum(p):
        n[0] += 1
        return str(p[2]) if p[2] is not None else str(n[0])

    y0 = g((len(left) - 1) * 2.54 / 2)
    for i, p in enumerate(left):
        if p:
            pins.append(pin(p[1], -w - 2.54, y0 - 2.54 * i, 0, p[0], nextnum(p)))
    y0 = g((len(right) - 1) * 2.54 / 2)
    for i, p in enumerate(right):
        if p:
            pins.append(pin(p[1], w + 2.54, y0 - 2.54 * i, 180, p[0], nextnum(p)))
    for side, y, ang in ((top, h + 2.54, 270), (bottom, -h - 2.54, 90)):
        x0 = -g((len(side) - 1) * 5.08 / 2)
        for i, p in enumerate(side):
            if p:
                pins.append(pin(p[1], x0 + 5.08 * i, y, ang, p[0], nextnum(p)))
    lib_id = f'limn:{name}'
    sym = ['symbol', Q(lib_id), ['pin_names', ['offset', '0.762']],
           ['exclude_from_sim', 'no'], ['in_bom', 'yes'], ['on_board', 'yes'],
           ['property', Q('Reference'), Q(ref), ['at', num(-w), num(h + 3.81), '0'], font(justify='left')],
           ['property', Q('Value'), Q(value or name.replace('_', ' ')), ['at', num(-w), num(h + 1.27), '0'], font(justify='left')],
           ['property', Q('Footprint'), Q(''), ['at', '0', '0', '0'], font(hide=True)],
           ['property', Q('Datasheet'), Q(''), ['at', '0', '0', '0'], font(hide=True)],
           ['property', Q('Description'), Q(desc), ['at', '0', '0', '0'], font(hide=True)],
           ['symbol', Q(name + '_0_1'),
            ['rectangle', ['start', num(-w), num(h)], ['end', num(w), num(-h)],
             ['stroke', ['width', '0.254'], ['type', 'default']], ['fill', ['type', 'background']]]],
           ['symbol', Q(name + '_1_1')] + pins,
           ['embedded_fonts', 'no']]
    return sym, w, h


def pin_table(sym):
    t = {}
    for sub in find(sym, 'symbol'):
        for p in find(sub, 'pin'):
            a = find(p, 'at')[0]
            t[str(find(p, 'number')[0][1])] = (float(a[1]), float(a[2]), int(a[3]), str(find(p, 'name')[0][1]))
    return t


def rot(px, py, r):
    return {0: (px, py), 90: (-py, px), 180: (-px, -py), 270: (py, -px)}[r]


DIR = {0: (1, 0), 90: (0, -1), 180: (-1, 0), 270: (0, 1)}


# ---------------------------------------------------------------- a sheet
class Sheet:

    def __init__(self, name, file, project, path, title, paper='A3'):
        self.name, self.file, self.project, self.path = name, file, Q(project), Q(path)
        self.title, self.paper = title, paper
        self.uuid = str(uuid.uuid4())
        self.lib = {}               # lib_id -> symbol
        self.pins = {}              # lib_id -> pin table
        self.boxes = {}             # lib_id -> (w, h) for drawn blocks
        self.items, self.refs, self.cnt = [], {}, [0]

    # library
    def use(self, lib, name):
        lib_id = f'{lib}:{name}'
        if lib_id not in self.lib:
            sym = kicad_symbol(lib, name)
            self.lib[lib_id] = sym
            self.pins[lib_id] = pin_table(sym)
        return lib_id

    def add_block(self, sym, w, h):
        lib_id = str(sym[1])
        self.lib[lib_id] = sym
        self.pins[lib_id] = pin_table(sym)
        self.boxes[lib_id] = (w, h)
        return lib_id

    # parts
    def place(self, lib_id, ref, value, x, y, rot=0, footprint='', on_board=True, dnp=False, note='', left=False):
        x, y = g(x), g(y)
        ta = '0'
        if lib_id in self.boxes:       # boards: Reference and Value above the box, clear of top pins
            w, h = self.boxes[lib_id]
            top = 11.43 if self._has_top(lib_id) else 0
            rp, vp = (x - w, y - h - top - 3.81, 'left'), (x - w, y - h - top - 1.27, 'left')
        elif rot in (90, 270):
            rp, vp, ta = (x, y - 2.54, ''), (x, y + 2.54, ''), str(rot)
        elif left:
            rp, vp = (x - 2.54, y - 1.27, 'right'), (x - 2.54, y + 1.27, 'right')
        else:
            rp, vp = (x + 2.54, y - 1.27, 'left'), (x + 2.54, y + 1.27, 'left')
        props = [['property', Q('Reference'), Q(ref), ['at', num(rp[0]), num(rp[1]), ta], font(justify=rp[2] or None)],
                 ['property', Q('Value'), Q(value), ['at', num(vp[0]), num(vp[1]), ta], font(justify=vp[2] or None)],
                 ['property', Q('Footprint'), Q(footprint), ['at', num(x), num(y), '0'], font(hide=True)],
                 ['property', Q('Datasheet'), Q(''), ['at', num(x), num(y), '0'], font(hide=True)],
                 ['property', Q('Description'), Q(note), ['at', num(x), num(y), '0'], font(hide=True)]]
        self.items.append(['symbol', ['lib_id', Q(lib_id)], ['at', num(x), num(y), str(rot)], ['unit', '1'],
                           ['exclude_from_sim', 'no'], ['in_bom', 'yes'], ['on_board', 'yes' if on_board else 'no'],
                           ['dnp', 'yes' if dnp else 'no'], ['uuid', u()]] + props +
                          [['pin', Q(n), ['uuid', u()]] for n in self.pins[lib_id]] +
                          [['instances', ['project', self.project, ['path', self.path, ['reference', Q(ref)], ['unit', '1']]]]])
        self.refs[ref] = (lib_id, x, y, rot)
        return ref

    def footprint(self, ref, fp):
        '''Set a placed part's Footprint property.'''
        for it in self.items:
            if it[0] == 'symbol' and any(isinstance(x, list) and x[:3] == ['property', Q('Reference'), Q(ref)] for x in it):
                for x in it:
                    if isinstance(x, list) and x[:2] == ['property', Q('Footprint')]:
                        x[2] = Q(fp)
                return
        raise KeyError(ref)

    def _has_top(self, lib_id):
        return any(p[2] == 270 for p in self.pins[lib_id].values())

    def _pin(self, ref, number):
        lib_id = self.refs[ref][0]
        t = self.pins[lib_id]
        if number in t:
            return number
        named = [k for k, v in t.items() if v[3] == number]
        if len(named) != 1:
            raise KeyError(f'{ref}: no single pin {number!r} ({sorted(v[3] for v in t.values())})')
        return named[0]

    def P(self, ref, number):
        '''A pin's end on the sheet (by number, or by a unique pin name).'''
        lib_id, x, y, r = self.refs[ref]
        px, py, _, _ = self.pins[lib_id][self._pin(ref, number)]
        rx, ry = rot(px, py, r)
        return (round(x + rx, 3), round(y - ry, 3))

    def away(self, ref, number):
        '''Direction (deg: 0 right, 90 up) pointing away from the part at this pin.'''
        lib_id, _, _, r = self.refs[ref]
        return (self.pins[lib_id][self._pin(ref, number)][2] + r + 180) % 360

    def out(self, ref, number, d=2.54):
        '''The point d mm out from a pin, along its direction.'''
        x, y = self.P(ref, number)
        dx, dy = DIR[self.away(ref, number)]
        return (g(x + dx * d), g(y + dy * d))

    # wiring
    def wire(self, *pts, chamfer=2.54):
        '''A path of horizontal/vertical runs; corners cut at 45°.'''
        pts = [(g(p[0]), g(p[1])) for p in pts]
        path = [pts[0]]
        for i in range(1, len(pts) - 1):
            a, b, c = path[-1], pts[i], pts[i + 1]
            d1 = (b[0] - a[0], b[1] - a[1])
            d2 = (c[0] - b[0], c[1] - b[1])
            l1, l2 = abs(d1[0]) + abs(d1[1]), abs(d2[0]) + abs(d2[1])
            turn = l1 and l2 and (d1[0] == 0) != (d2[0] == 0)
            k = g(min(chamfer, l1 / 2, l2 / 2)) if turn else 0
            if k:
                u1 = (d1[0] / l1, d1[1] / l1)
                u2 = (d2[0] / l2, d2[1] / l2)
                path.append((g(b[0] - u1[0] * k), g(b[1] - u1[1] * k)))
                path.append((g(b[0] + u2[0] * k), g(b[1] + u2[1] * k)))
            else:
                path.append(b)
        path.append(pts[-1])
        for a, b in zip(path, path[1:]):
            if a != b:
                self.items.append(['wire', ['pts', ['xy', num(a[0]), num(a[1])], ['xy', num(b[0]), num(b[1])]],
                                   ['stroke', ['width', '0'], ['type', 'default']], ['uuid', u()]])
        return path

    def connect(self, ref_a, pin_a, ref_b, pin_b, via=None, lane=0):
        '''A wire between two pins: out of each along its direction, an elbow between.
        Parallel wires between the same two parts need their own `lane` (2.54 mm each),
        or their middle runs overlap and short.'''
        a, b = self.P(ref_a, pin_a), self.P(ref_b, pin_b)
        pts = [a]
        if via:
            pts += via
        else:
            da, db = self.away(ref_a, pin_a), self.away(ref_b, pin_b)
            if da in (0, 180) and db in (0, 180):
                mx = g((a[0] + b[0]) / 2 + lane * 2.54)
                pts += [(mx, a[1]), (mx, b[1])]
            elif da in (90, 270) and db in (90, 270):
                my = g((a[1] + b[1]) / 2 + lane * 2.54)
                pts += [(a[0], my), (b[0], my)]
            elif da in (0, 180):
                pts += [(b[0], a[1])]
            else:
                pts += [(a[0], b[1])]
        pts.append(b)
        return self.wire(*pts)

    def junction(self, pt):
        self.items.append(['junction', ['at', num(pt[0]), num(pt[1])], ['diameter', '0'],
                           ['color', '0', '0', '0', '0'], ['uuid', u()]])

    def label_at(self, name, pt, ang):
        just = 'left bottom' if ang in (0, 90) else 'right bottom'
        self.items.append(['label', Q(name), ['at', num(pt[0]), num(pt[1]), str(ang)], ['fields_autoplaced', 'yes'],
                           font(justify=just), ['uuid', u()]])

    def label(self, name, ref, number, stub=0):
        '''A net label on a pin (or at the end of a short stub out of it).'''
        pt = self.P(ref, number)
        if stub:
            end = self.out(ref, number, stub)
            self.wire(pt, end)
            pt = end
        self.label_at(name, pt, self.away(ref, number))

    def glabel_at(self, name, pt, ang, shape='bidirectional'):
        just = 'left' if ang in (0, 90) else 'right'
        dx = {0: 1, 180: -1}.get(ang, 0)
        self.items.append(['global_label', Q(name), ['shape', shape], ['at', num(pt[0]), num(pt[1]), str(ang)],
                           ['fields_autoplaced', 'yes'], font(justify=just), ['uuid', u()],
                           ['property', Q('Intersheetrefs'), Q('${INTERSHEET_REFS}'),
                            ['at', num(pt[0] + dx * 12.7), num(pt[1]), '0'], font(hide=True, justify=just)]])

    def glabel(self, name, ref, number, shape='bidirectional', stub=2.54):
        '''A global label (crosses sheets) on a pin, at the end of a short stub.'''
        pt = self.P(ref, number)
        if stub:
            end = self.out(ref, number, stub)
            self.wire(pt, end)
            pt = end
        self.glabel_at(name, pt, self.away(ref, number), shape)

    def power_at(self, kind, pt, ang=None, net=None, show=True):
        '''A power symbol on pt pointing `ang` (GND: down, others: up). `net` renames the rail.'''
        lib_id = self.use('power', kind)
        self.cnt[0] += 1
        x, y = pt
        if ang is None:
            ang = 270 if kind.startswith('GND') else 90
        base = 270 if kind.startswith('GND') else 90
        r = (ang - base) % 360
        dx, dy = DIR[ang]
        name = net or kind
        tx, ty = x + dx * (3.81 + len(name) * 0.5 if ang in (0, 180) else 5.08), y + dy * 5.08
        just = {0: 'left', 180: 'right'}.get(ang)
        ref = Q(f'#PWR{self.cnt[0]:03d}')
        hide = not show or (kind.startswith('GND') and ang in (0, 180))
        self.items.append(['symbol', ['lib_id', Q(lib_id)], ['at', num(x), num(y), str(r)], ['unit', '1'],
                           ['exclude_from_sim', 'no'], ['in_bom', 'no'], ['on_board', 'yes'], ['dnp', 'no'], ['uuid', u()],
                           ['property', Q('Reference'), ref, ['at', num(x), num(y), '0'], font(hide=True)],
                           ['property', Q('Value'), Q(name), ['at', num(x + dx * 5.08 if ang in (0, 180) else x), num(ty),
                                                              str(r) if r in (90, 270) else '0'],
                            font(justify=just, hide=hide)],
                           ['property', Q('Footprint'), Q(''), ['at', num(x), num(y), '0'], font(hide=True)],
                           ['property', Q('Datasheet'), Q(''), ['at', num(x), num(y), '0'], font(hide=True)],
                           ['property', Q('Description'), Q(''), ['at', num(x), num(y), '0'], font(hide=True)],
                           ['pin', Q('1'), ['uuid', u()]],
                           ['instances', ['project', self.project, ['path', self.path, ['reference', ref], ['unit', '1']]]]])

    def power(self, kind, ref, number, net=None, stub=0, show=True):
        pt = self.P(ref, number)
        if stub:
            end = self.out(ref, number, stub)
            self.wire(pt, end)
            pt = end
        self.power_at(kind, pt, self.away(ref, number), net, show=show)

    def flag_at(self, pt):
        '''PWR_FLAG: this rail is driven from outside the drawing (ERC).'''
        lib_id = self.use('power', 'PWR_FLAG')
        self.cnt[0] += 1
        x, y = pt
        ref = Q(f'#FLG{self.cnt[0]:03d}')
        self.items.append(['symbol', ['lib_id', Q(lib_id)], ['at', num(x), num(y), '0'], ['unit', '1'],
                           ['exclude_from_sim', 'no'], ['in_bom', 'no'], ['on_board', 'yes'], ['dnp', 'no'], ['uuid', u()],
                           ['property', Q('Reference'), ref, ['at', num(x), num(y), '0'], font(hide=True)],
                           ['property', Q('Value'), Q('PWR_FLAG'), ['at', num(x), num(y - 3.81), '0'], font(hide=True)],
                           ['property', Q('Footprint'), Q(''), ['at', num(x), num(y), '0'], font(hide=True)],
                           ['property', Q('Datasheet'), Q(''), ['at', num(x), num(y), '0'], font(hide=True)],
                           ['property', Q('Description'), Q(''), ['at', num(x), num(y), '0'], font(hide=True)],
                           ['pin', Q('1'), ['uuid', u()]],
                           ['instances', ['project', self.project, ['path', self.path, ['reference', ref], ['unit', '1']]]]])

    def nc(self, ref, number):
        pt = self.P(ref, number)
        self.items.append(['no_connect', ['at', num(pt[0]), num(pt[1])], ['uuid', u()]])

    def nc_rest(self, ref):
        '''No-connect flags on every pin of `ref` nothing was put on yet.'''
        lib_id = self.refs[ref][0]
        used = set()
        for it in self.items:
            if it[0] in ('label', 'global_label', 'no_connect', 'junction'):
                a = find(it, 'at')[0]
                used.add((round(float(a[1]), 3), round(float(a[2]), 3)))
            elif it[0] == 'wire':
                for xy in find(find(it, 'pts')[0], 'xy'):
                    used.add((round(float(xy[1]), 3), round(float(xy[2]), 3)))
            elif it[0] == 'symbol' and str(find(it, 'lib_id')[0][1]).startswith('power:'):
                a = find(it, 'at')[0]
                used.add((round(float(a[1]), 3), round(float(a[2]), 3)))
        for number in self.pins[lib_id]:
            if self.P(ref, number) not in used:
                self.nc(ref, number)

    def text(self, s, x, y, size=1.27, bold=False, italic=False):
        self.items.append(['text', Q(s), ['exclude_from_sim', 'no'], ['at', num(g(x)), num(g(y)), '0'],
                           font(justify='left top', size=size, bold=bold, italic=italic), ['uuid', u()]])

    def title_text(self, s, x, y):
        self.text(s, x, y, size=2.0, bold=True)

    def enclose(self, x1, y1, x2, y2, title=None, planned=False):
        '''A box round a group: solid = one board / assembly, dashed = planned or going.'''
        self.items.append(['rectangle', ['start', num(g(x1)), num(g(y1))], ['end', num(g(x2)), num(g(y2))],
                           ['stroke', ['width', '0.254' if not planned else '0.2'], ['type', 'dash' if planned else 'solid'],
                            ['color', '72', '72', '72', '1'] if not planned else ['color', '132', '0', '0', '1']],
                           ['fill', ['type', 'none']], ['uuid', u()]])
        if title:
            self.text(title, x1 + 1.27, y1 + 1.27, size=1.5, bold=True, italic=planned)

    # output
    def sexpr(self, title_block=None):
        tb = ['title_block', ['title', Q(self.title)], ['date', Q('2026-10-16')], ['rev', Q('1')], ['company', Q('limn')]]
        if title_block:
            for i, c in enumerate(title_block, 1):
                tb.append(['comment', str(i), Q(c)])
        return ['kicad_sch', ['version', '20250114'], ['generator', Q('eeschema')], ['generator_version', Q('9.0')],
                ['uuid', Q(self.uuid)], ['paper', Q(self.paper)], tb,
                ['lib_symbols'] + list(self.lib.values())] + self.items + [['embedded_fonts', 'no']]
