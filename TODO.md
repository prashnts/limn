# Next

## plot/

- Fixes in the G-code generation (details to come, 2026-09-30).
- Text: fixes, and a way to see that a path is far too small for text, eg. a warning in the preview when glyphs come out smaller than the pen can draw.
- Pen-down: `z_touch - press` (1.2 less 0.15 for fineliners, 0.3 for the Stabilo 88), lifts by the press, `play.clear` and the play (`plot/profiles/play.toml`). The old "pens press too hard" was stale tags: done (`notebooks/act-7-camera-ladder.md`). To watch: touch moved by ~0.2mm from one sheet to the next (the Staedtler and the Stabilo both touched 0.2 low on sheet 2). Either a quick ladder per sheet, or `z_touch` per sheet/mesh.

## Pens, heights (limn_cam/)

- Holder 41 has the Stabilo "Stabilo Test Blue" (stb-88, dz 0.24, primed 2026-09-30): the only pen in use. The rest were taken out to keep them from drying.
- Micron 01 blue (dz 2.25): drew nothing even at Z0.8 on sheet 2. Seated? slid up in its clamp? writing? Then a ladder, `limn_cam ladder T<n> --z 2.0:0.4:0.1`.
- Staedtler 0.05 (dz 1.05): check on the next sheet it goes back in.
- Z play: gentle (0.3, 2mm strokes) and loaded (0.6, 10mm at 3000mm/min) tests both let go within 0.5mm over touch, the same all over the sheet (`limn_cam play`). The few mm measured by hand don't show on the lift. Still open: tilt while drawing (the pull along X vs Y), which a lift test doesn't see.
- Cameras aren't essential (OpenCV is the `cam` extra). Next: fixed focus on the axiscam; a camera on the tool for line width and contact; an upward endoscope for tip dx/dy (notebook act-7).

## ext/, klipper/

- Drying: per pen (`dry` minutes in pens.toml, 240 for the Stabilo 88, 10 for fineliners), twice that printing. To check on a real long plot: the SET_PIN beeps land between moves without a stall. Maybe a Fluidd button for `TOOL_DRY RESET=1`.
- BED_5 FSR: column 3 still faulty; z and edges moved to column 1, the aim to column 5. A 0.05 liner can't be measured on it (≤121 at PRESS=0.5).
- Toolchanger key rework: see *Toolhead rework* below.
- Tag reads: the PN532 listens for the whole 0.5 s now (`i2c.py`, `begin(retries=0xFF)`), untested on the plotter. If it still misses: read while approaching the reader from its edge, which reads best. Needs the edge's X and whether Z7 is safe for the last stretch.
- Holder 45 read empty with its pen in it (2026-09-29): seating or the switch.
- Key open with a tool still saved as carried: the saved tool is stale, the meshing could clear it instead of undocking.

## Toolhead rework (2026-09-30 discussion)

What's wrong now: the holders are slightly angled in X (the first tools push on the dock), and the key's centre is a bit off (a small crash as it enters a tool).

### Finding a tool's centre

The key sticks out ~7.5mm, so a QRE1113 anywhere on the carriage body is out of range (it works ~0.5-5mm, best ~1mm). On the key's tip it would work (wires through the key's limited turn), but it goes into every socket.
- [ ] **Chamfer first.** A generous lead-in on the key's tip and the socket, or a key that can float a little: a small miss becomes a slide. Sensing then only has to get close.
- [ ] **A magnet in each tool and a 3-axis Hall sensor on the carriage** (TMAG5273 or MLX90393: 2-3mm packages, I2C). A 3x2mm neodymium magnet, pressed in at a known spot by the socket, reads from 10-15mm. The field points at it: its offset from one or two readings, no scan. Dirt, light and plastic colour don't matter. The field's strength gives a rough height (a holder's tilt), and a polarity or a second magnet could tell tool types apart.
- [ ] **The coupling as a sensor.** If each of the three contact pairs can be read on its own before power goes on, the order they close in, on the way into a holder, tells which way it tilts, and when they close tells its height.
- A camera looking down (endoscope, tool camera) with a marker per tool also works, but is more work for this.

### Force at the tip: a flexure between toolhead and Z carriage

An FSR behind the key would see the key's preload less the pen's push, and FSRs are poor at small changes on a big load (hysteresis, creep). It's only good for crashes. A strain-gauge load cell carrying the whole toolhead is better, but too big for this toolhead. The compact version is a flexure with a displacement sensor:

- **Where**: between the toolhead and the Z carriage (which rides on Y). The Z carriage is the ground: bolt the flexure's fixed end to it and hang the toolhead from the moving end, so all of the pen's push goes through it. The Z play is between the carriage and the rails, further down, and doesn't disturb it. Nothing else may bridge toolhead and carriage (stiff cables, a second screw): a loose loop in the cables, strain relief on the carriage side. The toolhead's weight sits on it all the time: tare right before each pen-down.
- **Shape**: a parallelogram, two thin parallel blades clamped at both ends. It moves straight up and down and stays stiff sideways, so the drawing's drag and off-axis moments hardly show. Keep the pen's axis near its middle.
- **Blades**: spring steel shim (0.1-0.2mm, eg. feeler gauge stock) or FR4, clamped with screws. They're linear and don't creep. Printed blades (PETG over PLA) are fine to try but creep under the constant load.
- **Stiffness**: each blade clamped at both ends is `12 E I / L^3`, with `I = b t^3 / 12`, so two blades give `k = 2 E b t^3 / L^3`. Aim for ~2-10 N/mm, so the pen's 0.2-2N moves it 0.05-0.5mm. Eg. steel (E = 200 GPa) b = 8mm, t = 0.1mm, L = 20mm: k = 2 x 200000 x 8 x 0.001 / 8000 = 0.4 N/mm, too soft: t = 0.2mm gives 3.2 N/mm. PETG (E ~ 2 GPa) b = 10, t = 1, L = 15: ~12 N/mm.
- **An overload stop**: a hard stop ~0.5mm away, so a dock crash or a hand can't bend the blades past springing back.
- **Sensor**: a magnet on the moving side, a Hall sensor on the ground side 1-2mm away (TMAG5273, I2C). Or the QRE1113 facing a white patch ~1mm away (analog, its best range: the right use for it). Or strain gauges on steel blades and an HX711.
- **Calibrate**: known weights (coins) on the tool's tip give k; force = k x displacement.
- **Ringing**: it adds give. With k = 5 N/mm and a 100g toolhead, `f = sqrt(k/m) / 2pi` ~ 35 Hz, vertical only (Z moves are slow). A little foam or rubber in the stop damps it.
- **What it gives**: each pen's touch by probing with the pen (no ladder), the press by force instead of by height (and it gives a little, like a spring-loaded holder: it rides out the uneven height and the play), and crashes at the dock. In Klipper: a threshold is a probe endstop, and a small module reads the force.
- Or inside each tool: a pen on a spring, a magnet and a Hall sensor, through the new pogo pins. It's per tool; the flexure covers all of them at once.

### Power and data through the coupling

5V, GND, 5 data pins (pogo), the metal coupling as a power path. Power off until needed, turned on like the bed's: two pogo pins bridged by the tool.
- [ ] Order: the pogo pins touch before the coupling (ground). Turn the power on only when the bridge is seen *and* the key is locked, not on the bridge alone.
- [ ] Data pins as inputs, pull-ups off, until the tool has power and ground: a pin driven high into an unpowered tool powers it backwards through its chip's input protection.
- [ ] The Pololu MOSFET switch: reverse voltage protection, but check for a current limit. If none, a PTC fuse on the 5V for a pogo pin sliding onto the wrong pad; a soft start for a camera's inrush.
- [ ] A ground pogo next to the data pins, for their return path.
- [ ] TVS and small series resistors on the data pins: every hot plug is an ESD event.
- [ ] Tool type on one pin instead of the foil: a resistor to GND per tool type, read on an ADC (presence and type). Or a 1-Wire EEPROM (DS2431) that could carry the tool's offsets too, a tag without the reader.
- [ ] A camera tool, wired (the user keeps everything wired together):
  - USB through the pogo pins: full speed (12Mbps) is fine for stills and film scans. High speed (480Mbps, what most UVC cameras want) needs D+/D- on a matched pair of pins, the shortest paths and a ground pin next to them: worth a try, but fragile.
  - A Pi Zero on the tool with its CSI camera (the HQ camera), reached as a USB network device (gadget mode) through the pogo pins at full speed. Stitching and focus stacking stay on the tool.
  - Wi-Fi (an ESP32-S3 camera, 5V and GND only) as the fallback.
- [ ] A BLTouch tool: two data pins (servo, endstop) to a Klipper MCU pin; keep the endstop line clean, its timing matters.
- Pins: ID 1, BLTouch 2, 2 spare (I2C for tool sensors).

### Power budget of the 5V through the coupling (2026-09-30)

Typical, at 5V (check the real modules):

| Load | Typical | Peak |
|---|---|---|
| USB camera | 0.1-0.2 A | 0.3 A (autofocus, IR LEDs) |
| Bright LED | 0.1-0.2 A (0.5-1 W) | the same |
| BLTouch | 15 mA | ~0.3 A while its pin moves |
| MCUs | RP2040 ~30 mA, ESP32 ~0.25 A | ESP32 Wi-Fi bursts ~0.5 A |
| "1 W" laser module | 1-1.5 A if 1 W *optical*; ~0.2 A if 1 W drawn | the same |
| Pi Zero 2 W + HQ camera (stress case) | 0.6-0.9 A | 1.0-1.3 A booting, loaded |

Worst case ~1.3 A going on and on.
- [ ] **PTC**: hold 1.5-1.6 A (it holds less warm, a toolhead is warm), trip ~3 A, 6V or more, 0.1 ohm or less, 1812. It trips in seconds: it saves the wiring from a lasting short, not the electronics from a sliding pin.
- [ ] **Or an e-fuse** (TPS2595 family): limit set to ~2 A, trips in microseconds, soft start for a camera's or a Pi's inrush. It does the PTC's job and more, in one chip.
- [ ] **Voltage**: the Pi Zero warns under ~4.63V. PTC + pogo pins + wire can take ~0.3V at 1.3 A: feed the toolhead 5.1-5.2V, and two pogo pins in parallel for 5V if one is rated under ~2 A.
- The 5 W laser and the milling spindle: always tethered, their own supply and their own interlock, never through the coupling.

### Uses beyond pens (2026-09-30 brainstorm)

Where it shines: plot a design, then cut it on the same sheet, in register. The crosses of `limn_cam ladder` are already a print-and-cut registration: find them with a camera, fit the homography, cut along the design.

- **Cutting** (the bed is cutting mat): the rotating micro knife for stickers, stencils, papercraft, card, sewing patterns, masks for airbrush; a drag knife; a scoring/creasing stylus for folds.
- **Embossing and scoring**: a ball stylus for paper embossing, foil (cold foil, "foil quill"), leather tooling; Braille.
- **Engraving**: a diamond drag engraver (metal tags, acrylic, scratch art).
- **Film and flat scanning** (the camera tool, powered through the coupling, untethered): negatives on the backlit bed, stitched from frames at known XY, focus-stacked by Z; artwork and documents too, lit from above.
- **PCBs**: plot etch resist onto copper clad with a paint marker, etch; or a UV LED tool exposing dry-film resist or cyanotype paper directly (UV glasses).
- **Painting**: brush and watercolour (the `brush` kind already reloads), calligraphy with fountain and brush pens.
- **Dispensing**: a syringe for glue or solder paste; pipetting into well plates.
- **Pick and place**: a small vacuum nozzle for SMD parts, stickers, rhinestones, seeds on paper.
- **Testing**: a capacitive stylus tapping a phone or tablet (a touchscreen test robot); pressing keys and switches (with the load cell, force curves).
- **Measuring**: probing an object's height map with the BLTouch tool or the pen (2.5D scan); the camera measuring parts against the grid.
- **Laser** (later, see safety): engrave wood, leather, card; cut paper and thin card along a plotted design.

### Laser safety (before the first switch-on)

- [ ] **Glasses for the laser's wavelength.** Most diode laser modules are blue, 445-455nm. Glasses sold as "IR" protect at 808/1064nm and do nothing at 450nm. OD4 or more at the module's wavelength (on the label or the datasheet).
- [ ] **Never on or through the cutting mat**: most mats are PVC, and burning PVC (and vinyl sticker sheet) gives off chlorine gas. A metal honeycomb or a sacrificial board under anything lasered.
- [ ] An enclosure or shield, a lid or hand switch that cuts the laser's power in hardware (not only in G-code), smoke extraction, and someone watching for fire.
- [ ] `plot/`'s laser kind never touches (no press, no play); it needs its own safe travel height and an off (`M5`) on every error path, and Klipper's own laser PWM off at startup and shutdown.

