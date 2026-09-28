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
            {'origin': (108, 36), 'size': (10, 20), 'profile': 'lrt_fsr', 'probe_count': '4,5'},
            {'origin': (0, 30), 'size': (93, 130), 'profile': 'lrt_paper', 'probe_count': '4,6'},
        ],
        'marks': {'nx': 5, 'ny': 3, 'xrange': (15, 80), 'yrange': (120, 150), 'arm': 4},
        'fsr': {
            'z_park': PANEL_ZHOME,
            # origin: outer corner of cell (row 0, col 0); col_dir / row_dir:
            # plotter direction of increasing col / row. Check with LRT_FSR_Z
            # that the cell you aim at is the one that lights up.
            # aim: (row, col), in cells from the origin, where the tip first
            # comes down (fsr.py, locate). Mid cell, so a tool that is about
            # right lands clear of the dead zones. A tool whose tip is further
            # off than the array reaches from there is not found: here -3.75..
            # +6.25mm in X (4 rows), -8.75..+11.25mm in Y (8 cols).
            'arrays': [
                {'hop': 1, 'origin': (108, 36), 'col_dir': (0, 1), 'row_dir': (1, 0), 'aim': (1.5, 3.5)},
            ],
            'pitch': 2.5,
            'z_cell': (1, 1, 3),                # hop, row, col used for z
            # hop, (row, col) of a cell, (row, col) of its neighbour. The rows
            # run along X here: an edge between rows gives X, between cols Y.
            'x_edges': [(1, (1, 3), (2, 3))],
            'y_edges': [(1, (1, 3), (1, 4))],
            # Where a tool can touch, over the BLTouch z (like DZ on the tool
            # tags; the reference tool is ~1.0). The jog starts above the top
            # and never goes below the bottom.
            'tool_z': (-0.5, 3.0),
            'step': 0.2,            # mm, coarse z steps
            'fine_step': 0.02,      # mm, fine z steps
            'settle': 0.08,         # s, after a move before reading (one FSR frame + the link)
            'alive': 0.25,          # s, no frame from the array for this long: stop
            'respond': 150,         # strength (0..1000) that counts as touched
            'press_limit': 950,     # strength that means pressing too hard: lift now
            'press': 0.3,           # mm below contact for the XY taps
            'resolution': 0.02,     # mm, edge search stops here
            'repeats': 3,           # z measurements, median
        },
    },
}
