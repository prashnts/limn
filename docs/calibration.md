# Bed meshes, test marks and pen calibration

Moved out of the README. The commands are `LRT_*`, from the extension in `ext/limn/`.

`LRT_MESH_CALIBRATE` takes the meshes of the bed on the plotter (`meshes` in `ext/limn/beds.py`); with no bed on the plotter, the whole bed as `[bed_mesh]` in `printer.cfg` has it. A bed it doesn't know, it doesn't probe. `IF_STALE=1` only meshes when the meshes aren't of the bed as it sits now.

The meshes and the test marks belong to one placement of the bed. The Dock counts the beds placed and removed since it booted (`read_bed_id()`, see `micropython/STRATEGY.md`), so this holds over Klipper restarts. Once the bed has been off, or the Dock restarted, `LRT_PROBE_TOOL` meshes the bed again before probing the tool (and takes the tool back after), and the marks start over at the first one. The tools' tags stay as they are. `LRT_CALIBRATE` uses the meshes when they are of the bed as it sits (`MESH=1`: new ones anyway). The meshes and the calibration are kept in the saved variables too (`lrt_mesh_data`, `lrt_profile`) and put back at startup, so a restart without `SAVE_CONFIG` loses neither. Dock firmware without the count: the meshes are trusted until Klipper restarts.

Meshing a calibrated bed again also probes the calibration's bed z again (BLTouch, nothing on the carriage), which the tools' dz are measured against. Then, when holder 45 has the reference tool, tagged `REFERENCE=1` (`LRT_CALIBRATE` tags it), it is docked and the reference points are taken again too: a full calibration. Otherwise the old reference points stay, and tools probed after the move are off in XY by about as much as the bed moved. That's fine as long as the pens only have to agree with each other.

## Calibrating the pens on the FSR bed (BED_5)

```
LRT_CALIBRATE              ; the reference pen, in holder 45: a felt tip (a Stabilo). Its tag gets REFERENCE=1
LIMN_TOOL_CALIBRATE T=41   ; each other pen: its DX DY DZ go onto its tag. Wipe the sheet when it beeps
```

Nothing to pass. Each measurement finds where the pen's tip is (`locate()`), its contact on the measuring cell (1, 6), then two edges in X and two in Y, in turns (X, Y, X, Y), on the sheet's strong cells (`z_cell`, `x_edges`, `y_edges` in `ext/limn/beds.py`): each axis is their mean, and how far apart they put the tip goes into its ±. The first X and Y edges tap as deep as locate did; once they have put the tip, each edge after them finds its own depth on its two cells' centres, the weaker cell's. The taps press until the cell reads `press_strength` (a felt tip ~0.1 mm in), 0.2 mm past contact at most, less for a pen whose `press_max` in `plot/profiles/pens.toml` is less; each tool says how deep. `PRESS=` sets it by hand. `LRT_FSR_MEASURE` measures the same way but writes nothing: to try a pen first.

The sheet is wiped by hand between pens, and before the BLTouch probes it (meshing `lrt_fsr`, the calibration's bed z) once a tool has touched it: ink can hold the probe up, and the sheet reads high. It beeps and waits until a few cells have been pressed and released. `LRT_FSR_CLEAN` asks for a wipe any time; `CLEAN=0` on a command skips it. After a restart nothing is known of the sheet, so nothing is asked: wipe it then with `LRT_FSR_CLEAN`.

After a sensor swap:

1. Map it, with the reference pen on the carriage: `LRT_FSR_MAP TIP=2.0,2.13` (the pen's tip from the toolhead, as the edges measured it; without TIP the map is in toolhead coordinates). It touches the sheet spot by spot on a 1.25 mm grid over the array and a 1 mm margin (`STEP=`, `MARGIN=`), each from a baseline in the air until a cell rises 40 (`RISE=`), then reads every cell 0.02 mm deeper (`DEPTH=`). It fits the array's origin and pitch to where each cell answers strongest, lists the cells that never answer and those answering far from their place (a ribbon off by a pin), and writes a picture and the data to `~/printer_data/logs/fsr-maps/` (Moonraker: `/server/files/logs/fsr-maps/…`; `fsr_map_dir` in `[limn]`). Set `origin` in `ext/limn/beds.py` from it. ~20-30 min. A spot where nothing answers (the margin, a dead cell) is pressed at most 0.06 mm under where the sheet is expected.
2. `LRT_FSR_MATRIX` with nothing on the sheet: every cell low (under ~30), but row 3 (no series resistor).
3. With the reference pen (a felt tip) on the carriage:

```
LRT_FSR_SURVEY             ; ~8 min: every cell pressed once, 0.08 mm at most past first touch
LRT_CALIBRATE              ; the reference: holder 45
LIMN_TOOL_CALIBRATE T=41   ; and the others
```

The survey's warnings name cells to move `z_cell` or the edges to when the ones in the config are weak or faulty on this sheet.

It reads the sheet at rest, finds the tip, and presses every cell (but the dead row) from just above contact to 0.08 mm past first touch, one console line a cell. Then it judges: faulty (high at rest, or another cell answers while it is pressed), weak (under half the median), the noise floor and from it the `early` threshold, and an aim that brings the reference tip down mid cell on a good one. All saved per bed (`lrt_fsr_survey`) and gone by from then on: faulty cells aren't read, the aim and `early` are the survey's. It warns when the measuring cell or an edge cell is faulty or weak, with the strongest cells to use instead (`z_cell`, `x_edges`, `y_edges` in `ext/limn/beds.py`). `SURVEY=0` on a measurement ignores it, `LRT_FSR_SURVEY CLEAR=1` drops it.

What the sheet does, measured on 2026-10-07 (`ext/tests/test_fsr.py` simulates it, `bed5=True`): column 3 is faulty and never read (`faulty_cols`), row 3 has no series resistor (`dead_rows`); a press lifts its whole column, almost as much as the pressed cell at first touch; (2, 4) and (1, 4) are weak cells; the response stops rising ~0.13 mm in. A pen that comes down on another cell than aimed at is aimed again by that cell.

After `LRT_CALIBRATE` and `LRT_PROBE_TOOL` the tool draws a test mark on the paper: a corner that makes a `+` with the corner the previous tool left, and a corner at the next point for the next tool. Two pens that disagree show a step in the `+`: in its vertical line for X, in its horizontal line for Y. `LRT_MARKS` shows where the next one goes, `LRT_MARKS RESET=1` starts over on a new sheet.

Nothing is probed or drawn when a pen could hit the bed or the tools:
- Meshing puts the carried tool away first (`UNDOCK` in the `BED_MESH_CALIBRATE` macro). Empty holders are normal. With no tool saved as carried, the key locked (the `axis_k` endstop open) and exactly one holder empty, that tool is taken as the carried one and put away. With the key open, nothing is guessed: keeping the carriage empty is up to you.
- A mark is only drawn with a carried tool, with a paper mesh of this placement, inside that mesh and short of the holders (`MARKS_MAX_X`), and with sane offsets on its tag (`TOOL_MAX_DXY`, `TOOL_DZ`). The pen travels at the beds' travel height and comes down only over the mark.

There is some more info posted [here](https://hackaday.io/project/205431-limn-pen-plotter-with-toolchanger) about this project.
