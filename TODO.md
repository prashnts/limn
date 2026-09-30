# Next

## plot/

- Fixes in the G-code generation (details to come, 2026-09-30).
- Text: fixes, and a way to see that a path is far too small for text, eg. a warning in the preview when glyphs come out smaller than the pen can draw.
- Pen-down: `z_touch - press` (1.2 less 0.15 for fineliners, 0.3 for the Stabilo 88), lifts by the press, `play.clear` and the play (`plot/profiles/play.toml`). The old "pens press too hard" was stale tags: done (`notebooks/act-7-camera-ladder.md`). To watch: touch moved by ~0.2mm from one sheet to the next (the Staedtler and the Stabilo both touched 0.2 low on sheet 2). Either a quick ladder per sheet, or `z_touch` per sheet/mesh.

## Pens, heights (limn_cam/)

- Holder 41 has the Stabilo "Stabilo Test Blue" (stb-88, dz 0.24, primed 2026-09-30): the only pen in use. The rest were taken out to keep them from drying.
- Micron 01 blue (dz 2.25): drew nothing even at Z0.8 on sheet 2. Seated? slid up in its clamp? writing? Then a ladder, `limn_cam ladder T<n> --z 2.0:0.4:0.1`.
- Staedtler 0.05 (dz 1.05): check on the next sheet it goes back in.
- Z play: gentle (0.3, 2mm strokes) and loaded (0.6, 10mm at 3000mm/min) tests both let go within 0.5mm over touch, the same all over the sheet (`limn_cam play`). The few mm measured by hand don't show on the lift. Still open: tilt while drawing (the pull along X vs Y), which a lift test doesn't see.
- Cameras aren't essential (OpenCV is the `cam` extra). Next: fixed focus on the axiscam; a camera on the tool for line width and contact; an upward endoscope for tip dx/dy (notebook act-7).

## ext/, klipper/

- Drying: per pen (`dry` minutes in pens.toml, 240 for the Stabilo 88, 10 for fineliners), twice that printing. To check on a real long plot: the SET_PIN beeps land between moves without a stall. Maybe a Fluidd button for `TOOL_DRY RESET=1`.
- BED_5 FSR: column 3 still faulty; z and edges moved to column 1, the aim to column 5. A 0.05 liner can't be measured on it (≤121 at PRESS=0.5).
- Toolchanger key rework (2026-09-30): holders slightly angled in X (the first tools push on the dock), the key's centre a bit off (a small crash entering). Plan: a QRE1113 looking down, fixed to the carriage next to the key, not on its tip. The offset from the key's axis is constant, calibrated once on a tool the key has just locked. It finds each tool's socket by its edges in X and Y (tap across, both ways, as the FSR edges do; drive its LED from a pin to take the ambient IR, and the IR camera's light, out), and its level at a few points shows a holder's tilt. For force: an FSR behind the key would see the key's preload less the pen's push, poorly (hysteresis, creep); it's good for crashes at the dock only. A strain-gauge load cell (HX711/ADS1220) holding the whole toolhead mount measures tip force on the go, contact per pen (no ladder), and dock crashes.
- Tag reads: the PN532 listens for the whole 0.5 s now (`i2c.py`, `begin(retries=0xFF)`), untested on the plotter. If it still misses: read while approaching the reader from its edge, which reads best. Needs the edge's X and whether Z7 is safe for the last stretch.
- Holder 45 read empty with its pen in it (2026-09-29): seating or the switch.
- Key open with a tool still saved as carried: the saved tool is stale, the meshing could clear it instead of undocking.
