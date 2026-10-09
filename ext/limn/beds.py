# Limn - what is on each bed, and where
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# The Dock reads the bed id from its ID resistor (see micropython/lrt_dock_mcu.py).
# Coordinates are plotter coordinates in mm. Heights are raw machine z (no
# mesh applied), like the moves the routines make.

PANEL_ZHOME = 9     # travel height over the beds
PAPER_ZHOME = 6     # travel height over the paper

REFERENCE_TOOL = 45     # T4: the beds are calibrated with it, its tag says so (REFERENCE=1)

# No bed on the plotter: the whole bed, as [bed_mesh] in printer.cfg has it.
NO_BED_MESHES = [{'profile': 'default'}]

# Test marks (marks.py) stay inside the lrt_paper mesh, short of the tool holders
# and the tag reader, and are only drawn with offsets like these on the tag.
MARKS_MAX_X = 110
TOOL_MAX_DXY = 5            # mm, |dx| and |dy|
TOOL_DZ = (-0.5, 3.0)       # over the BLTouch z, the reference tool is ~1.0

BEDS = {
    # Resistive touch panel.
    'BED_3': {
        'sensor': 'rtp',
        'meshes': [
            {'origin': (5, 100), 'size': (110, 75), 'profile': 'lrt_paper', 'probe_count': '3,3'},
            {'origin': (25, 35), 'size': (60, 50), 'profile': 'lrt_panel', 'probe_count': '3,3'},
        ],
        # Centres of the + of the test marks, row by row; `arm`: length of each line.
        'marks': {'nx': 6, 'ny': 3, 'xrange': (20, 100), 'yrange': (120, 150), 'arm': 4},
        'rtp': {
            'z_park': PANEL_ZHOME,
            # Reference grid, probed with the BLTouch and with the reference tool.
            'grid': {'nx': 4, 'ny': 3, 'xrange': (30, 90), 'yrange': (42, 65)},
            'paper_grid': {'nx': 4, 'ny': 4, 'xrange': (30, 90), 'yrange': (110, 160), 'z_park': PAPER_ZHOME},
            # Three points for the raw -> plotter transform (Atmel AVR341).
            'touch_points': [(100, 52), (65, 40), (25, 70)],
            'touch_samples': 4,     # probes per touch point
            'ref_samples': 2,       # accepted probes per grid point, reference tool
            'tool_samples': 3,      # accepted probes per grid point, other tools
            'max_spread': 5,        # mm, readings of one probe further apart are retried
            'tool_points': 12,      # grid points probed for a tool, in random order
        },
    },

    # One FSR array, on the chain Dock -> hop 1.
    'BED_5': {
        'sensor': 'fsr',
        'meshes': [
            # Not to y 59: the sheet's edge (the array ends at 59.6), its row probed 0.2mm
            # under the rest while the pen found the sheet flat there to 0.02, and the taps
            # that follow the mesh went 0.07 out around col 1 (2026-10-07)
            {'origin': (111, 40), 'size': (7.5, 17), 'profile': 'lrt_fsr', 'probe_count': '4,5'},
            {'origin': (0, 30), 'size': (93, 130), 'profile': 'lrt_paper', 'probe_count': '4,6'},
        ],
        'marks': {'nx': 5, 'ny': 3, 'xrange': (15, 80), 'yrange': (120, 150), 'arm': 4},
        'fsr': {
            'z_park': PANEL_ZHOME,
            # origin: outer corner of cell (row 0, col 0); col_dir / row_dir:
            # plotter direction of increasing col / row. Check with LRT_FSR_Z
            # that the cell you aim at is the one that lights up. Mapped with
            # light presses on 2026-09-28 (the cols run towards -Y), to ~0.5mm.
            # dead_rows: rows never read. None: on the new sheet (2026-10-07) row 3 answers
            # like the others (230-490 pressed), it only lifts more with presses up its column
            # (~0.35 of them, rows 0-2 ~0.15) and reads 30-50 with the pen over the sheet. On
            # the old sheet it lifted to ~500 with any press in its column: dead then.
            # The new sheet sits ~1mm further +X and ~0.15mm +Y than `origin` (a light-tap map,
            # ~/limn-shot/fsr-2026-10-07-new-sheet-map.png); its columns 4-7 didn't answer
            # (presses there read as (3, 0)): its ribbon, to check before the origin is set.
            # faulty_cols: columns never read, like the dead rows. None on a fresh sheet:
            # after a swap LRT_FSR_SURVEY finds the faulty cells of this one (and the aim).
            # The sheet before (2026-09 to 10-07, a glue void from its transfer) had cols 3
            # and 4 faulty and its aim at col 6.3: the tests keep it as OLD_SHEET.
            # crosstalk_rows: a press in a column lifts row 0 too, less; with a
            # fine tip split on an edge, as much as the pressed cells (fsr.py, touched).
            # aim: (row, col), in cells from the origin, where the tip first
            # comes down (fsr.py, locate). Mid cell, so a tool that is about
            # right lands clear of the dead zones. A tool whose tip is further
            # off than the array reaches from there is not found: here -3.75..
            # +3.75mm in X (rows 0-2), -6.25..+13.75mm in Y (8 cols). This machine's pens
            # (tips ~2mm off in X and Y) come down around (2, 4). A survey moves it onto a good
            # cell of the sheet there is (judge_survey).
            'arrays': [
                {'hop': 1, 'origin': (111.0, 59.6), 'col_dir': (0, -1), 'row_dir': (1, 0), 'aim': (1.5, 5.5),
                 'dead_rows': (), 'faulty_cols': (), 'crosstalk_rows': (0,)},
            ],
            'pitch': 2.5,
            # z and the edges on cells 1-2: clear of the array's sides (a survey warns when
            # one of them is weak or faulty on the sheet there is)
            'z_cell': (1, 1, 1),                # hop, row, col used for z
            # hop, (row, col) of a cell, (row, col) of its neighbour. The rows
            # run along X here: an edge between rows gives X, between cols Y.
            'x_edges': [(1, (1, 1), (2, 1))],
            'y_edges': [(1, (1, 1), (1, 2))],
            # Where a tool can touch, over the BLTouch z (like DZ on the tool
            # tags; the reference tool is ~1.0). The jog starts above the top
            # and never goes below the bottom.
            'tool_z': (-0.5, 3.0),
            'step': 0.1,            # mm, coarse z steps: a step can go this far past contact before it is seen
            'confirm': 2,           # fine steps on past a touch: it must grow there, or it was a reading in the air
            'back_off': 0.4,        # mm up after finding contact: clear of it, a tip on an edge registers ~0.2 deep
            'fine_step': 0.02,      # mm, fine z steps
            'settle': 0.08,         # s, after a move before reading (one FSR frame + the link)
            'alive': 0.25,          # s, no frame from the array for this long: stop
            'respond': 150,         # strength (0..1000) that counts as touched
            'early': 60,            # coarse descents stop at this, then fine steps to `respond`: the sheet
                                    # reads <=6 at rest, col 4 ~24 (LRT_FSR_MATRIX, 2026-10-07)
            # A press lifts the other rows of its column too, row 3 (no series
            # resistor on its ADC line) to ~530 while the pressed cell is ~880:
            # A press also lifts the rest of its row: with a fine tip pressing weakly
            # (a Micron on (1,5) at 355) (1,3) read 259, 0.73 of it, 2026-09-29.
            'dominance': 0.9,       # a cell responds only this close to the strongest
            'sure': 450,            # another cell this strong: the tip is there, not crosstalk
            'press_limit': 950,     # strength that means pressing too hard: lift now
            # The XY taps press past contact until the cell reads press_strength,
            # `press` mm at most (fsr.py, press_depth): a felt tip ~0.05mm, a fine
            # one up to 0.3. Deeper only adds force, and 0.3mm taps with a Stabilo
            # (~670) left marks on the sheet, 2026-09-29.
            'press_strength': 450,
            'locate_strength': 180, # locate's taps: enough to tell the cell (a weak cell, (2, 4): ~220 at most)
            'identify': 0.06,       # mm past contact at least for locate's tap: past the first-touch crosstalk
            'press': 0.3,           # mm below contact for the XY taps, at most, when nothing else says
                                    # (ext/limn: the pen's own press, pens.toml; PRESS=)
            'prior_margin': 0.4,    # mm below an expected contact z the search may go
            # The taps follow the sheet with this mesh (the moves are raw, no mesh):
            # it drops ~0.05mm per mm towards -Y, a fine tip lost 0.25 of its 0.3mm
            # press over a 5mm search on 2026-09-28.
            'surface_mesh': 'lrt_fsr',
            # Between two pens the sheet is wiped (fsr.py, wait_clean): the carried
            # pen parks at `park`, over the paper and clear of the holders, until
            # presses on `wipe_cells` cells are seen and then `quiet` s without any.
            'clean': {'park': (60, 100), 'wipe_cells': 3, 'quiet': 2.0, 'timeout': 600},
            # The edges: taps `sweep[0]` apart over three cells' width, then `sweep[1]` apart
            # within `sweep[2]` of the border they show (fsr.py, find_edge and border)
            'sweep': (0.25, 0.05, 0.4),     # (0.5, ...): ~30 taps a pen fewer, less sure on a patchy sheet
            'off_cell': 0.02,       # mm less sure of a contact z another cell answered first for
            'max_sigma': 0.15,      # mm: a pen measured less sure than this gets no tag (probe_tool)
            'repeats': 3,           # z measurements, median
        },
    },
}
