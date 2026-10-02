+++
title = "Software"
nav = "Software"
order = 3
summary = "Klipper with an extension for the dock and the beds, MicroPython on the small boards, and a web UI that turns SVG into G-code."
+++

All of it is in the [repository](https://github.com/prashnts/limn).

| Folder | What it is |
|---|---|
| `klipper/` | Klipper's configuration for the toolchanger and the printer |
| `ext/limn/` | A Klipper extension: the dock, the calibration beds (`LRT_*` commands), the tool holders and tags |
| `micropython/` | Firmware for the dock and the bed MCUs, and `mcu.py` to install and update them |
| `plot/` | SVG to G-code, and the web UI to place, paint, preview and plot drawings |
| `limn_cam/` | What the cameras see: the Z ladder that finds where each pen touches, scans, stitching |
| `guide/` | This guide: STEP to pages, renders and downloads |

![The plot UI](/docs/plot-ui.png)

## Step: Install on the Pi

```sh
cd ~/limn && git pull && uv sync
ln -sfn ~/limn/ext/limn ~/klipper/klippy/extras/limn
sudo ln -sf ~/limn/limn_web.conf /etc/supervisor/conf.d/limn_web.conf
sudo supervisorctl reread && sudo supervisorctl update
```

- The plot UI is then on port 4219. It has no login: keep it on the LAN.
- [i] Scans go to the Pi's memory (`/dev/shm`). Set up the NAS in the Scan tab to keep them.

## Step: Calibrate the pens

- `LRT_MESH_CALIBRATE` meshes the bed, `LRT_PROBE_TOOL` measures a tool against it.
- Each pen's offsets are written to its tag (`TOOL_TAG_WRITE DX= DY= DZ=`), so they follow the pen from holder to holder.
- [?] A photo of a calibration run.

## How it got here

Until September 2026, Limn plotted from **PrusaSlicer** ([log #4](/log/2026-04-09-detecting-tools-tool-parameters-slicing.html)), set up as a printer with five extruders.

- You dropped an SVG into the slicer, and it made the G-code Klipper expected. *I really did not want to reinvent any more wheels.*
- Pen up and down replaced the retractions. Z stayed raw in the G-code, so the preview showed the pen's real moves, and Klipper changed the Z offset instead. The extrusions only fed the preview, and the G1 macro ignored them.
- `T0`…`T4` from the slicer became tool changes in Klipper macros. For more than five pens there were five more extruders: Klipper paused and beeped between the 5th and the 6th, so the whole dock could be swapped by hand.
- Two parameters, added to moves with a regex in the slicer config, told the G1 override what to do ([log #9](/log/2026-05-01-applying-tool-parameters-tethered-tools.html)). `ACT` set the pen: 1 down, 2 up, 3 travel. `ALIGN` applied the tool's offsets, only while drawing, never while docking or reading a tag.
- The tag was first read by a shell command from G-code (`EXECUTE_AND_STORE`, a small Klipper module). It worked, but any G-code file could have run any command. The `limn` extension does it now.
- [i] A Fluidd trick from then: a macro that reads its parameters as `params.dx` (not `params['dx']`) gets a little form in Fluidd's UI.

On 2026-09-29 the slicer went, replaced by `plot/`: Limn's own SVG to G-code, and the web UI around it (the [changelog](https://github.com/prashnts/limn/blob/llm-v2/CHANGELOG.md) has the detail). The G1 overrides went the day after.

Things to plot came from [plottersvgs.com](https://www.plottersvgs.com/browse) and Wikimedia Commons, with [Hershey-style single-line fonts](https://gitlab.com/oskay/svg-fonts) for text. The [pen plotter calibration](https://laserpilot.github.io/Pen-Plotter-Calibration/) sheets were for testing.
