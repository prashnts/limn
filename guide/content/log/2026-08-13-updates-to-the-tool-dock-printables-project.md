+++
title = "Updates to the Tool Dock & Printables Project"
date = 2026-08-13T14:41:00
author = "Prashant Sinha"
hackaday = 13
source = "https://hackaday.io/project/205431-limn-pen-plotter-with-toolchanger/logs"
+++

I've been having issues with the RFID tags on the tools: They are frequently getting damaged.

I noted that my previous dock design did not account for any tag. With extended usage, the tool holder seem to essentially rub against the tag and eventually destroys it.

Therefore I modified the tool dock to account for where the tag (particularly the chip on the tag) is and while at it I also added limit-switches to each tool holders.

The end result is that now limn:

- can reliably tell whether a tool is present on a holder
- whether the tool was successfully picked up
- hopefully not destroy the RFID tags

![](/log/img/1569711786631769531.webp)

The switches connect to a MCP23017 breakout board and will be handled by the klipper extension. The microswitches are from AliExpress.

I still am not convinced the RFID tags will be protected with the design change. I'd have tried to change the tools themselves to embed the tag inside, but at this point I've already printed ~20 tools and so am not very motivated to redo them (yet).

PS: I did not touch the plotter for about a month, and was happy to discover that it still worked. I still haven't finished my own designs that I'd like to plot, but I did create a printables project finally. It's available here:

[https://www.printables.com/model/1786450-limn-pen-plotter-with-automatic-tool-changer-parti](https://www.printables.com/model/1786450-limn-pen-plotter-with-automatic-tool-changer-parti)

I am focusing not on corexy side of the designs but the toolhead and toolchangers in the post for now.
