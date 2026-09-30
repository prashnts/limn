# plot

SVG to G-code for Limn, in place of PrusaSlicer. Tests: `uv run pytest`.

```sh
uv run python -m plot serve            # the web UI on :4220, workspace in plot-data/ (LIMN_PLOT_DATA)
```

Drop SVGs on the bed, drag them, paint shapes or whole colours with a tool (shift-click), set fills per colour,
pick fonts per text, and it slices again after every change (a move only writes the G-code again). Paths shows
the G-code read back, with a scrubber and the lines. Upload / Upload & plot send it to Klipper through Moonraker
(`moonraker` in the profile, or LIMN_MOONRAKER); with *follow Klipper* the bed, its paper and `lrt_paper` come
from `printer.limn.bed`.

Texts: in their own font when it is uploaded (TTF/OTF, matched by font-family, weight, style; shaped with HarfBuzz),
or in a line font (Hershey, or an uploaded SVG font) with the caps as high as the source's, and optionally as wide.

```sh
uv run python -m plot colors drawing.svg                  # its colours, and the tool each goes to
uv run python -m plot slice drawing.svg --map '#ffcd00=T1' --map '#ffffff=mask' \
    -o out.gcode --preview out.svg --save-job job.json
uv run python -m plot job job.json -o out.gcode           # after editing the job (placement, groups, ..)
uv run python -m plot preview any.gcode -o preview.svg    # ours, or PrusaSlicer's with ACT
```

- `profiles/limn.toml`: the bed, its art, the draw area, zones, z limits and travel heights, the G-code around a plot. A job overrides any of it with `machine_overrides`.
- `profiles/pens.toml`: the pen library, the kinds of pen a tool's tag can name. The web UI's *Pens* adds and edits them in this file (`pens.py`, comments stay); a key goes on the tags, so it is never renamed.
- Number fields in the UI drag sideways (Shift finer, Ctrl coarser); a click types into them.
- `profiles/tools.toml`: what is in the holders. Tool kinds are in `tools.py` (pen, pencil, brush, laser); your own go in a file listed in `plugins`.
- `svg.py` reads a drawing by colour, `slicer.py` makes each colour's paths (fills, occlusion, strokes as wide as the SVG has them), `emit.py` writes the G-code, `preview.py` reads any G-code back.
- A job's objects are sliced in their own coordinates, their placement applied when the G-code is written: moving or turning one doesn't slice it again.

The G-code is plain `G0` (travel) / `G1` (drawing) with real z, the tool macros (`T0` -> `DOCK`) and `_APPLY_OFFSETS`. It runs with or without the `G1` ACT macro in `klipper/limn.cfg`.
