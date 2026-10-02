+++
title = "Notebook: Pens on the panel, and its Z"
date = 2026-06-09
author = "Prashant Sinha"
note = "Written up by Claude from the code and data in notebooks/act3-synthetic-calib.ipynb and notebooks/act-5-z-calib.ipynb. The experiments are Prashant's. Hackaday log #12 has the short version."
source = "notebooks/act-5-z-calib.ipynb"
+++

After the test probe ([previous notebook](/log/2026-05-25-notebook-reading-the-touch-panel.html)), the next step was real pens, and then Z. This is the data behind the "it works" log (#12), from the day full pen calibration on the panel was committed.

## Four pens on one grid

The last part of `act3-synthetic-calib.ipynb` probes four pens over a 4 × 3 grid (X 35–71, Y 50–65): a purple felt tip, a 0.2 fineliner, a green fineliner and a red pen, two runs each. Each pen lands as a tight group beside every grid point. The groups sit apart from one another, and that gap is what has to be calibrated away:

![Four pens over the grid, and where the plotter touched](/log/img/nb-act3-pens.webp)

Purple and red differ by a median (-0.10, -0.21) mm.

## The reference over the panel

Next comes the reference pen over a 7 × 6 grid (X 30–90 in steps of 10, Y 42–62 in steps of 4). Its touch heights climb steadily with X, from about 5.1 at X 30 to 5.4 at X 90: the panel is tilted by 0.3 mm over 60 mm. So Z has to be measured where each pen touches, not once. Five single touches (one at X 30, 50, 60, 70 and 90) read 0.3–0.4 mm under their neighbours, which is why every point gets several touches and a median.

## The profile, v2.0

`act-5-z-calib.ipynb` reads a calibration profile as the Klipper side wrote it (`[limn] version = v2.0`). It has the following:

- `touch_params`: the six coefficients of the touch-to-plotter map;
- `ref_samples`: the reference pen on a 4 × 4 grid (X 30–90, Y 42–65), with where the plotter was and where the panel says the tip was, and the Z where it touched;
- `ref_z_panel` and `ref_z_paper`: the BLTouch over the same points on the panel, and over the paper from Y 110. The BLTouch sits 34.34 mm left of the pen and 25 mm behind it, so it probes (30, 42) from (64.34, 17).

The reference pen touches the panel **0.18 to 0.36 mm above** the BLTouch's trigger at the same spot: 0.28 on average, 0.31 median. That offset is how a height measured on the panel carries over to the paper, which only the BLTouch has seen.

A second pen is then measured the same way, and its median difference to the reference is its tag. For the red pen:

| | dx | dy | dz |
|---|---|---|---|
| red − reference | +0.61 | +1.33 | +0.95 |

These are the numbers `TOOL_TAG_WRITE` puts on the pen's NFC tag, and `_APPLY_OFFSETS` applies whenever that pen draws.
