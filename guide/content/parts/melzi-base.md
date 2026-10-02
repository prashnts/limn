+++
summary = "The Melzi controller from the donor Tronxy printer, on its printed base. Klipper's MCU for the motors."
+++

- A Sanguinololu-style board with four A4982 drivers, from a Tronxy P802M kit. References: the [RepRap wiki](https://reprap.org/wiki/Melzi), the [TronXY mainboard notes](https://tronxy.fandom.com/wiki/TronXY_Mainboard_Documentation).
- Changed for Limn: the Z and K drivers run on 5 V (the 12 V trace is cut), and the VREFs are set for small motors. Which port drives what, the EXT header and the VREF formula: [Electronics](/electronics.html).
