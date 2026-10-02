+++
title = "How it was made"
nav = "Story"
order = 1
summary = "Limn 2.0: a name from a robotics lab at Delhi University in 2015, a 3D printer saved from the bin, and the same DIY motto. From a servo lifting a pen in January 2026 to pens that calibrate themselves."
+++

The day-by-day account is in the [log](/log/index.html): the Hackaday posts, mirrored, and the write-ups from the notebooks. This page is the overview.

## Limn 1.0 (2015)

The name is older than this machine. It comes from a robotics lab at Delhi University, around 2015, during Prashant's undergrad, where the work was building RAMPS and RepRap 3D printers, and a plotter came out of it: *Limn*, to draw, to depict. It has a [video](https://www.youtube.com/watch?v=aWG2Bk5RMY4) from 2015-05-13, a calibration run (below).

Today's plotter is built on the same DIY motto, so it carries the name forward as **Limn 2.0**. The name is on the dock's plate.

## The donor printer

Limn 2.0 started on 2025-10-22, as a pen plotter built from a 3D printer. Three ways to get there were considered:

- **"Study"**: a tiny plotter made from spare drive parts.
- **"Notebook"**: convert the Ender 3, turning it into a two-axis machine with a third, configurable frame on its Y–Z axes. The trouble: making the Ender print again afterwards would be a pain.
- **"Tronxy"**: run Klipper on the board of an old Tronxy, and build a CoreXY frame around its parts. *Easy, DRY, free of NIH.* **This one won.**

The Tronxy was a DIY printer kit, a Prusa i3 clone (P802M), about six years old. It was given away by someone who knew it would interest Prashant, and it would have been thrown out otherwise. Its key components were kept, and they became Limn: the steel rods, the linear bearings, the XY stepper motors and the controller, a Melzi board with four stepper drivers. Two of the drivers go to the CoreXY motors, one to Z, and one to "K", the key axis that locks a tool to the head.

![CoreXY: two motors, one belt each, and the carriage moves by their sum and difference](/img/notes/corexy.webp)

The frame is meant to scale. Four corner pieces mate with rods, belts and a base of any length. A hard MDF board and the four steel rods make it square and rigid enough, and the tensioned belts pull it inward, which takes out the wobble. The tool dock had to stay put even when the toolhead crashes into it, so its brackets clamp a steel rod and rest on the base.

- [?] A photo of the Tronxy before, and of the parts laid out.

## First steps (January to March 2026)

![The first frame: a servo lifting the pen, January 2026](/img/notes/2026-01-servo-plotter.webp)

- **2026-01-18** Klipper running on the Melzi. **01-22** `printer.cfg`, two endstop switches, the first toolhead and rider. The pen went up and down on a 9 g servo with a clutch. Klipper didn't get along with that servo (it kept spinning), so it became an MG90: *a bit wobbly and slow, but works well.*

![The first plot](/img/notes/2026-01-first-plot.webp)

- Next came a Z axis for the pen instead of a servo, which is simpler in code and in mechanics. The first sketches had a probe, pen up and down, and levelling as its three jobs. The toolchanger's first idea used magnets and dowels.

<figure class="diagram"><a href="/img/drawings/sketch-pen-dock.webp"><img src="/img/drawings/sketch-pen-dock.webp" alt="Sketch: a pen held by magnets on dowels, and a dock"></a><figcaption>2026-01-24: the pen held by a magnet on dowels, and a dock to leave it in.</figcaption></figure>

<figure class="diagram"><a href="/img/drawings/sketch-z-axis.webp"><img src="/img/drawings/sketch-z-axis.webp" alt="Sketch: the Z axis's three jobs, and the electronics"></a><figcaption>2026-01-26: the Z axis's jobs (probe, pen up and down, levelling), a belt-driven slide, and the power: USB-C, a 12 V trigger, a buck converter.</figcaption></figure>

<figure class="diagram"><a href="/img/drawings/sketch-coupling.webp"><img src="/img/drawings/sketch-coupling.webp" alt="Sketch: coupling and clamp ideas"></a><figcaption>2026-01-29: clamps and couplings for the pen.</figcaption></figure>

![The toolhead in CAD, 2026-02-01: the Z slide, the BLTouch, the servo lift](/img/notes/2026-02-cad-toolhead.webp)

- **February**: the Z axis on an SRM1509, a tiny geared stepper. Then the BLTouch, and the toolchanger: a Maxwell (kinematic) coupling and a geared linear latch, done on 02-25. The dock holds 6 tools at 35 mm spacing.
- **March**: belt tensioners on X, Y and Z, a stronger base, and the Melzi modified so Z and K run on 5 V. On **03-12**: *Hardware is complete functionally, solid, not wobbly. All axes correctly move.* The first two tools were a Posca marker and a cutter.

![The machine in CAD, 2026-03-03](/img/notes/2026-03-cad.webp)


- **03-30**: *Magnets completed the puzzle.* With magnets on the coupling screws, the tools pull themselves into line, and the lock can close. The first full test plots with tool changes followed.

## Fixing Z (April)

The geared SRM1509 had play, and a [G1 override](/log/2026-04-03-nema-8-no-go-and-backlash-correction.html) corrected for it in software. A NEMA 8 on the belt was too weak (*I could stop the shaft with my fingers*). Then the Z axis was found to run smoother, and looser, on warm days. Either the gear was loose or the motor was failing. Z became a lead screw instead: an M3 bolt, locked into a bracket, turned by the NEMA 8. A screw on one side tilts the rider, so the rider follows an optical drive's layout and is kept level by a triangle of bearings.

On 04-11 the project went up on [Hackaday.io](https://hackaday.io/project/205431-limn-pen-plotter-with-toolchanger), and the Klipper config on GitHub. On 04-21 the Fusion 360 design and the STEP file followed: *about four months of effort*. Cameron Coward wrote it up for Hackster.io: [Someone Finally Put an Automatic Toolchanger on a Pen Plotter](https://www.hackster.io/news/someone-finally-put-an-automatic-toolchanger-on-a-pen-plotter-feaafe662e9e).

## Pens that know themselves (April to June)

Each tool lands a little differently, so each pen carries an NFC tag with its offsets. They were set by hand at first, then measured on a [resistive touch panel](/log/2026-05-12-automatic-tool-alignment-in-xyz.html). By **06-11**: *Fully automated pen alignment and plotting is now complete*, to about 0.2 mm. Along the way came LED feedback, beeps (05-15) and ArUco markers for the cameras.

![A tethered tool: a UVC camera on a tool, still docking](/img/notes/tethered-tool-camera.webp)

## The dock, the belts, the cameras (August to October)

- **08-13**: the tags kept getting rubbed off in the dock. The holders were redrawn around them, with a switch in each one.
- **08-15**: a camera on the key. Locked, it looks down at the paper; unlocked, it looks straight ahead, at the dock. A [VL53L5X](/parts/vl53l5x-tof.html) ToF sensor was tried for finding the holders, and dropped.
- **08-19**: the screen came off and the Pi moved, which freed the middle dock bracket for a belt tensioner.

<figure class="diagram"><a href="/img/drawings/belts-dock-tensioner.webp"><img src="/img/drawings/belts-dock-tensioner.webp" alt="Belt paths through the dock brackets, and tensioner references"></a><figcaption>2026-08-19: where the belts run past the dock, with references for idler tensioners.</figcaption></figure>

- **09-05**: the dock trouble turned out to be [loose belts](/log/2026-09-05-loose-belts.html). The fix was a tensioning "backpack" on the carriage, with tracks for the belt clips.
- **Late September**: force-sensing beds, Limn's own SVG-to-G-code generator in place of PrusaSlicer, and cameras that read where each pen touches. Then [the CAD over time](#the-cad-over-time) picks up.
- **09-24**: work began on a new toolhead.

## Designing it

Everything is drawn in Fusion 360, one design per part. The export the guide reads is `Limn-Export-42`. The toolhead is grouped on its own in the design, so it could go onto another CoreXY frame.

Bought parts are in the CAD too, mostly as the vendors' own models. The M3 screws (`AA041`, `AA171`), the bushings (`ED001`) and the dowels (`DA025`) carry their reference numbers. These are Bambu Lab's Maker's Supply codes, and the parts come from the [Bambu Lab EU store](https://eu.store.bambulab.com/collections/makers-supply). The [bill of materials](/bom.html) links each one. Most of the rest came from AliExpress.

<figure class="diagram"><a href="/img/drawings/belts-corexy.webp"><img src="/img/drawings/belts-corexy.webp" alt="The CoreXY belts in CAD"></a><figcaption>The belts, March 2026: the two loops, and an idler tensioner at a corner.</figcaption></figure>

Some ideas that shaped it:

- [PlotDevice](https://github.com/adammhaile/PlotDevice), a published plotter design.
- A magnetic pen changer [on Reddit](https://www.reddit.com/r/3Dprinting/s/kzsqGdSUoA).
- Toolchangers for printers: E3D's triangular coupling, the [RatRig V-Core 3 changer](https://www.printables.com/model/137147-ratrig-vcore-3-tool-changer), [MadMax](https://github.com/zruncho3d/madmax), and the [kinematic coupling](https://en.wikipedia.org/wiki/Kinematic_coupling) behind them.
- The models people share on GrabCAD and Printables.

The printable area was about 147 × 183 mm by March, close to A5 (148 × 210).

## The CAD over time

Four exports of the Fusion design, April to October 2026, compared part by part (`guide/compare.py`).

![v11, v46 and v88](/compare/limn.png)

### April → August (v11 → v46)

- **The camera moved.** The Pi Camera 3 swivel arm is gone. A USB webcam took its place, in a part that is also the
  Y endstop.
- **An LED UI:** a Unicorn pHAT in a case, with a diffuser and an icon mat.
- **The calibration bed** arrived under the bed: a resistive base, a 2.8" display, magnetic pogo pins.
- The paper sliders became bumpers. The ducts got covers, and the drag chain went from 4 links to 13.

![Bed](/compare/bed.png)

### August → October (v46 → v88)

- **The toolchanger lock was redone:** a K-gear, a K-pin and a dowel, with a QRE1113 sensor to see the lock, and 4
  pogo pins for data to the tool.

![Toolchanger head](/compare/toolchanger-head.png)

- **The Z rider got eyes:** a VL53L5X ToF sensor and a holder for the endoscope.

![Z axis rider](/compare/z-axis-rider.png)

- **The dock senses its tools:** a micro switch in each holder, read by an MCP23017.

![Tool dock](/compare/tool-dock.png)

- **The calibration bed, second take:** a 32-zone FSR, two RP2040-Tiny, a resistive touch panel.
- **Gone:** the hinged KlipperScreen, the bed LED plates, the Z top cover.

### Parts that changed shape

![plot-toolch-base](/compare/plot-toolch-base.png)
![Plot-Tool-Dock-Item](/compare/plot-tool-dock-item.png)
![Limn-Camera-Y-Endstop](/compare/limn-camera-y-endstop.png)
![Limn-Calibration-Base](/compare/limn-calibration-base.png)

## Printing

- Almost all parts print without supports.
- The tensioner body prints at an angle, which makes its small screw holes stronger.
- A lesson from 04-21: use threaded inserts for the critical parts.
- The toolhead and toolchanger are on [Printables](https://www.printables.com/model/1786450-limn-pen-plotter-with-automatic-tool-changer-parti).
- [?] Printer, materials, the settings used for most parts. Parts with their own settings say so on their page.

## Limn 3.0?

An Ender 3 waits in parts. It's the printer that made the first models for [disinfo](https://github.com/prashnts/disinfo). Its aluminium extrusions and its Sprite extruder might make it Limn 3.0 one day.
