# Next

## BED_5's new FSR sheet: to calibrated pens (2026-10-07, in progress)
- **Read `notebooks/act-8-fsr-checkpoint.md` first**: what went wrong on 2026-10-07/08 and the plan (Z from the paper, XY from ratio-fitted borders at a force target, hardware first). The items below are from before it; check them against it.
- **2026-10-09, the rework (`notebooks/act-9-fsr-rework.md`)**: contact is the sheet's rise whichever cell, the edges are tap sweeps judged by the two cells' share, unsure measurements write no tag. On the plotter since the evening of 10-09, with 47k loads on the sense rows: the reference (Stabilo) and three Micron 01s calibrated, their marks drawn. Results and next steps: act-9, *With the loads, on the plotter*.
  - [x] Deployed; `LRT_FSR_MEASURE` x3 before the loads, x2 after; `LRT_CALIBRATE` with the new contact.
  - [x] 47k from each sense row to GND, `"fsr_load": 47000` (5868a30). Rest and in the air every cell reads 0, row 3 is an ordinary row, no faulty cell, no give-ups since. The signal is ~3x smaller (median 134 at 0.08 mm).
  - [x] `LRT_FSR_SURVEY` after the loads: early 30, weak (0, 2) and (1, 2).
  - [ ] `dz_trim`: the reference was calibrated with `DZ_TRIM=0.3` (dz 0.31), the Microns (holders 41-43) probed with the default 0.1. One value in beds.py (and the pens again) or a per-pen press?
  - [ ] Retune to the loaded scale against a ladder: `respond` 150, `press_strength` 450 (never reached now: every tap goes to the 0.1 cap), `locate_strength`, `sure`; `early` 30 in the config (on 60 contact came out 0.3 mm low). Or a bigger load (100k) for more signal.
  - [ ] X repeats only to 0.17 mm over five runs (Y 0.06, z 0.08), even with the sweep on the same line; each run claims ±0.003. Taps logged (`VERBOSE=1`) over a few runs, a lower `PRESS`; then a sigma that includes run-to-run scatter.
  - [ ] The Y edge uses the weak (1, 2): move it to a strong pair (the survey: (3, 7), (1, 6), (3, 4), (1, 3)), or find out whether column 2 is the sheet or its ribbon.
  - [ ] If a pen takes too long: `sweep: (0.5, 0.05, 0.4)` in beds.py, ~30 taps fewer (as good at ±50% patchiness in the simulation, one 0.1 mm error at ±70%). A Micron took ~4 min on the plotter (10-09).
  - [ ] Record raw frames of a real `LRT_FSR_MEASURE` (all 32 cells per tap, not the top 6) as test fixtures: `border()` is tested against #30 only.
- [ ] `LRT_FSR_MAP TIP=2.0,2.13`: the origin (refined by edge searches) and pitch, which cells answer. The first run (2026-10-07 23:27) 'touched' 4 mm up on (3, 0)'s preload and mapped nothing: fixed (descents go by their rise over the air), to run again. Set `origin` in ext/limn/beds.py from it; `faulty_cols` if whole columns stay silent.
- [ ] Columns 4-7 answered as (3, 0) on the first hand map, and (3, 0) has a resting preload of 80-130 since the sheet was handled (was <=16): the ribbon and the (3, 0) corner, before trusting those columns.
- [x] Done 2026-10-09 after the loads (act-9). Was: `LRT_FSR_SURVEY` (the reference Stabilo in holder 45): faulty/weak cells, `early`, the aim. Its warnings say whether `z_cell` (1, 1) and the edges (1, 1)|(2, 1), (1, 1)|(1, 2) suit this sheet.
- [x] Done 2026-10-09 (act-9): X 0.17, Y 0.06, z 0.08 over five runs. Was: `LRT_FSR_MEASURE CLEAN=0` x3: X, Y and z repeat to ~0.05?
- [ ] `LRT_CALIBRATE` with paper on the bed (the test mark at Y 120-150): is z right? Then `LIMN_TOOL_CALIBRATE T=41..44`, each pen's tag named first (`TOOL_TAG_SET PEN=`).
- [ ] Fit the tests' fresh model (`FsrBed(fresh=True)`) to the new sheet's survey: its response curve (304 at 0.02mm, 469 at 0.04 on (1, 0)), crosstalk (~0.15, row 3 ~0.35).
- [ ] The survey takes ~8 min and presses only the cells' centres: faults near a border (the old sheet's col 4) slip through; LRT_FSR_MAP covers those.
- [ ] Fine pens on the new sheet: a ladder with a working fineliner (the test one is bent); `respond` for fine tips.
- [ ] 2026-10-11: the last plot after a full calibration was right for every pen except the Micron 01 Blue, whose z was slightly too high. The 0.10 mm press cap and other depth limits came from before the 47k loads: relax them for fine tips (a press aimed at a force, not a depth cap) and re-probe the Blue. The loads, as bodged, make BED_5 slightly uneven: fixed in the bed redesign.
  - Done in code 2026-10-11 (to deploy): `TAP_PRESS` 0.1 → 0.2, capped by a pen's `press_max` (not its plotting `press`); beds.py strengths rescaled to the loaded sheet: press_strength 450 → 120 (a Stabilo stops ~0.1, a fine tip goes to 0.2), respond 150 → 60, early 60 → 30, sure 450 → 150, locate_strength 180 → 70, press_limit 950 → 600. Tests: the old models keep the old strengths (`UNLOADED`), `test_the_loaded_sheet` is the new one. Then: full `LRT_CALIBRATE` with the Stabilo, the pens, the Blue's mark.
  - [ ] Known weights on (1, 1): `~/limn-shot/fsr-weights-2026-10-11.py` (strength against grams, creep over 10 s).
- [ ] Notes of the old sheet below (col 3/4 faults, weak (2, 4), Y-edge spread) are history: check each against the new sheet before acting on it.

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
- [ ] FSR and fine tips (2026-10-07): the FSR feels a fine tip only ~0.2mm in (simulated: `gain=700`), so a fineliner's contact is already deep and its taps go ~0.45-0.5mm past first touch even with the press_max cap (a felt tip: ~0.07). Done 2026-10-07: the floor at rest is <=6 (col 4 ~24), so coarse descents stop at `early` 60 and the rest is in fine steps; two Stabilo measurements agreed to 0.05mm (X), 0.01 (Y), 0.03 (z). Still to try: a lower `respond` (150) for fine pens, with a working fineliner (the test one is bent). The taps already press only the pen's own `press` (0.1 for fineliners); the ~0.2mm before the FSR feels a fine tip at all is what is left.
  - [x] Superseded 2026-10-09 (act-9: `locate()` only names the cell now, the sweeps reach a cell and a half). Was: `locate()` varies: the Stabilo's Y came out 1.6, 1.68 and 3.87 (the edges: 2.13), X 1.37 and 1.52 (2.00). The measurement aims again when it lands a cell off, but why? Taps at 0.15 (the Stabilo's own press) vs 0.1, row crosstalk at the col 4/5 border, column 4's preload. Log `last_response`'s points in locate on the plotter.
  - [ ] **The new sheet's columns 4-7 don't answer** (2026-10-07, a light-tap map: `~/limn-shot/fsr-2026-10-07-new-sheet-map.png`, data in `fsr-2026-10-07-manual.jsonl`): presses there read as (3, 0), below Y ~42 nothing. Rows 0-3 and columns 0-2 answer, column 3 partly. The old sheet's cols 4-7 worked, so the board is fine: check the ribbon (seated, square in its connector, the tail's traces). Then: the origin (the map puts the sheet ~1mm further +X, ~0.15mm +Y: ~(112.0, 59.75)), LRT_FSR_SURVEY, LRT_CALIBRATE.
  - New sheet, measured: at rest ≤16; first touch on (1, 0) at z ~3.49, 304 0.02mm in, 469 at 0.04 (twice the old sheet's (1, 1)); up its column rows 0-2 ~0.15, row 3 ~0.35; row 3 answers (230-490) like the others, reads 30-50 with the pen over the sheet. `dead_rows` is empty now, the tests' fresh model fitted to these.
  - [ ] New FSR sheet on BED_5 (2026-10-07: the old one is damaged). Then: `origin` if it sits elsewhere, LRT_FSR_MATRIX at rest, LRT_FSR_SURVEY, LRT_CALIBRATE, pens. Compare its survey with the old sheet's ladders (`~/limn-shot/fsr-2026-10-07-manual.*`), refit `frame_bed5`'s fresh model to it.
  - [ ] After the fixes of 2026-10-07 (mesh off the sheet edge, depth on (1, 1), two-spot descent): run LRT_FSR_MEASURE 3-4 times and check the Y edge repeats as X does (0.05). Cells differ a lot: (1, 2), (2, 1), (1, 5), (2, 5) strong (400+ 0.02-0.04mm in), (1, 4) and (2, 4) weak (~150-230). A fine pen needs its own ladder.
  - [ ] The Stabilo at 0.1mm taps, three runs (2026-10-07): X edge 113.949, 113.959, 113.998 (0.05 apart), Y edge 52.471, 52.481, 52.705 (0.23 apart: the third run's tip estimate was 1.52, the others 1.6), contact 0.714-0.740 over the BLTouch. Y wants more runs, maybe `repeats` on the edges as on z.
  - [ ] On the real sheet: are the edges as repeatable at 0.1mm taps (fineliners) as at 0.3? Run LIMN_TOOL_CALIBRATE twice on one pen and compare the offsets. If not, `PRESS=0.2`.
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

## Pens, heights (limn_cam/)

- Holder 41 has the Stabilo "Stabilo Test Blue" (stb-88, dz 0.24, primed 2026-09-30): the only pen in use. The rest were taken out to keep them from drying.
- Micron 01 blue (dz 2.25): drew nothing even at Z0.8 on sheet 2. Seated? slid up in its clamp? writing? Then a ladder, `limn_cam ladder T<n> --z 2.0:0.4:0.1`.
- Staedtler 0.05 (dz 1.05): check on the next sheet it goes back in.
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
- BED_5 FSR: column 3 still faulty; z and edges moved to column 1, the aim to column 5. A 0.05 liner can't be measured on it (≤121 at PRESS=0.5).
- Toolchanger key rework: see *Toolhead rework* below.
- Tag reads: the PN532 listens for the whole 0.5 s now (`i2c.py`, `begin(retries=0xFF)`), untested on the plotter. If it still misses: read while approaching the reader from its edge, which reads best. Needs the edge's X and whether Z7 is safe for the last stretch.
- Holder 45 read empty with its pen in it (2026-09-29): seating or the switch.
- Key open with a tool still saved as carried: the saved tool is stale, the meshing could clear it instead of undocking.

## Toolhead rework (2026-09-30 discussion)

What's wrong now: the holders are slightly angled in X (the first tools push on the dock), and the key's centre is a bit off (a small crash as it enters a tool).

### Finding a tool's centre

The key sticks out ~7.5mm, so a QRE1113 anywhere on the carriage body is out of range (it works ~0.5-5mm, best ~1mm). On the key's tip it would work (wires through the key's limited turn), but it goes into every socket.
- [ ] **Chamfer first.** A generous lead-in on the key's tip and the socket, or a key that can float a little: a small miss becomes a slide. Sensing then only has to get close.
- [ ] **A magnet in each tool and a 3-axis Hall sensor on the carriage** (TMAG5273 or MLX90393: 2-3mm packages, I2C). A 3x2mm neodymium magnet, pressed in at a known spot by the socket, reads from 10-15mm. The field points at it: its offset from one or two readings, no scan. Dirt, light and plastic colour don't matter. The field's strength gives a rough height (a holder's tilt), and a polarity or a second magnet could tell tool types apart.
- [ ] **The coupling as a sensor.** If each of the three contact pairs can be read on its own before power goes on, the order they close in, on the way into a holder, tells which way it tilts, and when they close tells its height.
- A camera looking down (endoscope, tool camera) with a marker per tool also works, but is more work for this.

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

### The toolhead knows the contact: the options (2026-10-11 discussion)

The rule for all of them: the sensor sits between the pen and the Z carriage, below the Z play (1.67 per mm of press), so the play doesn't blur the touch. One sensor on the toolhead covers every tool; one per tool means one per holder.
- **A kinematic seat (Voron Tap, CNC touch probes).** The toolhead rests on the carriage on three balls or pins in V-grooves (or a rail), held down by its weight or a light spring. Wire the three contacts in series: the pen's touch lifts the toolhead a few µm off the seat and the circuit opens. One digital pin, no ADC; Klipper treats it as a probe. Seats like this repeat to ~µm. The trigger force is the preload: the toolhead's weight (~1N at 100g) is too much for a 0.05 tip, so a counter-spring takes most of it, down to ~0.1-0.3N. Or an optical slot-endstop flag in place of the contacts (Tap does that: contacts wear and spark). Gives the touch only, no force.
- **The flexure + Hall sensor (above).** The same place, but it reads force: the touch *and* a press by force. Hall over I2C, or a strain-gauge bridge on the blades through an HX711/ADS1220 (two digital pins; Klipper has a `load_cell_probe` for this).
- **A piezo in the stack.** A piezo disc under the seat or the flexure's clamp feels the moment of contact (printer piezo Z probes do this with grams). Through a comparator it's one digital pin. It needs a little speed at contact (a few mm/s) and gives no steady force.
- **An accelerometer on the toolhead.** It feels the jolt of a touch, no mechanics. Too weak for a soft fineliner at slow speed: the last choice.
- **The Z motor itself** (TMC StallGuard, current): needs far more force than a pen tip gives. No.
- **Per tool:** the pen on a spring in its holder, the spring's travel read by a Hall sensor or a contact through the pogo pins. A spring-loaded pen also rides out uneven paper while drawing. One sensor per holder, and the pogo pins must carry it.
- My order: the kinematic seat with a counter-spring (cheapest, digital, proven) if the touch alone is enough; the flexure with a strain gauge or Hall if limn should press by force. Either one replaces the FSR's z for every pen, and fine tips too.
- **Correction (the user, 2026-10-11):** the tool already sits on three pins in V-grooves on the toolhead, and the key pulls it in with a ramp as it turns. After a dock tool and toolhead are one solid object: no seat to sense there. The sensing has to be in the Z axis.
- **The Z axis as it is:** a Z plate with the lead screw nut at one end, the toolhead in the middle, a slot riding a guide rail at the other end. The rail end can move up and down a little. So when the pen pushes, the plate tips about the nut, and the rail end lifts about twice as far as the toolhead (it's twice as far from the nut). That give is the play measured on 2026-09-30, and the contact can be read from it:
  - **An accelerometer as a tiltmeter** (not a jolt detector). Static, averaged readings at each step of a Z ladder: the angle stays flat in the air and starts to change at contact; the knee is the touch. Eg. a 100mm plate, 0.05mm of lift at the toolhead is 0.001 rad, 0.06°. An ADXL345 (~4 mg/LSB, noisy) needs heavy averaging to see that; an ADXL355 or a BMI270-class part sees it easily. Klipper reads accelerometers already (ADXL345, LIS2DW, MPU-xxxx; SPI or I2C). No mechanical change: the cheapest experiment.
  - **A Hall sensor at the rail end, a magnet on the frame.** Z only moves 5-8mm, so the field against Z can be recorded once in the air; at contact the reading leaves that curve. Measures the lift directly, twice the toolhead's, at µm level. One I2C sensor (TMAG5273).
  - **A switch at the rail end** works only against something that follows Z without tipping, and on this plate only the nut does. Possible in the redesign, see below.
- **The cost of the give:** the pen hangs below the pivot, so tipping moves the tip sideways too, along the screw–rail line: about height below the pivot × angle. Eg. 40mm × 0.006 rad (0.3mm of lift on a 100mm plate) is ~0.24mm. It is probably in every plot already, where the press differs. To check: draw one cross at 0.1 and one at 0.4 mm of press and compare.
- **In the redesign:** make the give deliberate instead of thread clearance. A flexure hinge between the nut block and the plate, a light spring at the rail end pre-loading the plate onto a stop on a stiff arm from the nut block. The pen lifts it off the stop above a set force (the spring sets it, ~2x at the toolhead's lever), a switch or optical flag at the stop sees it (one digital pin; the user's slot sensors fit there). Keep the travel to the stop small (~0.2mm) so the tip barely moves sideways. This is the flexure above, with the Z plate as its lever.
- **Tried 2026-10-11, the carriage's MPU9250 (Klipper `[mpu9250]` on the Pi's software I2C; accelerometer only, Klipper doesn't read its gyro or magnetometer):** the Stabilo (T4) over FSR cell (1, 1), averages of 12 `ACCELEROMETER_QUERY` per Z step (one reading per query, ~1.3 s each, sd ~35-60 mm/s² a reading, so ~±12 a step, ~0.07°). Two ladders: to 0.16mm past the FSR's first touch (top cell 160), then to 0.40 past (Z3.85 → 3.35, top cell 232). **No signal**: x, y, z stayed within the noise at every step, so the MPU's mount tilts less than ~0.1° even at a 0.4mm press. Script and data: `~/limn-shot/acc-2026-10-11.py`, `.jsonl`.
  - The FSR flattened from ~0.25mm past touch (227, 226, 229, 232 over 0.15mm more Z): either the force stops rising there (something gives at a constant force: the Z play, 1.67 per mm on 2026-09-30) or the loaded sheet saturates under a felt tip. If it's the play, the accelerometer isn't on the part that moves.
  - So: the sensor has to sit on the Z plate (or the toolhead), where the give is, not on the carriage. And first find out *where* the give is: watch the Z plate's two ends (the nut end, the rail end) with a dial gauge or the axiscam during a 0.4mm press.
  - The query path is too slow and noisy for a small knee: `ACCELEROMETER_MEASURE` (4000 readings/s into the Pi's /tmp, needs SSH to read) gives ~30x less noise per step.
- **After the test (2026-10-11 discussion):**
  - An ADXL345 on the Z plate is the same class of sensor as the MPU9250 (~0.3 mg/√Hz): it can show *where* the give is, not a fine touch. A tilt only shows once the plate lifts in its play, and that needs the pen to outweigh the toolhead: the FSR's flat top from ~0.25mm past touch is probably that point. So a sensor on the play (accelerometer, Hall, switch) triggers at about the toolhead's weight, too late for fine tips, unless a counter-spring takes most of the weight.
  - Wiring one for I2C if wanted: VCC 3.3V, GND, **CS to VCC** (that selects I2C), **SDO to GND** (address 0x53; to VCC: 0x1D), SDA/SCL to the Pi's I2C1 (GPIO2/3, `dtparam=i2c_arm=on`, Klipper `[adxl345] i2c_mcu: rpi`, `i2c_bus: i2c.1`), or onto the MPU's software bus (gpio4/5, it's 0x68 so no clash). INT1/INT2 unused. Cheaper for the same answer: a dial gauge or the phone on the plate's two ends during a 0.4mm press.
  - **What feels the touch from the first gram: a strain gauge on a part that carries the load.** Pen → toolhead → Z plate → nut: the plate is a beam held at the nut, and the pen's push bends it, from the first gram, whatever the play does. Glue two gauges (a half bridge: top and bottom face, or both on top along and across) on the plate next to the nut where the bending is largest, an HX711 (or ADS1220/HX717, faster) to two digital pins. Klipper has load cell support in recent versions (`[load_cell]`, a load-cell probe with tare and a trigger force: check what the Pi's Klipper has). No mechanical change; ~5 € of parts. How much it sees depends on the plate (material, thickness, the distance nut → toolhead): to estimate before buying.
  - A piezo disc in place of a washer in the toolhead↔plate bolt joint: sees the moment of contact (grams), one comparator to an endstop pin, a washer swap. Needs some speed at contact, no steady force: the strain gauge is better if the plate gives enough strain.
- **Follow-up (2026-10-11): the Z rider is printed, with inserts.** A piezo is out (no impacts in this machine).
  - Strain gauges on a printed rider: ~30x the strain of aluminium (PETG E ~2 GPa), but plastic creeps under the toolhead's constant weight (a slow drift), a gauge stiffens the thin plastic it sits on, and plastic's thermal expansion (~70e-6/K) shows as fake strain: a half bridge on the same part cancels some, tare right before each touch the rest. Works in short touches, fiddly. Better: a small aluminium or steel strip printed into the rider as the load path, the gauges on the strip.
  - **The user's idea: two QREs on the rider's far tip** (it moves most when the rider tips), looking at the carriage's walls by the rails; learn their readings against Z in the air, a reading off that curve while a tool is on = contact.
    - The geometry decides it. The tip moves *up* when the rider tips, so a QRE has to face a surface across that motion (above or below the tip). A wall parallel to Z barely changes its distance when the tip lifts. And a surface fixed to the frame moves by the whole Z travel (5-8mm) relative to the tip: past a QRE's useful range (~0.5-4mm, very nonlinear). It works against a surface that follows Z and doesn't tip (a block on the guide rail, if there is one), or over a narrow Z band. A Hall sensor and a magnet do a 5-8mm range better.
    - Top/bottom as a differential pair (one gap opens as the other closes) cancels the LED's drift, the temperature and the surface's shade, and doubles the signal. The learnt profile handles the rest.
  - **The limit of any sensor on the play (QRE, Hall, switch, tilt):** the rider only lifts in its play once the pen pushes harder than the toolhead and rider weigh at the pen; before that only the plastic bends (estimate for a PETG rider ~30 x 8mm, the toolhead 50mm from the nut: ~0.04mm per N at its tip, 4µm for 10g, too small for a QRE). So these trigger at the weight, unless a **counter-spring** (or magnets) carries most of it and the rider lifts at ~10-20g. With that, a QRE or a switch at the tip sees a big, clear motion, Voron Tap's idea.
  - [ ] First, a kitchen scale on the bed under the Stabilo, Z down in 0.05mm steps to 0.4mm past touch: the grams where it stops rising is the force the rider lifts at, also the force every plot presses at when Z is too low. It says how much a counter-spring must carry.
  - **Answers (2026-10-11):** the surfaces round the tip are 3-5mm away, printed, on the carriage (fixed in Z); the slotted end rides on the bare rail (nothing there follows Z); the toolhead ~200g. So a QRE against those walls sees the whole Z travel (−3..10 in the config, 5-8 used) on top of the lift: out of its range except in a narrow band. With nothing following Z there, a Hall sensor on the tip and a magnet on the frame (its field against Z learnt in the air, as the user proposed for the QREs) covers the range. ~2N at the pen before the rider lifts on its own: a counter-spring is needed for fine pens either way.
  - **Z motor current (an INA on its ~7V), the user's idea: no.** `rotation_distance: 0.03125` (printer.cfg): Z moves ~0.03mm per motor turn, so 1N at the pen is `F × lead / (2π × efficiency)` = 1 × 0.03125 / (2π × 0.3) ≈ 0.017 N·mm (0.017 mN·m) at the motor shaft, ~0.1% of a small stepper's torque, under the screw's friction. And the driver holds the coil current constant: the supply current hardly changes with load at 3mm/s, where back-EMF is tiny. StallGuard-type sensing has the same problem.
  - **The design, detailed (2026-10-11):**
    - **Hall:** one magnet on the carriage wall by the tip, a 3-axis Hall sensor (TMAG5273) on the tip: the tip's height against the carriage. The screw end's height is known from the steps. Tip against screw = the tilt: the user's "magnets as markers" idea, but one magnet does it. A ~10-15mm magnet magnetised along its length: the field's angle turns as the sensor passes (the TMAG computes it); angle ignores temperature and gap, ~10-20µm. A multi-pole strip (AS5311-type) would give µm, not needed.
    - **No profile needed for a probe:** at a steady descent the field changes at a steady rate in the air; at contact the tip stops while the screw goes on, the field stops changing: a knee in time. A small MCU watching for it pulls an endstop pin: Klipper sees a plain probe.
    - **Counter-spring:** gravity holds the tip at the bottom of its play, so now it lifts at ~2N at the pen. A spring at the tip carrying most of the weight leaves ~0.1-0.2N: contact at that force, then the tip floats up through the play (a big motion for the Hall). Also a constant pen force while plotting in the play, a spring-loaded holder for every tool. The tip is ~2x the toolhead's distance from the nut: ~1N, less the net force wanted (~0.9N). The force must not change over Z (the carriage end is fixed): a constant-force spring (steel tape, ~1N, ~10mm drum on the carriage), or a long soft extension spring (0.02 N/mm: 0.16N over 8mm, learnt). Not a counterweight (moving mass), not magnets (force against gap).
    - **Catches:** friction of the slot on the bare rail adds to the trigger force and sticks-slips (smooth rod, PTFE or grease, clearance): the biggest unknown. The tip moves sideways as it lifts (~0.2mm for 0.3mm of lift): plot only slightly below contact (~0.05 lift, ~0.04 shift). A floating rider can rattle on fast moves: grease damps it, travel moves with the pen fully up avoid it. The play also bows front/back: the 3-axis sensor sees it, the in-air recording takes it.
  - **At limn's scale (the carriage ~6cm wide), 2026-10-11:** no TMAG breakout. A 3-pin linear analog Hall, TO-92 or SOT-23: DRV5055 (3.3V, ratiometric, sensitivity grades A1-A4: pick the one the magnet doesn't saturate) or SS49E (3-6.5V, noisier). The TMAG5273 chip is a SOT-23-6 itself, only its breakout is big.
    - **Magnet on the rider's tip, sensor on the carriage wall:** no wires on the moving rider. A 2x1mm N52 disc, poles along Z, passing the sensor's face: the field across the face crosses zero as they line up and is ~linear ±1mm round it. Put that zero in the band where pens touch. Rough numbers: ~10-20 mT/mm at ~2mm, DRV5055A1 ~66 mV/mT at 3.3V: ~1 mV/µm, a few µm with averaging on a 12-bit ADC. One axis: the front/back bow changes it too, so judge the knee, not the absolute value.
    - **ADC: the Klipper RP2040 (`[mcu rpi]`) has GP26-GP29 (ADC0-3) free** (pinout.md §6), 3.3V like the DRV5055. Klipper has no generic ADC probe: a ladder (move, read, fit the knee) like the FSR's first, then maybe a small reader in ext/limn (the MCU's ADC through `setup_adc`, the knee on the host: ~10-20µm late at 0.5 mm/s). The Melzi's free thermistor inputs (PA6/PA7, with 4.7k pull-ups to 5V on the board) would also do, less well.
    - Counter-spring at this size: a small constant-force spring (3-6mm wide, ~6mm drum, 0.5-2N exist), or a rubber band to try.
  - **A bar load cell between the rider and the toolhead (the user's question, 2026-10-11):** a bar cell (TAL220-type, the kitchen-scale kind) is a cantilever: one end bolted, the force on the other end *across* its length (along its bolt holes), as in a scale: bar flat, weight down. Its two-hole "binocular" cut-out rejects moments and loads along its length, so mounted with its length vertical (the pen pushing along it) it reads almost nothing. It has to lie flat: one end on the rider, the toolhead hanging from the other, a small gap between them. So it adds its thickness to the stack (the small ones ~6-8mm square, ~35-50mm long, sizes to check). It carries the toolhead all the time: a 500g-1kg cell, tared before each touch; with an HX711 ~0.1-0.5g. It gives under load (~0.1-0.2mm at full scale): fine. Or a custom cell: gauges on a thin metal plate shaped as the rider↔toolhead mount (above).
  - **The kinematic coupling and the key:** clamped by the key's ramp, tool and toolhead are one body: the pen's push changes the pins' seating force by a fraction of the clamp's preload, too little to read. What they can do:
    - **Seating:** each metal pin bridging two contacts in its V-groove: three circuits, so seated, tilted or dirty is known per pin (the *coupling as a sensor* item above).
    - **Wires to the tool:** three pins, three conductors (GND, power, signal), if anything in a tool needs them.
    - **The key hole as a window into the tool:** a sensor in the key's tip (wired through its limited turn) looking down into the tool. With a *spring-loaded pen* in each tool (the pen sliding in a bushing on a light spring, a tiny magnet on its top end), a Hall sensor in the key reads the pen sliding up at contact. No electronics in the tools; each tool's spring sets its own force (light for a 0.05 liner, firmer for a felt tip), and it draws at that force. Costs: a sliding fit in printed parts (wobble in XY, friction), five holders to rebuild, the pen's top end has to be under the key.
  - **Where the discussion ended (2026-10-11):** the FSR stays. It's the only option here that gives XY and z in one spot, for every tool, with no change to the toolhead; each toolhead option costs mechanical work and gives z only. What the exploration showed is that the weak part is the Z axis (the play, the ~2N lift, the tip moving sideways as it tips), not the FSR. Next: relax the FSR's press limits now the loads are in (a press aimed at a force), re-probe the Micron Blue; the kitchen-scale test for the force the rider lifts at. A toolhead sensor (counter-spring + Hall) only if constant-force drawing or contact over the whole paper turns out to be needed.
  - [ ] Rough counter-spring test: a rubber band or soft spring from the carriage to the tip; does the tip lift smoothly at a small force (spring scale, coins on the pen)?
  - [ ] Bench Hall test: an analog Hall (SS49E/DRV5053) and a magnet on a spare ADC of a bench MCU, the knee during a slow ladder; then a TMAG5273.
  - [ ] The rider's geometry: what the slotted end rides on (a block on the rail that follows Z, or the bare rail), the gap at the tip top and bottom, the masses.
- [ ] First, free: the plate's tilt on a Z ladder with an accelerometer (an ADXL345 if one is around, or the camera watching the rail end): does a knee show at contact, and does it agree with the camera ladder for the Micron 005 and the Blue?
- [ ] Before choosing: how the toolhead hangs on the Z carriage now, and the room there; whether a free digital pin (seat) or I2C (Hall) is on the toolhead or the Klipper board; the force a Micron 005 draws well at (a kitchen scale under the pen: grams at first ink, grams where the line widens).

### Power and data through the coupling

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
- [ ] Which MCU reads it: the Klipper RP2040 (`rpi`, GPIO 26-28 free) is the better choice. The tool change runs in Klipper macros, so a small `ext/limn` module reading the pin with Klipper's `adc` (like `adc_scaled`) gives `printer.limn.tool_id` straight to `_DOCK_TOOL`. The Dock (GP26-28 free) would work too, through `!LRT>>` lines, but it's the bed's MCU and its loop is time-critical.
- [ ] If the third contact is the 1-Wire line (electronics.md: 3 V, GND, 1-Wire): a resistor to GND kills 1-Wire (it idles high through ~4.7k). One or the other on that pin: the resistor gives presence + type; the DS2431 gives type + offsets, but no presence until it answers.
- [ ] More than ~24 types: a second ID pin (16 × 16), or combine with the tag (the resistor says "a pen", the tag says which).

### Power budget of the 5V through the coupling (2026-09-30)

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
- [ ] **Voltage drop matters more than heat at 5V**: the GND wire carries the same current, so count the run twice. 1 m of 26 AWG each way at 1.3 A: ~0.35 V; plus 10 cm of 30 AWG each way: ~0.09 V more. That's already under the Pi Zero's 4.63V with 5.0V in. Better: send 24V (or 12V) down the chain and buck to 5V on the toolhead: ~5x less current: 5x less drop (and a far smaller share of 24V), ~25x less heat in the wire.
- **Cable chain** (2026-10-01, guesses: 26 AWG, ~1 m, Z NEMA 8 ~0.6 A/phase, K micro linear stepper ~0.2 A/phase): heat per metre in W/m.

  | Wires | Current | Heat |
  |---|---|---|
  | Z, 4 wires | 0.6 A | ~0.19 W/m |
  | K, 4 wires | 0.2 A | ~0.02 W/m |
  | Tool 5V + GND, 1 pair | 1.3 A | ~0.45 W/m |
  | Tool 5V + GND, doubled | 0.65 A per wire | ~0.23 W/m |
  | USB-C, endstops, sensors, accelerometer | mA | ~0 |

  ~0.65 W/m in all at worst. The hottest wire (single 5V) makes ~0.23 W/m, about a third of what a 26 AWG wire makes at its 2.2 A rating, in an open, ventilated chain that keeps moving: heat is no problem, and more wires are fine thermally. The limits are the chain's fill (≤ ~60-70% so wires can slide), bend radius/flex life, and noise.
  - [ ] Double 5V *and* GND (2 wires each): the drop halves (~0.17V instead of ~0.35V over 1 m at 1.3 A, the 30 AWG piece doubled too), and so does the heat. Or a higher rail and a buck on the toolhead, if the box has one.
  - [ ] Noise: the stepper wires carry chopper PWM (tens of kHz, fast edges). Keep them in their own ribbons. In the sensor/accelerometer ribbon, put a GND between signal wires (I2C/SPI over ~1 m next to steppers glitches); lower I2C speed or SPI if it does. The endoscope: decoder board on the toolhead, only USB through the chain, never the analog VOUT next to the steppers.
  - [ ] Don't tie the USB-C's VBUS to the tool 5V line: two supplies feeding each other. Share GND only.
- LED draw: ~3.0V × 350 mA ≈ 1.05 W (700 mA ≈ 2.1 W). From 24V through a buck driver (~85%): ~50 mA (~100 mA at 700). From 5V: ~0.25 A through a buck, 0.35 A through a linear driver (it draws the LED's current). On only per tile: ~30% average over a scan.
- The 5 W laser and the milling spindle: always tethered, their own supply and their own interlock, never through the coupling.

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

