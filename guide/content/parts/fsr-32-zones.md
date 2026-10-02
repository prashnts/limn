+++
summary = "FilmSensor FS-ARR-4X8-ROT: a 4 × 8 force-sensing resistor array, 2.5 mm cells, 0.3 mm thin. The calibration bed's fine sensor."
+++

![The sensor strip](/img/notes/fsr-strip.webp)

| | |
|---|---|
| Part | [FS-ARR-4X8-ROT](https://film-sensor.com/product/fs-arr-4x8-rot/), FilmSensor, from Alibaba |
| Array | 32 points: 8 × 4, each cell 2.5 × 2.5 mm, about 50 × 12 mm in all |
| Thickness | 0.3 mm |
| Actuation | 20 g; range 20 g – 5 kg per point |
| Not pressed | > 20 MΩ |
| Response | < 10 µs |
| Temperature | −20 to +65 °C |
| Connector | 12-pin FFC, 0.5 mm pitch |

![Its drawing](/img/notes/fsr-drawing.webp)

From the maker's notes:

- It shows the *trend* of a force, not an accurate value: the more force, the lower the resistance.
- Don't fold the sensing area, and don't bend it more than 90°.
- Mount it on something flat and smooth. Damp air and dirt can trigger it.
- Too much force doesn't damage it.

![Force against resistance](/img/notes/fsr-force-curve.webp)

![A 12-pin FFC breakout for it](/img/notes/fsr-ffc-adapter.webp)

In Limn it's read as a matrix: the bed MCU drives the 8 columns and reads the 4 rows on its ADCs. How it measures a pen tip, and what this sheet got wrong: [part 4](/log/2026-09-29-automatic-tool-alignment-part-4-one-fsr-is-enough.html).
