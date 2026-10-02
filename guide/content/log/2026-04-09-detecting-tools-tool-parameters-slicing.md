+++
title = "Detecting Tools, Tool Parameters, Slicing"
date = 2026-04-09T12:22:00
author = "Prashant Sinha"
hackaday = 4
source = "https://hackaday.io/project/205431/log/247167-detecting-tools-tool-parameters-slicing"
+++

The tool docking mechanism relies on [Maxwell Coupling](https://en.wikipedia.org/wiki/Kinematic_coupling) for repeatability, however this repeatability only holds per tool. As such, different pens will land at varying positions on the paper for the same coordinate.

My current understanding is that it will be too much effort to precisely align each tool, and rather it'd be easier to calibrate each tool against a reference tool (ideally the sharpest pen). Hence we need a way to configure the tool parameters (`{offset_x, offset_y, offset_z, depth...}`). 

For the sake of simplicity it'd be good that the printer handles this at runtime. Any print file could be printed by any tool/tools. 

I really did not want to reinvent any more wheels, so I stuck to PrusaSlicer. A new printer config, with custom gcode templates, multi-extruder toolhead, and some regex susbtitution later I can now drag an SVG file in the slicer, and generate the exact GCODE that klipper is expecting.

![](/log/img/6376361775737836768.webp)

Pen Up and Down motion is achieved by replacing `retraction` events. I chose to keep raw Z values here, and change Z-offset on klipper instead, so that the travel moves reflect actual pen moves in the preview. Similarly extrusions are kept only to have something in the preview, but are ignored by G1 macro.

The slicer emits T0..T4 commands for each tool change. On klipper side custom macros translate these commands to actual movement.

![](/log/img/1822171775739251506.webp)

I still haven't figured out varying nozzle sizes while slicing but it should be possible. 

---

Back to detecting tools: A basic detection can be done by physical contact with the coupling surface -- on the tool's side we can bridge two screws with a wire. I'm aware of 1Wire EEPROM being a thing but did not find any to buy. There seems to be several Spool detecting projects, such as OpenSpools, which can use RFID readers to detect the spools. We could use something like that.

To set the parameters there's now a spring-loaded-retractable RFID sensor mounted near the first tool. It can be slid back by the Y axis. 

![](/log/img/3043041775740555214.webp)

![](/log/img/6292771775740694779.webp)

(I did not realize that I wired the PN532 with I2C, but OpenSpools needs SPI connection. I'm too lazy to take it out so I'll likely have to figure out an alternative on this.)

On the tools we stick a tag and the docking macro will eventually use the sensor for tool parameters.
