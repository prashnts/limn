# Limn plot - a poster: drawings bigger than the paper, plotted sheet by sheet
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# With job.poster on, the drawings are placed on a poster (mm, y up) instead of the bed. It is
# cut into sheets of the bed's paper (the draw area), portrait as it sits on the bed or
# landscape (turned a quarter): a grid from what is drawn's top left corner, each sheet sharing
# `overlap` mm with the next to line them up. Each sheet is the same job with every drawing's
# placement moved into that sheet's frame: emit clips it to the paper, and the slices (object
# mm) are the same for every sheet. The sheets plot one after another, SHEET_NEXT between them
# (the carriage empty: PLOT_END put the pen away; a new sheet on, then RESUME). Crop marks: short
# ticks at the paper's edge where neighbouring sheets are cut to be joined. Locked (Poster.locked),
# the grid stays where it is (Poster.origin, cols, rows) whatever the drawings do.
import math
from dataclasses import dataclass

import numpy as np

from .job import Placement

MARK = 3.0          # mm a crop mark goes in from the paper's edge


@dataclass
class Sheet:
    n: int                      # 1.. in reading order: the top row first, left to right
    col: int
    row: int                    # 0: the bottom row (poster y up)
    rect: tuple                 # on the poster: x0, y0, x1, y1
    cuts: list                  # [(axis 'x'|'y', where on the poster)]: lines it is cut along to join it

    def to_bed(self, machine, turned):
        '''Placement mapping poster mm onto the bed for this sheet: (rotate, x, y).'''
        dx0, dy0, dx1, _ = machine.draw_area
        if not turned:
            return 0.0, dx0 - self.rect[0], dy0 - self.rect[1]
        # landscape: the sheet's (u, v) from its bottom left go to (dx1 - v, dy0 + u) on the bed
        return 90.0, dx1 + self.rect[1], dy0 - self.rect[0]


@dataclass
class Layout:
    sheet_w: float              # a sheet on the poster
    sheet_h: float
    overlap: float
    cols: int
    rows: int
    origin: tuple               # the grid's bottom left, on the poster
    sheets: list
    content: tuple | None       # what is drawn, on the poster

    def dump(self):
        return {'sheet': [self.sheet_w, self.sheet_h], 'overlap': self.overlap, 'cols': self.cols, 'rows': self.rows,
                'origin': list(self.origin), 'content': list(self.content) if self.content else None,
                'sheets': [{'n': s.n, 'col': s.col, 'row': s.row, 'rect': list(s.rect), 'cuts': s.cuts} for s in self.sheets]}


def ink_box(d, scale):
    '''What of a drawing (svg.Drawing) is drawn, object mm (y up, scaled): its shapes, its
    pictures, its texts' anchors. Kept on the drawing (svg.load_cached keeps it while the file
    doesn't change). None: nothing.'''
    box = getattr(d, '_ink', False)
    if box is False:
        pts = [p[:, :2] for sh in d.shapes for p in sh.paths if len(p)]
        pts += [im.corners() for im in d.images]
        pts += [np.array([[t.x * t.matrix[0] + t.y * t.matrix[2] + t.matrix[4],
                           t.x * t.matrix[1] + t.y * t.matrix[3] + t.matrix[5]]]) for t in d.texts if t.fill or t.stroke]
        if pts:
            a = np.vstack(pts)
            h = d.size[1]
            box = (float(a[:, 0].min()), float(h - a[:, 1].max()), float(a[:, 0].max()), float(h - a[:, 1].min()))
        else:
            box = None
        d._ink = box
    return tuple(v * scale for v in box) if box else None


def placed_box(obj, box):
    '''An object's box (object mm) as it is placed: on the poster.'''
    x0, y0, x1, y1 = box
    pts = obj.placement.apply([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
    return float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max())


def layout(poster, machine, objects, boxes) -> Layout:
    '''The sheets: boxes {object id: its ink, object mm}.'''
    dx0, dy0, dx1, dy1 = machine.draw_area
    w, h = dx1 - dx0, dy1 - dy0
    if poster.sheet == 'landscape':
        w, h = h, w
    ov = max(0.0, min(poster.overlap, min(w, h) / 3))
    px, py = w - ov, h - ov
    placed = [placed_box(o, boxes[o.id]) for o in objects if boxes.get(o.id)]
    content = None
    if placed:
        content = (min(b[0] for b in placed), min(b[1] for b in placed), max(b[2] for b in placed), max(b[3] for b in placed))
    if poster.locked and poster.origin is not None and poster.cols and poster.rows:
        cols, rows, (gx, gy) = poster.cols, poster.rows, poster.origin
    else:
        cw, ch = (content[2] - content[0], content[3] - content[1]) if content else (w, h)
        cols = max(1, math.ceil((cw - ov) / px - 1e-9))
        rows = max(1, math.ceil((ch - ov) / py - 1e-9))
        gh = rows * py + ov
        # from what is drawn's top left: it starts on sheet 1's corner, the slack goes right and down
        left, top = (content[0], content[3]) if content else (0.0, h)
        gx, gy = math.floor(left * 1000) / 1000, math.ceil(top * 1000) / 1000 - gh      # outwards: round it all
    sheets = []
    for row in range(rows - 1, -1, -1):
        for col in range(cols):
            x0, y0 = gx + col * px, gy + row * py
            cuts = []
            if col > 0:
                cuts.append(('x', x0 + ov / 2))
            if col < cols - 1:
                cuts.append(('x', x0 + w - ov / 2))
            if row > 0:
                cuts.append(('y', y0 + ov / 2))
            if row < rows - 1:
                cuts.append(('y', y0 + h - ov / 2))
            sheets.append(Sheet(len(sheets) + 1, col, row, (x0, y0, x0 + w, y0 + h), cuts))
    return Layout(w, h, ov, cols, rows, (gx, gy), sheets, content)


def sheet_job(job, sheet, machine, turned, boxes):
    '''The job as this sheet plots it: the drawings on it, their placements moved onto the bed.'''
    r, tx, ty = sheet.to_bed(machine, turned)
    c, s = math.cos(math.radians(r)), math.sin(math.radians(r))
    x0, y0, x1, y1 = sheet.rect
    objs = []
    for o in job.objects:
        b = boxes.get(o.id)
        if b:
            bx0, by0, bx1, by1 = placed_box(o, b)
            if bx1 < x0 or bx0 > x1 or by1 < y0 or by0 > y1:
                continue                                # not on this sheet
        p = o.placement
        pl = Placement(x=c * p.x - s * p.y + tx, y=s * p.x + c * p.y + ty, rotate=p.rotate + r)
        objs.append(o.model_copy(update={'placement': pl}))
    j = job.model_copy(update={'objects': objs, 'poster': None})
    j._root = job.root
    return j


def marks(sheet, machine, turned):
    '''The sheet's crop marks, bed mm (n, 3): a tick in from the paper's edge at each end of each cut.'''
    r, tx, ty = sheet.to_bed(machine, turned)
    pl = Placement(x=tx, y=ty, rotate=r)
    x0, y0, x1, y1 = sheet.rect
    out = []
    for axis, v in sheet.cuts:
        if axis == 'x':
            ticks = [[(v, y0), (v, y0 + MARK)], [(v, y1), (v, y1 - MARK)]]
        else:
            ticks = [[(x0, v), (x0 + MARK, v)], [(x1, v), (x1 - MARK, v)]]
        for t in ticks:
            p = pl.apply(np.array(t, float))
            out.append(np.column_stack([p, np.zeros(len(p))]))
    return out


def to_poster(sheet, machine, turned, pts):
    '''Bed mm of this sheet (n, 2) back onto the poster.'''
    r, tx, ty = sheet.to_bed(machine, turned)
    return Placement(x=tx, y=ty, rotate=r).local(pts)
