+++
title = "Calibrating the Dock Parameters Automatically with TOF sensor"
date = 2026-08-16T14:52:00
author = "Prashant Sinha"
hackaday = 14
source = "https://hackaday.io/project/205431-limn-pen-plotter-with-toolchanger/logs"
videos = ["W6ukHQGfqPw"]
+++

Calibrating the dock parameters is a very annoying and time consuming process. These parameters are what the plotter uses to dock a tool. I explored a few methods but in the end most were too complicated to integrate. The idea being that each tool have some defining featiures: the three screws for coupling, the keyhole, conduction based probing through the screws, a reflection sensor integrated in the key, etc. 

I'm currently exploring if a TOF sensor such as VL53L5X (which give 8x8 distance matrix as output, cost about 20 euros) can viably detect the center parameters of the docked tool.

![](/log/img/6495651786891724312.webp)

I borrowed some code (already borrowed from elsewhere) I had in micropython [on my disinfo project](https://github.com/prashnts/disinfo/tree/master/clients/websocket-rpi-matrix/src/websocket_rpi_matrix)and wired the sensor directly to the pi. On the same I2C bus the Dock occupancy switches exist.

Overall it seems viable, perhaps with some slight changes to the tool holder or the dock shape, retroreflective patches?

In another project I'm currently exploring, I got to play with some discarded, single-use medical endoscope cameras (there will be a post one day) and bolted it to the toolhead -- the controler for these OCHTA10 cameras are available online for a fair bit of money and appear as UVC video cameras. 

I've posted a video of the whole dock-sensor, tof sensor, and endoscope toolhead camera. Though I must admit that the camera is a gimmick for now.

https://www.youtube.com/watch?v=W6ukHQGfqPw

![](/log/img/7158181786892174359.webp)
