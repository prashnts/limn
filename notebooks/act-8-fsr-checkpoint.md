# Automatic Tool Alignment - Part 6: A checkpoint, and why patching thresholds didn't work

2026-10-07 to 10-08. A long session on BED_5's FSR calibration: an old sheet with a glue void, a new sheet fitted mid-way, and a lot of fixes. Each fix made one failure go away and the next one turn up. This note stops that loop. It says what is actually wrong, looking at the whole machine and not only at the FSR code, what can be done instead, and what was undone. The handoff for whoever continues is at the end.

## What we're trying to measure

For each pen, where its tip sits against the reference pen's: dx, dy (to ~0.05 mm) and dz (where it first touches, to ~0.05 mm). These go onto its tag. The FSR (a 4 × 8 grid of 2.5 mm cells on BED_5) was meant to give all three:

- **Z**: jog down onto a cell until it reads a threshold (`respond`, 150): "contact".
- **XY**: binary searches across the border between two cells, a tap each step, a threshold deciding "still on cell A".
- **Where to start**: `locate()`, a rough guess of the tip from the first touch, so the measuring cell is hit.

Every step decides on **one reading against a fixed threshold**. That is the root of almost everything below.

## What went wrong, and why

### 1. The FSR's signal isn't what the thresholds assume

Measured on the plotter this session (depth ladders, scans, maps; data in `~/limn-shot/fsr-2026-10-07-manual.jsonl`, maps in `~/limn-shot/fsr-2026-10-07-new-sheet-map*.png`):

| Effect | Old sheet | New sheet |
|---|---|---|
| Response vs depth | 112 → 523 over 0.01 → 0.10 mm, saturates ~570, then falls | ~2× more sensitive: 304 at 0.02, 469 at 0.04 |
| Cell to cell gain | 2–3× ((2,4) never over ~220, (1,2) 600+) | not characterised yet |
| Within a cell | ±7–15 % per 0.2 mm (the electrode pattern) | not characterised |
| Up its column (crosstalk) | 0.94 of the pressed cell at first touch, 0.4 deeper | ~0.15 |
| Row 3 | lifts with every press in its column (~0.95) | answers when pressed, lifts ~0.35–0.7 with its column, 30–50 with the head merely above |
| Baseline | drifts by tens, per cell, minute to minute | same; (3,0) rests at 80–130 since the sheet was handled |
| Faults | cols 3, 4: a glue void; pressing col 5 lit them | col 0 answers for presses all along its row (a leak?) |

A fixed threshold on a single reading is then wrong in a different way at every cell, every depth and every minute. Each failure tonight was one of these effects crossing a threshold: a preload counted as a touch 4 mm up, crosstalk counted as the pressed cell, a weak cell never reaching the target, a faulty column passing for the strongest.

### 2. Z isn't where the commanded Z says (the whole machine)

- **The Z axis has play of a few mm** (GEOMETRY.md, *The Z axis and its play*). A press lifts the axis within its play, more far from the lead screw. "0.1 mm past contact" is a commanded number. The real press depends on where on the bed, how hard, and the history of the move.
- **Pen tips are compliant.** A felt tip squashes, and the contact came out 0.14 mm lower after a run of deeper taps. A fineliner registers only ~0.2 mm in.
- **"Contact" is a force threshold, not first touch** (act-7). It depends on the cell's gain and the tip's stiffness. Two pens measured on the same cell differ in dz partly by their tips, not their length.

So the FSR can't give a pen's dz to 0.05 mm by threshold-crossing on this axis, however carefully the thresholds are tuned. act-7 already found that **asking the paper** (the camera Z ladder) gives Z better. That still holds.

### 3. XY by binary search on a non-monotonic signal

A binary search assumes "cell A answers" flips exactly once between A's centre and B's. With ripple, crosstalk and drift it can flip several times. The search then lands on whichever flip it meets, which is why the Y edge spread 0.23 mm over three runs while X spread 0.05. `locate()`'s quick guess was 1–2 mm out several times for the same reason. The "re-aim" patched the consequence, not the cause.

### 4. Why not just sample more?

More samples of the same estimator would mostly **average a biased answer**. The dominant errors aren't random noise:
- gain differences between and within cells;
- crosstalk;
- the play;
- drift between minutes.

Repeating a threshold crossing ten times gives the same wrong crossing ten times, with a smaller spread. Repetition helps once the estimator itself is unbiased (see below), and then it's worth it.

### 5. How the session went wrong (process)

- **One heuristic per failure:** `early`, `wrong_depth`, faulty columns, aim moves, three spots, a re-aim, two-read confirmations, an in-air baseline, a row-median rise, refinements. Each was tested in a simulator that I then fitted to the last failure. The code grew; the reliability didn't.
- **The config flipped with each observation,** with the faulty columns and the dead row toggled back and forth.
- **Presses outside the active area, on purpose:** the map's 1 mm margin and hand scans from both sides, and searches two cells over. Outside the cells is laminate with the tail's traces. The first new-sheet map pressed along the strip beyond column 0; (3,0)'s preload appeared afterwards. The sheet was also handled in between, so the cause is unknown, but **don't press outside the cells**.

## What can be done instead

In order of what I'd expect to matter most.

1. **Z from the paper, not the FSR.** The camera ladder (act-7, `limn_cam ladder`) measures where ink first appears, which is what plotting needs. Use the FSR for XY only, or for relative Z between pens only at a *force* target (next item).
2. **Force-targeted touches, not position-targeted.** Come down slowly while the frames stream (20 Hz now), and stop when the pressed cell's **rise** reaches a target. Then every tap is "the same press" whatever the play, the tip or the sheet height. The Z stepping loop already reads after each step; make the stop a force target, with a slow continuous approach rather than 0.01–0.1 mm stairs.
3. **XY from ratios, fitted, not a threshold crossing.** Across the border between cells A and B, at a force target, tap at 10–20 points and take `r = a / (a + b)` of the baseline-subtracted readings. Fit a sigmoid; the border is where r = 0.5. Cell gains cancel to first order, ripple averages out in the fit, symmetric crosstalk drops out. Do it on 2 borders per axis, and coming from both sides. This is where repeated sampling pays off.
4. **Characterise each sheet once, then correct.** A map and survey per sheet (the tools exist: `LRT_FSR_MAP`, `LRT_FSR_SURVEY`), stored as per-cell gain plus a crosstalk matrix. A reading `s = G·p + C·p + baseline` can then be inverted for p instead of thresholded.
5. **Hardware first where it's cheap:**
   - a series resistor on row 3's line;
   - find column 0's leak on the new sheet's tail;
   - mount the sheet flat (no void, no bulge);
   - tighten the Z rails.

   The play is the biggest Z error source and no algorithm removes it.
6. **Keep presses inside the cells.** Maps and searches should stay at least a dead-zone's width inside the array's edge.
7. **Test against recorded data, not invented models.** Log raw frames of real runs and replay them as fixtures. The `bed5` / `fresh` simulator models were fitted after each failure. They show the code runs, not that it's right.

## What was undone, and what stays

**Undone** (2026-10-08, not committed):
- The last batch: config `dead_rows (3,)` / `faulty_cols (0,)`, the map skipping those lines, the narrower map window, the simulator's `new_sheet` mode and `fresh_cfg`.
- Commit `ab92e5f` (a rise judged against its row's median, to hide row 3's head pickup), reverted in the working tree.

**Stays (review these):**

| What | Commit(s) | My view |
|---|---|---|
| Taps capped at 0.1 mm, and fine steps once contact is known | `ee4d065`, `30fb357`, `4d80ccc` | Sound: gentle on the sheet. |
| The in-air baseline per descent | `d88b7c3`, `424b289` | Sound signal processing, but it changes what every threshold means: check it against item 2 above. |
| The calibration and meshes in saved variables | `5716335`, `e5dc446` | Unrelated to accuracy: fine. |
| Re-aim on a neighbouring cell, two-read confirmation | `2bed56a`, `06d3dc7` | Resilience patches; they'd be unnecessary with ratio-fitted XY. |
| Three-spot first descent, `wrong_depth` | `e5dc446`, `2366961` | Safety (dead zones, wrong cells): keep until the approach changes. |
| `LRT_FSR_SURVEY`, `LRT_FSR_MAP` with edge refinement | `2add3ca` … `424b289` | Tools to characterise a sheet. The map's 1 mm margin presses outside the cells: set `MARGIN=0` or remove it. |
| Console logging | | Fine. |

BED_5's config is neutral (no dead rows, no faulty columns, aim (1.5, 5.5), origin (111.0, 59.6)). The new sheet sits about 1 mm further +X and 0.15 mm +Y, and its origin isn't set yet.

## Handoff

**State:**
- The new FSR sheet is on BED_5 (fitted 2026-10-07 evening).
- The Stabilo "Test Blue" (stb-88) from holder 45 is on the carriage; the plotter is idle at Z5.
- No survey and no FSR calibration are saved (`lrt_fsr_survey` empty, `fsr_calibrated` false).
- Tags: holder 45 still has its old values (dx −2.54, dy −1.12, dz 0.24).
- The Pi runs commit `ab92e5f`. The working tree has `ab92e5f` reverted and staged, not committed: deploy it, or keep `ab92e5f`, as you decide.

**Data:**
- `~/limn-shot/fsr-2026-10-07-manual.jsonl`: every manual ladder, scan and map, raw cell readings per step.
- Scripts in the same folder: `fsr-2026-10-07-manual.py` (ladders, scans over Moonraker; its stop at a reading of 450), `-map-per-spot.py` (a map that finds touch at each spot), `-draw-map.py` (map JSON to PNG), `-run-cmd.py` (send a command, follow the console). They import each other by their short names: copy them into one folder as `fsr_manual.py`, `run_cmd.py` to run them.
- Maps: `~/limn-shot/fsr-2026-10-07-new-sheet-map.png` (light taps at one height, the layout visible); `-map-2.png` (one height after handling: the lower half untouched, the sheet isn't level).
- The last `LRT_FSR_MAP` (2026-10-08 00:05, console only; its files were lost when the refinement failed) showed all 8 columns about 2.5 mm apart, column 0 answering for presses along their row, and row 3 often strongest at light presses.

**Next, in order:**
1. **Hardware look:** the new sheet's tail at column 0, and (3,0)'s corner (preload 80–130). A series resistor for row 3 if the board allows.
2. **Decide the Z source:** the camera ladder (act-7) for dz, the FSR for dx, dy only. That removes most of the threshold fights.
3. **Rewrite the XY measurement** as ratio-fitted borders at a force target (items 2–3 above), with recorded real frames as test fixtures. Replace `locate()`'s single-crossing searches with the same fit on a coarse scale.
4. **Then** set the new sheet's origin (a map with `MARGIN=0`), survey, calibrate the reference (`LRT_CALIBRATE`, paper on the bed for the mark), and the pens.
5. **Ask the user before:** changing the plotter's code path (they deploy and restart it themselves), and any move outside the FSR cells.
