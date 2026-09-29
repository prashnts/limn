# BED_3 rebuild: RTP and FSR side by side

The RTP finds the tip (anywhere on the panel, to ~0.1-0.2mm), the FSR then measures it precisely. Side by side, not stacked: a layer under the FSR weakens its signal, and fine tips are already the weak case (see act-6-fsr-alignment.md).

## Before the rebuild

- [ ] BED_5's column 3 leak, with a multimeter, power off, sheet unpressed:
  - [ ] column 3's line (GPIO 11) to each other column line: should be open (MΩ). kΩ to a few 100kΩ is the leak.
  - [ ] if there's a leak, lift the sheet's tail and measure again from the board side: still there: wiring, solder, flux or connector. Gone: the sheet.
  - [ ] column 1's continuity to its pin (it barely responded).
- [ ] Note the current RTP tags of every pen (TOOL_TAG_READ), in case the new ones need comparing.

## The bed

- [ ] Move the RTP and the FSR up by 15mm or more.
- [ ] Everything the BLTouch has to reach (the FSR, and the RTP grid points) at y ≥ 25 and x ≤ ~145. The BLTouch sits at (-34.34, +25) from the nozzle, travel X 0-180, Y 0-177.
- [ ] Keep the carriage out of the holders' lane (holders at x ~125-176) when the BLTouch is over the FSR: the carriage is 34mm to the right of it.
- [ ] Keep clear of the paper, which starts at y = 110.
- [ ] RTP: room for three touch points spread as far apart as the panel allows (they set the raw -> plotter transform).
- [ ] RTP: room around the locate spot for a pen off by ±5mm (~15x15mm).
- [ ] FSR: a rigid, flat backing. Nothing compliant under it.
- [ ] FSR: every row's ADC line the same (series resistor, and a capacitor to ground if the others have one). Row 3 on BED_5 had none, and reads ~500 whenever its column is pressed.
- [ ] Check the FSR's columns for leaks before gluing it down (as above).

## Diodes (all beds)

- [ ] Fit the Schottky diode from GPIO 2 (or 3) to DETECT on every bed MCU: RTP and FSR nodes.
- [ ] `"touch_pin": 2` in `nodes/rtp.json`, `nodes/fsr.json` (and `fsr_bed3.json`), `mcu.py update --hop N --config ...`
- [ ] `"trigger": "detect"` in `nodes/dock.json`, `mcu.py update --hop 0 --config dock`
- [ ] `mcu.py stats`: `bad: 0` on every link.

## After

- [ ] Tell me the rough positions of the RTP and the FSR: I'll add BED_3's FSR to `beds.py` (origin, directions, aim) from a few light presses, as on BED_5.
- [ ] `LRT_FSR_MATRIX HOP=` (to do): a finger on one cell at a time. Does any column light up in the pressed row, like column 3 on BED_5?
- [ ] Re-take the RTP calibration, reference first, then every pen: without the UART lag (~0.69mm) the RTP dz is no longer comparable with the old tags.
- [ ] Then RTP locate -> FSR measure (to do), and the Micron again.
