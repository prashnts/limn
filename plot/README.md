# plot

SVG to G-code for Limn, in place of PrusaSlicer. Tests: `uv run pytest`.

```sh
uv run python -m plot serve            # the web UI on :4220, workspace in plot-data/ (LIMN_PLOT_DATA)
```

Drop SVGs on the bed, drag them, give each colour a pen (the drawing's *Layers*), pick shapes to paint them apart or
group them, pick fonts per text, and it slices again after every change (a move only writes the G-code again). Paths shows
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
- `bleed`: mm kept clear around what another tool (or a mask) draws on top, so inks that run don't meet; the same tool on top: no gap. Set per tool in its tuning (*Tools*), or for all in *Drawing*.
- *Layers* (the selected drawing): one per pen, plus *Mask* and *Not drawn*, each with the colours it draws as chips (outlines a ring, fills a dot). Colours alike (closer than 60 in redmean distance) going to one pen share a chip, and a layer shows 12 chips before *+n*: an SVG of a thousand shades doesn't make a thousand rows. Drag a chip onto another pen (the empty layers show while dragging), or click it for its pen, fill, border, gap, its *bleed margin*, and each of its colours apart. A layer's ⬚ picks its shapes.
- *Bleed margin* (`inset` on a colour, a shape or a group): the fill stays its pen's `bleed` inside its own edge, the corners rounded; where the shape is too thin for round corners they stay sharp, and one too thin for any margin is filled as it is. Its border, if any, runs along that inner edge. The gap from inks on top stays as well.
- The shapes tool (`A`): click a shape (a grouped one picks its whole group, Alt the shape alone), Shift adds, drag a box. The picked shapes get their outline's pen, their fill's (only shapes that can be filled: not lines; a closed shape the SVG doesn't fill can take one), and the *bleed margin* and *border* checkboxes. These win over the colour's layer (`Obj.shapes`); the margin and border don't fix the pen, it still follows the layer. Paint (`P`) still paints shape by shape.
- Groups of shapes (`Obj.sets`, Ctrl+G with the shapes tool): painted together, over their colours; a shape's own paint still wins. Only how they are drawn: the shapes themselves never move.
- Groups of drawings (`Obj.group`): Shift-click drawings (on the bed or in the list), *Group* (Ctrl+G). They move and nudge together (`PATCH /api/objects`, one undo step), hide together from the group's row; scale and turn stay per drawing.
- `layers` (*light under dark*): a lighter ink isn't cut out where a darker one draws over it; it is drawn whole, and the plot takes the pens light to dark, so a black outline over a light fill stays crisp. Masks still cut. Off: each ink only where it shows. Mind the drying time of the light ink before the dark goes over it.
- `small`: shapes too small or dense for the tool's line (less than 2.5 widths across, or most of their inside painted over: handwriting or text at a small scale) are left out (`skip`, the default), drawn with a warning, or just drawn; the Tools view outlines them in red. A `<text>` in auto whose caps come under 8 widths is drawn in its line font instead.
- Masked regions (the mask tool, `M`): drag over a drawing where nothing of it is drawn, eg. over what is printed on the sheet already. Kept in the drawing's own mm (`Obj.masks`): they move and scale with it.
- `<image>`s (pictures embedded in the SVG; a linked file can't be read and is left out): on upload the UI asks whether to leave them out or make them into lines (`Obj.raster`, `raster.py`), and the drawing's *Images* section changes it after. *Dither*: Floyd–Steinberg on cells `pitch` apart, a row's dark cells joined into lines (the most detail, the longest plot). *Lines*: rows `pitch` apart, more of them where it is darker (4 levels; quick). *Halftone*: dots `cell` apart, each a spiral as wide as the spot is dark. Distances are mm as plotted; empty, they follow the pen that draws each ink (pitch: its fill spacing, so black is solid; dot grid: 6 of its lines, 0.5 to 3 mm). *Paper up to* (10% grey) leaves a light background without ink; gamma and invert. *Inks*: one colour (black by default); CMYK; or *onto the pens*, each pixel unmixed into the pens' own colours (inks multiply: least squares on their absorbances), each ink on its own screen angle. Each ink is a colour layer, so its chip gives it a pen; the lines are never "too small".
  - Fine pens: a 0.05 fineliner would make millions of cells. Dither is coarsened to 250 000 cells (about 60 000 dots: stippling, hours of Z hops), a halftone's turns spread past 500 000 points; the problems say so. *Lines* runs at the pen's own pitch (a 120 × 90 mm picture: 120 m of ink, about an hour).
- A page's background (a filled rectangle over the whole page, painted first, with something over it, as drawing apps export the canvas) is the paper: not drawn unless painted with the shapes tool. A fill written as `var(--x, fallback)` takes its fallback, a `url(...)` (pattern, gradient) is left out; both used to come out black.
- The shapes tool's *Pen* puts the picked shapes, whole, on one pen: the outline and, where filled, the fill. *Outline* and *Fill* set them apart.
- Captures (Scan tab): *Hide all* takes them all off the bed (or shows them again), *Delete all* deletes every one but the one being taken. A *look* is only for now: the next capture, whatever it is, deletes it.
- *Printer*: buttons for Klipper's useful macros (`macros` in the profile; the tool changes from `holders`), only those Klipper has (`/printer/gcode/help`); one that moves the machine asks first. *Fluidd at*: where Fluidd is for this browser, the cameras' addresses are taken from it (`settings.json`): needed when the UI runs on the Pi behind its own address.
- On a phone (under 760 px) the canvas is on top and the panels follow it, one column, scrolled like a page.
- The layout: the canvas is the whole page, the panels float over it (`static/panels.js`). Tap a panel's header to fold it, drag its grip to the other side or out over the canvas; the drawings and the captures stay put. The scan viewer and the cameras are windows: drag their bar, their corner resizes them, a double-click on the bar puts them back. *Panels* (or `\`) hides every panel; right- or Shift-click it to put everything back where it started. On a touch screen two fingers pan and zoom the canvas. *Display* shows the LED matrix UI and the dock strip live (`static/leds.js`, the README's *LEDs*).
- The scripts, each its own file and no build: `app.js` (the canvas, drawings, painting, panels' contents), `scan.js` (the Scan tab), `zoom.js` (pictures that zoom), `cams.js` (Klipper's cameras), `head.js` (the head, live), `leds.js` (the LED display), `panels.js` (the layout).
- `profiles/tools.toml`: what is in the holders. Tool kinds are in `tools.py` (pen, pencil, brush, laser); your own go in a file listed in `plugins`.
- `svg.py` reads a drawing by colour, `slicer.py` makes each colour's paths (fills, occlusion, strokes as wide as the SVG has them), `emit.py` writes the G-code, `preview.py` reads any G-code back.
- A job's objects are sliced in their own coordinates, their placement applied when the G-code is written: moving or turning one doesn't slice it again.

The G-code is plain `G0` (travel) / `G1` (drawing) with real z, the tool macros (`T0` -> `DOCK`) and `_APPLY_OFFSETS`. Off the paper (the bed's draw area) the tool is never under `safe_z` (Z5): travels that leave or cross it go up first and come down only on the paper, drawings are clipped to it, and every move written is checked for it. A plot that fails the check (`UNSAFE` in its problems) isn't uploaded.
