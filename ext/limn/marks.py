# Limn - the test marks on the paper, after a tool is calibrated
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Each mark is two corners (geometry.mark_strokes): └ where the previous tool
# left its ┐, which makes a +, and ┐ at the next point, for the next tool. Two
# pens that disagree show it in the +: a step in its vertical line is X, a step
# in its horizontal line Y.
#
# The pen travels raw at PANEL_ZHOME, over the beds, and only comes down over
# the mark, with the tool's offsets and the lrt_paper mesh applied: Z1 to draw,
# Z2.5 between the strokes (all on the paper), and Z7 before it leaves the paper.
# Off the paper it is never under Z5 (safe_z of plot/profiles/limn.toml). The
# caller checks the mesh is of this bed; problems() the rest.
#
# The wipe area (beds.py `wipe`) is drawn the same way: a pen primed there before
# it plots, the test mark of a pen probed mid-plot (wipe_problems()).
from .beds import PANEL_ZHOME, MARKS_MAX_X, TOOL_MAX_DXY, TOOL_DZ

DRAW_FEED = 2000
PEN_Z = 1.0             # drawing, as plot's pens (z_down)
HOP_Z = 2.5             # between the strokes, over the paper (plot's z_travel)
LEAVE_Z = 7.0           # before leaving the paper: over Z5


def problems(strokes, offsets, bounds):
    '''Why these strokes can't be drawn with a tool of `offsets` (dx, dy, dz) on
    a paper mesh of `bounds` ((min_x, min_y), (max_x, max_y)); [] when they can.'''
    dx, dy, dz = offsets
    why = []
    if abs(dx) > TOOL_MAX_DXY or abs(dy) > TOOL_MAX_DXY:
        why.append(f"the tool's offsets dx={dx} dy={dy} are over {TOOL_MAX_DXY}mm")
    if not TOOL_DZ[0] <= dz <= TOOL_DZ[1]:
        why.append(f"the tool's dz={dz} is outside {TOOL_DZ}")
    (x0, y0), (x1, y1) = bounds
    for x, y in (p for stroke in strokes for p in stroke):
        # Where the carriage travels to (raw), and where the pen draws
        for px, py in ((x, y), (x + dx, y + dy)):
            if not (x0 <= px <= x1 and y0 <= py <= y1) or px > MARKS_MAX_X:
                why.append(f"({px:.1f}, {py:.1f}) is off the paper mesh or past X{MARKS_MAX_X}")
                return why
    return why


def wipe_problems(strokes, offsets, rect, mesh):
    '''Why these strokes can't be drawn in the wipe area `rect` ((x0, y0), (x1, y1)) with a
    tool of `offsets`; mesh: the bounds of lrt_paper, whose heights it is drawn with (None:
    there is none). [] when they can.'''
    dx, dy, dz = offsets
    why = []
    if mesh is None:
        why.append("there is no lrt_paper mesh to draw it with")
    if abs(dx) > TOOL_MAX_DXY or abs(dy) > TOOL_MAX_DXY:
        why.append(f"the tool's offsets dx={dx} dy={dy} are over {TOOL_MAX_DXY}mm")
    if not TOOL_DZ[0] <= dz <= TOOL_DZ[1]:
        why.append(f"the tool's dz={dz} is outside {TOOL_DZ}")
    (x0, y0), (x1, y1) = rect
    for x, y in (p for stroke in strokes for p in stroke):
        if not (x0 <= x <= x1 and y0 <= y <= y1):
            why.append(f"({x:.1f}, {y:.1f}) is off the wipe area")
            return why
        if max(x, x + dx) > MARKS_MAX_X:
            why.append(f"({x:.1f}, {y:.1f}) with dx={dx} is past X{MARKS_MAX_X}, in the holders' way")
            return why
    return why


def draw(machine, strokes):
    run = machine.gcode_run
    x, y = strokes[0][0]
    machine.move(z=max(machine.position()[2], PANEL_ZHOME))
    machine.move(x=x)                   # away from the holders and the tag reader first
    machine.move(y=y)
    run("_APPLY_OFFSETS MESH=lrt_paper")
    run(f"G1 F{DRAW_FEED}")
    for stroke in strokes:
        (sx, sy), rest = stroke[0], stroke[1:]
        run(f"G1 X{sx} Y{sy}")
        run(f"G1 Z{PEN_Z}")
        for px, py in rest:
            run(f"G1 X{px} Y{py}")
        run(f"G1 Z{HOP_Z}")
    run(f"G1 Z{LEAVE_Z}")
    run("_CLEAR_OFFSETS")
