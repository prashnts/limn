+++
title = "Loose Belts"
date = 2026-09-05T17:12:00
author = "Prashant Sinha"
hackaday = 15
source = "https://hackaday.io/project/205431-limn-pen-plotter-with-toolchanger/logs"
+++

It turns out that my troubles with Dock parameters were caused by loose belts. In a previous iteration I'd designed an inline moving tensioner but the geometry was not optimal and caused too much belt wear. I've added a photo below.

In another iteration I'd designed a tensioning "backpack" that tensions one end of the belt at the toolhead. The other ends are held by the backpack. I decided to refine this idea further, specifically, I added tracks for the belt clips so they remain in place and increased the clearance.

![](/log/img/6577141788632801496.webp)

The main body prints at an angle giving some strength to the small screw holes. It's quite small so pretensioning is necessary -- the track chamfers in order to make it easier to insert clips under tension and engage them with the screws.

I'll upload a new version of the project soon. The plotter now has no issue docking/undocking, once again.

In the end I won't explore tof (time of flight) sensors for this project, but I did make a little webserver that serves tof output as mjpeg output so I can see it along with other cameras.

--

I'm currently testing the Paris Metro map elements for printability (plotability?). With a Micron 003 pen (and somewhat 0.05mm pen) I am able to plot 1.5mm tall characters. Yeah, the plotter is small and that poses a challenge in getting the map to fit and still be readable -- 2mm text was what I can go for, with some margin for smaller fonts elsewhere. 

![](/log/img/5245561788632925539.webp)
