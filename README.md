## Limn: Pen Plotter with Toolchanger

I wanted to build a plotter that could draw in different colors without
manual color swaps. Limn is my attempt to build one using 3D printed and 3D
printer parts. It has a 5-slot toolchanger, auto tool offset calibration,
can plot on A6 and A5 (~90%) paper, and it runs on klipper.

Build logs are on [Hackaday.io](https://hackaday.io/project/205431-limn-pen-plotter-with-toolchanger),
and the printed parts can be found on [Printables](https://www.printables.com/model/1786450-limn-pen-plotter-with-automatic-tool-changer-parti).


Due to physical constraints and geometry, no two tools/pens will land at the same
point on paper for the given coordinate. This implies that they have each a
certain offset relative to an origin. If we assign a reference pen as the origin,
we can calibrate other tools by comparing the tip position (eg. by drawing and measuring).

This calibration can be done both by hand or automatically. There's an RFID tag
on each tool. Automatic offset calibration requires a sensing surface where the
tools can be probed. Limn can use a Resistive Touch Panel or an FSR matrix
to probe the tool's tips and estimate the XYZ offset with about <0.2mm (best: 0.04mm). 

Then I needed software to actually draw things. I first used PrusaSlicer with
an absurd hack: we can translate "retract", "unretract" as signals to move the
pen up or down... and it worked quite well!

There's an experimental "slicer" in `plot/` which will replace the slicer 
gcode generation. It parses the SVG files natively and handles images, gradient,
text well. It's also "vibecoded". It handles images and gradients with dithering
and the pens can be layered. I intend to refine it further, but it does the job
right now.

Lots of things are currently undocumented and unstable. It's a build log with
code, not a kit: expect to fork it and do some debugging. There's a
`CHANGELOG.md` containing the progress.

## What's where

- `klipper/`: Klipper configuration for the toolchanger motion and printer.
- `ext/limn/`: Klipper extension for complex tasks (eg. calibration).
- `plot/`: SVG to G-code ["Slicer"](plot/README.md).
- `limn_cam/`: (experimental) Z ladder, homographies, scan stitching.
- `micropython/`: firmware for the Dock and the bed MCUs.
- `slicer/`: the old PrusaSlicer based setup, retired.
- `GEOMETRY.md`: plotter coordinates, hardware.
- `docs/`: the details below.

## Development

Install Klipper and clone this repository in the home dir. Create following symlinks for plotter config and extension:

```sh
ln -sfn ~/limn/klipper ~/printer_data/config/limn
ln -sfn ~/limn/ext/limn ~/klipper/klippy/extras/limn
```

The extension requires some packages, so does the plot tool. Extension runs in
Klipper's venv and requires `numpy` to be installed. The plot tool needs `uv`.
In practice these config will require hand tuning for your specific device.

Then add the limn config files to your Klipper config:

```ini
[include limn/limn.cfg]
[include limn/leds.cfg]
[include limn/buzzer.cfg]
```

`printer.cfg` is not linked because Klipper's `SAVE_CONFIG` replaces it with a new one, which would break a symlink.

The plot UI runs next to Klipper (or preferably on a different computer). Its
workspace (the job, dropped SVGs, fonts) is `~/limn/plot-data`.

```sh
cd ~/limn && git pull && uv sync
sudo ln -sf ~/limn/limn_web.conf /etc/supervisor/conf.d/limn_web.conf
sudo supervisorctl reread && sudo supervisorctl update
sudo supervisorctl status limn_web      # then http://<pi>:4219
```

Note that there's no authentication yet, but Moonraker's auth will be supported soon.

A camera tool (wifi/wired) can be calibrated in the UI to scan the bed and plot 
over an existing image (not fully tested yet) or they may be stitched with hugin:

`sudo apt install hugin-tools enblend`

Camera scans are kept in RAM (`/dev/shm/limn-captures`, 2 GB at most).


- Run Tests: `uv run python ext/tests/test_*.py`
- Interact/Update MCUs: `uv run python micropython/mcu.py`
- Camera: `uv sync --extra cam`


## Calibrating the pens

A Bed containg a FSR matrix is used to calibrate XYZ offsets of the pens using
these commands:

```
LRT_CALIBRATE              ; with the reference pen in holder 45
LRT_PROBE_TOOL T=41   ; each other pen: its DX DY DZ go onto its tag
```

TODO: Description.
Everything about meshes, the sensor and its quirks is in `docs/calibration.md`.

## More notes

- `docs/calibration.md`: bed meshes, test marks, the FSR sensor and its survey.
- `docs/leds.md`: the LED matrix and dock strip, and what each state means.
- `docs/toolhead.md`: tool holders and tags, hand-docked tools, the toolhead's wiring, the endoscope.
- `docs/cameras.md`: adding a camera to the Scan tab and calibrating it.
