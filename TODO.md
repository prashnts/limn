# Next

Trimmed 2026-11-05; the long discussions and reviews are in git (TODO.md before this date).
- **Load cell as the probe**: tool on paper works (11-03); next the Klipper probe on the touch line. *Load cell*.
- **Printed one-piece cell**: the open review items. *Load cell*.
- **Beam bed (XY)**: bench one pair, pick the bed ID. *Beam bed*.
- **Drag knife**: holder v2 with a spring, then the knife kind. *Plot & cut*.
- **Colour plots**: a swatch row with the real Stabilos.
- Endoscope: in `limn_endoscope` (ESP32-P4, notebooks endo-*, `esp32/NOTES.md`).

## Load cell (head, in the toolchanger; board LIT)

State (2026-11-03, LIT on the Pi's USB, scripts in pi:~/claude-cell): noise 0.11-0.19 g, drift ~0. Z 2 ↔ 7.5 within ±1 g after the wire fix. Tool on paper: contact z 3.888, sd 10 µm over 5; soft 0→6 g over 0.15 mm, then ~25 g/0.1 mm. LIT's grams 1.19x high (~1280 counts/g), not recalibrated.
Rules: tare after homing at Z ≤ 4 coming down; tare above the paper at each pen-down; fix drift by a fast final approach, not a threshold; moves with a tool stay at X < 120.
- [ ] Touches with a fast final approach (Klipper `[probe]` on the touch line), first-after-move vs later.
- [ ] XY drag with the new rider; then force while drawing (log first, re-tare per pen-up).
- [ ] `calibrate(<g>)` with known weights (when needed).
- [ ] FFC far end → K stepper (Melzi) + USB-C (hub).
- [ ] Z play: push the pen 50/100/200 g on a scale, watch Z + the cell (the rider flips past ~60 g).

Next cell: one-piece printed parallelogram (beams + blocks one part, gauges on the outer faces at both ends, PLA-CF; `~/limn-shot/loadcell-printed-ideal-20261027.svg`). Open from the PrintedCell2 / LoadCell41 reviews:
- [ ] The +Y groove at the moving end cuts the bottom beam's root and the top root's fillet (at B/D): keep it ≥1 behind the roots, between z 44.1-49.1.
- [ ] Ø2.2 holes: M2 + nut, or a ~1.6-1.8 pilot on the rider side for BT2.
- [ ] Rider plate in the window ≥0.5 clear of both beams; check light through the 0.8 gaps.
- Wiring: bridge closed on the cell, leaves from the fixed block, twisted pairs to LIT (E+/E−, S+/S−), one connector at most.
- Alternatives if it disappoints: A1 spring holder + Hall (49E + magnet; bench it against the head cell), A2 bar cells under the bed, a bought mini bar cell.

## Beam bed (XY)

Two IR pairs (PT1206BS + 940 nm), 15 mm slots in an L, RP2040-Tiny; Z from the load cell. KiCad `docs/kicad/beam_bed.kicad_sch` (refs 85x), board `beam_bed_board.kicad_pcb` (placed, not routed).
- [ ] Pick the bed ID (R851): a free BED_n after BED_6.
- [ ] Bench: one pair across a printed slot with razor slits, the Tiny streaming on/off levels; Micron 005 by hand: dip depth, edge repeat <0.03?
- [ ] `LRT_BEAM_MEASURE` → the tag's dx, dy. Measure Y first, then X at the same spot along the beam (beam angle); two heights for tilt if needed.
- Firmware: PIO half-duplex in lib/link.py on GP0, touch.py drives BED_PROBE (GP1/GP2) instead of DETECT.

## BED_5 FSR (kept until the load cell takes over)

Notebooks act-8..11. In code, to deploy: per-edge depths (act-11), `LRT_FSR_CLEAN`.
- [ ] Deploy; `LRT_CALIBRATE` with the Stabilo, then the pens and the Micron Blue.
- [ ] Y edge (1, 6)|(1, 7) is noisy: try a narrower border.
- [ ] Run-to-run scatter (X 0.17 vs claimed ±0.003): log taps over runs, a sigma that includes it.

## Paper and force

Writing force 20-40 g, light 5-10 g (kitchen scale). Plan: mesh with a stylus/pen + load cell (A), residual from pen-down forces (B), spring holder for the rest.
- [ ] A pen holder with a soft preloaded spring (~0.5-1 N/mm) before any new sensor.
- [ ] Small text: pen-down while moving vs stop-then-lower; accel / square_corner_velocity.
- [ ] Width ladder: force (or Z) x speed per pen, by limn_cam.
- [ ] Skew/scale: grid + ruler photo, `skew_correction`.
- Later: line-laser scan tool, vacuum bed.

## plot/

- [ ] Cuts (paint pieces): plot/cuts.py done; `Obj.cuts`, `ShapePaint.segments`, slicer, `/api/objects/{id}/cut`, the Cut tool, UI tests.
- [ ] Text: warn when glyphs are smaller than the pen can draw; the Plots-3 axis labels still chopped.
- [ ] Tune on real plots: `NEAR` (colour merge), `bleed`, `SMALL`/`LOST`/`TEXT_MIN`, raster pitch, halftone blotting.
- [ ] Groups of drawings: scale and turn together.
- [ ] Dither: speed (numba/C), serpentine or blue noise, travel order for many dashes.
- [ ] Ink check across drawings; timing on the Pi.
- [ ] `z_touch` moved ~0.2 between sheets: a ladder or `z_touch` per sheet.
- Wishlist: connectors that stay attached (straight/elbow/iso, ends, labels), shared with pi-thermal/vellum.

### Colour plots

Side by side (`plot/mix.py`), yellow first, K last, wipe between inks.
- [ ] Swatch row with the real C/M/Y/grey Stabilos: colour or stripes from a step back?
- [ ] Phase 3: swatch chart + camera measure the pens' real colours; choose which pens a mix may use.

### Plot & cut: the drag knife

Offset `d` (~0.25 at 45°, ~0.5 at 60°; 60° for 300 gsm card), swivels at corners, ramp in, overcut, shallow passes pass-major, inside out, tabs, knife after every pen.
- [ ] Holder v2: sleeve + spring (~2-4 N/mm) + exposure cap, RFID tag.
- [ ] Measure `d` per blade and the depth ladder on 80 / 300 gsm.
- [ ] `knife` kind in plot/tools.py (compensation, swivels, ramp, overcut, passes) + geometry tests.
- [ ] Planning module: containment tree, pass-major, tabs, magnets' margin; UI: knife layers, tabs, preview.

## Scan and cameras

- [ ] Camera scale: scan a ruler/grid, set fov (Hugin 119.9 px/mm vs pens.toml 125.9); `center` against the tool point.
- [ ] Flat field from plain paper; registration over blank paper (skip textureless overlaps, cap corrections).
- [ ] Flicker: fix at the light (DC or exposure in whole periods).
- [ ] Resume a cut-short scan; focus stacking for film.
- [ ] picam / rxcam tools: tag, fov, focus; Radxa V4L2 controls and colour.
- [ ] Film: HQ + 16 mm + tube test on a ruler and a negative; weight on the head.

## Web UI

- [ ] ES modules, no bundler (`state.js` instead of globals); `// @ts-check` + JSDoc, `tsc --noEmit` on the laptop. No build step on the Pi.

## ext/, klipper/, toolhead

- [ ] Holders slightly angled in X, the key's centre a bit off: chamfer the key/socket first; magnet + Hall (49E) bench for the tool's centre.
- [ ] Holder 45 read empty with its pen in it; key open with a stale carried tool.
- [ ] Tag reads: PN532 listening 0.5 s untested on the plotter.
- [ ] Tool ID: pull-up to 3.3 V, talking tools R ≥ 4.7k (the UART idles through it); settle ~100 ms after lock; cross-check with the holder switches.
- [ ] Coupling: power only when ID seen and key locked; data pins high-Z until powered; plating on the contact pins, drop under 1.3 A.
- [ ] Power: draw the whole tree; charger cuts all ports on plug-in (test); WS2812 at 5 V with a level shifter; Pico W VSYS ≤ 5.5 V.
- [ ] Drying beeps on a long plot; a Fluidd button for `TOOL_DRY RESET=1`.
- [ ] Key lock vs pogo pins (`Limn 2.1 v67 - section.step`, 2026-11-06): the floor the dowel bears on is flat (y −48.5, 30-150°), no lead-in; dowel 0.08 into it, set rigidly by the 3 M3 balls. With the 4 pins the clamp needs N ≥ their push, the dowel climbs the slot edge under load, the 16 T m0.6 pinion (r ≈ 4.8, ~1:1 to the dowel) stalls. Plan: (1) spring under the pinion's front face (shoulder 1.5 deeper, wave spring Ø7/11 or 1.5 O-ring), pinion rests on the cover: its 0.42 gap gives 0.5 interference; spring force at 0.5 ≈ 1.3× pin push (measure). (2) plate: 0.8 deep lead-in at both leading slot edges over ~40°, flat, 0.15 detent at 90°, chamfered edges; balls only seat (equal protrusion 3.65, caliper). (3) grease. Est. rack force: ~1.2 N on the ramp, ~0.5 N on the flat (μ 0.15, N 3.75 N).
  - `Limn-Tool-Dock-Plate.step` (2026-11-06): lead-ins on all 4 slot edges (either turn), linear from the edge (0.6 at r4 … 1.15 at r6.8) to 0 at ~68°, flat 68-84°, radial detent 0.15 deep at 90/270 (84-96°). Good. Rigid key until the O-ring: locked clamp = overlap − 0.15, so set the balls for ~0.25-0.3 overlap on the flat (or detent 0.08 for now).
  - `Limn-Tool-Dock-Plate.step 2` (2026-11-07, pen tools: no pogo contact): bottom pair in a 1.7 deep recess (8 x 2.5, pins at ±3/−9 inside, 0.6 below the tips), top pair through holes (±10, z 4); floor/ramps unchanged. Good; balls for ~0.15-0.2 overlap.

## Beyond pens

Cutting, embossing, engraving, film scanning, PCB resist, brush, dispensing, pick and place, touchscreen testing, 2.5D probing, laser.
- Laser, before switch-on: glasses for the wavelength (OD4+ at ~450 nm), never on the PVC mat, a hardware cut-off + extraction, the laser kind never touches and `M5` on every error path.
