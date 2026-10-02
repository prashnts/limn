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
uv run python -m plot preview any.gcode -o preview.svg    # any G-code, as the plotter would draw it
```

- `profiles/limn.toml`: the bed, its art, the draw area, zones, z limits and travel heights, the G-code around a plot. A job overrides any of it with `machine_overrides`.
- `profiles/pens.toml`: the pen library, the kinds of pen a tool's tag can name. The web UI's *Pens* adds and edits them in this file (`pens.py`, comments stay); a key goes on the tags, so it is never renamed.
- Number fields in the UI drag sideways (Shift finer, Ctrl coarser); a click types into them. `?` lists every keyboard shortcut.
- Drawings stack: the list has the top one first (⤒ ↑ ↓ ⤓ on the selected one, or `]` `[`, Shift for the front and back). One hides what is under it where it paints opaque, on the paper as on the canvas (`emit.hidden`; *what is on top hides* off: it hides nothing). Inside a drawing that was always so.
- How every tool draws, whatever its pen (*Drawing* panel, the job's `draw`): speed, plunge, overlap, link, fill, angle, border, stroke, `bleed` and `small`. A tool's tuning wins (`tool_overrides`), a colour's own fill and stroke settings over both (left empty: as its tool draws).
- `bleed`: mm kept clear around what another tool (or a mask) draws on top, so inks that run don't meet; the same tool on top: no gap.
- `layers` (*light under dark*): a lighter ink isn't cut out where a darker one draws over it; it is drawn whole, and the plot takes the pens light to dark, so a black outline over a light fill stays crisp. Masks still cut. Off: each ink only where it shows. Mind the drying time of the light ink before the dark goes over it.
- `small`: shapes too small or dense for the tool's line (less than 2.5 widths across, or most of their inside painted over: handwriting or text at a small scale) are left out (`skip`, the default), drawn with a warning, or just drawn; the Tools view outlines them in red. A `<text>` in auto whose caps come under 8 widths is drawn in its line font instead.
- Masked regions (the mask tool, `M`): drag over a drawing where nothing of it is drawn, eg. over what is printed on the sheet already. Kept in the drawing's own mm (`Obj.masks`): they move and scale with it.
- `<image>`s are taken out of an SVG when it is uploaded: they can't be plotted.
- *Printer*: buttons for Klipper's useful macros (`macros` in the profile; the tool changes from `holders`), only those Klipper has (`/printer/gcode/help`); one that moves the machine asks first. *Fluidd at*: where Fluidd is for this browser, the cameras' addresses are taken from it (`settings.json`): needed when the UI runs on the Pi behind its own address.
- On a phone (under 760 px) the canvas is on top and the panels follow it, one column, scrolled like a page.
- The layout: the canvas is the whole page, the panels float over it (`static/panels.js`). Tap a panel's header to fold it, drag its grip to the other side or out over the canvas; the drawings and the captures stay put. The scan viewer and the cameras are windows: drag their bar, their corner resizes them, a double-click on the bar puts them back. *Panels* (or `\`) hides every panel; right- or Shift-click it to put everything back where it started. On a touch screen two fingers pan and zoom the canvas. *Display* shows the LED matrix UI and the dock strip live (`static/leds.js`, the README's *LEDs*).
- The scripts, each its own file and no build: `app.js` (the canvas, drawings, painting, panels' contents), `scan.js` (the Scan tab), `zoom.js` (pictures that zoom), `cams.js` (Klipper's cameras), `head.js` (the head, live), `leds.js` (the LED display), `panels.js` (the layout).
- `profiles/tools.toml`: what is in the holders. Tool kinds are in `tools.py` (pen, pencil, brush, laser); your own go in a file listed in `plugins`.
- `svg.py` reads a drawing by colour, `slicer.py` makes each colour's paths (fills, occlusion, strokes as wide as the SVG has them), `emit.py` writes the G-code, `preview.py` reads any G-code back.
- A job's objects are sliced in their own coordinates, their placement applied when the G-code is written: moving or turning one doesn't slice it again.

The G-code is plain `G0` (travel) / `G1` (drawing) with real z, the tool macros (`T0` -> `DOCK`) and `_APPLY_OFFSETS`. Off the paper (the bed's draw area) the tool is never under `safe_z` (Z5): travels that leave or cross it go up first and come down only on the paper, drawings are clipped to it, and every move written is checked for it. A plot that fails the check (`UNSAFE` in its problems) isn't uploaded.
