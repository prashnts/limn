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


## Trigger path (planned)

- The Dock has a 10k pull-up on DETECT; the bed has the ID resistor to GND.
- Each bed MCU gets a Schottky diode from a spare GPIO (GPIO 2 or 3) to the DETECT net. Silicon diodes drop too much for BED_6.
  - Idle / unpowered: diode is off, the bed ID reads as before (the Dock reads it before powering the bed).
  - Touch: GPIO high, DETECT goes to ~3.0V (~59k counts), above every bed ID (max 53k).
- Nodes raise the line only when armed, hold it ~3ms, and lock out until the touch is released.
- Nodes detect touch with a hard pin IRQ where possible (RTP: pen-down detect like the XPT2046 does it).
- Dock reads the ADC every loop; a rising edge above ~56k while armed starts a 10ms pulse (PIO, so the loop keeps running).
- Bed removal = DETECT high for more than 250ms. A removal during a probe move triggers the probe, which is the safe outcome.
- Host sends `arm(role)` / `disarm()` around probe sessions, so an FSR touch cannot fire a pen probe.
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

Sensor payloads (little endian):
- FSR: `kind=0x4, state, n, n x (row:u8, col:u8, strength:u16 0..1000)`
- RTP: `kind=0x5, state, x:u16, y:u16, z:u32`
- state: `12` calibrating, `14` calibrated, `42` sample

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

### Dock <-> Klipper

Unchanged line format, so `ext/limn.py` keeps working:
```
!LRT>>SMP>>{"4": [[row, col, strength], ...], "5": [x, y, v], "hop": 2}>>
!LRT>>hello>>{"hop": 1, "role": "rtp", "emblem": "..."}>>
!LRT>>stats>>{"down": {"rx": .., "tx": .., "bad": .., "drop": ..}, "seq_gaps": {"1": 0, "2": 12}}>>
```

Host commands: `power_on()`, `power_off()`, `read_bed_id()`, `stats()`, and these, which are also sent down the chain: `calibrate()`, `debug_on()`, `debug_off()`, `reset()`, `ping()` (every node answers with hello).

### Baud

`BAUD` in `lib/link.py`, 115200 for now. Between bed MCUs (5-15cm, twisted) 921600 should be fine; the pogo pin link probably 460800. Raise it while `stats()` shows `bad: 0`.


## Firmware update over the chain (planned)

Files on each MCU:
```
boot.py        rollback + rescue, rarely changed
main.py        reads node.json, imports the app
node.json      role, pin map (BED_3 / BED_4), baud
lib/link.py    link + update receiver
app_*.py       dock / rtp / fsr
rescue.py      link relay + update receiver only, never updated automatically
```

Update, driven by `tools/chain_flash.py` through the Dock's USB (Klipper disconnected):
1. `ping()`: each node answers with role, `unique_id` and sha256 of its files. Only changed files are sent.
2. `QUIET` broadcast: nodes stop streaming. The RP2040 stalls during flash writes and would drop UART bytes.
3. `OTA_BEGIN(path, size, sha256)` -> `OTA_DATA(offset, <=192B)` with an ACK per chunk after it is written -> `OTA_END` checks sha256.
4. `OTA_COMMIT`: `x -> x.bak`, `x.new -> x`, write `pending`, reset.
5. The app confirms after ~10s of healthy link. `boot.py` rolls back after 3 unconfirmed boots, and runs `rescue.py` if the app does not import.

Each bed MCU needs one USB flash to get `boot.py` + `rescue.py`, then everything goes over the chain.


## Status

- [x] `lib/link.py`: framing, routing, queues, tests (`tests/test_link.py`)
- [x] Dock, RTP, FSR moved onto the link
- [ ] Hardware test: `stats()` per link, raise baud
- [ ] Trigger path: diodes, node touch IRQ, Dock ADC edge + PIO pulse, arming, removal debounce
- [ ] Sensor fixes: RTP settle times, FSR pull-downs and thresholds
- [ ] Firmware update over the chain
