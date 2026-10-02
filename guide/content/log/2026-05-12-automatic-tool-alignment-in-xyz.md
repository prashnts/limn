+++
title = "Automatic Tool Alignment in XYZ"
date = 2026-05-12T08:56:00
author = "Prashant Sinha"
hackaday = 10
source = "https://hackaday.io/project/205431-limn-pen-plotter-with-toolchanger/logs"
videos = ["SVqULv0Ljyk"]
+++

Last weekend I spent ~30 minutes calibrating three pens manually. Annoyed, I decided to automate this process as well. For complete pen alignment we need to offset the XYZ coordinates -- the offsets are stored in a RFID tag [(more details)](https://hackaday.io/project/205431-limn-pen-plotter-with-toolchanger/log/247548-applying-tool-parameters-tethered-tools). 

A Resistive Touch Panel was used to build a new plotter bed. By probing a tool over the panel at several location we can know the three spatial coordinates.

![](/log/img/5285051778578815574.webp)

![](/log/img/2463351778578964521.webp)

I used a Cheap Yellow Display (CYD) 2.8" which contains an XPT2046 resistive touch controller and panel. I removed the display entirely and soldered pigtails to four touch panel pins. Then I used another larger resistive panel that I reclaimed from an old car GPS. Magnetic Pogo Pins allow connecting the panel when needed.

The new bed is 2.5mm thick and magnetic alignement is highly repeatable. I posted a demo video of it in action.

**Hardware**

To connect the touch panel to klipper, I'm currently keeping the CYD in use.

- The CYD outputs a 3.3V 10ms pulse whenever a touch event is detected.
- An OR gate built with two NPN transistors combines the BLTouch Probe
    Signal and the touch signal, output of which is used as PROBE_ENDSTOP on klipper.
- Now, when running Bed Mesh or Probe calibration, the toolhead stops when
    EITHER resistive touch event or BLTouch trigger is detected.
- This essentially means that basic Z offset calculation work using BLTouch with no changes to klipper.
- CYD is connected to Klipper Pi over USB.
- There's a screen protector layer over the panel and the software will implement wear leveling to use the entire panel evenly.

**Software**

The CYD runs a very basic ESPHome firmware. It logs out the XY and Pressure values via serial port and can be read by a Python script. Klipper macros can use CLI command to run the script when probing to read the coordinates.

A PROBE_TOOLS macro will automate the whole process:

1. Partial BLTouch bed mesh over the touch panel.
2. Docks `reference tool` (T0) and probe at 4 locations. Stores the coordinates and scaling factor.
3. Following steps are repeated from tool T1 to T4:
    1. Dock Tool
    2. Slow Probe to find tool Z offset
    3. Fast Probe at 4 locations
    4. Calculate XYZ offset from reference pen
    5. Write the offset to pen's RFID tag
    6. Undock Tool
4. Partial bed mesh on paper area (A6 size).
5. Repeat from T0 to T4:
    1. Dock Tool (also reads the tag)
    2. Draw alignment pattern
    3. Undock
6. User/Camera confirmation

Roughly 10 units of displacement on the touchscreen corresponds to 1-2mm toolhead movement, in my observation. I'll work on alignment script next, given that I seem to have all the required parameters about tools available.

[Github repo](https://github.com/prashnts/limn) will be updated soon containing the config changes. 

PS: The screen that comes with the CYD is also sufficient, I just had some extra available. It was slightly thicker as well since I couldn't easily remove the display layer.

![](/log/img/1455621778580517460.webp)
