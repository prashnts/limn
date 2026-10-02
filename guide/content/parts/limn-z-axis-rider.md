+++
summary = "Lifts the toolchanger: a NEMA 8 turning an M3 lead screw, a rider on two 3 mm dowels, the BLTouch, the endstop, and the sensors that look down."
+++

## How Z got here

- The first pen lift was a 9 g servo, then an MG90: loud, imprecise, and only for a flat bed.
- Then an **SRM1509**, a tiny geared stepper, on a belt. It was just strong enough, but its gears had play: 1.8 mm of backlash, corrected in a G1 macro ([log #3](/log/2026-04-03-nema-8-no-go-and-backlash-correction.html)).
- A **NEMA 8** on the same belt was too weak. It buzzed, and fingers could stop it, even at 0.8 A.
- On warm days the geared Z ran smoother and looser. That decided it: a **lead screw**, driven by the NEMA 8 ([log #8](/log/2026-04-21-new-z-axis-plotter-bed-step-files.html)).

## Step: The lead screw

- The "lead screw" is an M3 threaded rod ([[carbon-steel-full-threaded-rod-m3x30-aa227]]). It's locked with thread-locker into the [[limn-m3-bolt-leadscrew-adapter]], and the [[limn-z-axis-coupler]] joins it to the [[nema-8-ali]] with four 2 × 12 screws.
- Its top end sits in an [[m3-bearing-mr63zz-ea006]], pressed in.
- An M3 heat-set insert in the rider is the nut.
- [i] `rotation_distance: 0.03125` at `microsteps: 1`. The Melzi's driver is wired for 16 microsteps that the AVR can't step fast enough, so 0.5 mm pitch over 16.

## Step: The rider

- Two [[3x50-mm-stainless-steel-dowel-pin-da025]] dowels are the rails, screwed in with 2.5 × 6–8 screws. The rider runs on two [[3x5x4-ed002-bushing]] bushings, each held by two 2 × 6 screws.
- With the screw on one side, the rider tilted and jammed. It now follows the layout of an optical drive's sled, which a triangle of contacts keeps level.
- A micro switch at the top is the Z endstop.
- The [[bltouch]] screws on with two 3 × 6 screws. Its wires run through the channels at the back.
- The toolhead base screws onto the rider with four 2 × 8 screws.

## Step: Eyes and ears

- The MPU9250 on the [[limn-z-axis-42-imu-base]] is for input shaping. It's read over I2C, because Klipper's ADXL345 support wants SPI.
- The [[vl53l5x-tof]] and the endoscope's [[scope-holder]] came in v88: see their pages.
