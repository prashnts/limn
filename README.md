# Limn

Limn is a pen plotter with a toolchanger. This repository contains the various klipper configuration files and some extra modules.

- `klipper/`: Klipper configuration for the toolchanger and printer.
- `ext/limn/`: Klipper extension for the Dock and the calibration beds (`LRT_*` commands). Install with `ln -sfn ~/limn/ext/limn ~/klipper/klippy/extras/limn`, tests: `uv run python ext/tests/test_*.py`.
- `ext/limn/tool_holder.py`: The tool holders' switches (MCP23017) and the tool tags (PN532), read by the extension straight off the Pi's I2C bus (`tool_holder_*` in `[limn]`). Commands: `TOOL_HOLDERS`, `TOOL_HOLDER_CHECK T= EXPECT=occupied|empty`, `TOOL_TAG_READ`, `TOOL_TAG_WRITE [DX= DY= DZ= NAME=]`. Klipper's user needs to be in the `i2c` group.
- `micropython/`: Firmware for the Dock and the bed MCUs, and `mcu.py` to install and update them.
- `slicer/config.ini`: Sample PrusaSlicer config to make it suitable for plotting.
- `step/`: (todo) 3D Printable Parts


## Bed meshes and test marks

`LRT_MESH_CALIBRATE` takes the meshes of the bed on the plotter (`meshes` in `ext/limn/beds.py`); with no bed on the plotter, the whole bed as `[bed_mesh]` in `printer.cfg` has it. A bed it doesn't know, it doesn't probe. `IF_STALE=1` only meshes when the meshes aren't of the bed as it sits now.

The meshes and the test marks belong to one placement of the bed. The Dock counts the beds placed and removed since it booted (`read_bed_id()`, see `micropython/STRATEGY.md`), so this holds over Klipper restarts. Once the bed has been off, or the Dock restarted, `LRT_PROBE_TOOL` meshes the bed again before probing the tool (and takes the tool back after), and the marks start over at the first one. The tools' tags stay as they are. The meshes are only in memory until `SAVE_CONFIG`; a restart without it meshes again too. Dock firmware without the count: the meshes are trusted until Klipper restarts.

After `LRT_CALIBRATE` and `LRT_PROBE_TOOL` the tool draws a test mark on the paper: a corner that makes a `+` with the corner the previous tool left, and a corner at the next point for the next tool. Two pens that disagree show a step in the `+`: in its vertical line for X, in its horizontal line for Y. `LRT_MARKS` shows where the next one goes, `LRT_MARKS RESET=1` starts over on a new sheet.

Nothing is probed or drawn when a pen could hit the bed or the tools:
- Meshing puts the carried tool away first, and stops if a holder is empty that isn't the carried tool's (a pen may be on the carriage without the extension knowing).
- A mark is only drawn with a carried tool, with a paper mesh of this placement, inside that mesh and short of the holders (`MARKS_MAX_X`), and with sane offsets on its tag (`TOOL_MAX_DXY`, `TOOL_DZ`). The pen travels at the beds' travel height and comes down only over the mark.

There is some more info posted [here](https://hackaday.io/project/205431-limn-pen-plotter-with-toolchanger) about this project.

## LEDs

The extension sets the tool holder and UI LEDs from what it knows. `klipper/leds.cfg` has how each state looks (`_led_styles`); `TOOL_LEDS` redraws them and lists the states.

| Where | State | Means |
|---|---|---|
| Dock strip, per holder | green | tool in its holder |
| | off | holder empty (its tool on the carriage, or missing), or holders unreadable |
| | red | the check at this holder failed |
| Fluidd tool buttons `T0`..`T4` | dot colour / highlight | green home, no dot empty, red failed / the carried tool (`tool_holder_macros` in `[limn]`) |
| UI digit | blue, breathing | tool being changed |
| | amber / white | carried tool, tag not read / tag applied |
| UI column 8 (red, yellow, green) | red, yellow, green blinking, green | tool change: travelling, at the holder, leaving, done. Red blinking: failed, until the next change or `DOCK_RESET` |
| UI tag (bottom left) | blue blink / green / red blink | reading / applied / failed |
| UI alert (top left), most urgent first | red, fast then slow blink | a check failed or the holders can't be read (fast for the first 3 s) |
| | blue spinner, faster near the holder | tool change: travelling, at the holder, leaving |
| | cyan spinner | reading or writing a tag |
| | green, quick blink | a tool change just went well |
| | amber blink, slowing down over 5 s | a hand was on the holders |
| | amber, breathing | a tool is unaccounted for, or the carried tool's tag failed |
| | green, breathing | carrying a tool with its tag read: ready |
| | dim green, slow | all tools home |

## Linking the Klipper config

Symlink the repo's `klipper/` folder into Klipper's config folder instead of copying the files over:

```sh
ln -sfn ~/limn/klipper ~/printer_data/config/limn
ln -sfn ~/limn/ext/limn ~/klipper/klippy/extras/limn
```

Then in `~/printer_data/config/printer.cfg` include them through the link:

```ini
[include limn/limn.cfg]
[include limn/leds.cfg]
[include limn/buzzer.cfg]
```

- `printer.cfg` itself stays a real file in `~/printer_data/config/`. `SAVE_CONFIG` rewrites it by renaming a new file over it, so a symlink would be replaced by a plain copy, and the saved `[limn]` calibration would stop reaching the repo. `klipper/printer.cfg` in the repo is a reference copy (the tests read its `SAVE_CONFIG` block); copy it back when you want the repo to have the latest calibration.
- Klipper resolves `[include]` relative to the file that has it. `limn.cfg` ends with `[include limn-tools.cfg]`, which through the link means `~/limn/klipper/limn-tools.cfg`. Either move that file into the repo's `klipper/`, or move the `[include limn-tools.cfg]` line from `limn.cfg` into `printer.cfg`.
- Editing the linked files in Fluidd/Mainsail edits the repo's files. After a `git pull`, `RESTART` picks up config changes; changes under `ext/limn` need `sudo systemctl restart klipper`, since Klipper imports its extras only once.
