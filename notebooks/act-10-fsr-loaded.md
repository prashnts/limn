# Act 10: the FSR on its loaded sheet, retuned (2026-10-11)

Follows `act-9-fsr-rework.md`. The 47k loads (2026-10-09) made the sheet quiet at rest but about 5× less sensitive, and the thresholds were still the old sheet's. Today's plot after a full calibration was right for every pen except the Micron 01 Blue, its z slightly high.

Commits: `1d31142` (thresholds, tap cap), `1602049` (contact check, strong cells, two edges), `48c60e8` (`dz_trim` 0.3). Logs and scripts in `~/limn-shot/`: `acc-2026-10-11.*`, `zloss-2026-10-11.*`, `fsr-2026-10-11-calibrate.log` (before), `fsr-2026-10-11-calibrate2.log` (after), `fsr-weights-2026-10-11.py` (not run yet).

## What the loaded sheet reads

The Stabilo (stb-88, holder 45) on (1, 1), raw G1 ladders with `LRT_FSR_MATRIX` (`acc-2026-10-11.jsonl`):

| Past first touch (mm) | 0 | 0.05 | 0.10 | 0.15 | 0.20 | 0.25 | 0.40 |
|---|---|---|---|---|---|---|---|
| (1, 1) | ~45 | ~65 | ~135 | ~165 | ~200 | ~227 | ~232 |

- It levels off from ~0.25 mm: either the force stops rising (the Z axis lifts in its play under ~2N: the toolhead weighs ~200 g) or the sheet saturates under a felt tip. Not told apart yet (the weight test would).
- At rest every cell reads 0. (1, 0) and (3, 1) lift with a press on (1, 1): ~40 and ~25.
- The survey of 2026-10-09, at 0.04/0.08 mm: (1, 1) 56/72 and (1, 2) 40/56 are among the weakest cells; (1, 6) 165/216, (1, 3) 165/201, (2, 5) 176/196, (3, 7) 169/237 among the strongest. The calibration ran on the weak ones.

## Changes

1. **Thresholds rescaled** (beds.py): `press_strength` 450 → 120, `respond` 150 → 60, `early` 60 → 30, `sure` 450 → 150, `locate_strength` 180 → 70, `press_limit` 950 → 600.
2. **The tap cap** (`TAP_PRESS`, ext/limn) 0.1 → 0.2, capped by a pen's `press_max` instead of its plotting `press`.
3. **The contact check** (`_descend`, `Fsr.growth`): confirmed by any cell's growth over its own reading at the onset (cells over half of `early`), within up to 5 fine steps. It used the strongest cell, and a flat crosstalk cell leading at first touch made real touches look like readings in the air.
4. **Strong cells, two edges an axis**: z (1, 6); X (1, 6)|(2, 6), (2, 5)|(3, 5); Y (1, 6)|(1, 7), (1, 3)|(1, 4). The sigma of an axis now includes how far apart its two edges put the tip.
5. **`dz_trim` 0.3** (was 0.1), the user's value from 10-09.

Tests: the old sheet models keep the old values (`UNLOADED` in test_fsr.py); `test_the_loaded_sheet` (gain 1350 felt / 450 fine, saturating at 230) and the crosstalk regression test are new.

## On the plotter

| | 18:45 (old check, (1, 1)) | 19:11 (new) |
|---|---|---|
| Contacts | 3.573, 3.611, 3.726 (two with 2-3 "in the air" each) | 3.620, 3.625, 3.622 |
| Reference over the BLTouch | 0.481 | 0.620 (10-09: 0.610) |
| X | 114.469 ±0.003, one edge | the tip 1.669 and 1.606 across two edges, ~±0.04 |
| Y | 52.531 ±0.011, one edge | −2.181 and −2.177, ~±0.01 |

The reference at dz 0.52 (trim 0.1) didn't touch the paper in its test mark; re-tagged at dz 0.32 (trim 0.3) by hand (`WRITE_TOOL_TAG DX=0 DY=0 DZ=0.320 REFERENCE=1`), and the user's plot with it looks right.

## Ruled out today

- **Z losing steps.** The user's experience: the weak, highly geared Z motor loses steps when fast. Over (1, 6), the first rise of the sheet (slow 0.02 mm steps) was 3.6525 / 3.6519 at the start, then 3.6596, 3.6594, 3.6591, 3.6593 after sets of 20 tap-like hops up at 5, 2, 5 and 1 mm/s, and 3.6593 after 5 trips to Z8. A one-off +0.008, then nothing: no loss at the FSR's speeds (`max_z_velocity` 5, `max_z_accel` 100). Speeds unchanged.
- **The carriage's MPU9250 as a contact sensor.** Averaged `ACCELEROMETER_QUERY` (12 a step, ±12 mm/s², ~0.07°) on two ladders to 0.16 and 0.40 mm past first touch: nothing above the noise. Whatever gives at contact, the accelerometer's mount doesn't tilt with it. The contact-sensing options for the toolhead (counter-spring and Hall sensor on the Z rider, strain gauges, the key hole) are in TODO.md, *The toolhead knows the contact*.

## Next

1. The pens with the new code: `LIMN_TOOL_CALIBRATE T=41..44`, the Micron Blue first; their marks.
2. The taps' depth is found on locate's estimate, before the edges: on 2026-10-11 both spots were on a border's dead zone and the Stabilo went the whole 0.2. Find it after the first X and Y edge, on the z cell's centre.
3. Interleave the edges (X, Y, X, Y): both X edges ran on locate's Y and each missed its first two lines.
4. The weight test (`fsr-weights-2026-10-11.py`): strength against grams on (1, 6), and whether ~230 is the sheet or the force.
5. Run-to-run repeatability with the two edges: `LRT_FSR_MEASURE CLEAN=0` ×3.
6. Wear-levelling: rotate the cells per calibration (TODO.md).
