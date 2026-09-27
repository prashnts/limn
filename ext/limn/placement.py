# Limn - what stays true about the bed on the plotter, over Klipper restarts
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# The meshes and the row of test marks belong to one placement of a bed. The
# Dock counts the beds placed and removed since it booted (read_bed_id's third
# item); once that count or its boot id changes, the bed may have moved: the
# meshes are taken again, the marks start over. Tool tags are not touched.
# Kept in save_variables:
#   lrt_meshes  {'placement': key, 'profiles': {name: fingerprint}}
#   lrt_marks   {'placement': key, 'next': index into the bed's mark grid}
import hashlib
import json


def placement_key(reply, live):
    '''read_bed_id's reply -> key of this placement, None while a bed is being
    placed (not confirmed by the Dock yet). Dock firmware without the count:
    `live`, Klipper's own count of the bed lines, only good until it restarts.'''
    name = reply[0]
    info = reply[2] if len(reply) > 2 and isinstance(reply[2], dict) else None
    if info is None:
        return f'{name}@{live}'
    if name != 'NONE' and not info.get('powered'):
        return None
    return f"{name}@dock:{info['boot']}:{info['placed']}"


def mesh_fingerprint(profile):
    '''A bed_mesh profile (points, mesh_params) -> short hash. Rounded, so that
    the profile SAVE_CONFIG wrote and Klipper read back hashes the same.'''
    if not profile or not profile.get('points'):
        return None
    params = profile.get('mesh_params', {})
    data = {'points': [[round(float(v), 3) for v in row] for row in profile['points']],
            'bounds': [round(float(params.get(k, 0)), 1) for k in ('min_x', 'max_x', 'min_y', 'max_y')]}
    return hashlib.sha1(json.dumps(data).encode()).hexdigest()[:12]


def mesh_bounds(profile):
    '''-> ((min_x, min_y), (max_x, max_y)) of a bed_mesh profile.'''
    p = profile['mesh_params']
    return (float(p['min_x']), float(p['min_y'])), (float(p['max_x']), float(p['max_y']))


def stale_meshes(record, key, profiles, names):
    '''Why the meshes `names` can't be used for the bed as it is now, [] when they can.
    record: lrt_meshes; profiles: bed_mesh's, as its status has them.'''
    if key is None:
        return ["the bed isn't settled on the plotter yet"]
    if not record or record.get('placement') != key:
        return ["the bed was placed after the last meshes"]
    why = []
    for name in names:
        fingerprint = mesh_fingerprint(profiles.get(name))
        if fingerprint is None:
            why.append(f"there is no {name} mesh")
        elif fingerprint != record.get('profiles', {}).get(name):
            why.append(f"{name} isn't the mesh taken last (restarted without SAVE_CONFIG?)")
    return why


def next_mark(record, key):
    '''Index of the next test mark: where the last one ended, on this placement.'''
    if key is not None and record and record.get('placement') == key:
        return int(record.get('next', 0))
    return 0
