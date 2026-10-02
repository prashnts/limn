+++
title = "Notebook: Reading the touch panel"
date = 2026-05-25
author = "Prashant Sinha"
note = "Written up by Claude from the code and data in notebooks/act1-grids.ipynb and notebooks/act3-synthetic-calib.ipynb. The experiments are Prashant's. Hackaday log #11 has the short version."
source = "notebooks/act3-synthetic-calib.ipynb"
+++

The resistive touch panel ([log #10](/log/2026-05-12-automatic-tool-alignment-in-xyz.html)) reports raw numbers, not millimetres. Before it could align pens, two questions needed answers. How do the panel's numbers map to the plotter's coordinates? And how well can it tell two pen tips apart? These two notebooks answer them.

## Where to touch (act 1)

`act1-grids.ipynb` plans the probing. It lays out three things:

- a 6 × 5 grid over X 25–100, Y 30–70;
- a denser 4 × 3 grid in one corner (X 25–50, Y 65–75);
- three calibration points at Z 9: (100, 52), (65, 30) and (25, 70), spread as far apart as the panel allows.

![The probe plan: the grids, and the three calibration points (large)](/log/img/nb-act1-grid.webp)

The second cell plans a zig-zag 5 × 5 grid over X 20–100, Y 120–150, which is on the paper rather than the panel. That one is for marks drawn to check the result by eye.

## From raw numbers to millimetres (act 3)

The CYD's XPT2046 gives 12-bit positions, which here run from about 450 to 3300. The panel lies turned 90° on the bed, so the plotter's X follows the panel's Y and the other way round. Raw readings over the grid come out as a sheared, rotated lattice:

![Raw panel readings for the whole grid](/log/img/nb-act3-raw.webp)

The panel gets three points, touched several times each. The median of each point's touches goes into the three-point calibration from Atmel's [AVR341](https://cdn-shop.adafruit.com/datasheets/AVR341.pdf) note. That gives six coefficients, an affine map from touch to plotter coordinates:

```python
A = (Xd1*(Yt2-Yt3) + Xd2*(Yt3-Yt1) + Xd3*(Yt1-Yt2)) / (Xt1*(Yt2-Yt3) + Xt2*(Yt3-Yt1) + Xt3*(Yt1-Yt2))
B = (A*(Xt3-Xt2) + Xd2 - Xd3) / (Yt2 - Yt3)
C = Xd3 - A*Xt3 - B*Yt3
# D, E, F the same way for Y
x = A*xt + B*yt + C
y = D*xt + E*yt + F
```

These six numbers are what later became `touch_params` in the calibration profile.

Some spots read much more steadily than others. Five touches at (30, 70) read 3140–3144. Five at (100, 52) spread over 80 counts, which is about 2 mm. So the notebook keeps only "good spots": points whose repeated touches have a standard deviation under 5 counts (`MINSTD = 5`).

## Can it see an offset?

Real pens weren't used to test this. A test probe was, and its tip can be pushed off-centre by loosening one of its three coupling screws. That made nine positions, numbered like this:

```
1     2
  3 4
   5
  6 7
8     9
```

Each position was probed over the whole grid, some of them several times (`gridfn1_1` … `gridfn9_3`). The comparison maps both runs through the transform and takes the median difference to the centred tip, position 5:

| Against 5 | dx, dy (mm), the runs separated by · |
|---|---|
| 5 again | -0.00, -0.01 · 0.05, 0.01 · -0.07, -0.14 |
| 2 | 3.73, -2.51 · 3.66, -2.60 |
| 3 | -1.43, 1.32 · -1.39, 1.30 · -1.59, 1.34 |
| 7 | -1.37, -1.16 · -1.40, -1.24 |
| 8 | 3.00, 2.57 · 2.65, 2.52 · 2.98, 2.62 |
| 9 | -2.31, -2.41 · -2.48, -2.46 · -2.32, -2.40 |
| 1 | -2.55, 2.43 · -2.51, 2.50 · -2.63, 2.44 |

The signs follow the layout, and runs of the same offset agree to within 0.1–0.35 mm. Reconstructed, each position shows up as its own small cluster beside every grid point:

![Every run through the transform, coloured by the tip's position](/log/img/nb-act3-reconstructed.webp)

That settled the plan in log #11. The panel would do rough XY (to about 0.2 mm) and Z, and a force-sensing array would come later for precise XY.
