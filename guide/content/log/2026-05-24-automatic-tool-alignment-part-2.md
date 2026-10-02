+++
title = "Automatic Tool Alignment - Part 2"
date = 2026-05-24T15:31:00
author = "Prashant Sinha"
hackaday = 11
source = "https://hackaday.io/project/205431-limn-pen-plotter-with-toolchanger/logs"
videos = ["4_-xa_EsdP0"]
+++

Using the Resistive Touch Panel I collected an extensive set of samples in order to figure out how to get tool offset. I simulated deviations in XY using this probe (pictured) -- the desired offset from center could be achieved by unscrewing a particular screw a bit.

There were 9 coordinates in total, and three samples were taken for each points in a grid. Raw values from the Resistive touch panels require filtering and transformation in order to obtain coordinates in plotter's space. Therefore a calibration step takes measurements at three locations (ref. [AVR341 app. note](https://cdn-shop.adafruit.com/datasheets/AVR341.pdf)) to get transformation parameters.

Following show the data I collected, indicating that the resistive panels can get us close to alignment. The data and transformation steps [are noted here](https://github.com/prashnts/limn/blob/master/notebooks/act3-synthetic-calib.ipynb).

![](/log/img/4954121779833761594.webp)

I've since concluded that I'll use the panel for rough XY and precise Z calibration. For getting precise XY calibration, I decided to use an 8x4 2.5mm array of Force Sensitive Resistors ([FS-ARR-4x8](https://film-sensor.com/product/fs-arr-4x8-rot/)). Idea being that we can aim for a particular cell and know precisely where we land.

I modified the bed to have two RP2040 modules (with 4 ADCs) each controlling the Resistive Touch Screen and FSR. I had to make the bed a bit thicker, at ~3.2mm, and sand a FFC breakoutboard to get everything to fit. 

The pogo pins induce noise and having power always present on the pins didn't seem like a great idea, so a third RP2040 can provide the power upon detecting the bed. The detection is by measuring the resistance between two pins on the connector. I posted a demo video:

The three MCUs run micropython and I'm still working on the firmware. For this purpose we do not need to chase speed so upython seemed particularly nice.

Here's an early picture of the back side:

![](/log/img/7715611779834378907.webp)
