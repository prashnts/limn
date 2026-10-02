+++
summary = "A 4-wire resistive touch panel, reclaimed from a car GPS. It finds a pen tip on the calibration bed to about 0.2 mm."
+++

![Out of the car GPS](/img/notes/rtp-car-gps-1.webp)

- Four wires: X+, X−, Y+, Y−. A [[rp2040-tiny-v1-1]] reads it directly on its ADCs (GPIO 28, 26, 27, 29). It was a CYD's XPT2046 at first.
- Waiting for a touch, the board grounds the Y plate, pulls X+ up, and watches for X+ to fall, as an XPT2046 does. With the touch line's diode fitted, that's quick enough to send the probe pulse at once.
- Accuracy: about 0.2 mm in XY after calibration, which is enough for 0.5 mm pens. The [notebooks](/log/2026-05-25-notebook-reading-the-touch-panel.html) have the data.
