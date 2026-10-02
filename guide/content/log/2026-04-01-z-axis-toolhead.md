+++
title = "Z Axis & Toolhead"
date = 2026-04-01T18:50:00
author = "Prashant Sinha"
hackaday = 2
source = "https://hackaday.io/project/205431-limn-pen-plotter-with-toolchanger/logs"
+++

For a plotter we do not really need large Z axis movement. Initial iterations used a MG14 servo motor for Pen Up/Pen Down motion. It worked but was loud, imprecise, and limited to flat bed.

I found that SRM1509 stepper motors were just strong enough while being small and are what in use currently. These use a gearbox so some trial and error yielded a close but incorrect Z scaling. Additionally there is significant play due to gears and I had to account for the backlash.

The motor module is designed separately so can be changed for a different system later. I plan to switch to NEMA8/NEMA11 motors soon. Currently the belt tension is achieved through three bolts that lift the entire motor and GT2 pulley assembly. 

For the motion system 3mm/5cm dowels and bushings are used. Belt rides on 603ZZ bearings. When tensioned, the motor module and Y axis "rider" are rigid. Weighs about 250g!

Attached some pictures.

![](/log/img/6960671775069779722.webp)

![](/log/img/1987631775069780478.webp)

![](/log/img/2397241775069780895.webp)

![](/log/img/7243731775069781671.webp)
