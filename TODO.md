# Next

What's open, the newest first. The details are in the sections below.
- **Toolhead and harness rework** (2026-10-12 plan): a small Klipper MCU on the toolhead for K, its endstop, an ADXL345, an HX711 strain gauge, the lock sensor and the tool's link; Z stays on the Melzi; the `rpi` Pico goes; power redone with the harness. *Toolhead and harness rework*.
- **FSR calibration on BED_5**: per-edge depths in code (act-11), to deploy; then the pens and the Micron Blue. *BED_5's FSR sheet*.
- **The drag knife**: holder v2 with a spring, then the knife kind in plot/. *Plot & cut*.
- **Colour plots**: a swatch row with the real Stabilos. *Colour plots*.
- **Endoscope**: the live work and notes are in `limn_endoscope` (ESP32-P4 since 2026-10-08, notebooks endo-1..7); the sections here are the 2026-10-01 notes.

## BED_5's FSR sheet: to calibrated pens (since 2026-10-07)

Read the notebooks in order: `act-8-fsr-checkpoint.md` (what went wrong on 10-07/08, the plan), `act-9-fsr-rework.md` (contact by the sheet's rise, tap sweeps, the 47k loads), `act-10-fsr-loaded.md` (retuned to the loaded sheet), `act-11-fsr-survey-depth.md` (each edge its own depth). Notes about the old sheet (col 3/4 faults, weak (2, 4)) are history; older items are in git.

Where it stands (2026-10-12):
- 47k from each sense row to GND (`"fsr_load": 47000`, 5868a30): every cell reads 0 at rest and in the air, no faulty cell, the signal ~3x smaller (median 134 at 0.08 mm). The survey of 10-12 (c0a13c0) found (0, 2), (1, 1), (1, 2) dead: the cells the calibrations had tapped most.
- Rescaled to the loaded sheet (2026-10-11): `TAP_PRESS` 0.2, capped by a pen's `press_max`; press_strength 120, respond 60, early 30, sure 150, locate_strength 70, press_limit 600; the old models keep the old strengths in the tests (`UNLOADED`). `dz_trim` 0.3 (48c60e8).
- The contact check judges each cell's growth over its own onset (`Fsr.growth`): contacts agree to 0.005 (they were 0.15 apart). z on (1, 6); X edges (1, 6)|(2, 6) and (2, 5)|(3, 5); Y edges (1, 6)|(1, 7) and (1, 3)|(1, 4). Each axis is the mean of two borders, their spread in its sigma (`edge_tips`). ~+2.5 min a pen.
- `LRT_CALIBRATE` 2026-10-11 19:11 (`~/limn-shot/fsr-2026-10-11-calibrate2.log`): contacts 3.620 / 3.625 / 3.622, the reference 0.620 over the BLTouch, X ~±0.04, Y ~±0.01. The last full plot was right for every pen except the Micron 01 Blue (z slightly high).
- No Z step loss at these speeds (2026-10-11, `~/limn-shot/zloss-2026-10-11.*`: a one-off +0.008, then none over 40 hops at 1-5 mm/s). Speeds left as they are.
- In code, to deploy: edges X, Y, X, Y, each finding its depth on its two cells as the tip now is (act-11, `test_each_edge_finds_its_own_depth_once_the_tip_is_known`); `LRT_FSR_CLEAN` and a wipe asked before meshing `lrt_fsr`, `LRT_CALIBRATE` and `_fsr_bed_z` when a tool touched the sheet since the last wipe (`CLEAN=0` skips; after a restart nothing is asked).

Open:
- [ ] Deploy; `LRT_CALIBRATE` with the Stabilo, then the pens and the Blue's mark.
- [ ] **The Y edge (1, 6)|(1, 7) is the noisy one** (10-12): gap 0.85-1.06, its point over 3 runs 39.963 / 40.044 / 40.088, against (1, 3)|(1, 4)'s 47.450 / .475 / .481. A narrower column border ((2, 5)|(2, 6), (3, 4)|(3, 5)): its gap first.
- [ ] **A stray tap's weight in `border()`'s sigma**: each counts as far as it lies from t0, so one tap 0.5 mm off makes ±0.5 while the point moves 0.01. If strays stay with the per-edge depth.
- [ ] **The two X borders are 2.606 apart, not 2.5** (every run, 10-12): systematic, cancels between pens, ~0.05 of X's sigma. The sheet's rows, or the row 3 trace?
- [ ] **Run-to-run scatter**: X repeated to 0.17 mm over five runs (Y 0.06, z 0.08, act-9) while each run claims ±0.003. Log the taps (`VERBOSE=1`) over a few runs; a sigma that includes the scatter.
- [ ] **BLTouch on an inked sheet**: (1, 6) inked against wiped, ~5 probes each: does ink lift the pin, how much?
- [ ] Known weights on (1, 6): `~/limn-shot/fsr-weights-2026-10-11.py` (strength against grams, creep over 10 s).
- [ ] `LRT_FSR_MAP TIP=2.0,2.13`: the origin (refined by edge searches) and pitch, which cells answer (the 10-07 run mapped nothing; fixed since). Set `origin` in ext/limn/beds.py; `faulty_cols` if whole columns stay silent. On the first hand map columns 4-7 answered as (3, 0), which had a resting preload of 80-130: check the ribbon and that corner before trusting those columns.
- [ ] `LRT_CALIBRATE` with paper on the bed (the test mark at Y 120-150): is z right? Then `LIMN_TOOL_CALIBRATE T=41..44`, each pen's tag named first (`TOOL_TAG_SET PEN=`).
- [ ] Fit the tests' fresh model (`FsrBed(fresh=True)`) to the new sheet's survey (304 at 0.02 mm, 469 at 0.04 on (1, 0); crosstalk ~0.15, row 3 ~0.35). Record raw frames of a real `LRT_FSR_MEASURE` (all 32 cells a tap) as fixtures: `border()` is tested against #30 only.
- [ ] Fine pens: a ladder with a working fineliner (the test one is bent); `respond` for fine tips. If a pen takes too long (a Micron ~4 min): `sweep: (0.5, 0.05, 0.4)` in beds.py, ~30 taps fewer.
- [ ] The survey (~8 min) presses only the cells' centres: faults near a border slip through; LRT_FSR_MAP covers those.
- [ ] **Wear-levelling the sheet** (the user's idea, 2026-10-11, for later): every pen taps the same spots (~4 edges × ~50 taps + contacts, up to 0.2 mm).
  - *Rotate the cells per calibration* (preferred): `LRT_CALIBRATE` picks the z cell and the edges from a pool of strong pairs (the survey's), stores them in the profile, and every pen of that calibration uses the same ones, so offsets stay border against the same border. The next calibration takes the next set. Needs a pool in beds.py, the profile carrying the cells, probe_tool reading them, z_cells for the BLTouch from it.
  - *Jitter*: move each sweep line ±0.4 mm along its border, and the contact spot within its cell, at random. Cheap, but a border not square to the axes reads off by offset × its tilt (2° and 0.8 mm apart: ~0.03 mm), different for each pen: noise in every offset.
  - The per-edge depths react to a cell as it is now; logged per cell, they're a free running survey, so the pool can follow the sheet's drift without a full `LRT_FSR_SURVEY`.

### A QRE1113 beside the FSR: find the tip without touching (2026-10-11 discussion, dropped)

The idea: a reflective sensor facing up, next to the sheet. Scan the pen over it in the air, take the peak as a rough tip XY, then aim the FSR at a known cell: edge sweeps start close, `locate` and its presses drop out.
- **What it gives**: no contact, so no tip wear and no crosstalk or force thresholds for this step. Fast: a 1mm grid over ±5mm (~100 points, or continuous lines with the ADC streaming), then one X and one Y line through the peak at 0.2mm, a fitted peak: a few seconds. The rise of the signal on the way down also says "about 1mm above it", so the descent to the FSR can be fast until there.
- **Where it stops**: the peak is the centre of what reflects most, not the tip. A fine liner's metal sleeve is shiny, a black nib absorbs IR, the holder and key reflect too. So expect ~0.5-1mm, pen by pen: good enough to land in the right cell (2.5mm pitch), not to replace the edges. One offset QRE→FSR measured once with the reference pen.
- **What it doesn't fix**: the open problem in act-9 is z, a fine tip at 0.10mm barely lifts the loaded sheet. XY/locate already worked (same cell, same tip twice).
- **Mounting**: a pocket in the bed, the sensor's face ~0.5mm below the surface so a pen can't ink it, no paper over it. In a spot plain to the cameras, so it can be wiped.
- **Light**: the IR camera light and daylight leak in: pulse the LED (a GPIO through a transistor) and read on minus off.
- **Wiring**: one spare ADC and one GPIO on the FSR node.
- **Against the upward endoscope**: a camera under the tip gives XY far better (and the tip's shape). The QRE is a cheap, robust coarse step until then, or a fallback.
- No free ADC pin is left on the FSR node (2026-10-11): it would need another MCU. Dropped for the break-beam below.

### A break-beam tool setter in the new bed (2026-10-11 discussion, preferred over the QRE)

An IR LED and a phototransistor facing each other across a ~6-10mm slot in the bed, each behind a ~0.3mm pinhole. The pen goes down into the slot or across it, and the tip **blocks** the beam. It's a transmission measurement, so ink, nib colour and shine don't matter (what blocks the QRE). CNC tool setters and toolchanger nozzle-alignment rigs work like this.
- **Digital, no ADC**: the phototransistor through a comparator (LM393 + trim pot) or a Schmitt input is an endstop. Any free digital pin, eg. on the Klipper board: a Klipper `probe`/endstop, so `PROBE`-style moves with Klipper's own trigger timing. A ready slot opto-endstop (TCST2103-type, ~3mm slot) works to try, but its slot is narrow for a Stabilo's cone.
- **X**: cross the beam in X at a height below the tip: the mean of the block and unblock edges is the tip's centre. Its width cancels out, both directions (backlash cancels too).
- **Y**: a second beam at 90°, or the same slot cut as an L/X. One beam gives only the coordinate across it.
- **Z without contact**: come down into the beam above the centre: the trigger height is the tip against the beam's height. Calibrate the beam's height to the paper once (reference pen: beam z against a camera ladder or the paper contact). A thin tip blocks less of the pinhole, so it triggers a bit lower: expect a small bias per tip size (~0.05mm?), measured once per pen type and stored with the tag profile.
- **Expected**: repeat ~0.01-0.03mm at slow approach (CNC setters do ~0.005), a few seconds per pen, no force on the tip: the 0.05 liners measure as well as a felt tip.
- **Against the FSR**: the FSR feels touch (the real contact, the fibre's give) and the beam sees geometry. Keep the FSR for a press/force check, or drop it if beam z + a per-type bias draws right.
- **Recessed, not protruding** (2026-10-11): the user pictured beams standing on the bed (only 5-8mm of Z room, they'd hit the motion system). The beam goes *inside* the bed: a pocket ~3mm deep, the beam ~1mm below the surface, side-looking SMD IR LED and phototransistor (~1mm tall parts) in the pocket walls, not a slot-endstop module (~10mm tall). Needs: Z allowed to go ~1.5mm below the paper over the pocket (a soft limit there only), and the pocket's floor deeper than that. The user's slot sensors (a few mm gap) can test the idea on the bench, upside-down or at the bed's edge.
- **Precision against the FSR**: the FSR repeats X 0.05, Y 0.10 over runs (act-9). An optical edge at a slow approach should repeat to ~0.01-0.03 (printers' optical endstops; not measured here). Its Z is the tip's geometry, not its touch: one offset per pen type.
- [ ] Try first: a slot opto-endstop (or an IR LED + phototransistor taped across a printed slot) on a free endstop pin, `QUERY_ENDSTOPS` while jogging the Micron 005 in holder 45 by hand. Do the X edges and the z trigger repeat to <0.03mm over 5 tries? How far apart do the Micron 005, a Micron 01 and the Stabilo trigger against their camera-ladder contact?
- [ ] If yes: an X-shaped slot in the new bed's design with two beams, pinholes, wiring to the Klipper MCU; `LRT_BEAM_MEASURE` (X edges, Y edges, z) → the tag's dx, dy, dz.

### Other ways to find the tip (2026-10-11 discussion)
- **Draw and look (no new hardware).** Each pen draws a small cross and a slow Z ramp (a line whose Z falls ~0.05mm per 10mm) on scrap paper, and the camera (limn_cam) measures them. The cross against the reference pen's cross gives dx, dy. Where the ramp's ink starts gives contact z, the real one: ink on paper, with that pen's give, on that paper. It is the camera ladder made continuous. Limits: the camera's mm per pixel, the paper's height under the ramp (the mesh), and a dry tip starting late. Cost: some paper per calibration, a few seconds per pen.
- **A piezo disc under a small pad, for z.** Piezo Z probes on printers feel a nozzle's touch with grams. It feels contact as an event (a tap at a few mm/s), not a steady force, so its trigger repeats where the FSR's slow rise doesn't. Digital through a comparator (no ADC), an endstop pin. z only: XY still from the FSR or the camera. Fine tips are its strength.
- **An upward camera under a window in the bed** (the endoscope work). The tip's XY to sub-pixel, its shape (a broken or dry tip), and its touch on the glass. Most capable, most work: the space under the bed and the endoscope's focus distance decide it.
- Weak: capacitive sensing (the tip is tiny, wet ink varies), electrical contact (the nibs aren't conductive or grounded).
- [ ] Draw and look first: it needs only G-code and limn_cam. Run it on the reference pen and the Micron 01 Blue (its z was high on 2026-10-11): does the ramp's start repeat to ~0.02mm?

### A thin upward camera: ≤3.5mm under the bed (2026-10-12 discussion)
The user can spend 3.5mm of bed thickness. Regular camera modules (even small ones) are 5-8mm with lens, so fold the optics:
- **Fold the path (my pick).** A micro right-angle prism or a mirror (2-3mm) under a thin window, the sensor lying flat beside it in a pocket or past the bed's edge, where thickness doesn't matter. Only prism + window (glass ~0.5-0.7mm) live in the 3.5mm. The tip is a few mm above the window, so a short-focus micro lens is needed (the endoscope's own lens/sensor, if its focus is right: check its close focus).
- **Coherent fibre bundle.** A 0.5-1mm image guide (~10k px) under the window, the camera at its other end anywhere. Thinnest, but low resolution and fragile; check the price.
- **Bare sensor, no lens** (shadow/contact imaging): **dropped (2026-10-12, the user's point).** ~1.5mm total, but an OV2640/OV5640-class die is only ~3.6×2.7mm and the tip must be almost touching it, so it has to land on a ~3mm field: the FSR's problem again (tag offsets between pens are several mm, e.g. dx −4.02). Searching by touching also wears the sensor's glass and inks it. A lens that *reduces* (~1:2, a 2mm lens, object ~6mm away) gives a ~7×5mm field from the same die, folded by the prism.
- **A tiny chip camera** (OmniVision's OVM6948 class, 0.6mm cube, 200×200 px): fits anywhere but ~25µm/px over a 5mm field: sub-pixel centroiding only gets ~10µm at best. Verify the part and its interface (MIPI) before counting on it.
- **Optical mouse sensor**: not as flow, only as a 30×30 imager; worse than any of the above.
- Light: a ring of side LEDs around the window, pulsed (on minus off) against daylight and the IR camera light.
- [ ] Measure the endoscope's close focus and field first: is a prism fold enough with what exists?

### FSR accuracy: fix the estimator, not new hardware (2026-10-12 discussion)
Ideas in the order I'd try them (see act-10). First quantify: which error is it, a bias (FSR against the camera/ink-cross truth) or a scatter (run to run)?
- [ ] **Ground truth first**: the ink cross/ramp (above) per pen, against the FSR's tag, over ≥5 runs and several cells. Residual by cell and by tip class says what to model.
- [ ] **Border transfer function**: the ratio b/(a+b) → position isn't linear (ripple ~15% per 0.2mm across a cell). Scan densely across each strong border once with the loaded sheet, store the curve per border (LUT/fit), and invert it instead of assuming a line.
- Crosstalk on the loaded sheet (acc-2026-10-11.jsonl, Stabilo on (1,1), others as a fraction of it): (1,0) 0.72-0.8 at first touch falling to 0.33; (3,1) 0.46-0.5 falling to 0.1. So it is still there after the 47k loads, and (1,0) is the same-row neighbour (a sneak path along the row?). Re-run the same ladder if the resistor change is newer than 10-11.
- [ ] **Crosstalk unmixing**: the loaded sheet leaks (1,0)~40, (3,1)~25 for a 45 press. Measure the leakage matrix once and solve for the true cell loads, then take the ratio (and the centroid over the 2×2 cluster, not one border).
- [ ] **Edge pairs from both directions**: the two X edges disagree by 0.06mm (1.669/1.606); a direction-dependent bias (backlash, tip compliance, hysteresis). Cross each border both ways and average (X, Y, X, Y is done: act-11).
- [ ] **Depth from the rise, not the onset**: fit reading against z over the rising part (≈0.03-0.2mm), extrapolate to zero. The onset threshold depends on gain per cell and tip; the extrapolated zero doesn't. The force target stays inside the rising part (the sheet flattens ~0.25mm: the weight test says whether that's sheet or Z play).
- [ ] **dz_trim per tip class** from the ramp/camera ladder instead of by eye (0.3 now).
- [ ] Average several samples per step and take the per-cell baseline right before each touch.

### Pen sets and a proxy reference (2026-10-12 muse, for later)
- **Re-initialise from a known pen:** a printer that lost its calibration (profile, bed z) measures one pen whose tag already holds offsets against the reference. Its measurement minus its tag gives the reference's numbers back, without the reference pen on hand. A measurement against a known pen already says everything about that pen.
- **Sets:** offsets on a tag are only true against the reference they were measured with. Tag each pen with its set (the reference's id, or the calibration's), so pens from different sets aren't mixed by mistake. Any pen of a set can then stand in as the proxy for the rest.
- **Plotting with several sets:** if the sets' references have been measured against each other once (or one pen of each set against the other's), the offset between the sets is known and a plot can use pens from both.
- Needs: a set id on the tags (`TOOL_TAG_WRITE`), the profile naming its set, probe_tool / calibrate going by a non-reference pen's tag, and a check that a set's pens are still in step (their test marks).

## plot/

- Fixes in the G-code generation (details to come, 2026-09-30).
- Painting (fixed 2026-10-01): clicks on thin lines missed (a stroke is drawn as wide as the SVG has it, often under a pixel). Shapes are now picked within 6 px, hover shows which, a miss says so. Paths view: only the G-code, the drawing as a faint outline with *drawing*.
- [ ] Cutting a shape's outline to paint its pieces with different tools: plot/cuts.py (pieces, nearest, keys "k@t") and its tests are in; still to do: `Obj.cuts` + `ShapePaint.segments` in job.py, the slicer drawing each piece with its own group, `/api/objects/{id}/cut`, the Cut tool (C) and segment painting in app.js, UI tests.
- Text: fixes, and a way to see that a path is far too small for text, eg. a warning in the preview when glyphs come out smaller than the pen can draw.
- Done 2026-10-02, the web plot's finishing touches: a phone layout (canvas on top, panels scroll under it); round colour buttons, palettes that line up; the Printer panel moved up with Tools and Display, with buttons for Klipper's macros (home, tool changes, calibration, bed mesh, lights); *Fluidd at* for the cameras when the UI runs behind its own address; `bleed`; shapes too small or dense for the pen left out (or warned) and tiny `<text>` in a line font; `<image>`s taken out on upload; keyboard shortcuts (`?`); masked regions (`M`); drawings in order (⤒ ↑ ↓ ⤓, `[` `]`), the top hiding the ones under it on the paper too; how every tool draws (*Drawing* panel, the job's `draw`), overridable per tool.
- Done 2026-10-07: layers by pen with colour chips (alike colours merged, `NEAR` 60, `CHIPS` 12 in app.js), the shapes tool (`A`), per-shape *bleed margin* and *border* (`inset`), groups of shapes (`Obj.sets`) and of drawings (`Obj.group`); captures' *Hide all* / *Delete all*; a look deleted by the next capture.
  - [ ] Tune `NEAR` on real drawings (a gradient-heavy SVG): too low lists shades apart, too high merges colours meant for different pens. The chip's *Each of its colours* splits one by hand.
  - [ ] Bleed margin on a real plot: which `bleed` keeps the Stabilo's fill from running past a fineliner outline, and whether round corners read better than sharp at small sizes.
  - [ ] Groups of drawings move together, but scale and turn are still per drawing.
- Done 2026-10-07: pictures in an SVG made plottable (`plot/raster.py`): dither, lines, halftone; the upload asks.
  - [ ] Plot each on paper with a fineliner: which pitch matches its line (0.5 is a guess), whether halftone spirals blot at the middle, how long dither takes for real (many short strokes: Z hops dominate).
  - [ ] Dither is a Python loop: an A4 picture at 0.3 mm (~700k cells) takes a few seconds per change of its settings. numba or a C pass if it gets in the way.
  - Done: colour separation (CMYK, or onto the pens), pitch from each ink's pen, caps for fine pens.
  - [ ] Tomorrow's plot: lines and halftone onto the pens with the Stabilos, and a 0.05 fineliner in lines and dither (stipple). Check: is black solid at the pen's own spacing; do halftone spirals blot in the middle; does the unmixing look right with pens that aren't C, M, Y.
  - [ ] The Pi is several times slower: dither and halftone slice in 3-6 s here.
  - [ ] The page-background guess (full-page rect, painted first, something over it): watch for drawings whose first shape is a real full-page fill.
  - [ ] Ordering: emit's travel order for thousands of dashes (dither); a serpentine order per row might beat it.
- [ ] Too small: the thresholds (2.5 widths, 70% of the inside painted over, text caps 8 widths) come from one drawing (the Feb–Apr 2025 sketch on the Pi, at 22/39/49%). Check on a plot what really blurs, then tune `SMALL`, `LOST`, `TEXT_MIN` in slicer.py. Letters that run into each other (each fine on its own) aren't seen yet.
- [ ] Drawings over drawings is new: the ferry and magnet icons on the Pi overlap each other and the Feb drawing; whichever is on top now cuts the others. Turn *what is on top hides* off on one that should draw over.
- Pen-down: `z_touch - press` (1.2 less 0.15 for fineliners, 0.3 for the Stabilo 88), lifts by the press, `play.clear` and the play (`plot/profiles/play.toml`). The old "pens press too hard" was stale tags: done (`notebooks/act-7-camera-ladder.md`). To watch: touch moved by ~0.2mm from one sheet to the next (the Staedtler and the Stabilo both touched 0.2 low on sheet 2). Either a quick ladder per sheet, or `z_touch` per sheet/mesh.
- Done 2026-10-11, ink on paper (`plot/ink.py`): `dense` (exact / merge small shapes whose inks touch: a scatter plot's dots, filled once), `overdraw` (cut / warn / draw: the top wins, another pen's ink kept `bleed` clear ink to ink, its own only along it, ends give way so a tick is shortened rather than its label cut), and an ink check on every G-code (layers of ink per spot over 1.6, inks running together). Fills: hatch a spacing inside the border, one line down areas too thin for a ring. Plots-3: blue's worst spot from 311 layers to under 1.6 with merge.
  - [ ] The re-plot of Plots-3 on a fresh sheet (merge): does the paper hold; the red badges ("{9.1}") lose most of their red under the black digits, the legend dots their fill inside the black rings: physics at that size, or draw the dark ink smaller there?
  - [ ] The axis labels "5", "7", "9" (Plots-3, merge) still come out chopped: not traced yet. The "0" of "20" is cut by its tick in the SVG itself (the line font is wider than the source font).
  - [ ] Ink check across drawings (only within one now), and on the Pi: how long it takes there (0.35 s here).
- Done 2026-10-11: an `<ellipse>`/`<circle>`/`<rect>` svgelements can't reify (turned, through a `<use>`) was drawn in its own user space: Orientations' ovals sat at the drawing's corner, not on their cylinders. Pictures: dither and halftone tones measured on a grey ramp (0.25 pen): dither's mean error 0.17 -> 0.05 (dot gain: a lone cell's dash with round ends inks ~1.7x its cell), halftone 0.06 -> 0.02 (dots by their true area, out to 5/8 of a cell for black), lines 0.06 -> 0.05 (8 row levels, not 4).
  - [ ] Dither: Floyd-Steinberg's worms (Pillow's isn't serpentine); a blue-noise threshold would also be fast and order-free.

### Colour plots: C, M, Y, grey + K (2026-10-11 brainstorm)

The goal: colour "prints" from pens, now that the plot itself is reliable. A vector fill in a colour no pen has (or a grey drawn by the black pen) is drawn solid today: Orientations' `#4C4B49` cylinders come out black, and the gradient over them fights the fill.

- Pens: **K** always a very good fineliner (Micron 005/01). **C, M, Y, grey**: not sold as process colours; ~0.4-0.5 Stabilo point 88 (turquoise/blue for C, pink/lilac for M, yellow, a grey). A second round with Micron blue / red / green where it reads better. Five holders for one pass.
- Separation for vectors as for pictures: each flat colour unmixed onto the pens there are (`raster.unmix`, least squares on absorbances, works for any pens). Grey replaces what C, M, Y share (GCR): light greys to the grey pen, dark to K, so neutrals don't go muddy and the Stabilos lay less ink.
- **Side by side, not over each other** (no overdraw, the inks never run together): one line screen over the area, lines a pen's width apart, each line given to an ink in proportion (a green: C, Y, C, Y; darker: a K line now and then; lighter: some lines left as paper). Error diffusion along the lines picks which. At most one layer of ink anywhere: what ink.py wants. Mixing is optical, as in print at a distance.
- Or layered (`layers`: light under dark), each ink its own screen angle (Y 0, C 15, M 75, grey 30, K 45 as `raster.CMYK`), crossings short. More saturated, but two layers where they cross: the drying time between pens, and the check's 1.6 layers.
- **Yellow first** always: a yellow tip that touches darker ink picks it up and draws dirty. Then the light ones, K last (emit's light-first order). Between passes over another ink, a wipe on the wipe pad (`LRT_WIPE`).
- Mixing inks on purpose (wet cyan over yellow for a green) is uncontrolled: the tip takes the colour it goes over. Maybe on the wipe pad as a palette, as an experiment.
- Calibration: a swatch chart (each pen at 10 coverages, and pairs side by side), photographed by the overhead camera / scanned, gives each pen's real colour and density: the colours `unmix` uses, instead of the tags' guesses.
- Decided 2026-10-11: side by side; the black pen last whenever it fits.
- Done 2026-10-11: phase 1, `tone` solid / screen (one pen, lines `width / coverage` apart, by linear light). Phase 2, the *mix of pens* layer (`plot/mix.py`): shares solved over the simplex in linear RGB (each pen's share costs a little of its chroma, so greys go to grey and black), lines `max(width + bleed)` apart numbered on a fixed grid, each to a pen by the golden ratio. Orientations' `#4C4B49`: T3 94%, paper 6%.
  - [ ] Plot a swatch row with the real C/M/Y/grey Stabilos: does side by side read as the colour from a step back, or as stripes? If stripes: finer pens for the mix, or the lines' order along each line (dashes) as well as across.
  - [ ] Strong colours side by side are dull (a #60b040 green from C + Y is ~15% off): the Micron green round, or layered as an option after all.
  - [ ] The pens' colours come from their tags: phase 3 measures them (swatch chart + camera).
  - [ ] Choosing which pens a mix may use (now: all, each ink once).
- [ ] Phase 3: the swatch chart and the camera's measurement.

### Plot & cut: the drag knife (2026-10-12 plan)

The tool: a small blade in a holder, free to turn on its axis. Its tip trails the axis by an **offset** `d` (~0.25 mm for a 45° blade, more for 60°; to measure), so it turns to follow the cut like a castor. That trailing is also its flaw: it cuts round corners and enters a cut pointing the wrong way unless the path makes up for it.

**The blade's geometry (the knife kind's `draw`):**
- **Offset compensation**: the holder's axis runs `d` *ahead* of the wanted cut along each segment, so the tip lands on the line.
- **Swivels at corners**: where the direction turns by more than `swivel` (~15-30°), go to `d` past the corner, then turn an arc of radius `d` around the corner point until the blade faces the next segment, then carry on. A gentle curve (small turns, segments longer than `d`) needs no swivel.
- **Entering a cut**: the blade faces wherever the last cut left it. Options: a small **pre-swivel** off the part (a short stroke on scrap or outside the outline, in the first segment's direction), or **ramp in** along the path (Z down gradually over 2-3 mm, so the blade turns before it bites). Never plunge straight down at full depth: it tears and drags the sheet.
- **Overcut** on closed paths: run `d` + ~0.5 mm past the start, so the loop closes without a nick.
- Corners sharper than the blade can turn in (radius under ~`d`) and holes smaller than ~3`d` get a warning, as `small` does for pens.

**Not dragging the paper:**
- **Passes, shallow first**: the first pass only scores (light force, little sideways pull), the next go deeper, the last just through into the mat (~0.1 mm). Paper 80 gsm: 1-2 passes; card 250-300 gsm: 3-4. The scored groove guides the blade on later passes, so they pull less.
- **Every pass in the same direction**, so the blade already faces the right way; a closed path loops down without lifting (a helical ramp: Z lowered along the loop, one pass flowing into the next).
- **Pass-major order**: pass 1 on every shape, then pass 2 on every shape, ... The sheet stays whole (only scored) until the last pass, so nothing comes loose while it still has cuts to take.
- **The last pass from inside out**: holes and inner details first, small shapes before big, the outermost outline last (a containment tree from shapely). A piece cut free can't shift under a cut that's still to come.
- **Tabs (bridges)**: leave the outer outlines joined to the sheet by small gaps (0.5-1 mm, ~1 per 40-60 mm of perimeter, on straight runs, never at a corner). On every pass, or only skipped by the last pass (a "skin" tab, easier to break off cleanly). Off per shape (UI: click a tab to move or remove it).
- **Slow and gentle**: a slow feed for the first pass, low acceleration, slower still in swivels. Travel at the pen's clear height.
- **Clamping**: the magnets hold the edges, the middle can lift. Keep cuts a margin away from the magnets (they're obstacles, as for the travel planner), and cut the parts near the free middle before the ones near the clamped edges. For thin paper, a low-tack carrier (a sheet with repositionable spray) might be needed after all; try without first.

**Depth, force (the risky part):**
- The Z axis has play: ~1.67 mm lift per mm of press (plot/profiles/play.toml). A blade set by position will lift as it cuts, and cut shallower where the mesh is wrong. The user's holder is rigid (2026-10-12): 300 gsm card is ~0.35-0.4 mm, so the window between "not through" and "deep into the mat" is a few tenths, about the size of the mesh's and the play's errors.
- **Add a spring (decided worth it, 2026-10-12)**: the blade's shaft slides in a sleeve (a brass tube or a reamed printed bore), a spring above it, a collar as the stop. Z then sets how far the spring is compressed, so the force, not the depth: 0.1 mm of Z error is only `k x 0.1` of force. Aim ~2-4 N/mm with ~1 mm of compression (~2-4 N, the range of hobby cutters on card, ~200-400 gf). The play then lifts the axis by the same amount every time (constant force), which a calibration takes out.
- **The spring, in detail (2026-10-12)**: springs in parallel do add (k = k1 + k2 + k3), but a coil spring is soft sideways, so three of them don't hold XY: the **guide** does. Three around the axis only balance the push (no tilt). The cut's sideways pull (~1-2 N) must move the tip < ~0.05 mm.
  - Soft and **preloaded** beats stiff: the force is preload + k x compression, and a Z error only changes the `k x error` part. Eg. k ~1 N/mm preloaded to 2 N, 1 mm of compression in use: 3 N, and 0.1 mm of Z error is 0.1 N (3%). A stiff 4 N/mm one without preload: 0.4 N (10%+).
  - Coil: k = G d^4 / (8 D^3 n), steel G = 79000 N/mm^2. Wire 0.5, mean diameter 4.5, 8 active coils: ~0.85 N/mm; wire 0.6: ~1.75. From an assortment box, measured with a kitchen scale and Z steps.
  - Guide A: the holder body in two bushings (brass tube or reamed printed bores), as far apart as possible (≥ 3x the diameter), a close fit; the spring above, a collar as the stop that sets the preload. Simple, but its clearance tilts the tip and its friction is force hysteresis (stiction).
  - Guide B: a flexure, no play and no friction: two diaphragms (3 spiral or straight arms, spring steel shim 0.1-0.2 or printed for a first try), 10-15 mm apart, the holder body through their middles. Stiff sideways and in tilt, soft along Z, and its own k is the spring (or adds to one). The same idea as *Force at the tip: a flexure* under *Toolhead rework*: the knife could be its first user. Printed ones creep under a constant load: steel for the keeper.
  - Start with A; go to B if the cuts show stiction (depth that changes along a line, notches where it starts).
- **Blade exposure as a depth stop**: a screw-on nose cap sets how far the blade sticks out (card thickness + ~0.1 mm). The spring gives the force, the cap a hard limit on depth. If the nose rides on the paper it is also a presser foot that holds the sheet down beside the blade (round and smooth its rim, so it doesn't push the paper itself).
- **XY on the FSR with a cap** (the user's idea, 2026-10-12): a printed cap over the blade with a rounded point, concentric with the holder's axis, a known height over the blade's tip. The FSR probes the cap like a pen: XY is the axis (the blade's tip trails it by `d`, which the compensation handles, so the axis is what the tag wants). The cap's height is only as good as the print (±0.1), so Z still comes from a depth ladder on scrap card: that measures what matters (through, not through), and a rounded cap point gives the FSR a stronger signal than a fine pen.
- Two offsets, not to mix up: the **tool offset** (dx, dy, dz on the tag, from the FSR, as for pens) and the blade's **trailing offset** `d` (the tip behind its own axis: a property of the blade, not the print). `d` is ~0.25 mm for a 45° blade, ~0.5 for a 60°, to measure for each. The user has both angles: **60° for 300 gsm card**, 45° for paper and stickers (sharper corners).
- The blade's offset `d`: cut a test pattern (squares and stars with `d` stepped 0.1-0.5), the camera or an eye picks the cleanest corners.
- The mesh (`lrt_paper`) applies, as for pens.

**Into plot/ (the code):**
- A `knife` kind in plot/tools.py: `offset`, `swivel`, `overcut`, `ramp`, `passes` (a list of depths or forces), `feed`, `tabs` (size, spacing, on which passes). `draw` does the compensation; it doesn't take part in ink.py (no bleed, overdraw, fills, small-ink checks) and fills aren't cut, only outlines (centrelines).
- A new module for the planning (not cuts.py: that is cutting outlines into painted pieces): the containment tree, pass-major order, tabs, the margin from the magnets. order.py's nearest-next works within one level of the tree.
- A layer (or a shape) given to the knife is cut, not drawn. The knife always goes after every pen (the ink dry; nothing moves before it's drawn). Plot then cut on the same sheet is in register for free; a sheet printed elsewhere needs camera registration (the ladder crosses + homography, later).
- The preview shows cuts dashed, the compensated path and swivels, tabs as gaps, the passes' order.
- `python -m plot knife-test`: the calibration pattern (lines at Z steps, squares and stars over `d` steps, small holes).

**Steps:**
- [ ] Holder v2: sleeve + spring (~2-4 N/mm) + exposure cap, the RFID tag as on the pens.
- [ ] The FSR cap (rounded point, known height) for the knife's XY.
- [ ] Measure: `d` for each blade (squares and stars), the depth ladder on 300 gsm. A hand G-code: a 20 mm square, a star, at 2-3 depths on 80 gsm and 300 gsm.
- [ ] The knife kind: compensation, swivels, ramp in, overcut, passes on one path. Unit tests on the geometry (the tip's path lands on the line).
- [ ] The planning: inside out, pass-major, tabs, magnets' margin.
- [ ] UI: knife layers, tabs, preview.
- [ ] Later: kiss cut (stickers: through the face, not the liner), a creasing / scoring tool (a ball stylus, no offset), registration on pre-printed sheets.

## Pens, heights (limn_cam/)

- Each pen's z and offsets come from the FSR calibration now (above); the camera ladders (`notebooks/act-7-camera-ladder.md`) are the check.
- Z play: gentle (0.3, 2mm strokes) and loaded (0.6, 10mm at 3000mm/min) tests both let go within 0.5mm over touch, the same all over the sheet (`limn_cam play`). The few mm measured by hand don't show on the lift. Still open: tilt while drawing (the pull along X vs Y), which a lift test doesn't see.
- Cameras aren't essential (OpenCV is the `cam` extra). Next: fixed focus on the axiscam; a camera on the tool for line width and contact; an upward endoscope for tip dx/dy (notebook act-7).

## Scan (the camera tool, limn_cam/scan.py, the Scan tab)

- Done 2026-10-01: scans live in RAM (/dev/shm/limn-captures, LIMN_CAPTURES, 2 GB at most, the oldest go): the SD card is spared, a reboot loses them. Kept on the NAS: an S3 bucket (OMV's S3/MinIO; limn_cam/nas.py signs its own requests, no boto3), settings in plot-data/nas.json (owner only), ⇪ per capture or *upload each scan when done*.
- Done 2026-10-01: Hugin stitching (limn_cam/hugin.py, the viewer's *Hugin*): features on contrast-stretched copies, matches that disagree left out (halftone repeats), the camera's real scale and turn measured from all pairs, then the tiles only slide (+ lens barrel), seams by enblend: no ghosts. Sticker: 0.31 px rms, tiles 0.32 mm from where sent. Needs `sudo apt install hugin-tools enblend` on the Pi.
- Done 2026-10-01: the region for film: presets (35 mm, 120 6x4.5-6x9, 4x5, mounts) with a margin, drag/resize on the bed, arrows nudge, Z zooms to it, *Check corners* (4 shots, click the film's edge to set the region there, 0.05 mm).
- [ ] The camera's scale: Hugin measured 119.9 px/mm on the sticker (fov 16.02 x 9.01, turn -179.38) and 116.5 on the whole bed, against pens.toml's 125.9 (15.25 x 8.58, -179.2, before the tube was lengthened). Scan something of known size (a ruler, a printed grid) and set fov from it; the sticker sits a little higher than the paper.
- Done 2026-10-01: a flickering light (the new one: bands every 137 rows) is found in every shot (limn_cam/flicker.py: each row against its neighbours per column, the median over the columns, so the picture's own edges don't count) and taken out: 3 frames of the spot, the brightest of each pixel (the bands only darken and move between frames): 1.2 -> 0.44 grey levels, as clean as under the camera's own light. Each tile's info says so; the Scan tab warns. Stitching couldn't: the bands are in every tile, elsewhere in each. Setting: Flicker auto / always / off, frames.
- [ ] Still best fixed at the light (each shot takes 3 frames now, +0.3 s): full power or DC/constant current, or an exposure a whole number of its periods long (v4l2 exposure_time_absolute in crowsnest). The film LEDs: pick a driver without PWM.
- Done 2026-10-01: *Cameras* (header) shows Klipper's cameras live over the bed (Moonraker's list; the stream is closed with it), *Fluidd ↗* opens Fluidd. Where they are: `fluidd` in profiles/limn.toml or LIMN_FLUIDD, else the printer's host (the page's own when Moonraker is on localhost).
- [ ] Flat field from a shot of plain paper with the new light (the median of a scan's own tiles leaves blotches on colourful work).
- [ ] The Pi runs the old plot code (its UI on :4219 didn't answer 2026-10-01): pull, `uv sync`, restart limn_web.

- The camera (holder 41, `cam-u20`, tethered, U20CAM on `/webcam/`, crowsnest `[cam usbcam]`) works in machine Z: `clear_z` 7.5, `z_min` 4 (a guess after the tube was lengthened: measure how low it may go, then lower `z_min` in pens.toml).
- Done 2026-09-30: focus Z9.2 (above home; a flat peak 9.0-9.4), one shot 15.25 x 8.58 mm (125.9 px/mm), turn -179.2 (upside down, 0.8 degree askew), all in pens.toml. A 20-tile scan of a sticker stitched well (`~/limn-shot/captures/20260930-233601/stitch-126.jpg`, 5240 x 4241): registered on the overlaps, the light's fall-off divided out.
- Done 2026-10-01: the head live on the canvas (*head*, both tabs): `plot/profiles/toolhead.svg` (traced from the overhead camera, mm, origin at the tool point; a `toolhead.svg` in plot-data wins: download it from /api/toolhead.svg, refine, put it back in profiles/), a crosshair at the carried tool's tip, the camera's view on the Scan tab.
- [ ] The camera's centre against the tool point (`center` in pens.toml, 0 now). The overhead trace puts the lens body ~4 mm towards -Y of the tool point (rough: the optical axis needn't be the body's centre): look at crosses a pen drew at known places (`cross_centre`, `px_to_mm` in limn_cam/scan.py). Until then a scan pinned "under the plot" can sit a few mm off.
- [ ] Stitch: halftone print repeats, so an overlap can match one dot off (pairs moved up to 1.6mm; check with a plain texture); white areas come out a little too bright (the flat field from the median); a faint seam left in places.
- Whole bed, 2026-09-30 23:40: 225 tiles (X5-111, Y5-172, Z9.2), `~/limn-shot/captures/20260930-234022/stitch-{25,70}.jpg` (70 px/mm: 7446 x 11831, under the 90 MP cap). The Pi's copy stopped at tile 127: a snapshot timed out (one stream hiccup); the other 98 were taken from the laptop into the local copy (snapshots retry 3 times now, in limn_cam/moonraker.py: sync it).
- [ ] Stitch, from the whole bed: every tile has a bright bluish blob (the camera's light reflected): the median flat field from mostly blank paper gets it wrong. Take a flat field from a shot of plain paper instead (and keep it with the camera).
- [ ] Registration over blank paper matches falsely (288 of 416 overlaps used, tiles moved up to 2.8mm, gaps and doubled edges): leave out overlaps without texture, and cap a tile's correction at what the carriage can be off (a few tenths of a mm).
- [ ] Resume a scan cut short from the web tool (the job skipping the tiles it has).
- [ ] Focus stacking for film; refocus per tile tried only in tests.
- Film scanning: the backlit bed, stitched tiles, `refocus` for curled film.
- Done 2026-10-07: the Pi camera tool, docked by hand (`DOCK_MANUAL`, `DOCK_CLEAR`, README): `limn_endoscope/picam` (limn_picam: Pi Zero 2 W + HQ / Camera Module 3, HTTP on :4250, /snapshot.jpg, /capture.jpg, /capture.dng, /stream.mjpg, controls, autofocus), `picam` in pens.toml (fixed while on), the dock fenced off at X 110.
  - [ ] On the plotter: does pushing a tool on trigger the key's switch (`QUERY_ENDSTOPS` with the key closed, then pushed)? It docks on closed -> triggered within 20 s of the scan. Measure `manual_dock_x_max` with the tool on (110 is a guess: the reader is at X135, the holders from X125).
  - [ ] Write its tag: the carriage empty, hold the tag to the reader, `TOOL_TAG_WRITE PEN=picam NAME="Pi HQ" MOVE=0` (it also saves the tag's offsets as the carried tool's: `DOCK_RESET` after). Set its URL in pens.toml, then fov / turn / center / focus_z as for cam-u20.
  - [ ] Scans: the Scan tab's focus sweep moves Z; with the Camera Module 3, autofocus (`/capture.jpg?af=1`) instead, a setting for it.
- Done 2026-10-07: the Radxa camera tool: the same limn_picam, `--backend radxa` (a Cubie A7A / A7Z + Camera 13M 214, IMX214, 4208 x 3120; GStreamer with Radxa's ISP in v4l2src, `en-awisp=1`), `rxcam` in pens.toml. The HQ stays on the Pi Zero 2 W (`picam`). Both tethered on their own power, docked by hand. Tested on GStreamer's test picture only.
  - [ ] On the Cubie: `install.sh --backend radxa`; which V4L2 controls it has (exposure, focus: `v4l2-ctl -d /dev/video1 --list-ctrls`; maybe on a subdevice), whether autofocus works through them. The forum has reports of grey / near black-and-white pictures with the A733 images: check colour first.
- **Clip-on phone macro lenses on the 13M (2026-10-07 discussion).** Worth trying, for paper and quick looks; the HQ stays the film camera (raw, a real lens).
  - A close-up lens in front of a camera focused far: magnification m ≈ f_camera / f_clip-on, the film at about f_clip-on away. The 13M's lens is a phone one, f = 3.57 mm, f/2.0 (Radxa's spec), pixels 1.12 um. f_clip 25 mm: m ≈ 0.15, ~135 px/mm (3400 dpi), a 31 x 23 mm view (a 35 mm frame in one or two shots), ~25 mm away. f_clip 12.5 mm: m ≈ 0.3, ~270 px/mm, 15.5 x 11.5 mm, ~12 mm away.
  - Depth of field at f/2.2: ~0.5 mm at m 0.15, ~0.15 mm at m 0.3: flat film, Z or the camera's own focus (its lens moves a few mm' worth: fine focus, stacking without Z).
  - Distortion is the easy part (a grid shot, as the endoscope's lens.py, or Hugin's barrel). What can't be corrected: soft corners and field curvature, colour fringes, flare, and a clip-on that sits off-axis or tilted. So: the macro element only (of a wide + macro kit, the small one alone, never the wide/fisheye), held square and centred by a printed mount, not the phone clip; only the middle of each shot (more overlap).
  - The 13M gives the ISP's 8-bit output (its tone curve, sharpening): inverting negatives from it loses range. Fine for proofs.
  - [ ] Try: each clip-on on a ruler and a printed grid: px/mm, working distance, where sharpness falls off from the middle, the fringes. Keep the best one, design the mount.
- **Film camera choice (2026-10-07 discussion).** 35 mm frame 36 x 24 mm; film holds ~4000-5000 dpi (157-200 px/mm) of real detail, past that it is grain. 160-200 px/mm over a frame is ~22-35 MP. Fewer, bigger tiles stitch better: smooth film (sky, the base between frames) gives nothing to register on (see the false matches over blank paper above), so place tiles from carriage XY and use features only to fine-tune.
  - **Pick: the HQ camera (IMX477)** 4056 x 3040, 1.55 um pixels, sensor 6.29 x 4.71 mm, **12-bit raw** (DNG via picamera2/rpicam-still: dense negatives and the orange mask need the range; no MJPEG), manual exposure (fixes the flicker too: exposure a whole number of its periods), C/CS lenses on extension tubes.
  - Magnification m = 1.55 um x px/mm: m 0.25 → 160 px/mm, a 25 x 19 mm view (a frame in 2-4 tiles); m 0.4 → 260 px/mm, 15.7 x 11.8 mm (~3x3 tiles), oversampled to cover a soft lens.
  - Extension = m x f, lens-to-film ≈ f(1 + 1/m): 6 mm wide: 1.5-2.4 mm, ~21-30 mm away (lightest, soft corners: crop to the centre); 16 mm: 4-6.5 mm, ~56-80 mm (the likely best of the set); 35 mm: 9-14 mm, ~120-175 mm (too tall for the head). The 10x macro zoom: too heavy; maybe a fixed-stand reference.
  - Aperture: small pixels are diffraction-bound early. Effective f-number N(1+m) ≲ 4-5 keeps the Airy disc to ~2-3 px, so f/2.8-4, and the depth of field is then only ~0.2-0.3 mm: hold the film flat (glass or a tensioned holder), or focus-stack by Z.
  - Pi Camera V3 / Radxa 12MP AF: phone lenses, closest focus ~10 cm → ~35 px/mm; they need a close-up lens and the optics aren't made for it. Their one trick: a focus sweep by the VCM without moving Z. UVC: the U20 already gives ~126 px/mm (~3200 dpi) at 15.25 x 8.58 mm, so it is the baseline; but 8-bit MJPEG.
  - [ ] Weigh the HQ board + each lens + tubes against what the head carries.
  - [ ] CSI to the head: a long flex ribbon to the Pi (fatigue on a moving carriage) or the Pi Zero on the tool (above).
  - [ ] Test before building: HQ + 16 mm + ~5 mm tube on a ruler and a negative's edge print, f/2.8 / 4 / 5.6: px/mm, where it stops getting sharper, grain visible or not.
  - [ ] Light: high-CRI white or RGB for colour negatives, no PWM (above).

## The web UI: keeping it maintainable (2026-10-01 discussion)

Plain HTML/JS with no build step was right while it was small: nothing to install on the Pi, the server serves files as they are. At ~1,900 lines of JS (app.js 1,400, in shared globals) it is at the point where it needs some structure, but not a framework with a build.
- **Done: browser tests** (plot/tests/test_ui.py, Playwright, Firefox; `uv run --group ui pytest plot/tests/test_ui.py`): painting, the Paths view, corners, region, film presets, Hugin. The paint bug shipped because nothing clicked through the UI; this is the safety net that makes the rest possible.
- Done 2026-10-01, partly: the UI is in files by job now (zoom.js, cams.js, head.js, leds.js, panels.js beside app.js and scan.js), still classic scripts sharing globals; the floating layout (panels over a full-page canvas, windows, touch) is in panels.js.
- [ ] **ES modules, no bundler**: `<script type="module">`, one module per panel (plot canvas, paint, output, tools, pens, scan, nas) and a small `state.js` (S, api, store) instead of globals. Browsers load them as they are: still no build, still nothing on the Pi.
- [ ] **Types without TypeScript files**: `// @ts-check` + JSDoc on the modules, checked with `tsc --noEmit` on the laptop only (dev). It catches the wrong field names that are most of the bugs here.
- When the panels' state gets hard to follow (the redraw rules in fill()/quietly()): Preact + htm (or Lit) vendored as one file in static/, still no build. Not before the modules: most of the pain is globals, not rendering.
- Not: React/Vite/npm on the Pi. A build step would be the thing that breaks after a `git pull` on the plotter.

## ext/, klipper/

- Drying: per pen (`dry` minutes in pens.toml, 240 for the Stabilo 88, 10 for fineliners), twice that printing. To check on a real long plot: the SET_PIN beeps land between moves without a stall. Maybe a Fluidd button for `TOOL_DRY RESET=1`.
- Toolchanger key rework: see *Toolhead and harness rework* below.
- Tag reads: the PN532 listens for the whole 0.5 s now (`i2c.py`, `begin(retries=0xFF)`), untested on the plotter. If it still misses: read while approaching the reader from its edge, which reads best. Needs the edge's X and whether Z7 is safe for the last stretch.
- Holder 45 read empty with its pen in it (2026-09-29): seating or the switch.
- Key open with a tool still saved as carried: the saved tool is stale, the meshing could clear it instead of undocking.

## Toolhead and harness rework

What's wrong now: the holders are slightly angled in X (the first tools push on the dock), and the key's centre is a bit off (a small crash as it enters a tool). The harness is being redone (2026-10-12), with the power distribution.

### The plan (2026-10-12): a toolhead MCU and a new harness

Decided with the user on 2026-10-12:
- **A small Klipper MCU on the toolhead** (RP2350-Zero or RP2040-Zero class, `[mcu tool]`, USB or CAN to the Pi). It carries:
  - K's driver and K's endstop (`^PA2` on the Melzi now): *Driving K on the toolhead*.
  - An **ADXL345** in place of the MPU9250, for the input shaper. Klipper reads it on any MCU, over SPI (or I2C in recent versions: check the Pi's Klipper). For I2C: CS to VCC (that selects I2C), SDO to GND (address 0x53; to VCC 0x1D), INT1/INT2 unused.
  - An **HX711** and the BF350 strain gauge: *The strain gauge*.
  - The QRE1113 lock sensor, the tool's ID resistor, the tool's power switch and UART: *The coupling*.
- **Z stays on the Melzi as it is**: its stepper, its endstop (`^!PC4`) and the BLTouch. X and Y and their endstops stay too.
- **The `rpi` Pico goes, for a smaller MCU.** Its jobs today: the NeoPixels (gpio 15, 16, 17), the buzzer (gpio 9), the MPU9250 on software I2C (gpio 4/5). The MPU is replaced by the ADXL on the toolhead.
  - [ ] Where the NeoPixels and the buzzer go: on the toolhead MCU if their wires end near it, or a small MCU in the electronics bay. (My reading: the toolhead MCU takes them. To confirm with the user.)
- **A stepper, its endstop and the probe that stops it on one MCU.** Klipper doesn't require it: multi-MCU homing works, the endstop's MCU timestamps the trigger so the position stays right, but the stop goes through the host and comes a few ms late (~0.01-0.03 mm at Z's `homing_speed: 3`), and on a busy USB it can fail with *Communication timeout during homing*. So K moves with its endstop, and Z, its endstop and the BLTouch stay together. The load cell sits on the toolhead while Z is on the Melzi: fine for step-and-read ladders (Z stops before each reading); as a moving Klipper probe it would be multi-MCU homing.
- **Pins on the toolhead MCU**: K step/dir/enable (3), K's endstop (1), HX711 (2), ADXL345 (SPI 4, or I2C 2), QRE1113 (1 ADC), the tool's ID (1 ADC), the tool's power switch + UART (3): 13-15. With the NeoPixels and the buzzer (4): ~19. A Zero board has 20 GPIOs on its edges and 9 on pads underneath, ADC on GPIO 26-29: enough, 2 ADCs to spare (a Hall sensor, a thermistor).
- **The chain afterwards**, roughly: Z's motor (4), the Y and Z endstops, the BLTouch (5), power (24 V + GND, doubled), USB (or CAN, 2). Out of it: K's 4 motor wires and its endstop, the MPU's I2C. Today: 21 wires.
  - [ ] Count the real wires and plan the ribbons: motors apart from signals, a GND between signal wires.
- [ ] Bench: a Zero board with a DRV8834 carrier on K, the HX711 and the ADXL345, on 5 V first, before a PCB.
- [ ] The circuit diagram for the docs (projects/limn/content/electronics.md): the toolhead MCU, the HX711, the BF350 quarter bridge.

### Power distribution (redone with the harness)

- **24 V (or 12 V) + GND down the chain, a buck to 5 V on the toolhead** for the MCU, the tool's 5 V and the LEDs. ~5x less current than sending 5 V: ~5x less drop (and a far smaller share of 24 V), ~25x less heat in the wire.
- **K's driver**: a DRV8834 runs from the 5 V (2.5-10.8 V); a TMC2209 wants ≥ 4.75 V and browns out on a dip at 5 V, so it goes on the 24 V.
- **USB (or CAN) for data only**: its VBUS not tied to the toolhead's 5 V (two supplies feeding each other); GND shared. USB-PD from the cable instead (a CH224K/HUSB238 asking for 9-20 V) needs a PD source with data, which the Pi isn't: skipped.
- **The tool's 5 V through an e-fuse or a PTC**, switched on only when the tool is seen and the key is locked (*The coupling*).
- [ ] Draw the whole tree: the PSU, the Melzi, the Pi, the Dock and the beds, the chain, the toolhead's buck, the tool. Which branch has which fuse.

### Power budget of the tool's 5 V (2026-09-30)

Typical, at 5V (check the real modules):

| Load | Typical | Peak |
|---|---|---|
| USB camera | 0.1-0.2 A | 0.3 A (autofocus, IR LEDs) |
| Bright LED | 0.1-0.2 A (0.5-1 W) | the same |
| BLTouch | 15 mA | ~0.3 A while its pin moves |
| MCUs | RP2040 ~30 mA, ESP32 ~0.25 A | ESP32 Wi-Fi bursts ~0.5 A |
| "1 W" laser module | 1-1.5 A if 1 W *optical*; ~0.2 A if 1 W drawn | the same |
| Pi Zero 2 W + HQ camera (stress case) | 0.6-0.9 A | 1.0-1.3 A booting, loaded |

Worst case ~1.3 A going on and on.
- [ ] **PTC**: hold 1.5-1.6 A (it holds less warm, a toolhead is warm), trip ~3 A, 6V or more, 0.1 ohm or less, 1812. It trips in seconds: it saves the wiring from a lasting short, not the electronics from a sliding pin.
- [ ] **Or an e-fuse** (TPS2595 family): limit set to ~2 A, trips in microseconds, soft start for a camera's or a Pi's inrush. It does the PTC's job and more, in one chip.
- [ ] **Voltage**: the Pi Zero warns under ~4.63V. PTC + pogo pins + wire can take ~0.3V at 1.3 A: feed the toolhead 5.1-5.2V, and two pogo pins in parallel for 5V if one is rated under ~2 A.
- [ ] **Wire gauge** (2026-10-01): 26 AWG ~0.134 ohm/m (chassis rating ~2.2 A), 30 AWG ~0.34 ohm/m (~0.86 A). A wire's rating is about heat. A 30 AWG piece only a few cm long can carry more than its rating, because the thicker wire and connectors at both ends draw the heat away. Past ~5-10 cm, its middle runs as hot as a long 30 AWG wire. Derate in a packed cable chain next to stepper wires; in the moving part, use high-flex stranded wire (thin wire fatigues).
- [ ] **Voltage drop matters more than heat at 5V**: the GND wire carries the same current, so count the run twice. 1 m of 26 AWG each way at 1.3 A: ~0.35 V; plus 10 cm of 30 AWG each way: ~0.09 V more. That's already under the Pi Zero's 4.63V with 5.0V in. Hence 24 V down the chain and a buck on the toolhead (above).
- **Cable chain** (2026-10-01, guesses: 26 AWG, ~1 m, Z NEMA 8 ~0.6 A/phase, K micro linear stepper ~0.2 A/phase): heat per metre in W/m.

  | Wires | Current | Heat |
  |---|---|---|
  | Z, 4 wires | 0.6 A | ~0.19 W/m |
  | K, 4 wires | 0.2 A | ~0.02 W/m |
  | Tool 5V + GND, 1 pair | 1.3 A | ~0.45 W/m |
  | Tool 5V + GND, doubled | 0.65 A per wire | ~0.23 W/m |
  | USB-C, endstops, sensors, accelerometer | mA | ~0 |

  ~0.65 W/m in all at worst (at 5 V; far less with 24 V). Heat is no problem in an open, moving chain; the limits are the chain's fill (≤ ~60-70% so wires can slide), bend radius/flex life, and noise.
  - [ ] Noise: the stepper wires carry chopper PWM (tens of kHz, fast edges). Keep them in their own ribbons. In the sensor ribbon, put a GND between signal wires (I2C/SPI over ~1 m next to steppers glitches); lower I2C speed or SPI if it does. The endoscope: decoder board on the toolhead, only USB through the chain, never the analog VOUT next to the steppers.
- LED draw: ~3.0V × 350 mA ≈ 1.05 W (700 mA ≈ 2.1 W). From 24V through a buck driver (~85%): ~50 mA (~100 mA at 700). From 5V: ~0.25 A through a buck, 0.35 A through a linear driver (it draws the LED's current). On only per tile: ~30% average over a scan.
- The 5 W laser and the milling spindle: always tethered, their own supply and their own interlock, never through the coupling.

### Driving K on the toolhead (2026-10-12 discussion)

- **Not from the MCU's pins.** A GPIO gives ~4-12 mA (RP2040: 50 mA for all pins together); K draws ~0.23-0.34 A/phase (14.5 Ω at 3.3-5 V). It's bipolar (4 wires): each coil needs current both ways (an H-bridge per coil), and the coil's kick at switch-off needs diodes. A ULN2003 is for 5-wire unipolar motors, not this.
- **Klipper only speaks step/dir.** A bare dual H-bridge (DRV8833) driven by the MCU's PWM would work in our own firmware, not in Klipper. So a step/dir driver chip: 3x3 mm (DRV8834 4x4, TMC2209 5x5); the StepStick-size carriers 15x20 mm.
- **K (14.5 Ω, 3-5 V, gearbox, 10 mm):**
  - At 5 V straight it makes ~1.7 W per coil, ~3.4 W held: too hot to hold for long in a motor that small. Limit it to ~0.2 A/phase (it's disabled after each lock move already: `K_LOCK`, `K_UNLOCK`).
  - At 5 V the coil's resistance alone nearly sets the current (5/14.5 = 0.34 A): the chopper only trims it. Fine.
  - Precision comes from the gearbox and the screw, not microstepping: one full step is already tiny at the screw. Microstepping a 20-step can-stack motor gives smoothness, not accurate positions between full steps. The gear's backlash is the error: approach the end position always from the same side, home on the switch, a spring to preload the screw if the lock needs it.
- **Driver choice:**
  - **DRV8834**: 2.5-10.8 V, step/dir, up to 1/32, current set by a resistor on VREF. Runs happily from 5 V; Klipper sees a plain step/dir driver (`microsteps` must match the M0/M1 pins). Louder than StealthChop.
  - **TMC2209**: StealthChop (quiet), UART current setting, Klipper's `[tmc2209]`. VM ≥ 4.75 V: on the 24 V.
  - **TMC2300**: 2-11 V, StealthChop, 3x3 mm, made for low-voltage motors like K. Mainline Klipper has no `[tmc2300]` (check).
  - Ready boards (BTT EBB36/42, Mellow SB2040) carry one driver, for an extruder: it would do for K, but they're bigger than a Zero and a carrier, and bring a heater and fans we don't use.
- **Z, if it ever moves to the toolhead too:** NEMA 8, 5.2 Ω, 1.3 mH, 0.4 A, run ~0.3 A RMS. From 5 V torque falls past roughly 10 rev/s (2.1 V go into the resistance at 0.4 A); from 12-24 V much faster.
- **USB in a moving cable**: Klipper's toolhead boards mostly use CAN because a USB drop mid-plot shuts Klipper down (`Lost communication with MCU`). A shielded, flex-rated cable, short (≤ ~1.5 m), a ferrite, its own ribbon away from the steppers, GND shared. CAN (2 wires + power) is the fallback, through a USB-CAN adapter or a CAN bridge board.
- **Klipper config** (pins and bus names are placeholders; check Klipper's Config Reference for the exact options):
  ```
  [mcu tool]
  serial: /dev/serial/by-id/usb-Klipper_rp2350_<id>-if00

  [manual_stepper axis_k]
  step_pin: tool:gpio10
  dir_pin: !tool:gpio11
  enable_pin: !tool:gpio12
  endstop_pin: ^tool:gpio13
  # rest unchanged; with a DRV8834, microsteps = its M0/M1 setting

  [adxl345]
  cs_pin: tool:gpio1
  spi_bus: <the SPI bus on those pins>
  # [resonance_tester] accel_chip: adxl345

  [load_cell]
  sensor_type: hx711
  sclk_pin: tool:gpio20
  dout_pin: tool:gpio21
  sample_rate: 80            # must match the board's RATE pin
  ```
- [ ] Measure K's step angle and gear ratio (18:1 in the config) and the screw's lead, to know its full step at the screw.

### The strain gauge: a BF350 and an HX711 (2026-10-12 discussion)

The user's gauge: a **BF350-3AA** (350 Ω foil, gauge factor ~2.0-2.2, 3 mm grid), kept for years, superglued on.
- **The MCU's own ADC can't read a bare bridge.** It's 12 bits on 3.3 V (0.8 mV a step, ~9 good bits). A quarter bridge with the BF350 on 3.3 V gives `3.3 × 2.08 × ε / 4` ≈ 1.7 mV per 1000 µε, and a pen's push is probably tens to a few hundred µε: a fraction of one step.
- **An in-amp in between makes it readable** (INA333, `G = 1 + 100k/RG`, RG ≈ 100 Ω for ~1000): ~1.7 V per 1000 µε. But Klipper's `[load_cell]` has no MCU-ADC sensor: our own module, polled from the host, a slow reading and no probe. The ADC's linearity errors (the RP2040's are known; check the RP2350's) show up in the force.
- **A bridge ADC is simpler, and Klipper reads it as it is**: `[load_cell]` + `[load_cell_probe]` take an HX711/HX717 (2 GPIOs, bit-banged, any pins) or an ADS1220 (SPI + DRDY, 5 GPIOs). Klipper has no I2C load-cell ADC (a NAU7802 would be our own module).
  - HX711: ~1 €, 10 or 80 samples/s (the RATE pin: many boards tie it to 10, check). HX717: up to 320/s. ADS1220: up to 2000/s, lower noise, ratiometric with REFP0/REFN0 across the bridge.
  - **The rate only matters for probing while moving** (the user asked why): Z goes on between samples, so the touch is seen up to `speed / rate` late, plus a few samples for the filter, and that overtravel presses the pen. At 1 mm/s: 10/s → ≥0.1 mm, 80/s → ~0.0125 mm a sample. A **step-and-read ladder** (move, stop, settle, read, like the FSR's) needs only a few readings a step: there the rate is only speed (the HX711's filter settles in ~4 samples: ~0.4 s a step at 10/s, ~0.05 s at 80/s). At these rates the HX711 resolves as finely as the others.
  - **The user's pick: an HX711, RATE at 80.** Fine for ladders and a first test; for a moving `load_cell_probe` it's at the slow end (an HX717 or ADS1220 then, on almost the same wiring).
- **Which wires go long: the digital ones.** The ADC sits by the gauge, within a few cm. The bridge's ~1 mV picks up stepper noise on a long lead (a differential input rejects only part of it), and in a quarter bridge the lead's resistance is in the arm, so warming copper (~0.4 %/K) reads as strain (3 wires to the gauge cancel that). SPI or the HX711's clock/data are 0/3.3 V: up to ~30 cm is easy, with a 33-100 Ω series resistor at each line's driving end and a GND beside the signals. With the toolhead MCU everything is on the toolhead: keep it all short.
- **The MCU's ADC inputs stay useful** for analog sensors with a big swing: the QRE1113 on the lock, a DRV5055 Hall on the rider's tip (~1 mV/µm), a tool's ID resistor. RP2040, RP2350A and the Zero boards: 4 (GPIO 26-29); RP2350B: 8 (GPIO 40-47).
- **The glued gauge**: calibrate the whole assembly with weights, or a kitchen scale under the pen (a Z ladder, grams against counts), not from the gauge factor. Check first: ~350 Ω across it; no continuity to a metal part under it; a straight line over 3-5 loads; the same reading going up and down; the drift with a weight left on for 5 min (superglue creeps a little); the drift with warm air and no load. A second gauge on the opposite face (half bridge) doubles the signal and cancels most of the temperature drift.
- [ ] Bench: the BF350 + 3 × 350 Ω 0.1 % on an HX711 board, on the Zero, `[load_cell]`, coins.

### Sensing the pen's contact at the toolhead (2026-10-11 discussion, summed up)

Where it ended: **the FSR stays** for XY and z: it's the only option giving both, for every tool, with no change to the toolhead. The weak part is the Z axis, not the FSR: its play, the ~2 N before the rider lifts, the tip moving sideways as it tips. The strain gauge on the toolhead (above) is the next try at feeling the touch from the first gram.

What we learnt:
- **The sensor has to sit between the pen and the Z carriage**, below the Z play (1.67 per mm of press). Not in the tool's coupling: the tool sits on three pins in V-grooves and the key's ramp clamps it, so tool and toolhead are one body (the user's correction); the pen's push changes the pins' seating force by a fraction of the clamp's preload.
- **The Z axis**: a printed Z plate (the rider, with inserts), the lead screw nut at one end, the toolhead (~200 g) in the middle, a slot riding the bare guide rail at the other end. Once the pen pushes harder than the toolhead and rider weigh at the pen (~2 N), the plate tips about the nut and the rail end lifts ~2x as far as the toolhead. Before that only the plastic bends (~0.04 mm per N at the tip: 4 µm for 10 g). The surfaces round the tip are 3-5 mm away, printed, on the carriage (fixed in Z).
- **The cost of the give**: tipping moves the tip sideways along the screw–rail line, ~height below the pivot × angle: 40 mm × 0.006 rad (0.3 mm of lift on a 100 mm plate) ≈ 0.24 mm, probably in every plot where the press differs.
- **Tried 2026-10-11, the carriage's MPU9250 as a tiltmeter**: 12 `ACCELEROMETER_QUERY` averaged per Z step (sd ~35-60 mm/s² a reading), the Stabilo over cell (1, 1) to 0.40 mm past touch: **no signal**, the mount tilts less than ~0.1°. The FSR flattened from ~0.25 mm past touch: the play giving at a constant force, or the sheet saturating. An accelerometer on the plate would show *where* the give is, not a fine touch; `ACCELEROMETER_MEASURE` (4000/s) has ~30x less noise per step than the query. Data: `~/limn-shot/acc-2026-10-11.*`.
- **Sensors on the play** (QRE, Hall, switch, tilt) trigger only once the rider lifts, at ~2 N: too late for fine tips, unless a **counter-spring** carries most of the weight. Its force must not change over Z: a constant-force spring (3-6 mm wide, 0.5-2 N; ~1 N at the tip), or a long soft extension spring; not magnets or a counterweight. Then the tip floats up through the play at ~0.1-0.2 N, a big motion for a sensor.
  - **A Hall at the rider's tip**: a 2x1 mm N52 disc on the tip, poles along Z; a DRV5055 (3.3 V, ratiometric, grade A1-A4 so the magnet doesn't saturate it) or an SS49E on the carriage wall. The field across its face crosses zero as they line up, ~linear ±1 mm, ~1 mV/µm (A1): a few µm averaged on a 12-bit ADC. During a steady descent the touch is a knee in time, no profile needed. The TMAG5273 (3-axis, angle) is a SOT-23-6, but its breakouts are too big here.
  - **QREs at the tip** (the user's idea): a frame surface moves the whole Z travel (5-8 mm) past them, out of their ~0.5-4 mm range; they'd need a surface that follows Z without tipping. A top/bottom pair would cancel drift.
  - Catches: the slot's friction on the bare rail (stick-slip: a smooth rod, PTFE or grease), the tip moving sideways as it lifts (~0.2 mm for 0.3 mm), rattle on fast moves.
- **Strain gauges on a part that carries the load** feel the touch from the first gram, whatever the play does (pen → toolhead → plate → nut). On printed PETG the strain is ~30x aluminium's, but plastic creeps under the toolhead's weight, a gauge stiffens thin plastic, and its expansion (~70e-6/K) reads as strain: a half bridge on the same part and a tare right before each touch. Better: a small aluminium or steel strip printed into the rider as the load path, the gauges on it.
- **A bar load cell** (TAL220 type) between rider and toolhead must lie flat (the force across its length, as in a scale): upright it reads almost nothing. It adds ~6-8 mm to the stack; a 500 g-1 kg cell, tared before each touch, ~0.1-0.5 g with an HX711; it gives ~0.1-0.2 mm at full scale.
- **No**: the Z motor's current or StallGuard (`rotation_distance: 0.03125`: 1 N at the pen is ~0.017 N·mm at the shaft, ~0.1% of its torque, under the screw's friction; the driver holds the current constant anyway); a piezo (no impacts in this machine); an accelerometer as a jolt detector (too weak for a soft fineliner at slow speed).
- **In a redesign**: make the give deliberate. A flexure hinge between the nut block and the plate, a light spring pre-loading the plate onto a stop on a stiff arm; the pen lifts it off above a set force, a switch or optical flag at the stop sees it (one digital pin; the user's slot sensors fit). ~0.2 mm of travel to the stop, so the tip barely moves sideways. Or a kinematic seat (Voron Tap) between the plate and the toolhead, with a counter-spring for ~0.1-0.3 N.
- **Per tool**: a spring-loaded pen in each tool (a bushing, a light spring, a tiny magnet on its top end) and a Hall sensor in the key's tip reading it slide up. No electronics in the tools, each tool's spring its own force; costs a sliding fit and five rebuilt holders.
- [ ] A kitchen scale on the bed under the Stabilo, Z down in 0.05 mm steps to 0.4 mm past touch: the grams where it stops rising is the force the rider lifts at, also what every plot presses at when Z is too low; it sizes a counter-spring. The same for a Micron 005: grams at first ink, grams where the line widens.
- [ ] Draw one cross at 0.1 and one at 0.4 mm of press and compare: the sideways shift from the tipping.
- [ ] Rough counter-spring test: a rubber band from the carriage to the tip; does the tip lift smoothly at a small force (a spring scale, coins on the pen)?
- [ ] Bench Hall test: an analog Hall (SS49E/DRV5055) and a magnet on a spare ADC, the knee during a slow ladder.

### Force at the tip: a flexure between toolhead and Z carriage

An FSR behind the key would see the key's preload less the pen's push, and FSRs are poor at small changes on a big load (hysteresis, creep). It's only good for crashes. A strain-gauge load cell carrying the whole toolhead is better, but too big for this toolhead. The compact version is a flexure with a displacement sensor:

- **Where**: between the toolhead and the Z carriage (which rides on Y). The Z carriage is the ground: bolt the flexure's fixed end to it and hang the toolhead from the moving end, so all of the pen's push goes through it. The Z play is between the carriage and the rails, further down, and doesn't disturb it. Nothing else may bridge toolhead and carriage (stiff cables, a second screw): a loose loop in the cables, strain relief on the carriage side. The toolhead's weight sits on it all the time: tare right before each pen-down.
- **Shape**: a parallelogram, two thin parallel blades clamped at both ends. It moves straight up and down and stays stiff sideways, so the drawing's drag and off-axis moments hardly show. Keep the pen's axis near its middle.
- **Blades**: spring steel shim (0.1-0.2mm, eg. feeler gauge stock) or FR4, clamped with screws. They're linear and don't creep. Printed blades (PETG over PLA) are fine to try but creep under the constant load.
- **Stiffness**: each blade clamped at both ends is `12 E I / L^3`, with `I = b t^3 / 12`, so two blades give `k = 2 E b t^3 / L^3`. Aim for ~2-10 N/mm, so the pen's 0.2-2N moves it 0.05-0.5mm. Eg. steel (E = 200 GPa) b = 8mm, t = 0.1mm, L = 20mm: k = 2 x 200000 x 8 x 0.001 / 8000 = 0.4 N/mm, too soft: t = 0.2mm gives 3.2 N/mm. PETG (E ~ 2 GPa) b = 10, t = 1, L = 15: ~12 N/mm.
- **An overload stop**: a hard stop ~0.5mm away, so a dock crash or a hand can't bend the blades past springing back.
- **Sensor**: a magnet on the moving side, a Hall sensor on the ground side 1-2mm away (TMAG5273, I2C). Or the QRE1113 facing a white patch ~1mm away (analog, its best range: the right use for it). Or strain gauges on steel blades and an HX711.
- **Calibrate**: known weights (coins) on the tool's tip give k; force = k x displacement.
- **Ringing**: it adds give. With k = 5 N/mm and a 100g toolhead, `f = sqrt(k/m) / 2pi` ~ 35 Hz, vertical only (Z moves are slow). A little foam or rubber in the stop damps it.
- **What it gives**: each pen's touch by probing with the pen (no ladder), the press by force instead of by height (and it gives a little, like a spring-loaded holder: it rides out the uneven height and the play), and crashes at the dock. In Klipper: a threshold is a probe endstop, and a small module reads the force.
- Or inside each tool: a pen on a spring, a magnet and a Hall sensor, through the new pogo pins. It's per tool; the flexure covers all of them at once.

### Finding a tool's centre

The key sticks out ~7.5mm, so a QRE1113 anywhere on the carriage body is out of range (it works ~0.5-5mm, best ~1mm). On the key's tip it would work (wires through the key's limited turn), but it goes into every socket.
- [ ] **Chamfer first.** A generous lead-in on the key's tip and the socket, or a key that can float a little: a small miss becomes a slide. Sensing then only has to get close.
- [ ] **A magnet in each tool and a 3-axis Hall sensor on the carriage** (TMAG5273 or MLX90393: 2-3mm packages, I2C). A 3x2mm neodymium magnet, pressed in at a known spot by the socket, reads from 10-15mm. The field points at it: its offset from one or two readings, no scan. Dirt, light and plastic colour don't matter. The field's strength gives a rough height (a holder's tilt), and a polarity or a second magnet could tell tool types apart.
  - **With the 49E (TO-92 linear Hall, on hand), 2026-10-11:** one axis each, perpendicular to the branded face; ~1.4-3 mV/G at 5V (ratiometric: ~1-2 mV/G at 3.3V), linear ±~1000G, so no saturation risk here. On a 12-bit MCU ADC ~1-2G per reading, ~0.3G averaged; the null drifts with temperature, so take a baseline away from the magnets before each scan. Field model (N42, axis pointing at the head; on-axis Bz / slope of the across-field at the centre):

    | magnet | 10mm | 15mm | 20mm | across-slope 10mm | 15mm |
    |---|---|---|---|---|---|
    | 6x3 | 110G | 39G | 18G | 14 G/mm | 3.4 G/mm |
    | 8x3 | 180G | 66G | 31G | 22 G/mm | 5.7 G/mm |
    | 10x5 | 370G | 143G | 69G | 39 G/mm | 12 G/mm |

    Detected to ~25-40mm (a few G), located only within ~1-1.5x the gap sideways. The sideways field crosses zero exactly over the magnet's axis: a zero, not a peak, so magnet strength, gap and the sensor's gain drop out; only its null offset counts (1G ≈ 0.05mm at 10mm gap with an 8x3, ≈ 0.2mm at 15mm). Scanning past also gives the gap: the two lobes of that sideways field are ~1.2x the gap apart.
  - The two sensors: both on the head's face toward the dock, one sensing along X (centre in X), one along Z (centre in Z, the holder's height/tilt), side by side; their 2-3mm offset is a constant, measured once (the camera or a careful dock). Scan in X past each holder (move, dwell, read, like the ladders), fit the zero crossing to the readings around it.
  - Neighbours: a holder's field bends its neighbours' zeros unless the pitch is ≳2.5x the gap (the ends are lopsided). Alternating polarity per holder also tells holders apart by sign. Steel nearby (screws, rails) and the key's motor bend the field: magnets and sensors away from them, a baseline per holder spot without magnets if needed.
  - [ ] Bench: an 8x3 magnet on a ruler, a 49E at 3.3V on a spare ADC (the Klipper RP2040 GPIO 26-28), readings every 0.5mm at 10 and 15mm: how well does the zero repeat? Check the 49E's datasheet minimum supply (some clones want 4V+: then 5V and a divider).
- [ ] **The coupling as a sensor.** If each of the three contact pairs can be read on its own before power goes on, the order they close in, on the way into a holder, tells which way it tilts, and when they close tells its height.
- A camera looking down (endoscope, tool camera) with a marker per tool also works, but is more work for this.

### The coupling: power and data to the tool

5V, GND, 5 data pins (pogo), the metal coupling as a power path. Power off until needed, turned on like the bed's: two pogo pins bridged by the tool.
- [ ] Order: the pogo pins touch before the coupling (ground). Turn the power on only when the bridge is seen *and* the key is locked, not on the bridge alone.
- [ ] Data pins as inputs, pull-ups off, until the tool has power and ground: a pin driven high into an unpowered tool powers it backwards through its chip's input protection.
- [ ] The Pololu MOSFET switch: reverse voltage protection, but check for a current limit. If none, a PTC fuse on the 5V for a pogo pin sliding onto the wrong pad; a soft start for a camera's inrush.
- [ ] A ground pogo next to the data pins, for their return path.
- [ ] TVS and small series resistors on the data pins: every hot plug is an ESD event.
- [ ] Tool type on one pin instead of the foil: a resistor to GND per tool type, read on an ADC (presence and type; worked out below, *Tool presence and type*). Or a 1-Wire EEPROM (DS2431) that could carry the tool's offsets too, a tag without the reader.
- [ ] A camera tool, wired (the user keeps everything wired together):
  - USB through the pogo pins: full speed (12Mbps) is fine for stills and film scans. High speed (480Mbps, what most UVC cameras want) needs D+/D- on a matched pair of pins, the shortest paths and a ground pin next to them: worth a try, but fragile.
  - A Pi Zero on the tool with its CSI camera (the HQ camera), reached as a USB network device (gadget mode) through the pogo pins at full speed. Stitching and focus stacking stay on the tool.
  - Wi-Fi (an ESP32-S3 camera, 5V and GND only) as the fallback.
- [ ] A BLTouch tool: two data pins (servo, endstop) to a Klipper MCU pin; keep the endstop line clean, its timing matters.
- Pins: ID 1, BLTouch 2, 2 spare (I2C for tool sensors).

### Tool presence and type: an ID resistor, like the beds (2026-10-08)

The coupling's third contact to GND through a resistor in the tool, a pull-up on the toolhead side, read on an ADC. The same as the bed's DETECT (`micropython/lrt_dock_mcu.py`, `BEDS`), but with more types: 16 types + "bare bridge" + "no tool" (the beds have 6).

- **Pull-up to the ADC's own 3.3 V, never 5 V**: the reading is then a ratio (R / (R + Rpu)), the supply drops out. The RP2040's ADC pins (GPIO 26-29) aren't 5 V tolerant.
- **Bands equal in counts, not resistors on a log scale.** 18 bands over the 12-bit range, 241 counts each, resistor picked as `Rpu * x / (1 - x)` and rounded to E96 (1%). Rpu = 10k 1%:

  | Type | R (1%) | Counts | Band |
  |---|---|---|---|
  | 0 bare bridge | 0 | 0 | 0-120 |
  | 1 | 619 | 239 | 120-361 |
  | 2 | 1.33k | 481 | 361-602 |
  | 3 | 2.15k | 725 | 602-843 |
  | 4 | 3.09k | 967 | 843-1084 |
  | 5 | 4.12k | 1195 | 1084-1325 |
  | 6 | 5.49k | 1451 | 1325-1566 |
  | 7 | 6.98k | 1683 | 1566-1807 |
  | 8 | 8.87k | 1925 | 1807-2048 |
  | 9 | 11.3k | 2172 | 2048-2288 |
  | 10 | 14.3k | 2410 | 2288-2529 |
  | 11 | 18.2k | 2643 | 2529-2770 |
  | 12 | 24.3k | 2901 | 2770-3011 |
  | 13 | 32.4k | 3129 | 3011-3252 |
  | 14 | 46.4k | 3369 | 3252-3493 |
  | 15 | 75k | 3613 | 3493-3734 |
  | 16 | 162k | 3857 | 3734-3975 |
  | none (open) | ∞ | 4095 | 3975-4095 |

  Every value sits ≥ 110 counts inside its band. Worst error from two 1% resistors: ±20 counts (mid-scale); the RP2040 ADC's noise (~9 effective bits) and its DNL steps (at 512, 1536, 2560, 3584) a few more: average 16+ samples. 24 types (~170 counts a band) would still fit; past ~32 the margin goes.
- **Contact resistance** (pogo, a dirty ball): 0.1-1 Ω against 619 Ω or more. Doesn't matter. The 162k and a 10k pull-up: keep the ID wire away from the stepper wires, or a 100 nF on the ADC pin (time constant ~1 ms at 10k, fine).
- **Settle, then believe it.** The contacts chatter while the balls seat: accept a type only after it reads the same band for ~100 ms, after the key is locked. A value between bands for long = a fault, not a type.
- **"Bare bridge" as the default is ambiguous**: if the coupling's metal is the ground path, an ID contact touching the frame also reads 0 Ω. Better: the default tool gets a resistor too (type 1), and 0 Ω means "check the toolhead".
- **No tool and a broken wire both read open.** Cross-check with the holder switches (MCP23017): a tool on the head ⇔ its holder empty. A mismatch stops the tool change.
- [ ] Which MCU reads it: the toolhead MCU (2026-10-12 plan; before it, the `rpi` RP2040 with GPIO 26-28 free). The tool change runs in Klipper macros, so a small `ext/limn` module reading the pin with Klipper's `adc` (like `adc_scaled`) gives `printer.limn.tool_id` straight to `_DOCK_TOOL`. The Dock (GP26-28 free) would work too, through `!LRT>>` lines, but it's the bed's MCU and its loop is time-critical.
- [ ] If the third contact is the 1-Wire line (electronics.md: 3 V, GND, 1-Wire): a resistor to GND kills 1-Wire (it idles high through ~4.7k). One or the other on that pin: the resistor gives presence + type; the DS2431 gives type + offsets, but no presence until it answers.
- [ ] More than ~24 types: a second ID pin (16 × 16), or combine with the tag (the resistor says "a pen", the tag says which).

## Endoscope (the 2026-10-01 notes; the live work is in limn_endoscope)

### Endoscope camera and its adapter (2026-10-01)

Reclaimed medical endoscope: a 4-wire sensor (VDD, GND, VCLK, VOUT) on a USB decoder board (Xitech 0bde:8076, UVC, 400x400 YUYV/MJPG only, crowsnest `[cam endocam]`, port 8082 = `/webcam3/`). 400x400 and 4 wires look like an OmniVision OV6946/OVM6946 (a guess, not checked); its companion chip is the OV426.
- The sensor has no ADC and sends no digital data: VOUT is raw analog, one pixel's level after another, clocked by VCLK (the board drives it, a few MHz: 400x400 at 30 fps is 4.8 Mpixel/s plus blanking). Not composite/NTSC: a composite capture card can't read it.
- The decoder: clock out, sample VOUT in step with the clock (ADC), find the frame start, black level, demosaic (Bayer), white balance, gamma, then UVC over USB. No lock on VOUT = the USB side streams packets but no frames.
- The pot (2026-10-02): the user traced it on the board photos: it sits in the **clock** path and is not connected to the LED driver IC next to it. (I said once that it set LED brightness. That was a guess and it's wrong. The older note here, VOUT's level, was a guess too.) What it does there, unconfirmed, most likely first:
  - **Sampling phase**: an RC delay on the clock (to the sensor, or to the decoder's ADC). The decoder samples VOUT a set time after its own edge, and the cable adds a delay both ways, so a longer or shorter probe needs a new phase. Datasheet: "due to analog circuit delay, data output may start from rising or falling edge relative to XVCLK".
  - **Clock edges/level**: a series R that slows the edges (less coupling into VOUT; the datasheet allows tr/tf up to 30 ns) or sets the swing (XVCLK VIH ≥ 2.31 V, VIL ≤ 0.99 V, input 10 pF).
  - Not the frequency: the datasheet wants a 4 MHz input clock within 500 ppm, so it comes from a crystal or a PLL, not an RC.
  - [ ] Check: measure the pot's two ends and wiper to the clock IC's pin, the connector's XVCLK pin, a cap to GND or an ADC CLK pin. With the decoder running, scope VCLK at the connector while turning it: a phase shift, slower edges or a change in amplitude?
- From the OVM6946 datasheet (v1.06): XVCLK and VOUT are both I/O. During vertical blanking the host *writes* exposure/gain registers over VOUT, clocked by XVCLK (header 0xA6, then 8 registers, MSB first), and at each frame start the sensor sends its register values back the same way. VOUT levels: black 1.0 V, data 1.0-1.8 V (linear range), data type 0.3 V, at most 2.45 V. A line is 288 clocks (212 of data), and the sample rate is 8 MHz (2× the 4 MHz clock).
- Other ways to read it: a fast ADC (8-10 bit, ≥20 MS/s, e.g. AD9226) clocked with VCLK, into an FPGA or an RP2040's PIO; plus the ISP steps in software. Weeks of work; the board already does it.
- [ ] Adapter, VOUT: it carries MHz analog over a thin cable. Put a GND between VOUT and VCLK (G-VOUT-G-VCLK-G-VDD), keep the run short, and route it away from the stepper and heater wires. Use shielded cable if the run is long, shield to GND at the board end only.
- [ ] Adapter, VCLK: square edges couple into VOUT (noise, bars). Twist it with a GND, and maybe add a series resistor (22-47 ohm) at the board end against ringing.
- [ ] Adapter, VDD: noise on VDD goes straight into the picture. 100nF + 1uF as close to the sensor as possible; check VDD *at the sensor end* under load.
- [ ] Clean the no-clean flux off the adapter's sensor connector (IPA 99% and a brush, plenty, then dry): liquid flux that spread past the heated joints never activated and stays tacky and ionic (leakage, corrosion with VDD next to GND), and flux wicked into the mating contacts gives exactly an intermittent VOUT/VCLK. Then inspect the joints for bridges and cold joints (the scan camera at 126 px/mm).
- [ ] A locking connector with strain relief: the toolhead moves, and a pin that flickers on VOUT/VCLK is exactly "online, no frames".
- [ ] Never plug the sensor in while the board has power: bare sensor pins, no ESD protection. TVS on the adapter if it's going to be plugged often.
- [ ] Scope check at the adapter: VCLK a steady square wave; VOUT a pattern that repeats per line and changes with light. VOUT flat = sensor or contact.
- [ ] 2026-10-01 dropout: the USB side is clean (UVC streamed, `Failed to resubmit video URB (-19)` at the unplug), ustreamer online=false, 0 frames. uvcvideo stats while `v4l2-ctl --stream-mmap` hung: one stream with 12309 frames (an old session, likely the IR cam), one with 0 packets (likely the endoscope: nothing at all arrives, not even empty packets). Check which is which (`grep -H frames /sys/kernel/debug/usb/uvcvideo/*/stats`, the directory name has the device number from `lsusb`). Did "works on another computer" have the same sensor and adapter, and show a picture?
- Encryption: no. The sensor is a dumb analog chip on 4 wires. Single-use medical scopes sometimes have an ID/EEPROM chip on extra pins to stop reuse, but the video isn't scrambled.
- Own capture, for a few frames at chosen places: an 8-bit ADC module (AD9280, ~32 MS/s) or a 12-bit one (AD9226), read by an RP2350's PIO into RAM. One 400x400 8-bit frame is 160 KB, which fits in its 520 KB. Steps: measure the board's VCLK frequency and VOUT's frame layout (sync, blanking, Bayer order) with a scope while it works, then drive VCLK yourself. A slower clock would allow a slower ADC, but the minimum clock is unknown (droop, dark current), so risky. A few weekends' work, and it doesn't make the toolhead smaller: the sensor is the tiny part either way, and the decoder board can sit up the cable. Plan: *Endoscope: own snapshot capture* below.
- Light (2026-10-01): no LEDs in the tip. Two light fibers end at a polished face on the connector, ~1 cm from the camera connector. A 1W LED shone at it works: objects show from 5-10 mm away. The LED gets very warm, and an 8° collimating lens didn't help much.
  - Not like telecom fiber (single-mode: 9 µm core, accepts ±7°). Endoscope light fibers are multimode, glass bundles or plastic, with NA 0.5-0.6: they *want* a wide cone (±30-35°) on a tiny spot. A collimator does the opposite: a narrow beam over a wide spot, and most of it misses the fiber.
  - Étendue sets the ceiling: light in ≤ (fiber area × NA²) / (LED emitter area × 1). A 0.5 mm fiber at NA 0.5 against a 1x1 mm lambertian die: ≤ ~5%, whatever the lens. So brightness per mm² of emitter (luminance) matters, not watts.
  - [ ] Measure first: the fibers' diameter and spacing on the face (the scan camera, 126 px/mm, holder 41), and their NA (light into the tip end, measure the spot from the connector on paper at a known distance: NA ≈ sin(atan(r/d))).
  - [ ] Butt-couple: a flat-top (domeless) high-luminance LED (e.g. Cree XP-L HI, Osram Oslon Square/Black Flat class, high CRI 90+ for colours) with its emitter 0.1-0.3 mm from the fiber face, held by a bore that fits the connector. A domed LED keeps the die mm away and loses most of it. If both fibers fit inside one emitter, one LED; otherwise one per fiber.
  - [ ] If the LED must sit further off (heat, the camera connector 1 cm away): image the emitter onto the face with a ball lens or a short asphere, the spot no bigger than the fibers and the cone within their NA. It doesn't beat butt-coupling, it only moves the LED.
  - Measured (the user's model, ±0.1-0.2 mm, `~/limn-shot/endo-connector-model-20261001.png`): two fibers of Ø0.9 mm, 1.40 mm apart, so together ~1.8-2.3 mm across. One emitter of ~2 mm square covers both: a 3.5 mm LED package is the right size, not too big. Any emitter area beyond the fibers is only heat. Ceiling at NA 0.5: fibers ~1.0 mm²sr against ~12.6 for a 2x2 mm die, so ≤ ~8%; ~10 lm into the fibers from a ~1W LED at best.
  - Solid 0.9 mm cores are likely plastic (PMMA) fiber: it softens around 80°C. Keep a ~0.1 mm gap (a kapton ring) and the LED face cool; never press a hot LED onto it.
  - LEDs: flat-top/domeless ones from the flashlight scene (Luminus SFT-40-W / SST-20, Cree XP-L HI) on copper boards: AliExpress flashlight shops, Mouser/DigiKey for the genuine parts. A cheap first test: one flat 2835/3030 high-CRI LED cut from a strip, pushed against the ferrule.
  - Scrap sources (best first): an old phone's camera flash LED (small bright emitter ~1-1.5 mm, flat, made for 1 A pulses: suits per-tile snapshots; often on a flex, keep a piece to solder to; dual-tone flashes have two emitters side by side); a cheap LED torch, bike light or headlamp (a 3535 XP-E/XP-G class emitter, already on a star board: the holder and heat path come with it); a car headlight LED bulb (flat CSP chips on a metal core). Household bulbs: no (many weak 2835s, filament chips, or COBs too big, and a mains driver with charged capacitors). The best of all: the light source from the scope's own console, if one turns up.
  - Pick: one white emitter ~1.5-2.5 mm, flat or a small dome, on its own board. Measure the emitter with the scan camera. Unknown rating: start at 100 mA on a current-limited supply, note Vf, go up while watching the heat. Phones: take the battery out first and never bend or puncture it.
  - [ ] Holder: a bore that fits the ferrule, the emitter centred on the pair of fibers, the kapton spacer, the LED board screwed to metal.
  - [ ] Heat numbers: ~60-70% of the electrical power is heat in the die. Target die ≤ 85°C with ~35°C around the toolhead: ≤ ~70 K/W in all at 0.7 W of heat. A 16/20 mm star screwed with paste to a metal part of the toolhead, or a small finned block (~15x15x10 mm, ~20-30 K/W), is enough even continuous. Run 350 mA rather than 700 mA: about half the heat, better lm/W.
  - [ ] Power: not from a Pi GPIO (a few mA). A constant-current buck module (PT4115 class, 350 mA, 6-30 V in) from the printer's 24 V, its DIM pin on/off from a Klipper MCU pin (`[output_pin endolight]`, not PWM; check DIM's threshold against 3.3 V), or a Mean Well LDD-350H. If it goes through the tool coupling's 5V instead: +0.35 A in the 5V budget above (at 5V a linear driver drops ~0.6 W itself).
  - [ ] limn_cam: SET_PIN on before a tile's snapshot (let auto exposure settle a few frames), off while moving: ~30% duty over a scan.
  - [ ] Heat: light only for the snapshot (a Klipper output pin, on/off, constant current), not all the time: the average power then is tiny, and a short overdrive is possible. Not PWM: a rolling shutter shows it as bands. MCPCB on aluminium; printed holders in PETG/ASA, not PLA. OV6946 heads (~1 mm) with their USB board are sold cheap as hobby endoscope kits (a spare and a datasheet-like reference); OV9734-based 3.9 mm digital USB modules (720p) if a little more room turns up.

### Endoscope probe cable: bends, shortening, soldering (2026-10-01)

The user plans to resolder the adapter, run several cameras, and shorten their cables.
- Bends do kill them: the conductors are very fine (often 40-44 AWG or micro-coax). Each sharp bend work-hardens the copper until a strand cracks, often inside intact insulation. The weak spots are where the rigid tip meets the cable and at the connector's strain relief. An intermittent break on VOUT/VCLK looks exactly like today's "enumerates, 0 frames". In motion keep the bend radius ≥ ~10× the cable's diameter. Better: let the probe cable not move at all; clamp it at the toolhead and let a sturdy cable take the flexing.
- [ ] Shorten: cut the probe cable near the toolhead and end it on a small adapter board (pads for the 4 wires, 100nF + 1uF on VDD, a locking connector), the decoder or own capture right next to it. A shorter cable changes VOUT's level (less loss), so retune the board's pot. Before cutting the first one, prove the whole chain works on an uncut probe.
- [ ] Before soldering, know what the wires are (the scan camera, 126 px/mm):
  - shiny copper/amber strands that won't take solder: **enamelled** wire. Most fine wire has solderable polyurethane enamel: dip the end into a fresh solder blob at ~380-400°C for a few seconds until it tins. If it won't (polyimide enamel), scrape it off with a scalpel or 600-grit paper;
  - a braid around an insulated core: **micro-coax**. Twist the braid into a pigtail to GND, the core is the signal (VOUT, maybe VCLK). Don't overheat the dielectric;
  - loose bare strands: twist them, then tin.
- [ ] How: clamp or tape the cable down first, so the wire can't move or carry load. Solder to pads (1.27 mm perfboard, an adapter PCB), never wire-to-wire in the air. Strip ~0.5-1 mm, twist and tin the wire, pre-tin the pad, lay the wire on, touch with iron + gel flux, no extra solder. Fine conical tip, 0.3 mm solder, magnification, a grounded iron (the sensor has no ESD protection).
- [ ] After: clean the flux (IPA), check continuity and that neighbours don't short. Then glue the wires to the board 2-3 mm before the joint (UV glue or epoxy) so the bend never lands on the joint: wire breaks right at the edge where solder wicked in and stiffened it.

### Endoscope: own snapshot capture, RP2350 PIO + AD9226 (plan, 2026-10-01)

- 2026-10-02: the probe's board is `OJOS-OV426-V1.0`. The OV426 digitizes VOUT and outputs DVP + I2C, so the Pico may read DVP instead of an AD9226. Small ADC options, RTL-SDR (no), the regulator (`6627` = XC6206 3.3 V): `limn_endoscope/notebooks/endo-1-notes.md`.

Goal: a few raw frames on demand from several probes, no decoder boards. One RP2350 (Pico 2), one AD9226, one analog mux; the ISP steps run in Python as a limn_cam source.
- Several cameras, one ADC: snapshots only need one probe at a time. Shared VCLK, VOUTs through an analog mux (ADG704/TS5A-class, ≥50 MHz bandwidth) into a single ADC. Switch each probe's VDD on its own (a load switch) if idle probes load the clock or mux. One ADC per probe is 12 GPIO each: 2-3 at most on the RP2350B, more board, no gain for snapshots.
- AD9226: 12-bit pipeline ADC up to 65 MS/s, 7 clocks of pipeline latency (a sample comes out 7 clocks later), input span 1 or 2 V p-p. [ ] Check the module's schematic: many have an op-amp front end scaled for a larger (±5 V class) input, and a sub-volt VOUT would then use only a few of the 12 bits. Change its gain/offset or bypass it. That front end does the job of the decoder board's pot. [ ] Its data outputs must be 3.3 V (DRVDD), and it has a minimum clock rate (datasheet).
- Wiring: D11..D0 to 12 consecutive GPIOs (PIO `in pins` reads a contiguous run; for 8-bit take D11..D4). VCLK and ADC CLK on two side-set pins. Mux select + probe enables on plain GPIOs.
- PIO, two state machines:
  - SM0 makes the clocks and never stalls: VCLK, then ADC CLK a set delay later, so the ADC samples VOUT once it has settled after the sensor's edge. Its delays give the phase in 6.7 ns steps (150 MHz); patch them at load to sweep the phase, and pick the phase with the most contrast. The sensor needs a steady clock all the time (exposure, readout), so the clock can't come from the capturing SM: a full FIFO would stall it and stop the clock.
  - SM1 captures, enabled only for a snapshot: `wait 1 pin ADCCLK` → (data-valid delay) → `in pins, 16` (or 8), autopush 32 → DMA into RAM. 12 bits stored as 16 = 2 B/sample, or 1 B with 8 bits.
  - Sketch of SM0: `.side_set 2` · `nop side 0b01 [d1]` (VCLK up) · `nop side 0b11 [d2]` (ADC samples) · `nop side 0b10 [d3]` · `nop side 0b00 [d4]`; pixel rate = sys / (4 + d1..d4).
- Memory: at ~6 MHz VCLK and 30 fps a frame is ~200k samples, blanking included: 400 KB at 16-bit, 200 KB at 8-bit, in the RP2350's 520 KB. Capture one frame + a margin, raw, alignment in Python. A slower VCLK means longer exposure and fewer samples, but the minimum clock is unknown (droop, dark current); try it once things work.
- Out: USB CDC (full speed ~1 MB/s, a frame in ~0.3-0.5 s, fine for snapshots), a tiny command set (`probe N`, `phase P`, `snap` → raw bytes + header). Host: `limn_cam` source `endoraw`: find line and frame period (autocorrelation), black level from optical-black rows/cols, Bayer order (try all 4 against a known coloured target), demosaic (OpenCV), white balance, gamma.
- Order:
  - [ ] 0. **Sniff first, with the working decoder board** (after the adapter is resoldered): tap VCLK + VOUT and leave the board in charge. A logic analyser (or a second Pico with sigrok-pico) gives the VCLK frequency, duty and any pattern at power-up. **The init sequence exists** (datasheet): the decoder writes exposure/gain over VOUT during vertical blanking, and the sensor answers with 0xA6 + 8 registers per frame. Capture both so own capture can replay the writes, or run with the defaults (AEC 0x0020). Then the AD9226 clocked from the board's VCLK, through SM1 with an `ADC CLK = VCLK + delay` variant, gives VOUT's real waveform: levels, line/frame layout, blanking, black rows. No scope needed.
  - [ ] 1. SM0 drives VCLK at the measured frequency into one probe, no board. Look for the same VOUT pattern.
  - [ ] 2. Phase sweep, black level, first raw grey frame, then Bayer → colour.
  - [ ] 3. The mux and a second probe; switching settles in a few frames (exposure), so drop those.
  - [ ] 4. limn_cam integration; the LED on only for the snapshot (see light above).
- To order: 2× AD9226 module (one spare), Pico 2 (or RP2350B board for spare pins), an ADG704-class mux, load switches for probe VDD, an SMA/u.FL pigtail or short coax for VOUT, a cheap logic analyser if there isn't one.

## Beyond pens

### Uses beyond pens (2026-09-30 brainstorm)

Where it shines: plot a design, then cut it on the same sheet, in register. The crosses of `limn_cam ladder` are already a print-and-cut registration: find them with a camera, fit the homography, cut along the design.

- **Cutting** (the bed is cutting mat): the rotating micro knife for stickers, stencils, papercraft, card, sewing patterns, masks for airbrush; a drag knife; a scoring/creasing stylus for folds.
- **Embossing and scoring**: a ball stylus for paper embossing, foil (cold foil, "foil quill"), leather tooling; Braille.
- **Engraving**: a diamond drag engraver (metal tags, acrylic, scratch art).
- **Film and flat scanning** (the camera tool, powered through the coupling, untethered): negatives on the backlit bed, stitched from frames at known XY, focus-stacked by Z; artwork and documents too, lit from above.
- **PCBs**: plot etch resist onto copper clad with a paint marker, etch; or a UV LED tool exposing dry-film resist or cyanotype paper directly (UV glasses).
- **Painting**: brush and watercolour (the `brush` kind already reloads), calligraphy with fountain and brush pens.
- **Dispensing**: a syringe for glue or solder paste; pipetting into well plates.
- **Pick and place**: a small vacuum nozzle for SMD parts, stickers, rhinestones, seeds on paper.
- **Testing**: a capacitive stylus tapping a phone or tablet (a touchscreen test robot); pressing keys and switches (with the load cell, force curves).
- **Measuring**: probing an object's height map with the BLTouch tool or the pen (2.5D scan); the camera measuring parts against the grid.
- **Laser** (later, see safety): engrave wood, leather, card; cut paper and thin card along a plotted design.

### Laser safety (before the first switch-on)

- [ ] **Glasses for the laser's wavelength.** Most diode laser modules are blue, 445-455nm. Glasses sold as "IR" protect at 808/1064nm and do nothing at 450nm. OD4 or more at the module's wavelength (on the label or the datasheet).
- [ ] **Never on or through the cutting mat**: most mats are PVC, and burning PVC (and vinyl sticker sheet) gives off chlorine gas. A metal honeycomb or a sacrificial board under anything lasered.
- [ ] An enclosure or shield, a lid or hand switch that cuts the laser's power in hardware (not only in G-code), smoke extraction, and someone watching for fire.
- [ ] `plot/`'s laser kind never touches (no press, no play); it needs its own safe travel height and an off (`M5`) on every error path, and Klipper's own laser PWM off at startup and shutdown.

