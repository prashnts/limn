"""Product shots in Blender: a glTF in a soft studio light, CAD edges, transparent background.

    blender -b -P guide/render/shot.py -- jobs.json

jobs.json: [{"glb": ..., "png": ..., "view": "iso"|"front-iso"|"rear"|"top"|"front"|"low",
             "color": [r, g, b] (sRGB 0-1, optional: one filament colour for all),
             "size": [w, h], "samples": 96, "edges": true, "gpu": false, "engine": "cycles"|"eevee"}]
Writes a transparent PNG (guide/render/backdrop.py can put it on a backdrop). EEVEE is the GPU;
Cycles has a shadow catcher under the part, EEVEE no floor at all.
"""
import json
import math
import sys
from pathlib import Path

# Blender's glTF importer needs numpy, which a distro Blender may not have:
# `uv pip install --python 3.14 --target guide/.cache/blender-site numpy`
sys.path.append(str(Path(__file__).resolve().parents[1] / '.cache' / 'blender-site'))

import bpy  # noqa: E402
from mathutils import Vector

VIEWS = {'iso': (1, -1.25, 0.75), 'rear': (-1.2, 1, 0.8), 'top': (0.001, -0.001, 1),
         'front': (0, -1, 0.25), 'low': (1.3, -0.9, 0.35), 'side': (1, 0, 0.3),
         'front-iso': (-1, 1.25, 0.75)}     # the whole machine as it stands in front of you (iso is its back)


def srgb_to_linear(c):
    return [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in c]


def setup_device(scene, gpu):
    """CPU unless asked: HIP on the Radeon 8060S faults (Blender 5.0.1, ROCm 7.2)."""
    if not gpu:
        scene.cycles.device = 'CPU'
        return 'CPU'
    prefs = bpy.context.preferences.addons['cycles'].preferences
    for kind in ('HIP', 'OPTIX', 'CUDA', 'ONEAPI', 'METAL'):
        try:
            prefs.compute_device_type = kind
            prefs.get_devices()
            gpus = [d for d in prefs.devices if d.type == kind]
            if gpus:
                for d in prefs.devices:
                    d.use = d.type == kind
                scene.cycles.device = 'GPU'
                return kind
        except TypeError:
            continue
    scene.cycles.device = 'CPU'
    return 'CPU'


def shot(job):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    eevee = job.get('engine') == 'eevee'
    if eevee:
        # the GPU through OpenGL: no shadow catcher, so no floor
        scene.render.engine = 'BLENDER_EEVEE'
        scene.eevee.taa_render_samples = job.get('samples', 64)
        scene.eevee.use_raytracing = True
        scene.eevee.use_shadows = True
        scene.eevee.shadow_ray_count = 3
        scene.eevee.shadow_step_count = 12
        device = 'EEVEE'
    else:
        scene.render.engine = 'CYCLES'
        device = setup_device(scene, job.get('gpu', False))
        scene.cycles.samples = job.get('samples', 96)
        scene.cycles.use_denoising = True
    scene.render.film_transparent = True
    w, h = job.get('size', [2000, 1500])
    scene.render.resolution_x, scene.render.resolution_y = w, h
    scene.view_settings.view_transform = 'AgX'
    scene.view_settings.look = 'AgX - Medium High Contrast'

    bpy.ops.import_scene.gltf(filepath=job['glb'])
    meshes = [o for o in scene.objects if o.type == 'MESH']
    tint = job.get('color')
    for o in meshes:
        for slot in o.material_slots:
            m = slot.material
            if not m or not m.use_nodes:
                continue
            m = m.copy()
            slot.material = m
            bsdf = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
            if tint:
                bsdf.inputs['Base Color'].default_value = (*srgb_to_linear(tint), 1)
            bsdf.inputs['Metallic'].default_value = 0.0
            bsdf.inputs['Roughness'].default_value = 0.48
            # printed plastic: a touch of coat, light passing a little under the surface
            bsdf.inputs['Coat Weight'].default_value = 0.08
        o.data.shade_smooth_by_angle(angle=math.radians(35)) if hasattr(o.data, 'shade_smooth_by_angle') else None

    # bounds, then stand it on the floor at the origin
    pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    shift = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    for o in scene.objects:
        if o.parent is None:
            o.location -= shift
    size = hi - lo
    r = size.length / 2
    target = Vector((0, 0, size.z / 2))

    # floor: catches shadows only (Cycles)
    if not eevee:
        bpy.ops.mesh.primitive_plane_add(size=r * 60, location=(0, 0, 0))
        bpy.context.object.is_shadow_catcher = True

    def area(name, loc, power, size_, color=(1, 1, 1)):
        bpy.ops.object.light_add(type='AREA', location=loc)
        lamp = bpy.context.object
        lamp.name = name
        lamp.data.energy = power * r * r
        lamp.data.size = size_ * r
        lamp.data.color = color
        d = target - lamp.location
        lamp.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    area('key', (r * 2.2, -r * 2.0, r * 3.2), 90, 2.5)
    area('fill', (-r * 3, -r * 1.5, r * 1.4), 28, 4, (0.92, 0.95, 1.0))
    area('rim', (-r * 1.2, r * 3, r * 2.2), 60, 2)
    world = bpy.data.worlds.new('studio')
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs['Color'].default_value = (0.8, 0.82, 0.85, 1)
    world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.45

    # camera: the bounding sphere inside the frame
    cam_data = bpy.data.cameras.new('cam')
    cam_data.lens = 85
    cam_data.sensor_fit = 'AUTO'
    cam = bpy.data.objects.new('cam', cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    d = Vector(VIEWS.get(job.get('view', 'iso'), VIEWS['iso'])).normalized()
    fov = cam_data.angle * (min(w, h) / max(w, h)) if w >= h else cam_data.angle
    dist = r * job.get('zoom', 1.05) / math.sin(fov / 2)
    cam.location = target + d * dist
    cam.rotation_euler = (target - cam.location).to_track_quat('-Z', 'Y').to_euler()
    cam_data.clip_start, cam_data.clip_end = dist / 100, dist * 10

    if job.get('edges', True):
        scene.render.use_freestyle = True
        scene.render.line_thickness_mode = 'ABSOLUTE'
        scene.render.line_thickness = max(1.0, w / 1600)
        ls = scene.view_layers[0].freestyle_settings.linesets[0]
        ls.select_by_visibility = True
        ls.select_silhouette, ls.select_border, ls.select_crease = True, True, True
        scene.view_layers[0].freestyle_settings.crease_angle = math.radians(140)
        ls.linestyle = ls.linestyle or bpy.data.linestyles.new('cad')
        ls.linestyle.color = (0.07, 0.08, 0.1)
        ls.linestyle.alpha = 0.45

    if job.get('ids'):
        ids(job, scene, meshes, cam)
    scene.render.filepath = job['png']
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    bpy.ops.render.render(write_still=True)
    print(f'shot {job["png"]} ({device})', flush=True)


def ids(job, scene, meshes, cam):
    """The same view, each mesh in a flat colour that is its number: (r, g, b) in 16 levels each, so
    sRGB rounding can't confuse two. job['ids'] gets, per number, the names from the mesh up to the
    root, and where its bounds fall in the picture (0-1, y down), for the ones out of sight."""
    from bpy_extras.object_utils import world_to_camera_view
    bpy.context.view_layer.update()                  # matrix_world after the move onto the floor
    scene.render.engine = 'BLENDER_EEVEE'
    scene.eevee.taa_render_samples = 1
    scene.render.filter_size = 0
    scene.render.use_freestyle = False
    scene.render.dither_intensity = 0
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0
    out = {}
    for i, o in enumerate(meshes, 1):
        level = [(i >> s) & 15 for s in (8, 4, 0)]
        m = bpy.data.materials.new(f'id{i}')
        m.use_nodes = True
        nodes = m.node_tree.nodes
        nodes.clear()
        em = nodes.new('ShaderNodeEmission')
        em.inputs['Color'].default_value = (*srgb_to_linear([v / 15 for v in level]), 1)
        m.node_tree.links.new(em.outputs[0], nodes.new('ShaderNodeOutputMaterial').inputs[0])
        if not o.material_slots:
            o.data.materials.append(None)
        for slot in o.material_slots:            # on the object: instances share their mesh
            slot.link = 'OBJECT'
            slot.material = m
        names, p = [], o
        while p:
            names.append(p.name)
            p = p.parent
        uv = [world_to_camera_view(scene, cam, o.matrix_world @ Vector(c)) for c in o.bound_box]
        out[i] = {'names': names, 'box': [min(v.x for v in uv), 1 - max(v.y for v in uv),
                                          max(v.x for v in uv), 1 - min(v.y for v in uv)]}
    Path(job['ids']).write_text(json.dumps(out))


if __name__ == '__main__':
    jobs = json.load(open(sys.argv[sys.argv.index('--') + 1]))
    for job in jobs:
        shot(job)
