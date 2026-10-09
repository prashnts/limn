# Automatic Tool Alignment - Part 7: Is it the sheet, or the code?

2026-10-09. After act-8, the question was whether BED_5's FSR can work with the calibration at all, faults and all, or whether the code is what fails. I went back to the readings recorded on 2026-10-07 (`~/limn-shot/fsr-2026-10-07-manual.jsonl`) and asked them directly. The short answer: mostly the code. The sheet answers some questions well and one badly, and the code was built on the bad one. This part covers the evidence, the rework, and what's still open.

## What the sheet answers well

| Question | Evidence (manual.jsonl) | Answer |
|---|---|---|
| Same spot, same press, again? | #12–17: 552, 522, 516, 518, 510, 509 | ±2% after the first tap |
| Deeper is more? | every ladder (#0, #21–26, #29, #32) | always, monotonic |
| Where does it first touch? | #2–6, five offsets across (1, 1) | z 3.46–3.48: ±0.01 mm |
| Which column is the tip in? | #27, a walk along Y: cols 4 → 5 → 6 | right every time |
| Where is a row border? | #30, a walk along X, every 0.5 mm | three borders, exactly 2.50 mm apart |

## What it answers badly

**Which cell of a row or a column is pressed**, from one reading:

- **Crosstalk:** up the column, row 3 the worst on both sheets; at first touch, 0.95 of the pressed cell.
- **Patchiness:** one scan (#1) read (1, 1) at 485, 208, 427, 632, 322, 784, 0.2 mm apart at one z. At its weak spots row 3's crosstalk beat it (208 against 445).
- **The new sheet's column 0:** it reads 350–550 at the middle of other cells of row 1 (#30, the Y walk).

## What the code asked

Every decision was one reading of one cell against a fixed threshold. A cell counted as "responding" when it read over 150 and over 0.9 of the strongest of all 32 cells.

- Contact z needed *the aimed cell* to win.
- The edges were binary searches on that test.
- `locate` bounded the tip by where the cell stopped winning.

On this sheet the winner changes every 0.2 mm, so each search went wherever its first unlucky reading sent it. Each failure then got a heuristic (`wrong_depth`, re-aiming, two-read confirmations, and my retry from earlier today), and all of them treated symptoms.

## The rework (ext/limn/fsr.py)

1. **Contact is the sheet rising under the tip, whichever cell.** Any cell rising `early` (60) over the reading in the air counts. It must still be rising two fine steps deeper; a reading in the air doesn't, a press always does. The z is interpolated between the step before and the first over. `respond` (150) was the wrong level: a weak cell crosses it ~0.07 mm past first touch and a strong one ~0.015, while 60 is ~0.01 on both. The "another cell responds" stops are gone (`WrongCell`, `OtherCell`, `wrong_depth`, the retry): the tip touched either way. A contact another cell answered first for is reported less sure (`off_cell`, +0.02).
2. **Edges are taps across the border, judged by share.** A tap votes on which side it is from b / (a + b), the two cells of the edge only. The border is the split with the fewest taps on the wrong side (`border()`). Ripple, cell gain and symmetric crosstalk move both cells together; their share moves much less. A stray tap is one vote, not a search sent the wrong way. A tap doesn't vote:
   - in the dead zone (a + b too small);
   - when a third cell is the strongest (the tip isn't on a or b);
   - when a and b are within 10% of each other: a pressed cell that isn't read lifts them evenly, a coin toss.

   Taps go 0.25 mm apart over a cell and a half either side, then 0.05 mm apart over the border, then two taps narrowing each end of the dead zone (~100 taps a pen). They never go beyond the array, nor onto dead rows or faulty columns. Each edge comes with a sigma.
3. **`locate` only names the cell.** The tip is known to half a cell, the cell's centre. The sweeps reach a cell and a half, and a line that finds no border is swept again beside it. The tap that names the cell presses at least 0.06 mm in (`identify`): at 0.02 mm a row's crosstalk tied seven cells.
4. **The order is now:** locate, the edges (each one corrects the tip estimate across its border), then contact z mid cell, where the tip now is.
5. **Unsure means no tag.** `probe_tool` combines the pen's sigma with the reference's. Over `max_sigma` (0.15 mm) it stops and prints the values instead of writing them. A wrong tag is worse than none.

Safety stops are unchanged: too hard, no frames, the floor, still touching after backing off.

## Results

- **Tests:** all 35 FSR tests pass, the old scenarios included. Three that asserted the old stops now assert a measurement.
- **Real data replay:** `test_the_border_from_real_taps` runs #30's taps through `border()`. It finds the three row borders 2.50 mm apart with no tap on the wrong side. The old rule, on the same taps, came within one tap of turning on column 0's leak.
- **Head to head on a patchy sheet:** the measured BED_5 physics (fresh sheet) plus #1's patchiness, 12 random tips per run, three runs each. Not a test: a model, but its numbers come from the data above.

| Patchiness | Old code | New code |
|---|---|---|
| none, ±30% | 12/12, worst 0.004 mm | 12/12, worst 0.006 mm |
| ±50% | 11, 10, 6 of 12 (stopped) | 12, 12, 12 of 12, worst 0.006 mm |
| ±70% | the reference didn't calibrate | 6, 10, 4 of 12; the rest refused, never wrong |

## What changes for running it

- **Calibrate the reference again (`LRT_CALIBRATE`) before any pen.** Contact z means something else now (the onset, not 150), so an old profile's dz doesn't compare. Old profiles have no sigma; they count as exact.
- **The output changed:**
  - `LRT_FSR_Z` prints `±`;
  - `LRT_FSR_EDGE` and `LRT_FSR_MEASURE` print sigmas;
  - each edge says how many taps it took and how many fell on the wrong side;
  - `VERBOSE=1` lists every tap with both cells.
- **It's slower:** ~100 taps a pen, against ~45. `sweep: (0.5, ...)` in beds.py saves ~30 a pen. In the simulation that was as good at ±50% patchiness and let one 0.1 mm error through at ±70%.

## Still open

*(As of the morning of 2026-10-09; the Handoff below supersedes it: the loads are being fitted, and the reworked code has run on the plotter.)*

- **The readout electronics.** The sense rows are ADC pins whose pull-downs `ADC()` switches off. `fsr_pull_down` isn't set in `nodes/fsr.json`, so unless the board has load resistors, the rows float. Floating, high-impedance sense lines would explain several things at once:
  - crosstalk up the columns on *both* sheets, worst on row 3 (the one without a series resistor);
  - row 3 hearing the head hover (30–50);
  - baselines that drift by tens a minute.

  act-6 listed `fsr_pull_down` as the next experiment, and it never ran. It costs ten minutes: `mcu.py send 'diag()'`, then `"fsr_pull_down": true` in `nodes/fsr.json`, then a ladder and a scan with `fsr_manual.py`, against #0 and #1. If the crosstalk drops, the `× 0.8` on row 3 and `crosstalk_rows` may be able to go.
- **Not yet on the plotter.** Everything above is the simulator and replayed readings. Next: `LRT_FSR_MEASURE CLEAN=0 VERBOSE=1` three times with the Stabilo. Do X, Y and z repeat within their sigma, and how many taps vote wrong?
- **Z from the FSR is still a force threshold** (act-7, act-8): the onset is closer to first touch than 150 was, but the paper (the camera ladder) is still the better judge of dz.
- **Faults near a border:** a sweep crosses only the cells of its edge, so it never sees faults elsewhere. A survey still helps pick good edge cells.

## Handoff (2026-10-09 evening, for whoever continues)

The user is fitting 47k load resistors from each FSR sense row to GND tonight. This session ends there: the measurement code is reworked and committed, and the firmware change for the resistors is written but not yet flashed.

**State:**
- **Committed** (`4afd41d` *fsr: switch algorithm*, `8ae8fe7` *fsr: z depth*): the rework above, plus `dz_trim` (beds.py, 0.1; `DZ_TRIM=` on `LRT_CALIBRATE` / `LRT_PROBE_TOOL`). It takes every FSR tag's dz down alike: the reference's first test mark at Z1 drew nothing.
- **Uncommitted** (the user commits):
  - `micropython/lrt_fsr_array.py`: `"fsr_load"` in node.json means external loads, so the internal pulls stay off and row 3's × 0.8 goes; `diag()` reports it;
  - `micropython/nodes/fsr.json`: `"fsr_load": 47000`. Flash it only with the resistors fitted: without them row 3 reads high;
  - `notebooks/pinout.md`: the loads drawn in, how to size them, and BED_5's rows 2/3 corrected: **row 3 is GP26** (`fsr.json` is `[29, 28, 27, 26]`; the page had it swapped);
  - `TODO.md`: the steps.
- **Why the resistors:** the rows have floated all along. `ADC()` turns the pad pull-downs off, and `"fsr_pull_down"` was never set. That fits the column crosstalk on both sheets, row 3 (no series resistor) the worst, row 3 hearing the head, and the drift.
- **On the plotter now:** the reworked host code (the user deployed it), the old firmware, the Stabilo as reference. `LRT_CALIBRATE` was running at the end of the session. Its profile will be stale once the loads change the readings.
- **Measured with the reworked code, before the loads:** `LRT_FSR_MEASURE` three times:

  | Run | x | y | z | ± x, y, z |
  |---|---|---|---|---|
  | 1 | 114.806 | 52.600 | 3.519 | 0.003, 0.005, 0.03 |
  | 2 | 114.756 | 52.663 | 3.517 | 0.003, 0.009, 0.03 |
  | 3 | 114.763 | 52.700 | 3.534 | 0.003, 0.009, 0.01 |

  bed_z 2.810, tip ~(1.2, 1.95), gaps ~0 (x) and ~1.0 (y). z repeats well. X spreads 0.05 and Y 0.10 while each run claims under 0.01: **the sigma only covers the taps within a sweep, not run to run** (drift, the Z play, the tip estimate), so `max_sigma` won't catch that scatter.

**Next, in order:**
1. **Hardware check** with the user: four 47k resistors fitted, GP26–29 to GND. Did they measure a cell with a meter? If the cell under a pen tap is far from 47k, note it in pinout.md's table.
2. **Flash:** the user flashes with `mcu.py update`; ask, don't flash yourself. Then `mcu.py send 'diag()'` should say `fsr_load=47000`, `pull_down=0` on the four pins.
3. **Did the loads fix the sensor?** A ladder on (1, 1) and a scan along its column with `~/limn-shot/fsr-2026-10-07-manual.py` (copy it as `fsr_manual.py` with `-run-cmd.py` as `run_cmd.py`). Compare against `fsr-2026-10-07-manual.jsonl` #0 (ladder) and #1 (scan), and log to a new jsonl. Look at:
   - how much the column's other rows lift against the pressed cell (it was 0.15–0.35 on the new sheet, row 3 the most);
   - row 3 with the head just over the sheet (it read 30–50);
   - the rest level over a minute (it drifted by tens);
   - the response against depth: the scale changes with the load.

   Write down what changed, in a new act or appended here.
4. **Retune to the new scale:** `LRT_FSR_SURVEY` sets `early` from the noise at rest. Check `respond` (150), `press_strength` (450), `locate_strength` (180), `sure` (450) and `press_limit` (950) against the ladder. If the column crosstalk is gone, `crosstalk_rows: (0,)` in beds.py may go too.
5. **Calibrate:**
   - `LRT_CALIBRATE` with paper on the bed;
   - tune `dz_trim` (try `DZ_TRIM=` first) until the Stabilo's test mark is complete with the least trim;
   - `LRT_FSR_MEASURE CLEAN=0` three times: did the X / Y spread (0.05 / 0.10 before) shrink?
6. **If the spread didn't shrink:** make the sigma honest about run-to-run scatter. For example, measure each edge twice, from both sides, and fold their difference into sigma, or keep a per-sheet floor from repeated runs. Then `max_sigma` means something. Fix the estimator; don't add a threshold.
7. **Then the pens:** `LIMN_TOOL_CALIBRATE T=41..44`, each tag named first.

**Ground rules** (from the user, see memory):
- the user deploys and restarts Klipper and flashes the MCUs: say what is ready and wait;
- ask before using the printer's URLs or SSH;
- keep every press inside the FSR cells;
- fix the estimator rather than patching thresholds;
- test against recorded real data where there is any (`test_the_border_from_real_taps` is the one fixture so far; record raw 32-cell frames when you can);
- every image goes in `~/limn-shot`.
