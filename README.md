# Limn

Limn is a pen plotter with a toolchanger. This repository contains the various klipper configuration files and some extra modules.

- `rfid.py`: Script to read and update tool's NFC tag data.
- `klipper/`: Klipper configuration for the toolchanger and printer.
- `ext/limn/`: Klipper extension for the Dock and the calibration beds (`LRT_*` commands). Install with `ln -sfn ~/limn/ext/limn ~/klipper/klippy/extras/limn`, tests: `uv run python ext/tests/test_*.py`.
- `micropython/`: Firmware for the Dock and the bed MCUs, and `mcu.py` to install and update them.
- `slicer/config.ini`: Sample PrusaSlicer config to make it suitable for plotting.
- `step/`: (todo) 3D Printable Parts


There is some more info posted [here](https://hackaday.io/project/205431-limn-pen-plotter-with-toolchanger) about this project.
