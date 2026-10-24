# Limn Resistive Touch

Firmware for the Dock, the bed MCUs (resistive panel, FSR array), the plot bed (load cells) and LIT (the plot bed board: the head's cell + the bed dock), and `mcu.py` to install and update them.

- `main.py`: bootloader, runs the app named in `node.json`, rolls back bad updates.
- `lib/`: shared by all MCUs. `link.py` (UART chain), `ota.py` (updates), `touch.py` (touch line), `bridge.py` (USB host). `ads1220.py` only goes to the plot bed (`APP_LIBS` in `mcu.py`).
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
uv run micropython/mcu.py install plot_bed --port ... # load cells, on the Pi's USB: docs/load-cell.md
uv run micropython/mcu.py install lit --port ...      # LIT, the plot bed board: the head's cell + the bed dock
```

The beds' first node (`rtp`, `fsr`) is on LIT's one wire now (`"up": {"pin": 0}`, BED_PROBE on GP1: STRATEGY.md *LIT*). On the old Dock: `"up": {"id": 0}` instead, and no `probe_pin`.

`--port` can be left out when only one board is connected, or set once with `export LIMN_PORT=...`.

Without the Dock, watch a board's own output (debug prints, errors): `uv run micropython/mcu.py console`.


## Everything else, through the Dock

Stop Klipper first, it holds the Dock's port (`sudo systemctl stop klipper`).
```
uv run micropython/mcu.py topology          # who is where, are the files current
uv run micropython/mcu.py update            # send what changed, farthest node first
uv run micropython/mcu.py update --hop 2    # one node
uv run micropython/mcu.py info --hop 1      # full report of one node
uv run micropython/mcu.py stats             # link counters
uv run micropython/mcu.py send 'calibrate()'
uv run micropython/mcu.py monitor --kind data
uv run micropython/mcu.py send 'diag()'     # FSR sense pins: are the pull-downs on
```

From the Klipper console, without stopping it: `LRT_CHAIN`.

No Dock at hand (bed on the bench)? Plug in the first bed MCU instead: it becomes hop 0 and does the same for the MCUs below it.
```
uv run micropython/mcu.py topology --port <rtp port>                      # rtp at hop 0, fsr at hop 1
uv run micropython/mcu.py monitor  --port <rtp port>                      # includes the fsr's data
uv run micropython/mcu.py update --hop 1 --config fsr_bed3 --port <rtp port>
```

`main.py` and `lib/ota.py` are only replaced with `update --force`: a broken copy needs a USB install to fix.


## Load cell bench test

How good a cell is (noise, drift, zero shift after presses, hysteresis, creep, the cable), guided step by step against LIT on USB; the report and the samples go to `notebooks/cell-test/`:
```
uv run micropython/cell_test.py --weights 7.5,16,24.5 --label v1 --port <LIT port>
uv run micropython/cell_test.py --only presses --only wiggle    # no weights at hand
```


## Tests

On a PC, no hardware:
```
python3 micropython/tests/test_link.py                  # link library
uv run python micropython/tests/test_chain.py           # Dock, RTP, FSR, plot bed as processes
uv run python micropython/tests/test_chain.py plot_bed  # the plot bed only (fake ADS1220s)
uv run python micropython/tests/test_chain.py lit       # LIT only
```
