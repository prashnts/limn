# Automatic Tool Alignment - Part 5: Pressing too hard, and a camera instead

The first plots from `plot/` looked wrong on 2026-09-30. With a Micron 01 the lines grew wide and the small text went blobby, and the pens were getting damaged. `plot/` puts the pen down at `G1 Z1`, the old ACT1, so the question was where the pens actually touch the paper. This post covers the day spent finding out: an FSR that couldn't say, a Z ladder read off a photo, and why the next step is a better camera, not a better bed.

## What pen-down means

```
Klipper Z  =  G-code Z  +  tag dz  +  lrt_paper mesh at (x, y)
```

The tag's dz comes from the FSR: contact on the z cell, less the BLTouch z of that cell. There are two catches.

- `bltouch_z()` stores Klipper's raw trigger height (`test_z`). The mesh stores `test_z - z_offset`, and z_offset is 0.8.
- The FSR's "contact" is a force threshold (a cell reading 150), not first touch.

So a pen whose tag is right touches the paper at about **G-code Z0.9**, not Z1. The pens only drew at all because their tags were stale in the right direction, and that is exactly what went wrong: the tips had broken and changed length since they were tagged.

## The FSR, again

I tried re-measuring the tags on BED_5's FSR first.

- **Column 3 is still faulty** (the glue void, see the 09-29 survey). The z cell and both edges were on it. They are on column 1 now, and the first touch comes down mid column 5. Moving the aim 10mm from the z cell meant following the sheet's slope from one to the other (the `lrt_fsr` mesh), or the contact search started pressed in already.
- **A bent 0.05 liner reads in the air.** The Staedtler lifted a cell over 150 before its tip was down. Pressed in from there it felt nothing, and the routine gave up. Now that's a *false start*: it carries on down to the floor, and backing off only counts a real press (`sure`, 450) as still touching.
- **The Micron measured**: dz 2.04 against its tag's 1.45, the tip 3.4, 2.7mm off the toolhead. **The Staedtler never did**, even at `PRESS=0.5`: at best 121, scattered over cells it wasn't on.

The Z axis has play too, a few mm (GEOMETRY.md, *The Z axis and its play*): a press lifts it, and a pen only lets go once it is back down. That blurs any single pressure measurement, and it's why each pen now has its own press and the lift after a stroke follows the play (`limn_cam play`).

## The Z ladder

Asking the paper directly works better. Each pen draws short strokes along +Y, one per z, from high (in the air) to low (pressing), 2.5mm apart along X. The first stroke that shows is where the pen touches. Every stroke comes down from the same hop over the highest z, so the play in Z is taken up the same way each time, as a plot's pen-downs do.

By eye first, on the overhead IR camera (`/webcam4`). That was a mistake worth writing down: **on that camera +X runs up the image and +Y runs left**, and I swapped the two pens' columns.

Then automatically, with `limn_cam/` (new, see below):

1. Park the empty carriage out of view (X0 Y0 Z9), take a shot.
2. Plot the ladder. The first pen also draws **five crosses** around the block: four at the corners and one a third of the way along one side and further out, so they fit only one way round. The first try had that fifth cross on the line of two others, and a mirrored fit (two corners swapped) fitted better than the right one.
3. Park, take a second shot.
4. **Ink** = how much darker each pixel got, as a fraction of its local brightness (both shots divided by their own blur), so a change in the light doesn't read as ink. Only the paper counts: the largest bright, smooth region in the first shot. The lens's black ring and the rest of the machine change between shots too.
5. **Register**: the crosses are the square-ish blobs of ink (a stroke's box is long and thin; a cross drawn light can weigh less than a stroke pressed hard). Try every assignment of four of them to the corners, check that the fifth lands, and keep the best. That gives the homography from paper mm to pixels, whatever the camera. It fits to 0.2px.
6. **Read** each stroke: sample the ink along where it should be, and take the share over the threshold. The pen touches from the highest z where it and everything below drew.

```
2.8 px/mm, crosses fit to 0.21 px, ink threshold 0.0661
T0: touches at z 1.7, a whole line from z 1.6   [2.4:. .. 1.8:. 1.7:+ 1.6:# .. 1:#]
T1: touches at z 2.0, a whole line from z 1.9   [2.4:. .. 2.1:. 2:+ 1.9:# .. 1:#]
```

`uv run python -m limn_cam ladder T0 T1 --url https://limn.nb.malow.im` does all of it and suggests the new dz. `--resume` finishes a ladder that was cut short, drawing only the missing rows.

## Numbers

Sheet 1, first plots at pen-down Z1:

| Pen | Tag dz | Touches at | Pressed at Z1 | FSR dz |
|---|---|---|---|---|
| T0 Staedtler 0.05 | 0.75 | Z1.7 | ~0.7mm | not measurable |
| T1 Micron 01 blue | 1.45 | Z2.0 | ~1.0mm | 2.04 |

New dz so that both touch at Z1.2, 0.2mm of press at Z1: T0 1.25, T1 2.25. T1's 2.25 then broke the tool change: `_APPLY_OFFSETS` sets the offset with `MOVE=1` from Z8, and 8 + 2.25 went past position_max 10. Both offset macros now stay under Z9.5 less the dz.

Sheet 2, fresh sheet and mesh, the ladder packed into the bottom-left corner, with the Stabilo:

| Pen | Tag dz | Touches at | Then |
|---|---|---|---|
| T0 Staedtler | 1.25 | Z1.0 (not 1.2) | dz 1.05 |
| T3 Stabilo blue (sacrificial) | -0.06 | Z1.7 | dz 0.44 |
| T1 Micron | 2.25 | nothing down to Z0.8 | ? |

- The Staedtler came 0.2mm off target on the new sheet. Its drawing came out complete and looks better.
- The Stabilo's drawing misses whole patches. The G-code has every stroke, and both early and late strokes are missing, so the pen didn't run dry. The frame around the gaps came out whole, so it looks local: a spot where the sheet sits a little lower than the 4x6 mesh says, and 0.2mm of press doesn't reach. A felt tip wants more press anyway.
- The Micron drew nothing at all. Maybe it slid up in its clamp (the FSR taps and the old 1mm presses push on it). To be checked.

The shots are in `~/limn-shot/ladder-20260930-*` and `drawing-20260930-*`.

Later, the Stabilo moved to holder 41 (T0). It had been out of its cap for hours, and a ladder there only left broken crosses even at Z0.8. Primed, it touched at Z1.0 (0.2 low again on this sheet, like the Staedtler) and got dz 0.24. The drawing redrawn with it at the new heights (pen-down Z0.9: press 0.3; hops Z2.0) came out complete, next to its patchy copy from before. That makes the patches a dried tip more than a height problem.

`limn_cam play` then measured the play: four spots, 13 trial rises, a 0.3 press. At every spot the pen still dragged ink at rises of 0 and 0.25mm over touch, and let go from 0.5mm: 1.67 per mm of press, into `plot/profiles/play.toml`. The four spots only spread 15mm in Y (sheet 2 was full), so the next sheet spread six: Y 40, 94 and 148, X 11 and 56. Every spot gave the same result: a drag at rises of 0 and 0.25, gone from 0.5. With a 0.3 press and a slow lift, the play of a few mm measured by hand doesn't show, and some of that 0.5 is this sheet's ±0.2 in touch. It may take a harder press, the sideways pull of drawing, or faster moves to bring it out: a test to design. The factor stays 1.67 (hops Z2.2 after a 0.3 press), safe either way.

## Why this goes in circles

Each measurement is one number per pen, taken in one place: a corner of the sheet, or the FSR. The errors that matter are ±0.2mm and they vary:
- by place: the sheet's flatness, the mesh's ~30mm grid;
- by run: Z play, a new sheet, a new mesh;
- by pen: tips that break and slide in their clamps.

Pressing 0.2mm past touch is inside that noise, and so every correction moves the problem somewhere else.

The overhead camera doesn't help enough either. At 2.8 px/mm it can tell ink from none, but not a 0.1mm line from a 0.3mm one, or a blob from a letter. It says whether a pen drew, not how well.

## A camera instead

The ladder shows the paper can be the sensor. What it lacks is a close look, and a look in the right place at the right time. Cameras that could provide that:

**Camera on the tool.** A small camera riding with the pen, looking at the paper just behind the tip. My camera-on-tool experiment showed the view is there. At 50+ px/mm it sees what the overhead camera can't:
- **Line width** straight after the stroke, so z_down can be chosen for a width, not guessed. A short ladder read up close gives width against z for each pen: the press curve.
- **Ink appearing.** Come down slowly at any spot until ink shows (a short wiggle at each z): that is the contact z there, on this sheet, now. A dozen spots over the drawing area give the surface in the pen's own terms, and show where the BLTouch mesh is off (a sheet not lying flat, a patch like the Stabilo's).
- **Gaps and blobs** during a plot: a stroke that left no ink gets redrawn a little lower; a line that grows wider than the pen means lift.

**Endoscope looking up at the tip.** Fixed at a known spot the carriage visits (like a toolchanger's nozzle camera), backlit. It sees the tip itself:
- **dx, dy** to a few hundredths: the tip's centre in the image against the reference pen's. No pressing on anything, so the fine and bent tips the FSR can't feel are no problem.
- **A broken or bent tip**, its shape and length, before it ruins a plot. Checked at every pickup, it catches a pen that slid in its clamp.
- Seen from the side instead (the endoscope level with the paper), **the gap between tip and paper**, for contact z without touching.

**The axiscam and the ArUco tags.** The axis camera rides on X. The tags on the carriage give the toolhead's position and scale in every frame, so the camera's view can be tied to machine coordinates without a calibration card. It works for any camera that sees a tag, the tool camera too.

For all of them:
- **Fixed focus.** Autofocus hunts on near things (the axiscam locked onto the carriage). The focus can be set in crowsnest's `v4l2ctl` (`focus_automatic_continuous=0, focus_absolute=..`).
- **Steady light.** The ink map copes with the light changing between shots, but a flash or a moving shadow is worse.
- **Enough pixels:** 20 px/mm at least to see a 0.1mm line, 50 to measure its width.

## limn_cam

`limn_cam/` is in layers, so a new camera or library slots in:

- **Sources**: Moonraker webcams by name (`moonraker.py`), image files. An endoscope over USB would be one more.
- **Backends** (`backend.py`): connected blobs and ArUco markers. OpenCV (`opencv-python-headless`) when it's there, numpy alone for blobs.
- **Core, numpy** (`geometry.py`, `image.py`): homographies from paper mm to pixels, the lighting-proof ink map, finding the paper, sampling.
- **Procedures** (`ladder.py`): the ladder's G-code (checked with `plot`'s safety check: never under safe_z off the paper), registration, the reading, the suggested dz.

Tests: `uv run pytest limn_cam/tests`. A synthetic ladder is shot through a turned, perspective, unevenly lit camera, and the touch heights come back out.

## Next

- [ ] The Micron: seated? writing? Then its ladder row again.
- [ ] The Stabilo: more press (~0.4-0.5mm), redrawn in the free band at the top of sheet 2.
- [ ] Fixed focus on the axiscam, and a look at the paper right by the tip.
- [ ] The camera on the tool, mounted for good: the close ladder (width against z), then contact at a grid of spots.
- [ ] An upward endoscope at a fixed spot: dx/dy from the tip's image, and a tip check at every pickup.
- [ ] The ladder at more than one place per sheet, until the tool camera takes over.
