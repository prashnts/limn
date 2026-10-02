+++
summary = "Five holders for the tools, with a micro switch in each, and the NFC reader at the end. It has to stay put when the toolhead runs into it."
+++

## Step: Hold it in place

- The dock's brackets clamp onto a steel rod and rest on the base, so a crash doesn't move it.
- The middle bracket used to be the hinge for the KlipperScreen. Since the screen came off (2026-08-19), it holds a belt tensioner.

## Step: The holders

- Each holder has two 5 × 10 × 1 mm magnets (10 for the dock), facing the other way from the tool's own pair.
- The holders were redrawn in August 2026: the old ones rubbed against the pens' NFC tags until they broke. The new ones leave room for the tag, and for its chip especially ([log #13](/log/2026-08-13-updates-to-the-tool-dock-printables-project.html)).
- At the same time each holder got a [[dongnan-kw4a-s-micro-switch|micro switch]], read through the [[mcp23017-adafruit]]. Now Limn knows whether a holder has a tool, and whether a pick-up worked. Which pin is which holder: [Electronics](/electronics.html).
- [i] The holders are numbered 41 to 45 in Klipper.

## Step: Dock positions

The dock's coordinates for each holder used to be found by hand, *a very annoying and time consuming process*. A [[vl53l5x-tof]] was tried for finding them ([log #14](/log/2026-08-16-calibrating-the-dock-parameters-automatically-with-tof-sensor.html)). In the end, the misses were [loose belts](/log/2026-09-05-loose-belts.html), and the positions held once the belts were fixed.

## Hardware, from the build notes

| Part | Qty | For |
|---|---|---|
| 5 × 10 × 1 mm magnet | 10 | the holders |
| Micro switch | 5 | a tool in the holder |
| MCP23017 | 1 | reads the switches |
| PN532 | 1 | the [[limn-nfc]] |
| 2 × 50 dowel, 2 mm bushing | 2, 2 | the reader's slider |
| Extension spring | | pushes the reader back out |
