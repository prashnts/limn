+++
summary = "A detachable bed that measures the pens: a resistive touch panel finds a tip to ~0.2 mm, a 32-zone force sensor finer still. It plugs in on magnetic pogo pins."
+++

## Why

Every tool lands a little differently on the paper, even though the coupling repeats per tool. Aligning each pen by hand took about 30 minutes for three pens. So the plotter measures them itself: each pen touches a sensor, and its offset from a reference pen goes onto its NFC tag ([log #10](/log/2026-05-12-automatic-tool-alignment-in-xyz.html)).

## Step: The touch panel

- The first bed used a **Cheap Yellow Display** (CYD 2.8"), whose XPT2046 reads a resistive panel. The display came off, and pigtails went onto the four panel pins.
- The panel itself came from an old car GPS. The CYD's own panel works as well, and it's thinner.

![The car GPS's panel, taken out](/img/notes/rtp-car-gps-1.webp)

![On the bed](/img/notes/rtp-car-gps-2.webp)

- The panel reads in its own units. Three touch points give an affine transform to the plotter's millimetres (Atmel's AVR341 method). Some spots read much more steadily than others, so the early calibration kept only the "good spots". The [notebook](/log/2026-05-25-notebook-reading-the-touch-panel.html) has the numbers.

![Offsets from the panel, early on: the shape is right, but the scale drifted between runs](/img/notes/rtp-affine-offsets.webp)

- There's a screen protector over the panel. Probes spread over it so it wears evenly.

## Step: The force sensor

For fine tips (0.05 fineliners, a Micron), the bed gained an [[fsr-32-zones]]. Its cells are 2.5 mm, so a tip landing on a known cell, or between two, gives its position precisely. One array is enough for both X and Y ([part 4](/log/2026-09-29-automatic-tool-alignment-part-4-one-fsr-is-enough.html)).

- Two [[rp2040-tiny-v1-1]] boards sit in the bed, one for the panel and one for the array. The bed grew to about 3.2 mm thick, with a sanded FFC breakout.
- [!] On BED_5, column 3 leaks into its row (GPIO 11), and row 3 has no series resistor. Both are worked around in software, but a new sheet is due.

## Step: The connector

- 5 [[magnetic-pogo-pins-connector|magnetic pogo pins]]: power, GND, DETECT, TX and RX. The magnets make the bed's position repeatable.
- The Dock reads the bed's ID resistor on DETECT and only then switches power on, through a Pololu power switch. Wiring: [Electronics](/electronics.html).
- [!] The pogo pins have been fussy: a bad contact on DETECT was fixed on 2026-09-15.

## Step: Probing

A touch on the bed works like a BLTouch trigger. The Dock pulses an OR gate shared with the BLTouch, so Klipper's own `PROBE` stops on it. `LRT_*` commands do the rest: mesh the panel and the paper, probe the reference pen, then each tool, and write the tags. See [Software](/software.html).
