# Limn Resistive Touch

Firmware for the Dock and the bed MCUs (resistive panel, FSR array), and `mcu.py` to install and update them.

- `main.py`: bootloader, runs the app named in `node.json`, rolls back bad updates.
- `lib/`: shared by all MCUs. `link.py` (UART chain), `ota.py` (updates), `touch.py` (touch line).
- `lrt_*.py`: the apps.
- `nodes/`: `node.json` for each kind of MCU (role, app, UART and pins).
- `STRATEGY.md`: how it all fits together.


## First install, over USB

One board at a time:
```
uv run micropython/mcu.py ports
uv run micropython/mcu.py install dock --port /dev/cu.usbmodem1101
uv run micropython/mcu.py install rtp  --port ...
uv run micropython/mcu.py install fsr  --port ...     # fsr_bed3 for BED_3
```

`--port` can be left out when only one board is connected, or set once with `export LIMN_PORT=...`.


## Everything else, through the Dock

Stop Klipper first, it holds the Dock's port (`sudo systemctl stop klipper`).
```
uv run micropython/mcu.py topology          # who is where, are the files current
uv run micropython/mcu.py update            # send what changed, farthest node first
uv run micropython/mcu.py update --hop 2    # one node
uv run micropython/mcu.py info --hop 1      # full report of one node
uv run micropython/mcu.py stats             # link counters
uv run micropython/mcu.py send 'calibrate()'
uv run micropython/mcu.py monitor --kind SMP
uv run micropython/mcu.py send 'diag()'     # FSR sense pins: are the pull-downs on
```

From the Klipper console, without stopping it: `LRT_CHAIN`.

`main.py` and `lib/ota.py` are only replaced with `update --force`: a broken copy needs a USB install to fix.


## Tests

On a PC, no hardware:
```
python3 micropython/tests/test_link.py                  # link library
uv run python micropython/tests/test_chain.py           # Dock, RTP, FSR as processes
```
