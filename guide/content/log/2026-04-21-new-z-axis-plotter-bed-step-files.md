+++
title = "New Z axis, Plotter Bed, STEP Files"
date = 2026-04-21T14:36:00
author = "Prashant Sinha"
hackaday = 8
source = "https://hackaday.io/project/205431-limn-pen-plotter-with-toolchanger/logs"
videos = ["CmZjZAT7KsA"]
+++

I spent some time reflecting and then decided to actually fix the backlash issue in the Z axis. My initial tests showed that the NEMA 8 motor would be good enough for a lead-screw driven axis. A 35mm M3 bolt was attached to a bracket with a nut and fixed with thread-locker. Then the "lead screw" is fixed to the motor using a coupler.

![](/log/img/2066081777064012091.webp)

The lead-screw, which drives the Z axis, is placed on one side. This posed a challenge because the "rider" would tilt up/down and jam. I looked around at slide mechanisms, and noticed that many optical drives a common layout -- the rider is kept level through triangular geometry. The following shows the current slider layout:

![](/log/img/2978991777065841835.webp)
This works surprisingly well, although is a bit slower than belted axis. I'd need to recalibrate the tool dock and also find the correct rotation-distance. 

**Update**: I'm reasonably close to correct value: 0.03 mm/rotation (the value is explained by the fact that I'm using no microstepping on a driver hard-wired for 16 microsteps. I can't use microstepping because the AVR MCU can't generate steps fast enough.) The probe accuracy is reasonably better:

![](/log/img/6082271777114552619.webp)

----

To keep the paper flat I designed a magnetic bed system adapted for A5 paper size. I believe it'd be good enough to cut/score paper as well.

![](/log/img/2919681777068536370.webp)

![](/log/img/8544331777068564163.webp)

----

Checkpoint 1: I've published all the current design files in the GitHub repository. The Fusion360 file barely fits under 100MB (zipped) and is fully articulated. Also uploaded the STEP file.

The printer config is no longer valid and I'll update them later. 

This took about four months of effort and I'm pleased with the results so far. I think the toolhead could be easily adapted to fit on other CoreXY frames as well, and hence I've grouped it (and others) together in the design files. Majority of the components were sourced from Bambu store and AliExpress.

I'll also post the files to Printables next month along with some instructions.

Link to Files: [https://github.com/prashnts/limn/tree/master/step](https://github.com/prashnts/limn/tree/master/step)
