+++
title = "Automatic Tool Alignment - Part 3 - it works"
date = 2026-06-13T09:11:00
author = "Prashant Sinha"
hackaday = 12
source = "https://hackaday.io/project/205431-limn-pen-plotter-with-toolchanger/logs"
videos = ["6deuipWtRt8"]
+++

After a few trials, updated code, and slicer config, Limn is now able to calibrate its tools. I managed to have ~0.2mm precision with the Resistive Touch Panel to align the tools. In fact, I still haven't trialled the Force Sensor Array because the Resistive Panel seemed quite good already -- at least with 0.5mm pens.

The system now works as follows:

**Sensor Calibration**

- Calibrate the touch panel and bed using BL-Touch to obtain z-meshes.
- Pick tool T4, which acts as the "zero" reference pen, and probe the touch sensor at three locations (for touch calibration).
- Next, collect a set of samples (in plotter's coordinates) on the touch panel.
- Store the tool's RFID tag with the Z value.
- Draw a line on the paper and undock the tool.
- The panel mesh, paper mesh, and sample points are stored as calibration parameters.

**Tool Calibration**

- Pick a tool from the dock.
- Probe the tool at random coordinates (from the samples set).
- Subtract the tools' coordinates from the samples set.
- Write the XYZ offset to the RFID tag.
- Continue the previously drawn line on the paper for visual inspection.

An overview of this process is shown in this video:

I'm currently designing a few plots that I'd like to create before moving onto the next step: use the FSR sensor to improve the aligment accuracy. 

Additionally I figured a scheme to plot with more than 5 tools. First I added 5 more extruders in the slicer. On klipper when going from 5th to 6th tool, there will be a Pause and beep -- allowing me to manually swap all the tools.
