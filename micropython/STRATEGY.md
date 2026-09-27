# MCU Chain Strategy

How the Dock and the bed MCUs talk, how a touch reaches Klipper, and how firmware gets updated. Status of each part is at the end.

```
Klipper host ──USB── Dock ──UART── node 1 ──UART── node 2 ── ...
                      │                (on the detachable bed)
                      └── PIN_PROBE_OUT ── OR gate (with BLTouch) ── PROBE_ENDSTOP
```

- The bed connector has 5 pogo pins: power, GND, DETECT, TX, RX. Between bed MCUs we can add wires.
- Node order is not fixed (eg. `Dock -> RTP -> FSR`, or `Dock -> RTP -> RTP -> FSR`). Nothing is configured per position.


## Two paths

- **Trigger path** (time critical): a touch must become a ~10ms pulse on `PIN_PROBE_OUT` as fast as possible. It does not use UART.
- **Data path** (UART): touch coordinates, FSR frames, commands, logs, firmware updates. Not time critical, but should be efficient and never block.


## Trigger path

The Dock picks the trigger with `"trigger"` in its `node.json`:
- `"uart"` (default until the diodes are in): pulse on touch samples arriving over UART, not armed. Same as the old firmware, slower.
- `"detect"`: everything below.

A bed node only arms when its `node.json` has `"touch_pin": 2`, which means its diode is fitted. Without it, `arm()` is ignored and the node behaves as before (the RTP keeps measuring all the time). The configs in `nodes/` leave it out for now.

- The Dock has a 10k pull-up on DETECT; the bed has the ID resistor to GND.
- Each bed MCU gets a Schottky diode from a spare GPIO (GPIO 2 or 3) to the DETECT net. Silicon diodes drop too much for BED_6.
  - Idle / unpowered: diode is off, the bed ID reads as before (the Dock reads it before powering the bed).
  - Touch: GPIO high, DETECT goes to ~3.0V (~59k counts), above every bed ID (max 53k).
- Nodes raise the line only when armed, hold it 3ms, and lock out until the touch is released (`lib/touch.py`).
- RTP: while armed and idle it waits in pen detect mode (Y plate grounded, X+ pulled up, hard IRQ on X+ falling, like the XPT2046). The IRQ raises the line directly, then the RTP measures. Only lifting the pen re-arms it.
- FSR: raises the line from its scan loop (~25ms), no IRQ yet.
- Dock reads the ADC every loop; a rising edge above 56k (`touch_threshold`) while armed starts a 10ms pulse (PIO, so the loop keeps running), then ignores touches for 50ms.
- Bed removal = DETECT reads "no bed" for more than 250ms. A removal during a probe move triggers the probe, which is the safe outcome.
- Host sends `arm(rtp)` / `disarm()` around every probe (`ext/limn.py`, `probe_at`), so an FSR touch cannot fire a pen probe. `arm(all)` arms every node.
- Budget: node IRQ (<0.1ms) + Dock polling (<0.2ms, a few ms during GC) ≈ 1ms typ, 3ms worst.


## Data path

All of it lives in `lib/link.py`, shared by every MCU.

### Frames

SLIP framing, CRC32:
```
END | type:u8 hop:u8 seq:u8 payload... crc32:u32le | END      (0xC0 and 0xDB escaped)
```

| type      | direction | payload                                   |
|-----------|-----------|-------------------------------------------|
| `T_HELLO` | up        | `b'<role>>><emblem>'`                     |
| `T_CMD`   | down      | command text, eg. `b'calibrate()'`        |
| `T_LOG`   | up        | text                                      |
| `T_DATA`  | up        | `pack_fsr()` / `pack_rtp()`               |
| `T_OTA`   | both      | update request / reply, see `lib/ota.py`  |

Sensor payloads (little endian):
- FSR: `kind=0x4, state, n, n x (row:u8, col:u8, strength:u16 0..1000)`
- RTP: `kind=0x5, state, x:u16, y:u16, z:u32`
- state: `12` calibrating, `13` calibration failed, `14` calibrated, `42` sample, `43` matrix (all cells)

### Routing

- Up: sender puts `hop=0`, every receiver adds 1. At the Dock, `hop` is the position of the sender.
- Down: `hop` is the target position, every receiver subtracts 1 and keeps the frame when it reaches it. `0xFF` is broadcast: every node handles it and passes it on.
- So the Dock answers a node by sending to the same `hop` it heard from.

### Queues

Each UART has three queues, sent in this order:
1. Control (commands, hello): never skipped.
2. Latest: sensor data, only the newest frame per (sender, sensor) is kept. A slow link skips stale samples instead of backing up.
3. Bulk (logs): dropped first.

- Frames go out in batches of 128 bytes, only once the previous batch left the UART. Nothing blocks.
- Timers only set flags; all UART writes happen in the main loop.
- A node forwards `reset()` down (`link.flush()`) before resetting itself.
- Main loops run under `link.Guard`: an error is logged up the chain (`log` line with `error>>`) and the loop carries on. 20 in a row and the app gives up; `main.py` then runs the rescue loop, which still takes updates.

### Dock <-> Klipper

One line per frame, so several nodes of the same kind stay apart (read by `ext/limn/dock.py`):
```
!LRT>>data>>{"hop": 2, "kind": 4, "state": 42, "values": [[row, col, strength], ...]}>>
!LRT>>data>>{"hop": 1, "kind": 5, "state": 42, "values": [x, y, z]}>>
!LRT>>hello>>{"hop": 1, "role": "rtp", "emblem": "..."}>>
!LRT>>stats>>{"down": {"rx": .., "tx": .., "bad": .., "drop": ..}, "seq_gaps": {"1": 0, "2": 12}, ..}>>
!LRT>>frame>>{"hop": 1, "type": 5, "b64": "..."}>>
```

Host commands only the Dock handles: `power_on()`, `power_off()`, `read_bed_id()`, `stats()`, `frame(<hop>,<type>,<base64>)` (raw frame, hop 0 = the Dock). Every other command is also sent down the chain:
- `read_bed_id()` answers `["BED_3", [spec], {"boot": "9f2c01aa", "placed": 3, "powered": true}]`. `placed` counts the beds placed and removed since the Dock booted, `boot` is new on every boot. Klipper keeps its meshes and test marks per `(boot, placed)`: once either changes, the bed may have moved.
- `calibrate()`, `debug_on()`, `debug_off()`, `reset()`
- `ping()`: every node answers with hello
- `arm(<role>)`, `disarm()`
- `diag()`: FSR, pull state of its sense pins
- `matrix(on)` / `matrix(off)`: FSR, send all 32 cells every frame (state 43). To reach one node only, send it as a `frame(<hop>,2,...)`.

The USB side lives in `lib/bridge.py`. Every MCU runs it, so without a Dock the first bed MCU on USB plays the Dock for the ones below it (it is hop 0). A bed node stays silent on USB until the host sends its first command; from then on it prints every frame (`hello`, `log`, `frame`, and `data` lines for sensor samples).

On the Klipper side, `ext/limn/dock.py` reads these lines; `ext/limn/fsr.py` switches the arrays to matrix mode (one hop at a time, as `frame(<hop>,2,..)`) while it measures.

In Klipper, `LRT_CHAIN` shows the hellos and link counters without stopping Klipper. Error lines from any MCU are always shown.

### Baud

`BAUD` in `lib/link.py`, 115200 for now. Between bed MCUs (5-15cm, twisted) 921600 should be fine; the pogo pin link probably 460800. Raise it while `stats()` shows `bad: 0`.


## Firmware update over the chain

Files on each MCU:
```
main.py        bootloader: runs the app from node.json, rolls back, rescue loop
node.json      role, app, UARTs, pins (eg. BED_3 / BED_4 FSR rows), trigger
lib/link.py    UART chain
lib/ota.py     update receiver, rollback, rescue loop
lib/touch.py   touch line
lrt_*.py       the app
```

`mcu.py install` puts these on a board over USB once. After that `mcu.py update` goes through the Dock:
1. `ping()`, then `INFO` per hop: role, app, `unique_id`, sha256 of every file. Only files that differ are sent.
2. `QUIET` broadcast: nodes stop sending data and logs. The RP2040 stalls during flash writes and would drop UART bytes.
3. `BEGIN(path, size, sha256)` -> `DATA(offset, 192B)`, each acked once written -> `END` checks size and sha256.
4. `COMMIT`: `x -> x.bak`, `x.new -> x`, write `ota_pending.json`, reset.
5. `mcu.py` waits for the node, checks the hashes and sends `CONFIRM`, which drops the `.bak` files.
   - The app does not import: `main.py` rolls back and resets.
   - No confirm within 60s, or 3 boots without one: rolled back.
   - No update pending and the app does not import: rescue loop (link + updates only).
6. Farthest node first, the Dock last (it re-opens its USB port after the reset).

`main.py` and `lib/ota.py` are only replaced with `--force`. The rest, including `lib/link.py`, is covered by the rollback.

`tests/test_chain.py` runs Dock, RTP and FSR as processes (`tests/sim_mcu.py`, fake `machine`) and goes through arming, updates, a broken update and a Dock update with `mcu.py` itself.


## Status

- [x] `lib/link.py`: framing, routing, queues, tests (`tests/test_link.py`)
- [x] Dock, RTP, FSR moved onto the link
- [x] Trigger path in firmware: touch line, RTP pen-down IRQ, Dock ADC edge + PIO pulse, arming, removal debounce
- [x] Firmware update over the chain, `mcu.py`, `tests/test_chain.py`
- [x] RTP: same 1ms settle time for X, Y and Z (was 10ms for X, none for Y and Z)
- [ ] Hardware test: `mcu.py stats` per link, raise baud
- [ ] Diodes on the bed, then:
  - `"touch_pin": 2` in `nodes/rtp.json` and `nodes/fsr.json`, `mcu.py update --hop N --config rtp` (and fsr)
  - `"trigger": "detect"` in `nodes/dock.json`, `mcu.py update --hop 0 --config dock`
- [x] FSR: calibration that times out is reported (state 13, log), keeps the previous baseline; dead knobs removed, same touch rule
- [x] RTP: samples taken while the pen lands or lifts (spread > `max_spread`) are not sent; panel released between reads
- [x] Errors in a main loop are reported and survived (`Guard`)
- [ ] Tune `touch_threshold`, `SETTLE_US` and `max_spread` on the real panel
- [ ] FSR pull-downs: `mcu.py send 'diag()'`. If `pull_down=0`, try `"fsr_pull_down": true` in node.json and re-tune the thresholds
- [ ] FSR touch IRQ
