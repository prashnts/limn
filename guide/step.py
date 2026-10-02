"""Read the Fusion STEP export: the part tree, and any part cut out as its own STEP file.

STEP (ISO 10303-21) is text: one `#id=TYPE(args);` per entity. The tree is
PRODUCT -> PRODUCT_DEFINITION_FORMATION -> PRODUCT_DEFINITION, and each
NEXT_ASSEMBLY_USAGE_OCCURRENCE links a parent definition to a child. No CAD
library is needed for that, nor for cutting a part out: its entities are what
its PRODUCT_DEFINITION reaches, plus the few link entities that point back at
it (shapes, children, placements, colours).

    uv run python guide/step.py tree "step/Limn-Export-42 v11.step"
    uv run python guide/step.py cut  "step/Limn-Export-42 v11.step" Limn-NFC-Slider out.step
"""
import collections
import functools
import re
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

START = re.compile(rb'\n#(\d+)=\s*(\(|[A-Z0-9_]+)')
REF = re.compile(rb'#(\d+)')
STR = re.compile(rb"'((?:[^']|'')*)'")
PRODUCT_NAME = re.compile(rb"^(#\d+=PRODUCT\('(?:[^']|'')*',)'(?:[^']|'')*'")

# Entities that point at the part rather than the other way round, and which of
# their references (by position) ties them to it. NAUO only by its parent, so a
# child never drags its parents in.
BACKREF = {
    b'PRODUCT_DEFINITION_SHAPE': None,
    b'SHAPE_DEFINITION_REPRESENTATION': 0,
    b'NEXT_ASSEMBLY_USAGE_OCCURRENCE': 0,
    b'CONTEXT_DEPENDENT_SHAPE_REPRESENTATION': 1,
    b'SHAPE_REPRESENTATION_RELATIONSHIP': None,
    b'STYLED_ITEM': -1,
    b'PROPERTY_DEFINITION': None,
    b'PROPERTY_DEFINITION_REPRESENTATION': 0,
}


def decode(s: bytes) -> str:
    """STEP strings: '' for ', \\X\\hh latin-1, \\X2\\hhhh..\\X0\\ UTF-16."""
    s = s.replace(b"''", b"'").decode('latin-1')
    s = re.sub(r'\\X2\\((?:[0-9A-F]{4})+)\\X0\\',
               lambda m: bytes.fromhex(m.group(1)).decode('utf-16-be'), s)
    return re.sub(r'\\X\\([0-9A-F]{2})', lambda m: chr(int(m.group(1), 16)), s)


def load(path: Path) -> bytes:
    if path.suffix == '.zip':
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(('.step', '.stp')) and '__MACOSX' not in n)
            return z.read(name)
    return path.read_bytes()


@dataclass
class Part:
    pd: int                      # PRODUCT_DEFINITION id
    product: int                 # its PRODUCT
    name: str                    # the component's name in Fusion
    source: str                  # the design it comes from ("Limn-NFC-Slider v16")
    children: list = field(default_factory=list)   # [(Part, count)]
    parents: set = field(default_factory=set)
    bodies: list = field(default_factory=list)     # its own solids' ids (not its children's)
    vendor: bool = False         # bought or downloaded, not one of Limn's designs


OWN = re.compile(r'^(\[[A-Z0-9]+\] )?(Limn|Plot|Paper-|Plotter-|Bed-|Tool-|Controller-|Drag-Chain|ToolChanger|melzi-base|KevStand|SteelRod|MDF-Plaque|Belt-|Pi-Cam-3--Swivel|PCBs)', re.I)


HARDWARE = re.compile(r'PCB|FFC|screw|bolt|nut|rod|spring|pin\b|motor|bearing|switch|jst|usb|cable|magnet|duct|pulley|idler', re.I)


def is_vendor(name: str, source: str, parent_vendor: bool) -> bool:
    """Bought or downloaded parts: not from one of Limn's own designs. A body
    without a design of its own (Component5, Clip-Top) is its assembly's, unless
    its name says hardware."""
    if OWN.match(source) or OWN.match(name):
        return False
    if source:
        return True
    return parent_vendor or bool(HARDWARE.search(name))


class Step:
    def __init__(self, data: bytes):
        self.data = data
        self.header = data[:data.index(b'DATA;') + 5]
        idx = [(int(m.group(1)), m.start() + 1, m.group(2)) for m in START.finditer(data)]
        end = data.index(b'ENDSEC;', idx[-1][1])
        self.at = {}             # id -> (start, end, type)
        for (i, s, t), nxt in zip(idx, idx[1:] + [(0, end, b'')]):
            self.at[i] = (s, nxt[1], t)
        self._tree()

    def text(self, i: int) -> bytes:
        s, e, _ = self.at[i]
        return self.data[s:e].rstrip()

    def type(self, i: int) -> bytes:
        return self.at[i][2]

    def refs(self, i: int) -> list[int]:
        t = self.text(i)
        return [int(x) for x in REF.findall(t[t.index(b'=') + 1:])]

    def of(self, *types: bytes):
        return (i for i, (_, _, t) in self.at.items() if t in types)

    def _tree(self):
        prod = {i: [decode(s) for s in STR.findall(self.text(i))] for i in self.of(b'PRODUCT')}
        pdf = {i: self.refs(i)[0] for i in self.of(b'PRODUCT_DEFINITION_FORMATION',
                                                   b'PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE')}
        self.parts = {}
        for i in self.of(b'PRODUCT_DEFINITION'):
            product = pdf[self.refs(i)[0]]
            name, source = (' '.join(s.split()) for s in prod[product][:2])
            self.parts[i] = Part(i, product, name, '' if source == name else source)
        uses = collections.defaultdict(collections.Counter)
        for i in self.of(b'NEXT_ASSEMBLY_USAGE_OCCURRENCE'):
            parent, child = self.refs(i)[:2]
            uses[parent][child] += 1
        for parent, kids in uses.items():
            p = self.parts[parent]
            p.children = sorted(((self.parts[c], n) for c, n in kids.items()), key=lambda cn: cn[0].name.lower())
            for c in kids:
                self.parts[c].parents.add(parent)
        # bodies: SDR(PDS(pd), SHAPE_REPRESENTATION) <- SRR -> ABSR(items: solids)
        pds = {self.refs(i)[0]: i for i in self.of(b'PRODUCT_DEFINITION_SHAPE')}
        sr = {self.refs(i)[0]: self.refs(i)[1] for i in self.of(b'SHAPE_DEFINITION_REPRESENTATION')}
        brep = collections.defaultdict(list)
        for i in self.of(b'SHAPE_REPRESENTATION_RELATIONSHIP'):
            a, b = self.refs(i)[:2]
            brep[a].append(b)
            brep[b].append(a)
        for pd, p in self.parts.items():
            for rep in brep.get(sr.get(pds.get(pd), -1), []):
                p.bodies += [r for r in self.refs(rep) if self.type(r) in
                             (b'MANIFOLD_SOLID_BREP', b'BREP_WITH_VOIDS', b'SHELL_BASED_SURFACE_MODEL')]
        self.roots = [p for p in self.parts.values() if not p.parents]
        seen = set()

        def classify(p, parent_vendor):
            if p.pd in seen:
                return
            seen.add(p.pd)
            p.vendor = is_vendor(p.name, p.source, parent_vendor)
            for c, _ in p.children:
                classify(c, p.vendor)
        for r in self.roots:
            classify(r, False)

    def shape(self, part: Part) -> tuple:
        """What its own bodies look like, the same from one export to the next
        (ids aren't): bodies, faces by surface type, bounding box in 0.01 mm."""
        seen, todo, kinds, pts = set(), list(part.bodies), collections.Counter(), []
        while todo:
            i = todo.pop()
            if i in seen:
                continue
            seen.add(i)
            t = self.type(i)
            if t == b'CARTESIAN_POINT':
                pts.append([float(x) for x in re.findall(rb'[-+0-9.E]+', self.text(i).split(b'(', 2)[2])[:3]])
                continue
            if t == b'ADVANCED_FACE':
                kinds[self.type(self.refs(i)[-1]).decode()] += 1
            todo.extend(self.refs(i))
        box = tuple(round(max(c) - min(c), 2) for c in zip(*pts)) if pts else ()
        return len(part.bodies), tuple(sorted(kinds.items())), box

    def placement(self, axis2: int):
        """AXIS2_PLACEMENT_3D as a 4x4 (rows), mm."""
        loc, z, x = self.refs(axis2)[:3]
        num = lambda i: [float(v) for v in re.findall(rb'[-+]?[0-9.]+(?:E[-+]?[0-9]+)?', self.text(i).split(b'(', 2)[2])[:3]]
        o, z, x = num(loc), num(z), num(x)
        n = sum(v * v for v in z) ** .5
        z = [v / n for v in z]
        d = sum(a * b for a, b in zip(x, z))
        x = [a - d * b for a, b in zip(x, z)]
        n = sum(v * v for v in x) ** .5
        x = [v / n for v in x]
        y = [z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0]]
        return [[x[0], y[0], z[0], o[0]], [x[1], y[1], z[1], o[1]], [x[2], y[2], z[2], o[2]], [0, 0, 0, 1]]

    def occurrences(self, part: Part):
        """[(child Part, 4x4 child-to-part transform)], one per placed instance."""
        if not hasattr(self, '_occ'):
            pds_of = {self.refs(i)[0]: i for i in self.of(b'PRODUCT_DEFINITION_SHAPE')}
            cdsr = {self.refs(i)[1]: self.refs(i)[0] for i in self.of(b'CONTEXT_DEPENDENT_SHAPE_REPRESENTATION')}
            self._occ = collections.defaultdict(list)
            self._occ_names = collections.defaultdict(list)
            for i in self.of(b'NEXT_ASSEMBLY_USAGE_OCCURRENCE'):
                parent, child = self.refs(i)[:2]
                self._occ_names[parent].append(decode(STR.findall(self.text(i))[0]))
                rr = cdsr.get(pds_of.get(i))
                m = None
                if rr is not None:
                    idt = next(r for r in self.refs(rr) if self.type(r) == b'ITEM_DEFINED_TRANSFORMATION')
                    a1, a2 = self.refs(idt)[:2]
                    m = matmul(self.placement(a2), inverse(self.placement(a1)))
                self._occ[parent].append((self.parts[child], m or [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]))
        return self._occ[part.pd]

    def occurrence_names(self, part: Part) -> list[str]:
        """The names of occurrences(part), in its order: Fusion's occurrence names ('Limn-NFC-Rider:1'),
        whose paths joined by '+' are Fusion's fullPathName."""
        self.occurrences(part)
        return self._occ_names[part.pd]

    def find(self, name: str) -> Part:
        nover = lambda s: re.sub(r'\s+v\d+.*$', '', s)
        hits = [p for p in self.parts.values() if p.name == name] or \
               [p for p in self.parts.values() if nover(p.source) == name] or \
               [p for p in self.parts.values() if p.source.startswith(name)]
        if not hits:
            raise KeyError(name)
        return hits[0]

    @functools.cached_property
    def back(self):
        back = collections.defaultdict(list)
        for i, (_, _, t) in self.at.items():
            if t in BACKREF:
                pos = BACKREF[t]
                rs = self.refs(i)
                for r in (rs if pos is None else [rs[pos]]):
                    back[r].append(i)
        return back

    def cut(self, part: Part, names: dict | None = None, deep: bool = True) -> bytes:
        """The part (and everything under it, unless not `deep`) as a STEP file
        of its own. `names` ({pd: name}) renames products: CAD programs show that name."""
        back = self.back
        mdgpr = next(self.of(b'MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION'), None)
        ctx = self.refs(mdgpr)[-1] if mdgpr else None
        keep, todo = set(), [part.pd] + ([ctx] if ctx else [])
        while todo:
            i = todo.pop()
            if i in keep:
                continue
            keep.add(i)
            todo.extend(self.refs(i))
            todo.extend(b for b in back.get(i, ()) if deep or self.type(b) != b'NEXT_ASSEMBLY_USAGE_OCCURRENCE')
        styled = sorted(i for i in keep if self.type(i) == b'STYLED_ITEM')
        out = [self.header, b'\n']
        rename = {self.parts[pd].product: n for pd, n in (names or {}).items()}

        def text(i):
            if i not in rename:
                return self.text(i)
            name = rename[i].replace("'", "''").encode('latin-1', 'replace')
            return PRODUCT_NAME.sub(lambda m: m.group(1) + b"'" + name + b"'", self.text(i), count=1)
        out += [text(i) + b'\n' for i in sorted(keep)]
        if mdgpr and styled:
            out.append(b'#%d=MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION(\'\',(%s),#%d);\n'
                       % (mdgpr, b','.join(b'#%d' % i for i in styled), ctx))
        out.append(b'ENDSEC;\nEND-ISO-10303-21;\n')
        return b''.join(out)


def matmul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def inverse(m):
    """Of a rigid transform: transpose the rotation, turn the translation back."""
    r = [[m[j][i] for j in range(3)] for i in range(3)]
    t = [-sum(r[i][k] * m[k][3] for k in range(3)) for i in range(3)]
    return [r[0] + [t[0]], r[1] + [t[1]], r[2] + [t[2]], [0, 0, 0, 1]]


def walk(part: Part, depth=0, count=1, stop_at_vendor=True):
    """(part, depth, count) down the tree, not into bought parts' insides."""
    yield part, depth, count
    if stop_at_vendor and part.vendor and depth:
        return
    for c, n in part.children:
        yield from walk(c, depth + 1, n, stop_at_vendor)


if __name__ == '__main__':
    cmd, path, *rest = sys.argv[1:]
    step = Step(load(Path(path)))
    if cmd == 'tree':
        for root in step.roots:
            for p, d, n in walk(root):
                tag = 'buy' if p.vendor else ('asm' if p.children else 'own')
                print(f"{'  ' * d}{p.name}{f'  x{n}' if n > 1 else ''}  <{tag}>{f'  [{p.source}]' if p.source else ''}")
    elif cmd == 'cut':
        Path(rest[1]).write_bytes(step.cut(step.find(rest[0])))
