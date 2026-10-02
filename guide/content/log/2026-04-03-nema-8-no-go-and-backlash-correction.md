+++
title = "NEMA 8 - No Go and Backlash Correction"
date = 2026-04-03T15:46:00
author = "Prashant Sinha"
hackaday = 3
source = "https://hackaday.io/project/205431-limn-pen-plotter-with-toolchanger/logs"
+++

I received the AliExpress NEMA 8 motors yesterday and replaced the SRM1509 for a test. After tightening the belts I can turn the axis manually but the stepper just buzzes. I tried upping the stepper current till 0.8A but I could stop the shaft with my fingers. Oh well. I went back to the previous motor.

![](/log/img/2007031775230561038.webp)

I wanted to make a note about the pulleys. Normally even if you make the shaft hole good size the pulley would not engage and the little flex it has will allow it to turn. I figured a good way to prevent this is by embedded nuts. Essentially a nut on the flat surface of the shaft, and a screw. 

![](/log/img/3913881775231014515.webp)

Since for now we have to live with the gear play I attempted correcting the backlash in software. Klipper allows you to override any macros, including G1, and with a macro variable one can keep track of the direction the motor was going in previously. If we are about to go in opposite direction then extra motor movement can correct for backlash IF it is stable (it is in my case). Only problem is that BED_CALIBRATE does not seem to be using a G1 command so the bed mesh is not corrected.

For plotting without a bed mesh the backlash is not really a big deal. With bed mesh we need to just be careful to not overshoot the end positions on the axis. I haven't found a clean way to do this yet, but I'm looking at /extras dir in klipper right now.

```ini
[gcode_macro G1]
rename_existing: G1.1 # Rename the existing G1 command to G1.1
gcode:
  {% set is_abs = printer.gcode_move.absolute_coordinates %}
  {% set curr_z = printer.toolhead.position.z %}
  {% set param_z = params.Z|default(-42)|float %}
  {% set new_z = 0 %}
  {% if 'Z' in params %}
    {% set next_z = param_z if is_abs else (curr_z + param_z) %}
    {% set delta = next_z - curr_z %}
    {% set direction = (delta / delta|abs) if delta != 0 else last_dir %}
    {% set backlash = 1.8 if direction != last_dir else 0  %}
    {% set correction = backlash * direction %}
    SET_GCODE_VARIABLE MACRO=G1 VARIABLE=last_dir VALUE={direction}
    {% if correction %}
      {% set step_to = correction if not is_abs else (curr_z + correction) %}
      # SET_KINEMATIC_POSITION Z={curr_z - correction} SET_HOMED=''
      G92 Z{curr_z - correction}
      G1.1 Z{step_to}
      # SET_KINEMATIC_POSITION Z={curr_z} SET_HOMED=''
      G92 Z{curr_z}
      M118 Corrected: Backlash: {backlash} Direction: {direction}
    {% endif %}
  {% endif %}
  {% set p_x = ' X' ~ params.X if 'X' in params else '' %}
  {% set p_y = ' Y' ~ params.Y if 'Y' in params else '' %}
  {% set p_z = ' Z' ~ params.Z if 'Z' in params else '' %}
  {% set p_f = ' F' ~ params.F if 'F' in params else '' %}
  {% set ps = p_x + p_y + p_z + p_f %}
  G1.1 {ps}
variable_last_dir: 1
```

PS: The 3-point coupling seems to be good enough to pass some electricity, finally! 

![](/log/img/8178091775231272087.webp)
