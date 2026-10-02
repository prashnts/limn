"""Limn: how the joints move, for the guide's 3D views.

Run it in Fusion on the open Limn design (Utilities > Add-Ins > Scripts and Add-Ins >
+ > Script or add-in from device: this folder). It drives every joint that can move
(revolute, slider, cylindrical, pin-slot, as-built ones too) through a few positions
within its limits, and records where every occurrence that moved goes, motion links
(the gears) included. Then it sets each joint back. Nothing is saved; if Fusion offers
to capture the position afterwards, choose Revert.

Writes limn-motion.json (asks where): occurrence paths as Fusion's fullPathName
(the STEP export's occurrence names joined by '+'), 4x4 world matrices, row-major, mm.
Put it in the repository as guide/motion.json; guide/build.py does the rest.
"""
import json
import math
import time
import traceback

import adsk.core
import adsk.fusion

STEPS = 16              # positions over a joint's range (a full turn without limits)
SLIDE_FREE = 1.0        # cm each way for a slider without limits


def matrix(occ):
    """World transform, row-major, mm."""
    a = list(occ.transform2.asArray())
    if any(abs(v) > 1e-9 for v in a[12:15]):        # column-major after all: the translation is at the bottom
        a = [a[c * 4 + r] for r in range(4) for c in range(4)]
    for i in (3, 7, 11):
        a[i] *= 10.0
    return [round(v, 6) for v in a]


def moved(a, b):
    return any(abs(x - y) > 1e-4 for x, y in zip(a, b))


def all_joints(design):
    """Every joint, in the root's context (a proxy per occurrence of its component)."""
    root = design.rootComponent
    seen = set()
    for comp in design.allComponents:
        for kind, coll in (('joint', comp.joints), ('as-built', comp.asBuiltJoints)):
            for j in coll:
                if comp == root:
                    out = [(j, '')]
                else:
                    out = []
                    for occ in root.allOccurrencesByComponent(comp):
                        try:
                            out.append((j.createForAssemblyContext(occ), occ.fullPathName))
                        except Exception:
                            pass
                for p, where in out:
                    key = (comp.name, j.name, where)
                    if key not in seen:
                        seen.add(key)
                        yield p, kind, comp.name, where


def dofs(motion):
    """[(dof, getter name, limits, unit)] of a joint's motion."""
    t = motion.jointType
    J = adsk.fusion.JointTypes
    out = []
    if t in (J.RevoluteJointType, J.CylindricalJointType, J.PinSlotJointType):
        out.append(('rotation', 'rotationValue', motion.rotationLimits))
    if t in (J.SliderJointType, J.CylindricalJointType, J.PinSlotJointType):
        out.append(('slide', 'slideValue', motion.slideLimits))
    return out


def values(dof, limits, now):
    lo = limits.minimumValue if limits.isMinimumValueEnabled else None
    hi = limits.maximumValue if limits.isMaximumValueEnabled else None
    if dof == 'rotation':
        if lo is None or hi is None:
            lo, hi = now, now + 2 * math.pi
    else:
        lo = now - SLIDE_FREE if lo is None else lo
        hi = now + SLIDE_FREE if hi is None else hi
    return [lo + (hi - lo) * i / STEPS for i in range(STEPS + 1)]


def run(context):
    app = adsk.core.Application.get()
    ui = app.userInterface
    try:
        design = adsk.fusion.Design.cast(app.activeProduct)
        if not design:
            ui.messageBox('Open the Limn design first.')
            return
        root = design.rootComponent
        occs = list(root.allOccurrences)
        rest = {o.fullPathName: matrix(o) for o in occs}
        drives, skipped = [], []
        joints = [j for j in all_joints(design)]
        progress = ui.createProgressDialog()
        progress.show('Limn motion', 'Joint %v of %m', 0, len(joints), 0)
        for n, (j, kind, comp, where) in enumerate(joints):
            progress.progressValue = n
            if progress.wasCancelled:
                break
            try:
                motion = j.jointMotion
                if j.isSuppressed or not dofs(motion):
                    continue
            except Exception:
                continue
            for dof, attr, limits in dofs(motion):
                now = getattr(motion, attr)
                vals, samples = values(dof, limits, now), []
                try:
                    for v in vals:
                        setattr(motion, attr, v)
                        adsk.doEvents()
                        samples.append({p: m for p, m in ((o.fullPathName, matrix(o)) for o in occs) if moved(m, rest[p])})
                except Exception as e:
                    skipped.append(f'{comp} / {j.name} ({dof}): {e}')
                    samples = []
                finally:
                    try:
                        setattr(motion, attr, now)
                        adsk.doEvents()
                    except Exception as e:
                        skipped.append(f'{comp} / {j.name}: not set back ({e})')
                if not samples or not any(samples):
                    continue
                unit = 'deg' if dof == 'rotation' else 'mm'
                show = (lambda v: math.degrees(v)) if dof == 'rotation' else (lambda v: v * 10)
                drives.append({'joint': j.name, 'kind': kind, 'component': comp, 'in': where,
                               'type': str(motion.jointType), 'dof': dof, 'unit': unit,
                               'values': [round(show(v), 4) for v in vals], 'rest': round(show(now), 4),
                               'samples': samples})
        progress.hide()
        dlg = ui.createFileDialog()
        dlg.title = 'Save the motion for the Limn guide'
        dlg.filter = 'JSON (*.json)'
        dlg.initialFilename = 'limn-motion.json'
        if dlg.showSave() != adsk.core.DialogResults.DialogOK:
            return
        with open(dlg.filename, 'w') as f:
            json.dump({'document': design.parentDocument.name, 'made': time.strftime('%Y-%m-%d %H:%M'),
                       'units': 'mm', 'matrix': 'row-major world', 'rest': rest, 'drives': drives,
                       'skipped': skipped}, f)
        ui.messageBox(f'{len(drives)} motions from {len(joints)} joints written to\n{dlg.filename}'
                      + (f'\n\n{len(skipped)} skipped (listed in the file)' if skipped else ''))
    except Exception:
        ui.messageBox('Limn motion failed:\n' + traceback.format_exc())
