# Automatic Tool Alignment - Part 4: One FSR is enough

The resistive touch panel got the tools to ~0.2mm, which is fine for 0.5mm pens. For the fine ones (0.05 fineliners, the Micron) I wanted the Force Sensitive Resistor array. The plan was two 4x8 arrays at right angles on BED_5, one for X and one for Y. I couldn't fit two of them on the bed, so before cutting another one I simulated whether the second array was needed at all.

It isn't. This post covers why, how the alignment works now, what the real sheet taught me, and the first numbers.

## One array or two?

The alignment finds the edge between two cells. Between two cells there is a dead zone (<0.5mm) where neither responds, so I tap from cell A's centre towards cell B's until A stops responding, then from B's towards A's until B stops. The edge is halfway between the two, so the width of the dead zone cancels out:

```python
a_off = last_response(cell_a, start=centre(a), end=centre(b))
b_on  = last_response(cell_b, start=centre(b), end=centre(a))
edge  = (a_off + b_on) / 2
```

A tool whose tip sits off by `t` meets the edge `t` early, so `dx = x_tool - x_reference`. One edge only sees the offset along its own normal, which is why I thought I needed a second array turned 90°.

But the array is a real 4x8 matrix (8 driven columns, 4 sensed rows), so it has edges both ways: between columns, and between rows. The code only ever used the column edges. A single array turned 45° doesn't help either: a column edge then measures `(dx + dy)/√2`, and a tool off by (+0.5, -0.5) looks perfect.

I ran it through a Monte Carlo sim (the real search code over a simulated sheet with mounting error, uneven dead zones, tip sizes, backlash). Errors are in mm, tips within ±1mm:

| Layout | Axes solved | RMS dx / dy | Sensor wait per tool |
|---|---|---|---|
| 2 arrays, column edges (the old plan) | 2 | 0.024 / 0.024 | 18s |
| **1 array, column + row edge** | 2 | 0.026 / 0.025 | 11s |
| 1 array at 45°, column + row edge | 2 | 0.030 / 0.029 | 11s |
| 1 array at 45°, column edges only | 1 | 0.39 / 0.40 | 11s |

One array does the same job, faster, since there's only one contact z to find. The 45° one also takes a 21x21mm footprint instead of 20x10.

## How it measures now

For every tool, reference or not:

1. **BLTouch z** of the sheet, the pen put away first (the probe sits 34mm left of the pen, which puts the carriage right in holder 41's lane).
2. **Locate**: come down at the array's aim point until any cell responds, press in, take the strongest cell, then tap outwards along the columns and the rows until that cell lets go. That gives the tip's offset to a few tenths.
3. **Contact z** on the z cell, aimed with that offset: coarse 0.2mm steps, back off, 0.02mm steps, three times, median.
4. **The two edges**, X between rows 1|2 and Y between columns 3|4, again aimed with the offset.

Step 2 is what makes unknown pens safe: a pen 3mm off still lands on the cells it measures. A pen that misses the array feels nothing and goes down to a floor, never below 0.5mm under the BLTouch z, then lifts and stops. With `Z=` (the contact I expect, eg. from another bed's tag) the floor is 0.4mm under that instead.

The FSR is too slow for the probe endstop (~20 frames/s over the chain), so the routine moves and reads the array itself, in "matrix mode": all 32 cells every frame, touched or not. No frames for 0.25s, or any cell above 950: lift and stop.

## What the real sheet taught me

The sim assumed a clean sheet. The real one had opinions.

- **The columns run towards -Y**, not +Y, and the array sat ~3mm further along X and Y than configured. Mapped with a few light presses at known points. `locate` doesn't mind small errors, as long as the aim lands on the array.
- **Row 3 is useless.** My RP2040 board has series resistors on the ADC lines, except on row 3. Any press in a column lifts row 3 to ~500, pressed or not. It's now a `dead_row`.
- **Row 0 hears its column too**, less. A tip on (1,5) reads 880 there, and row 0 picks up a share. With a fine tip split across two rows, each half can drop to row 0's level, so row 0 only counts when no other row of its column responds.
- **And column 3 hears its row.** With the Micron pressing (1,5) at 355, (1,3) read 259: 0.73 of it (more on that in the Micron part). So a cell only responds if it is at least 90% of the strongest:

```python
def responds(strengths, cell):
    s = strengths.get(cell, 0)
    return s >= 150 and s >= 0.9 * max(strengths.values())
```

- **The taps follow the `lrt_fsr` mesh.** The routine's moves are raw, so Klipper's mesh never corrected them. I first blamed a sloped sheet for the Micron's trouble, but the BLTouch says the array is flat to ±0.06mm. It was the columns (below). The taps keep their depth anyway:

```python
def follow(xy, at):
    '''How much higher the sheet is at xy than where the contact z was found.'''
    return mesh_z(lrt_fsr, *xy) - mesh_z(lrt_fsr, *at)
```

- **A fine tip on an edge is a coin toss.** Aimed blind, the 0.05 fineliner came down right on the row 1|2 edge. `TIP=x,y` lets me aim so it lands mid-cell.
- And two plain bugs: numpy floats in the toolhead position broke Klipper's status JSON, and a garbled line from the Dock took all of Klipper down from its read timer. Both fixed. The FSR also needed its firmware updated before it would do matrix mode at all.

## Parameters

From `ext/limn/beds.py`, BED_5:

| Parameter | Value | What for |
|---|---|---|
| `pitch` | 2.5mm | cell size |
| `respond` | 150 | strength (0..1000) that counts as touched |
| `dominance` | 0.9 | ...and at least this share of the strongest cell |
| `sure` | 700 | another cell this strong: the tip is there, not crosstalk |
| `press` | 0.3mm | below contact for the XY taps. 0.2 was worse on a 0.05 tip |
| `step` / `fine_step` | 0.2 / 0.02mm | z search |
| `resolution` | 0.02mm | edge search (0.1 in `locate`) |
| `tool_z` | -0.5..3.0mm | search window over the BLTouch z |
| `prior_margin` | 0.4mm | below an expected contact, with `Z=` |
| `dead_rows` / `crosstalk_rows` | (3,) / (0,) | see above |
| `aim` | row 1.5, col 3.5 | reach from there: ±3.75mm in X, -8.75..+11.25mm in Y |

## Results

All on BED_5, with `LRT_FSR_MEASURE`, which runs the calibration measurement but only reports it. One BLTouch z (2.721) for all pens, so their dz compare directly.

**Repeatability**, spread between runs:

| Pen | Runs | x | y | contact z |
|---|---|---|---|---|
| Stabilo Test Blue | 5 | 0.020 | 0.039 | 0.02 |
| Staedtler Black 0.5 | 2 | 0.039 | 0.000 | 0.02 |
| Fineliner 0.05 | 2 | 0.010 | 0.312 | 0.02 |

The two normal pens repeat to a few hundredths, as the sim said (~0.02 RMS). The 0.05 fineliner doesn't in Y: its needle tip likely bends under the press, and is too thin to bridge the dead zone (Y gaps up to 0.6-1.0mm, against under 0.25mm for the others).

**FSR against the RTP tags**, as differences between pens (both are relative to a reference, so only differences compare):

| Pair | FSR (dx, dy, dz) | RTP tags | Difference |
|---|---|---|---|
| Staedtler - Stabilo | +0.69, +0.88, +0.53 | +0.73, +0.70, +0.56 | -0.04, +0.18, -0.03 |
| Fineliner - Stabilo | -0.06, +0.67, +0.75 | +0.14, +0.98, +0.81 | -0.20, -0.31, -0.06 |
| Fineliner - Staedtler | -0.75, -0.21, +0.22 | -0.59, +0.28, +0.25 | -0.16, -0.49, -0.03 |

X agrees to 0.04mm on the two normal pens, Y to 0.18mm, which is about what I expected from the RTP (~0.2mm). The fineliner rows are dominated by its own 0.3mm scatter.

**Z** turned up something about the RTP: FSR dz minus tag dz is 0.72, 0.69 and 0.66 for the three pens. A constant 0.69mm is the RTP's trigger lag. Without the diodes the touch reaches the probe endstop over UART, and at 5mm/s the probe keeps going for ~140ms. It cancels between pens, but its jitter is in every RTP dz.

**Time**: ~2 minutes per measurement, ~2.5 with the BLTouch z, mostly the z search and the taps at 2mm/s.

## The Micron

T0 is my old reference pen, a fine Micron, so it went last and with everything the other three pens could tell me about it. Their FSR positions minus their RTP tags put its tip at (-1.3, 0.95) from the toolhead, and their dz put its contact at z=5.31 (it touched at 5.25). So it was measured with `TIP=-1.3,0.95 Z=5.31`: aimed mid-cell, and never more than 0.4mm past where it should touch.

It didn't produce a number, and every try stopped and lifted as it should. Holding it at a few points and reading the whole matrix showed why:

| Tip on | z | Strongest cells |
|---|---|---|
| (1,3), 0.3mm in | 4.95 | (1,3)=764, (3,3)=354 (dead row), (0,3)=78 |
| (1,5), ~0.1mm in | 4.92 | (1,5)=355, (1,3)=259, (3,5)=200, (1,0)=179 |
| (1,5), ~0.25mm in | 4.77 | (1,5)=401, (1,3)=288, (3,5)=248 |

(1,3) kept reading high with the tip two columns away. `locate` held on to it about 1.2mm past its edge, and the next search aimed half a cell off, straight onto the edge between columns 3 and 4, where (1,3) read 16. I stopped rather than press the Micron more for a number I wouldn't trust.

Then I did the same with the 0.05 fineliner, moving its tip along row 1 and into row 2:

| Tip over | Strongest cells |
|---|---|
| (1,3) | (1,3)=517, (1,4)=208 |
| halfway into (1,4) | (1,3)=479, (1,4)=177 |
| (1,5) | (1,3)=416, (1,5)=244 |
| (1,6) | (1,3)=309, (1,6)=208, (1,0)=192 |
| (2,5) | (2,5)=276, (2,3)=114 |

At rest (1,3) reads under 10. But press anywhere in row 1, even 7mm away, and it lights up, often above the cell that's actually pressed. Row 2 does it too, weaker. That's not the sheet: column 3's drive line (GPIO 11) seems to leak into the other columns, so whatever is pressed in a row also shows up in column 3. Column 0 a little too. A thick pen saturates its cell at ~880 and still wins, which is why the Stabilo and the 0.5 Staedtler measured fine. A fine tip presses 250-500 and loses. And every measurement so far used column 3: the aim, the z cell and both edges.

## Next

- Find column 3's leak. Until then, move the aim, the z cell and the edges off column 3 (eg. to columns 5 and 6), or treat it like row 3. Then the Micron again.
- A pause between pens to wipe the sheet, so ink from one pen doesn't end up on the next. It can tell the sheet was wiped from the presses themselves.
- The meshing guard assumed holder 44's pen was on the carriage because 44 was empty and nothing was saved as carried. 44 has simply never had a pen. It stopped safely, but it shouldn't guess a holder that has held nothing since boot.
- `fsr_pull_down` in the node config, to see whether the crosstalk goes away at the source.
- A command to move a tool between holders, so the reference can go into holder 45 without my hands.
