+++
summary = "Reads the pens' NFC tags: hold a pen to it until it beeps, then put it in a holder. A PN532 on a slider, on the Pi's I2C bus."
+++

## Step: Print

- Print the [[limn-nfc-mount]], the [[limn-nfc-rail]], the [[limn-nfc-rider]], the [[limn-nfc-back]] and the
  [[limn-nfc-top-cover]].
- [?] Material, orientation, supports.

## Step: The slider

- The reader rides on two 2 × 50 mm dowels, through two [[2x5x3-ed001-bushing]] bushings.
- The slider lets the reader retract. It sits beside the first holder, where the carriage pushes it back on Y, and an extension spring brings it out again ([log #4](/log/2026-04-09-detecting-tools-tool-parameters-slicing.html)).
- [?] How the bushings and dowels go in (pressed, glued?).

## Step: The reader

- The PN532 board sits between the back (embossed *PN532 I2C*) and the top cover.
- [i] The reader listens for 0.5 s per try. It reads best from its edge.
- [?] Its I2C setting, the soldering, the cable to the Pi.
