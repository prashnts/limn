"""How Limn moves: its joints, recorded in Fusion, as sliders under the 3D views.

guide/fusion/LimnMotion (a Fusion script, run on the design the STEP export comes from)
drives every joint through its range and writes guide/motion.json: per joint, where each
occurrence that moved went, as world matrices, keyed by Fusion's occurrence path. The
STEP export has the same occurrence names, so the path finds the same part here.

For each assembly page with something moving inside it, page_motions() gives every joint
as the change of each moving part in the page's own model (glTF axes, mm), one 4x4 per
position. The page then shows its model composed from the parts (build.tree(), each node
named with its occurrence in userData.occ) so static/viewer.js can find them. Only the
outermost part that moves is kept: moving it carries what it holds along.
"""
import json
from pathlib import Path

import numpy as np

R = np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, -1, 0, 0], [0, 0, 0, 1]], float)    # STEP's Z up to glTF's Y up
R_INV = R.T


def load(path: Path):
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    m = lambda a: np.array(a, float).reshape(4, 4)
    data['rest'] = {p: m(a) for p, a in data['rest'].items()}
    for d in data['drives']:
        d['samples'] = [{p: m(a) for p, a in s.items()} for s in d['samples']]
    return data


def instance_paths(catalog) -> dict:
    """page slug -> the occurrence paths of its instances in the whole machine ('' the machine)."""
    out = {catalog.top.slug: ['']}
    st = catalog.step

    def walk(part, path):
        for (c, _), name in zip(st.occurrences(part), st.occurrence_names(part)):
            p = f'{path}+{name}' if path else name
            out.setdefault(catalog.by_pd[c.pd].slug, []).append(p)
            if c.children and not c.vendor:
                walk(c, p)
    walk(catalog.top.part, '')
    return out


def page_motions(data, catalog) -> dict:
    """page slug -> {'drives': [{name, dof, unit, values, rest, nodes: {path in the page: [16 column-major] a position}}]}"""
    rest = data['rest']
    out = {}
    for slug, paths in instance_paths(catalog).items():
        page = catalog.pages[slug]
        if not page.children:
            continue
        here = paths[0]                                       # the first one of it
        prefix = here + '+' if here else ''
        drives = []
        for d in data['drives']:
            samples = d['samples']
            inside = sorted({p for s in samples for p in s if p.startswith(prefix)})
            if not inside:
                continue
            frame = lambda s: s.get(here, rest[here]) if here else np.eye(4)
            world = lambda s, p: s.get(p, rest[p])
            local = lambda s, p: np.linalg.inv(frame(s)) @ world(s, p)            # in the page's own frame
            parent = lambda p: p.rsplit('+', 1)[0] if '+' in p else ''
            nodes = {}
            for p in inside:
                q = parent(p)
                # carried by a parent that moves the same: the parent is enough
                if q in inside and all(np.allclose(np.linalg.inv(local(s, q)) @ local(s, p),
                                                   np.linalg.inv(local({}, q)) @ local({}, p), atol=1e-4) for s in samples):
                    continue
                rest_l = np.linalg.inv(local({}, p))
                ms = [R @ (local(s, p) @ rest_l) @ R_INV for s in samples]
                if all(np.allclose(m, np.eye(4), atol=1e-4) for m in ms):
                    continue                                  # moves only with the page itself
                nodes[p[len(prefix):]] = [[round(float(v), 5) for v in m.T.ravel()] for m in ms]
            if nodes:
                name = d['joint'] + (f' · {d["component"]}' if d.get('component') else '')
                drives.append({'name': name, 'dof': d['dof'], 'unit': d['unit'], 'values': d['values'],
                               'rest': d['rest'], 'nodes': nodes})
        if drives:
            out[slug] = {'drives': drives}
    return out
