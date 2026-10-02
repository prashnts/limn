"""Binary glTF: read, check, and put an assembly together from its parts' files.

OpenCASCADE gives up on a whole document when one shape in it fails, so a big
assembly can come out with every mesh empty while each of its parts meshes fine.
compose() builds the assembly from the parts' .glb instead, placed as the STEP
file places them (step.Step.occurrences).
"""
import json
import struct
from pathlib import Path

Z_UP = [-0.5 ** .5, 0, 0, 0.5 ** .5]          # STEP's Z up to glTF's Y up (as mesh.mjs)


def read(path: Path):
    d = path.read_bytes()
    n = struct.unpack('<I', d[12:16])[0]
    gltf = json.loads(d[20:20 + n])
    binary = d[20 + n + 8:] if len(d) > 20 + n else b''
    return gltf, binary


def write(path: Path, gltf: dict, binary: bytes):
    js = json.dumps(gltf, separators=(',', ':')).encode()
    js += b' ' * (-len(js) % 4)
    binary += b'\0' * (-len(binary) % 4)
    out = struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(binary))
    out += struct.pack('<II', len(js), 0x4E4F534A) + js + struct.pack('<II', len(binary), 0x004E4942) + binary
    path.write_bytes(out)


def triangles(path: Path):
    """Every triangle of the file, placed, in STEP's own axes (Z up, mm): (n, 3, 3) float32."""
    import numpy as np
    gltf, binary = read(path)
    sizes = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}
    types = {5126: np.float32, 5125: np.uint32, 5123: np.uint16, 5121: np.uint8}

    def accessor(i):
        a = gltf['accessors'][i]
        v = gltf['bufferViews'][a['bufferView']]
        dt, k = np.dtype(types[a['componentType']]), sizes[a['type']]
        start = v.get('byteOffset', 0) + a.get('byteOffset', 0)
        stride = v.get('byteStride') or dt.itemsize * k
        raw = np.frombuffer(binary, np.uint8, count=stride * (a['count'] - 1) + dt.itemsize * k, offset=start)
        if stride == dt.itemsize * k:
            return raw.view(dt).reshape(a['count'], k)
        return np.lib.stride_tricks.as_strided(raw, (a['count'], k * dt.itemsize), (stride, 1)).copy().view(dt)

    def local(n):
        if 'matrix' in n:
            return np.array(n['matrix'], float).reshape(4, 4).T
        m = np.eye(4)
        x, y, z, w = n.get('rotation', [0, 0, 0, 1])
        m[:3, :3] = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
        m[:3, :3] *= np.array(n.get('scale', [1, 1, 1]))
        m[:3, 3] = n.get('translation', [0, 0, 0])
        return m
    out = []

    def walk(i, parent):
        n = gltf['nodes'][i]
        m = parent @ local(n)
        if n.get('name') == 'Z up':             # back to STEP's Z up: STL is printed that way
            m = parent
        for p in gltf['meshes'][n['mesh']]['primitives'] if 'mesh' in n else []:
            if p.get('mode', 4) != 4:
                continue
            pos = accessor(p['attributes']['POSITION']).astype(np.float64)
            idx = accessor(p['indices']).ravel() if 'indices' in p else np.arange(len(pos))
            pts = pos @ m[:3, :3].T + m[:3, 3]
            out.append(pts[idx.reshape(-1, 3)].astype(np.float32))
        for c in n.get('children', []):
            walk(c, m)
    for r in gltf['scenes'][gltf.get('scene', 0)]['nodes']:
        walk(r, np.eye(4))
    return np.concatenate(out) if out else np.zeros((0, 3, 3), np.float32)


def stl(path: Path, out: Path, name: str = '') -> int:
    """The .glb as a binary STL (mm, Z up) -> its triangles."""
    import numpy as np
    t = triangles(path)
    n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    rec = np.zeros(len(t), [('n', '<f4', 3), ('v', '<f4', (3, 3)), ('a', '<u2')])
    rec['n'], rec['v'] = n, t
    head = (f'limn guide: {name}'.encode()[:80]).ljust(80, b' ')
    out.write_bytes(head + struct.pack('<I', len(t)) + rec.tobytes())
    return len(t)


def broken(path: Path) -> bool:
    """No file, or meshes without a single vertex (their bounds are null)."""
    if not path.exists():
        return True
    gltf, _ = read(path)
    acc = gltf.get('accessors', [])
    return not acc or all(a.get('min') and None in a['min'] for a in acc if 'min' in a)


def compose(out: Path, name: str, instances: list):
    """instances: [(child .glb, name, 4x4 row-major child-to-assembly[, occurrence name])] -> one .glb.
    An occurrence name goes into the node's extras ({"occ": ..}): three.js has it as userData.occ,
    and the names from the top down make Fusion's path to it (guide/motion.py)."""
    gltf = {'asset': {'version': '2.0', 'generator': 'limn guide (composed)'}, 'scene': 0,
            'nodes': [], 'meshes': [], 'materials': [], 'accessors': [], 'bufferViews': []}
    blob = bytearray()
    loaded = {}                                   # child path -> (mesh offset, its gltf)

    def load(path):
        if path in loaded:
            return loaded[path]
        g, b = read(path)
        off = {k: len(gltf[k]) for k in ('meshes', 'materials', 'accessors', 'bufferViews')}
        base = len(blob)
        blob.extend(b)
        blob.extend(b'\0' * (-len(blob) % 4))
        for v in g.get('bufferViews', []):
            gltf['bufferViews'].append({**v, 'buffer': 0, 'byteOffset': v.get('byteOffset', 0) + base})
        for a in g.get('accessors', []):
            gltf['accessors'].append({**a, 'bufferView': a['bufferView'] + off['bufferViews']})
        gltf['materials'] += g.get('materials', [])
        for m in g.get('meshes', []):
            prims = [{**p, 'attributes': {k: v + off['accessors'] for k, v in p['attributes'].items()},
                      'indices': p['indices'] + off['accessors'],
                      **({'material': p['material'] + off['materials']} if 'material' in p else {})}
                     for p in m['primitives']]
            gltf['meshes'].append({**m, 'primitives': prims})
        loaded[path] = (off['meshes'], g)
        return loaded[path]

    def copy(g, i, mesh_off):
        """A copy of node i (of g) and what's under it; its new index."""
        n = g['nodes'][i]
        new = {k: v for k, v in n.items() if k not in ('children', 'mesh')}
        if 'mesh' in n:
            new['mesh'] = n['mesh'] + mesh_off
        kids = [copy(g, c, mesh_off) for c in n.get('children', [])]
        if kids:
            new['children'] = kids
        gltf['nodes'].append(new)
        return len(gltf['nodes']) - 1

    top = []
    for path, child_name, m, *occ in instances:
        mesh_off, g = load(path)
        # the child's own top is its "Z up" node: take what's under it, unturned
        zup = g['nodes'][g['scenes'][0]['nodes'][0]]
        kids = [copy(g, c, mesh_off) for c in zup.get('children', [])]
        gltf['nodes'].append({'name': child_name, 'children': kids,
                              'matrix': [m[r][c] for c in range(4) for r in range(4)],
                              **({'extras': {'occ': occ[0]}} if occ else {})})
        top.append(len(gltf['nodes']) - 1)
    gltf['nodes'].append({'name': name, 'children': top})
    gltf['nodes'].append({'name': 'Z up', 'children': [len(gltf['nodes']) - 1], 'rotation': Z_UP})
    gltf['scenes'] = [{'nodes': [len(gltf['nodes']) - 1]}]
    gltf['buffers'] = [{'byteLength': len(blob)}]
    write(out, gltf, bytes(blob))
