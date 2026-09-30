# Next

## plot/

- Fixes in the G-code generation (details to come, 2026-09-30).
- Text: fixes, and a way to see that a path is far too small for text, eg. a warning in the preview when glyphs come out smaller than the pen can draw.
- Pens press a bit too hard (2026-09-29 plots). Aim for what the old LRT setup did: 1.5 mm high text came out very well there. `z_down` is 1.0 (`plot/tools.py`), the same as the old `ACT1` Z1, so the difference is elsewhere: the mesh loaded (`lrt_paper`), the tag dz, or what the plot adds on top. Compare a plot's G-code and Klipper's Z at pen down with an old PrusaSlicer one.

## ext/, klipper/

- Tag reads: the PN532 listens for the whole 0.5 s now (`i2c.py`, `begin(retries=0xFF)`), untested on the plotter. If it still misses: read while approaching the reader from its edge, which reads best. Needs the edge's X and whether Z7 is safe for the last stretch.
- Holder 45 read empty with its pen in it (2026-09-29): seating or the switch.
- Key open with a tool still saved as carried: the saved tool is stale, the meshing could clear it instead of undocking.
