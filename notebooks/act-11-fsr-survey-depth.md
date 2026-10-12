# Act 11: the survey's tip, the sheet wiped for the BLTouch, the taps' depth per edge (2026-10-12)

Follows `act-10-fsr-loaded.md`. The survey pressed every cell on a corner; fixed (`c0a13c0`), the sheet surveyed again, a calibration and two measures. Then, in code and not deployed yet: `LRT_FSR_CLEAN` and a wipe before the BLTouch probes an inked sheet, the edges in turns (X, Y, X, Y), and each edge's own tap depth.

Data: `~/limn-shot/fsr-2026-10-12-survey-check.jsonl` (hand ladders, survey spot against the edges' spot).

## The survey pressed every cell on a corner

Two `LRT_FSR_SURVEY` runs read "nothing" on all 32 cells and saved them all as faulty. The user saw the pen stay on a border the whole grid, ~2-3 mm off in X.

- `survey()` took the tip as `_boundary(first edge) - mean(m['x'], m['y'])`. Since `1602049` those means average two *different* borders an axis (rows 1|2 and 2|3, cols 6|7 and 3|4), so it was off by half a pitch in X and 1.5 pitches in Y: (0.225, -1.698) for (1.475, 2.05). Every press was on the corner of four cells.
- It said "nothing" because it only counts the named cell's own rise: at a corner a neighbour rose instead ((0, 2)'s spot lit (0, 1) to 122, (1, 6)'s lit (1, 5) to ~90).
- Hand ladders at the edges' tip: (1, 6) 154 → 214, (3, 4) 194, (1, 3) 145, (2, 1) 111, (0, 2) 37 (with (3, 2) 62).
- Fix: `shift = m['tip']`, measure()'s own (`c0a13c0`, the user's commit). The tests passed before and after: the simulated survey never had two borders an axis.

### On the origin (the user's point)

The FSR alone can't tell the origin from the tip: an edge sweep finds where the tip crosses a border, origin + tip. 2 mm off in `origin` is 2 mm the other way in the reported tip, and nothing in the log shows it. What the edges do check: the cells by their electrical identity (no corner ambiguity), the pitch and numbering (two borders an axis agree), and that positions relative to the measured borders are right (an origin error cancels in the survey and in the pens' offsets). It matters for the absolute tip and locate's first guess. An inked picture of the sheet against its grid would pin it.

## The survey, fixed

`LRT_FSR_SURVEY` 13:16, the tip [1.406, 2.084]: 29 of 32 cells answer, median 134 at 0.08 mm.

- Faulty: (0, 2), (1, 1), (1, 2). The calibration's cells until 10-11, tapped most and often the whole 0.2 (the depth found on a border, act-10 *Next* 2): the pen dug in, the user thinks.
- Strongest at 0.08: (3, 7) 232, (1, 6) 229, (3, 5) 216, (2, 5) 193, (1, 7) 188, (2, 6) 182. The z cell and both edge pairs are on good cells.
- Weaker: row 0, (2, 0)-(2, 4) 60-104, (0, 5) flat at 74.
- First touch 3.634 along col 7, up to 3.69-3.80 at col 0 ((3, 0) 3.804): ~0.17 mm along Y.
- (3, 0) reads ~27 at rest, as before. The survey's aim: [1.94, 5.33].

## Calibration and two measures (13:4x, the deployed code: `c0a13c0`)

| | X (two edges' mean) | Y | contact z on (1, 6) | dz over the BLTouch |
|---|---|---|---|---|
| `LRT_CALIBRATE` | 115.809 | 43.707 (2nd edge a line over) | 3.621 | 0.650 (tag 0.35) |
| `LRT_FSR_MEASURE` | 115.809 | 43.759 | 3.623 | 0.651 |
| `LRT_FSR_MEASURE` | 115.809 | 43.784 | 3.628 | 0.656 |

- Locate with the survey's aim: [1.40, 2.07] against the edges' [1.39, 2.12]. The depth was found mid (1, 6): 0.04, 0.02, 0.02 mm.
- The reference's dz 0.35 (10-11: 0.32, contact 0.620 → 0.650). The BLTouch probed the sheet just after the survey, unwiped: ink holding the probe up would make dz *smaller*, so no sign of it here.
- **The (1, 6)|(1, 7) Y edge is the noisy one:** its gap 0.85-1.06 mm, its point 39.963, 40.044, 40.088 (0.125). (1, 3)|(1, 4): 47.450, 47.475, 47.481. A column border with a narrow gap instead ((2, 5)|(2, 6), (3, 4)|(3, 5)): check its gap first.
- **Stray taps on (2, 5)|(3, 5):** 1-2 on the wrong side in both measures, sigma 0.574 and 0.372, the point within 0.013 of the calibration's. X's sigma 0.29 and 0.19 against `max_sigma` 0.15: a pen measured so gets no tag. The calibration tapped 0.04 and had none, the measures 0.02: the depth found on the strongest cell is too shallow for the weaker edge cells.
- **The two X borders are 2.606 apart, not 2.5:** the tip 1.494 / 1.388 across them every run. Systematic, it cancels between pens; ~0.05 of X's sigma.
- The calibration's (1, 3)|(1, 4): its first line got 0 of 26 taps, found a line over (the sheet ~0.04 higher there than at (1, 6): taps in the air?). Not in the measures.

## Changes (uncommitted, to deploy)

1. **A wipe before the BLTouch probes an inked sheet** (the user's point: ink can hold the probe up). `LRT_FSR_CLEAN` parks and waits for a hand wipe (`wait_clean`). Meshing `lrt_fsr`, `LRT_CALIBRATE` and `_fsr_bed_z` ask first when a tool touched the sheet since the last wipe (`_fsr_last`); `CLEAN=0` skips. Unknown after a restart: nothing asked. Test: `test_an_inked_sheet_is_wiped_before_the_bltouch_probes_it`.
2. **Edges X, Y, X, Y:** each after the first goes by the tip the ones before found (both X edges on locate's Y missed their first lines, 10-11).
3. **Each edge's own depth:** the first X and Y tap at locate's depth; every edge after them finds its depth on the centres of its two cells as the tip now is, from each cell's own contact estimate, and takes the weaker cell's (the deeper). The depth on the z cell (or locate's spot) is gone. Weaker edge cells get enough press; strong ones no more than they need; a cell higher than the mesh says gets it from its own spot. ~4 short descents more a measurement. Test: `test_each_edge_finds_its_own_depth_once_the_tip_is_known`; `test_taps_press_only_as_deep_as_needed` now with two edges an axis. The models have no patchy cells: whether the strays go away is for the plotter to say.

## Next

1. Deploy; `LRT_FSR_CLEAN`, `LRT_CALIBRATE`, `LRT_FSR_MEASURE` ×2: the depth lines per edge, the (2, 5)|(3, 5) sigma, X's.
2. The pens: `LIMN_TOOL_CALIBRATE T=41..44`, the Micron 01 Blue first.
3. The Y edge (1, 6)|(1, 7): a narrower column border.
4. A stray tap's weight in `border()`'s sigma (each counts as far as it lies from t0): if strays stay with the per-edge depth.
5. BLTouch on (1, 6), inked against wiped, ~5 probes each: how much ink lifts it.
6. Wear-levelling (TODO.md), with each measurement's per-cell depths as a running survey.

## 2026-10-12 22:05: the Micron 005 swept beside the sheet

Two LRT_CALIBRATE runs with the Micron 005 Black (holder 45), both coming down at the aim X115.850 Y46.275 and touching (1, 4) and (3, 4) together. The first named (1, 4) (tip X −1.1) and passed (saved −1.08, 1.14). The second named (3, 4): tip X +3.9, two rows (5mm) out. Every line of the (1, 6)|(2, 6) sweep then started ~3.5mm outside the sheet (true tip X 107.3-110.8, the sheet begins at 111). 15 taps a line read nothing on any cell, and five lines were inked.

Cause: row 3 (no series resistor) reads 40-65 whenever its column is pressed (that night: (3, 6) 45-65 for (1, 6) at 22-312), about as much as a fine tip's own cell at 0.2mm. touched() only filtered crosstalk *after* the dominance test, and row 3 wasn't in crosstalk_rows, so which cell won was a coin toss.

Fix: `lifted_rows: (3,)` in beds.py. In touched(), a row-3 cell under `sure` drops out before dominance whenever another row of its column reads `level`. A real row-3 press keeps it: rows 0-2 lift ~0.15 of a press, under `early` until row 3 is past `sure`. Test: test_row_3_lifted_by_its_column_is_not_the_tip, a fine and a felt tip on (1, 4) and on row 3 (6 seeds each). It fails without the fix. The simulator now flags any press with the tip off the array (`off_sheet`).

### The check after locate, and the sweeps' margin (same night)

The user's idea: once locate has a cell, the tip is within that cell (±1.25mm), so check it before anything goes by it.

- `_check_cell()`: the candidates are the cells close to the strongest in locate's tap (`responds`; that includes row 3 when its lift is as strong). Along each axis where they differ, the toolhead steps one cell from the aim, in a direction that keeps the tip on the sheet whichever candidate it is on. Tonight's (1, 4)/(3, 4) gives one row towards row 0. The candidate whose predicted cell answers, clearly over the others, is the tip's cell. When none does, or no safe step exists: FsrError "stopped before the edges", with nothing pressed off the sheet. Along an axis where the candidates agree, the tap only confirms that the named cell's neighbour answers.
- `press_depth()` on "the strongest" skips lifted rows under `sure`: row 3's flat lift reached `locate_strength` at once and the taps came out shallow.
- `find_edge(unsure=...)`: until an edge has put the tip across an axis, the sweeps keep half a cell more clear of the sheet's end on it. Simulated at the survey's aim, the Micron's Y sweep on (1, 6)|(1, 7) otherwise pressed 0.19mm past col 7's end: locate's Y 2.07 against a true 1.14.
- Simulator: `crosstalk={'other': 0.15, 'lift': {3: 55}}`, row 3's flat lift as in tonight's sweeps. With `lifted_rows` off, locate still named (3, 4) in 2/20 runs, and the check moved both to (1, 4). The first X edge's tip came out −1.11 to −1.07 for −1.08, and nothing pressed off the sheet. Test: test_a_wrong_cell_from_locate_is_caught_on_the_sheet, which fails without the check and without the margin.
- Still off the sheet by design: a tool >3.75mm off (locate's first descent misses the sheet: tests `test_off_the_array_*`, `test_prior_z_*`) and LRT_FSR_MAP.
- Seen in the simulator only: the (2, 5)|(3, 5) X edge is pulled ~0.17mm by row 3's lift (b reads +55 whenever a is pressed). On the plotter the two X edges agreed (−1.075/−1.081), but it is the edge to watch.
