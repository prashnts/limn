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

### 22:36 deploy: the Blue refused, the (2, 5)|(3, 5) edge unsure

With 84d6dd0 on the plotter, locate was right for the Micron 01 Blue. Its tip is ~+3.1 in X (tag dx −4.36 against the reference's −1.08; edge tips 3.22 and 3.00), so it lands on row 3, and (3, 4) was its cell. LIMN_TOOL_CALIBRATE refused the tag instead: dx ±0.327, all of it from (2, 5)|(3, 5) at ±0.41, "1 on the wrong side". The Micron 005 reference just before had the same edge at ±0.426 (reference X ±0.23).

From the verbose taps of the reference's sweep: at toolhead X117.194 the tip sat on the (1, 5)|(2, 5) border, with (1, 5)=22 and (2, 5)=6. (3, 5)'s lift of 62 led them both, and a + b = 68 just passed the vote floor of 67.8. That was a vote for (3, 5)'s side 2.3mm from the border, and the one wrong vote set sigma.

Fix: `judge_taps()` (fsr.py, used by find_edge). A row-3 cell on an edge is judged less its lift (its median on the taps where its column partner is the pressed cell, ~43-46 here) only for "is the tip on a or b, or on a third cell". Its share of a + b stays as read. Replayed on the logged taps:
- as before: X119.556 ±0.002 and X119.525 ±0.426 (1 wrong)
- share less the lift too: X119.834 and X120.031: the border moved and the runs went 0.2 apart (rejected)
- third-cell test less the lift (kept): X119.556 ±0.002 and X119.525 ±0.002, 0 wrong

Test: test_row_3_lift_doesnt_vote_on_its_edge, on the plotter's taps (tests/fsr-2026-10-12-row3-edge.json).

Still to watch: the two X edges differ by ~0.2mm on every pen ((1, 6)|(2, 6) against (2, 5)|(3, 5): −1.194/−1.025 for the reference, 3.219/2.998 for the Blue). It's the same on both, so it cancels in dx, but it's either the sheet's geometry or row 3's lift.
The Blue's first try, as tool 0 (its tag not read), found no contact down to z=2.35.

### 23:21: the Blue refused again; the check stopped the reference

- The Blue: all four edges clean (±0.001-0.011) with the edge fix. Refused at dx ±0.256: the reference's stale ±0.23, plus its own two X edges 0.23 apart.
- The reference: the check stopped a right locate. A row over, (2, 4) (a weak cell) read 16 at locate's depth, under `early`.

Changes (the user's go, 23:30):
1. The check presses a row over until one of the predicted cells reads `locate_strength`, a fine step short of the cap (`_press_until_answered`). It answers if it rose `early`, or if it leads the cells pressed (a lifted row's lift excluded). The test now forces locate's mistake (names (3, 4)) on the real config.
2. Random borders (`pick_edges`, cfg `edges: (4, 3)`). The reference measures 4 an axis at random, each kept in fsr_ref['edges']. A pen measures 3 an axis of the reference's, and dx/dy are border by border, the uncertainty being their spread (`probe_tool`). The first border of an axis is interior (off the outer rows and cols). Weak cells from a survey are excluded (`weak_cells`). The old sheet models keep the fixed borders (`edges: None`). Simulated: 25 references × 2 pens, all 50 probed, none off the sheet, worst error 0.11mm.

Replay of tonight's borders (reference 22:36 runs A/B, Blue 22:36/23:21):
- each border repeats per pen: reference X 0.03/0.03, Y 0.035/0.003; Blue X 0.05/0.06, Y 0/0.07
- dy border by border: −0.782, −0.869: the sheet's own irregularity cancels
- dx border by border: −4.366 ((1, 6)|(2, 6)), −3.966 ((2, 5)|(3, 5)): 0.40 apart, so it would still be refused (±0.2)
- the two X borders in toolhead X: reference 2.33 apart, Blue 2.73: pen-dependent
- lead: depth. Since 55c6a2c the first X edge taps at locate's depth (0.12-0.20) and the second at its own (0.02-0.04). In the one Micron run with every edge at 0.20 (before 55c6a2c), the X tips agreed to 0.006. A pen pressed deeper slides sideways by its own amount (nib compliance, tilt).

## 2026-10-13: write rough tags, Z on several cells (not deployed yet)

The user: a pen corrected from ~3mm to ~0.3 should be stored, not refused. Changes:
1. `probe_tool` writes the tag whatever its sigma (over `max_sigma` it says "rough"). It stops only when one axis' borders are half a cell or more apart (`np.ptp(d) >= pitch/2`): a wrong cell, not noise. Last night's Blue (dx −4.366 / −3.966) would have been written as ≈−4.17.
2. A pen measures all 4 of the reference's borders an axis (`edges: (4, 4)`).
3. `measure()` takes contact z on every BLTouch'd cell of the hop ((1, 6), (2, 5), (1, 3)), not on the z cell alone: `above` is their median over the BLTouch, sigma from their spread. dz (reference and pens) is from `above`. ~6 fine descents more per measurement. `m['z']` is still the z cell's.
Test: test_an_unsure_pen_is_written_a_cell_off_is_not.
Test plan: one LRT_CALIBRATE with the Micron 005 (the new reference, its `above`), then LIMN_TOOL_CALIBRATE with the Micron 01 Blue. This also runs last night's untested changes (`_check_cell`, `judge_taps`, random borders).

## 2026-10-13 11:3x: the calibration stopped; the survey; the stowed BLTouch pin

- LRT_CALIBRATE (Micron 005) stopped in `_check_cell`: locate named (3, 4), a row over (0, 4)=210 answered, so the tip was on (1, 4). The old survey's aim (toolhead row 1.94, col 5.33) put this pen's tip (−1.24, 0.93) on the (1, 4)|(1, 5) border, and (1, 5) now reads 32 at 0.08: the user's guess (a stale survey) holds. The check could have named (1, 4) from the cell that answered (answered − step) instead of stopping: not done yet.
- Survey 11:48 (the 005): median 158 at 0.08 (134 on 10-12), rest 0 on every cell, (0, 2), (1, 1), (1, 2) answer again. Faulty (1, 3), (1, 5), (1, 7), (2, 5), (2, 6), (3, 5), but (1, 3), (1, 7), (2, 5), (2, 6) only because col 0 of their row answered ((1, 0) 86-110 on row-1 presses): col 0 lifts with its row, as row 3 with its column. Real: (3, 5) nothing, (1, 5) 32. Its aim (3.99, 3.87) puts the 005 on (3, 3), the outer row: a pen ~4mm +X (the Blue) would come down off the sheet. Not to calibrate with as is.
- Tag dz 2.17 matches: contact over the BLTouch 2.486 (cells 2.427, 2.534, 2.486) less the 0.3 trim.
- Stowed BLTouch pin (no tool, ~/limn-shot/bltouch-2026-10-13-ladder.py, .jsonl): nominal (2, 1) via the probe offsets, (2, 0) answered (350 vs (2, 1) ~50 at +0.12): the pin sits ~+1.5-3.5 Y of the offset, or it's col 0's lift. Contact z −2.380 on all 3 runs (machine Z min −3; deployed trigger ~2.87). QUERY_PROBE stays "open": the push isn't seen. Readings rose run over run (+0.02: 117, 156, 183; +0.12: 314, 349, 358), and taps 0.06 and 0.02 deep read 439 and 413: stopped there, the pin to be looked at by the user.

## 2026-10-13 afternoon: locate finds the tip's cell by the taps around it (not deployed)

The user's direction: keep the aim off the outer rows; locate says where the tip lands, then correct the position to a safe spot, re-locate, and only then the edges; taps that cover more cells, diagonally too; the activation signals and cell positions as locators ("triplets of cells pointing to another"); move a bit when the first contact is on a weak cell. T4 (Micron 005, holder 45) stays the reference; the BLTouch pin idea is parked.

1. **Col 0 lifted** (`lifted_cols: (0,)`), like row 3: `lifted_by()`, `unlifted()`, `touched()`, `press_depth`, `judge_taps` (a lifted partner is no third cell under `sure`), and the survey (a cell lifted by the pressed one doesn't "answer" for it: (1, 3), (1, 7), (2, 5), (2, 6) were faulty for that alone).
2. **The survey's aim on inner cells only** (rows 1..2, cols 1..6). Today's numbers: aim (1.99, 4.87) instead of (3.99, 3.87); the Blue (+4.4 X) lands on the sheet.
3. **`_find_cell` replaces `_check_cell`.** Every cell the tip could be on predicts the cell a tap `o` over answers (cell + o); the answer points back at the tip's cell. Taps only where every possible cell's prediction is read (and on the sheet), rather not on lifted lines, weak or outer cells; diagonal first; ties at random (wear). An answer nobody predicted names the cell (answer − o), and another tap must agree. Done when one cell is left and a tap put the tip on an inner cell and was answered there.
   - **Lifts as locators:** row 3 rises only with presses up its own column, col 0 only along its own row: with no real answer, (3, c) and (r, 0) point at (r, c), even a cell reading nothing; one lift alone narrows to a row or column. A named cell that is only a lifted line's lift makes the whole line possible.
   - **A quarter cell on:** when the first contact is unsure (a weak cell, a lift, under half of locate_strength) or two taps go unanswered: a quarter cell diagonally towards the middle, then the other quarter from where it came down. Of three spots a quarter apart at most one is in a dead zone (half a cell had moved the other axis onto its border).
4. `measure()` takes an inner border first per axis (the config's (1, 6)|(1, 7) first was too short a sweep on col 7 with the tip known to half a cell).

Simulated on today's sheet (row 3 flat 55, col 0 flat 80, weak (1, 5) 0.15, (2, 5) 0.3, (2, 6) 0.4, (3, 4) 0.4, (1, 6) 0.5, (3, 5) unread; aim (1.99, 4.87); 103 tips from −2.5..3.5 X, −2.5..2.5 Y, fine and felt): 187 right, 0 wrong, 0 presses beside the sheet, 19 stopped, all landing on (3, 5), (1, 5), (2, 5) or (3, 4). Script: scratchpad locate_sweep.py (not kept). Tests: test_a_tip_beside_a_dead_cell_is_found_by_the_taps_around_it (this morning's case, 16 locates + 3 calibrations), test_col_0_lifted_along_its_row_is_not_the_tip, test_the_survey_aims_off_the_outer_rows_and_cols.

To run: deploy, **LRT_FSR_SURVEY again** (the saved one has the old aim on row 3 and the col-0 "faulty" cells), then LRT_CALIBRATE with the 005, then the Blue.

### 2026-10-13 ~13:00: the survey of 12:42, and locate's reach

Survey 12:42 (new code): faulty only (0, 5) (nothing), weak (2, 4) (76), median 153 at 0.08, rest 0; col 0's lift no longer makes cells faulty. Contact over the BLTouch 2.482 (2.486 at 11:41). Its aim [2.94, 6.03] put the 005 on (2, 5): inner, but the Blue (+4.4 X, an offset the user set on purpose to test this) would land at row 4.3. The user: locate should cope with that itself, trying other spots at the same z; a gentle touch beside the sheet is fine.

- **Locate's reach** (`locate_reach: (1.5, -1.5)` rows, `reach_after: 0.3`): once the aim's spots have gone 0.3mm past where the reference touched (`ref_above`, set by probe_tool) with no answer, it also comes down 1.5 rows either way (each as the aim and its (1/4, 1/2) spot), by turns at the same z. Not from the start: a far spot answering first (slope, a dead row's crosstalk) took locate off the aim in 7 tests. The reference's own calibration has no reach.
- **The survey's aim**: side neighbours of a faulty cell only (the diagonal (0, 5) pushed it from (1, 4) to (2, 5)). The 12:42 numbers now give [1.94, 5.03], the 005 mid (1, 4).
- **Random borders off lifted lines** (row 3, col 0): (0, 0)|(0, 1) stopped 4 of 20 simulated Blue runs.
- **A line with most taps unanswered presses 0.04 deeper on the next** (the cap less a fine step at most): the 12:10 calibration (old aim, tip on (3, 3), locate's depth 0.06) got 0-4 of 29 taps on (1, 2)|(2, 2) on five lines. A fixed 0.12 for the first edges broke the press limits for felt tips (5 tests).

Simulated: a Blue-like pen (tip 4.4 +X, 0.88 −Y of the reference, shorter by 0.3) after a reference calibration, on today's sheet model: 30/30 right at the saved aim [2.94, 6.03] and at [1.94, 5.03]. The 206-locate sweep unchanged (187 right, 0 wrong, 0 beside the sheet). 175 tests pass.
To run: deploy, LRT_FSR_SURVEY (the aim moves to row 1), LRT_CALIBRATE (005), then the Blue.
