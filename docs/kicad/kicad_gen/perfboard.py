# Limn KiCad generator - an empty board for a perfboard layout (docs/kicad/limn.kicad_pcb)
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# The layers and setup come from KiCad's own Arduino_Uno template (its parts and nets dropped). The
# perfboard is drawn as an outline (Edge.Cuts) and a dot per hole on Dwgs.User; the grid origin sits on
# the first hole, so on the 100 mil grid every grid point is a hole. Fill it with Update PCB from
# Schematic (F8); never regenerated over a layout (--force does not touch an existing board).
import uuid
from .core import parse, dump, Q

TEMPLATE = '/usr/share/kicad/template/Arduino_Uno/Arduino_Uno.kicad_pcb'
P = 2.54


def board(cols=38, rows=17, x0=50.8, y0=50.8, margin=3.81, title='Limn plot bed board (head cell): perfboard',
          holes=True):     # the user's board: 38 x 17 holes. holes=False: a plain outline (a real PCB), no hole dots
    t = parse(open(TEMPLATE).read())
    keep = [it for it in t[1:] if isinstance(it, list) and it[0] in ('version', 'generator', 'generator_version',
                                                                     'general', 'paper', 'layers', 'setup')]
    for it in keep:
        if it[0] == 'setup':
            it[:] = [x for x in it if not (isinstance(x, list) and x[0] in ('aux_axis_origin', 'grid_origin'))]
            it += [['aux_axis_origin', str(x0), str(y0)], ['grid_origin', str(x0), str(y0)]]
    note = 'Holes on Dwgs.User, 100 mil grid from the first hole. Update PCB from Schematic (F8).' if holes else \
        'A PCB: outline only; parts placed, not routed.'
    items = [['title_block', ['title', Q(title)], ['company', Q('limn')], ['comment', '1', Q(note)]],
             ['net', '0', Q('')]]
    w, h = (cols - 1) * P, (rows - 1) * P
    items.append(['gr_rect', ['start', f'{x0 - margin:.2f}', f'{y0 - margin:.2f}'],
                  ['end', f'{x0 + w + margin:.2f}', f'{y0 + h + margin:.2f}'],
                  ['stroke', ['width', '0.1'], ['type', 'solid']], ['fill', 'no'], ['layer', Q('Edge.Cuts')],
                  ['uuid', Q(str(uuid.uuid4()))]])
    for i in range(cols if holes else 0):
        for j in range(rows):
            x, y = round(x0 + i * P, 2), round(y0 + j * P, 2)
            items.append(['gr_circle', ['center', str(x), str(y)], ['end', str(round(x + 0.5, 2)), str(y)],
                          ['stroke', ['width', '0.1'], ['type', 'solid']], ['fill', 'no'], ['layer', Q('Dwgs.User')],
                          ['uuid', Q(str(uuid.uuid4()))]])
    if holes:
        items += strips(cols, rows, x0, y0)
    items.append(['gr_text', Q(f'perfboard {cols} x {rows} holes, 2.54 mm' if holes else f'{w + 2 * margin:.1f} x {h + 2 * margin:.1f} mm'), ['at', str(x0), f'{y0 - margin - 1.5:.2f}', '0'],
                  ['layer', Q('Dwgs.User')], ['uuid', Q(str(uuid.uuid4()))],
                  ['effects', ['font', ['size', '1', '1'], ['thickness', '0.15']], ['justify', 'left']]])
    return dump(['kicad_pcb'] + keep + items + [['embedded_fonts', 'no']]) + '\n'


def strips(cols=38, rows=17, x0=50.8, y0=50.8, group=3):
    '''The board\'s copper, drawn on Dwgs.User between the hole dots (the user\'s board, 2026-10-23): the top and
    bottom rows each one strip across, the rows between joined down each column in groups of 3 (17 rows: 5 groups).'''
    r, items = 0.5, []

    def line(a, b):
        items.append(['gr_line', ['start', str(round(a[0], 2)), str(round(a[1], 2))], ['end', str(round(b[0], 2)), str(round(b[1], 2))],
                      ['stroke', ['width', '0.3'], ['type', 'solid']], ['layer', Q('Dwgs.User')], ['uuid', Q(str(uuid.uuid4()))]])
    for j in (0, rows - 1):
        for i in range(cols - 1):
            x, y = x0 + i * P, y0 + j * P
            line((x + r, y), (x + P - r, y))
    for i in range(cols):
        for j in range(1, rows - 1):
            if (j - 1) % group != group - 1 and j + 1 < rows - 1:
                x, y = x0 + i * P, y0 + j * P
                line((x, y + r), (x, y + P - r))
    return items
