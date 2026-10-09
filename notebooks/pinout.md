# Pinouts: every MCU and component, as the code declares them

2026-10-08. Read from the code only: `micropython/` (the Dock and the bed MCUs), `micropython/nodes/*.json`, `klipper/*.cfg` and `ext/limn/`. Nothing here was measured on the machine. Where a pin comes from a library default rather than from the code, it says so.

Contents:
1. [The whole machine](#1-the-whole-machine)
2. [Dock (RP2040, MicroPython)](#2-dock-rp2040-micropython)
3. [RTP node (RP2040, MicroPython)](#3-rtp-node-rp2040-micropython)
4. [FSR node (RP2040, MicroPython)](#4-fsr-node-rp2040-micropython)
5. [The bed connector and the chain](#5-the-bed-connector-and-the-chain)
6. [Klipper RP2040 MCU (`[mcu rpi]`)](#6-klipper-rp2040-mcu-mcu-rpi)
7. [Melzi (main Klipper MCU)](#7-melzi-main-klipper-mcu)
8. [Raspberry Pi I2C bus 1: MCP23017 and PN532](#8-raspberry-pi-i2c-bus-1-mcp23017-and-pn532)
9. [All RP2040 GPIOs side by side](#9-all-rp2040-gpios-side-by-side)
10. [Loose ends found while reading](#10-loose-ends-found-while-reading)
11. [The probe OR gate, rebuilt](#11-the-probe-or-gate-rebuilt)


## 1. The whole machine

```
                              Raspberry Pi (Klipper host, Moonraker)
          ┌──────────────────────────┬──────────────┼──────────────────────┬────────────────────────┐
          │ USB (FTDI FT232R)        │ USB          │ USB                  │ I2C bus 1 (/dev/i2c-1) │
          ▼                          ▼              ▼                      ▼                        │
   ┌─────────────┐          ┌────────────────┐  ┌──────────────┐   ┌──────────────┐  ┌───────────┐  │
   │ Melzi       │          │ RP2040 Klipper │  │ Dock RP2040  │   │ MCP23017     │  │ PN532     │  │
   │ ATmega1284p │          │ MCU  [mcu rpi] │  │ MicroPython  │   │ 0x20         │  │ 0x24      │  │
   │ [mcu]       │          │                │  │ [limn]       │   │ holder sw.   │  │ tag reader│  │
   └──┬───┬───┬──┘          └─┬───┬───┬───┬──┘  └──┬───┬───┬───┘   └──────────────┘  └───────────┘  │
      │   │   │               │   │   │   │        │   │   │                                         │
  steppers│ BLTouch     MPU9250 beeper  3× NeoPixel│   │   └── PWR_ON / PWR_OFF ──▶ bed power switch │
  X Y Z K │ (servo,     (sw I2C) (PWM)  indockator │   │                                             │
  endstops│  sensor)                    lamp       │   └──── UART0 + DETECT ─── 5 pogo pins ─── bed  │
          │      ▲                      picam/UI   │                                    │            │
          │      │                                 │                                    ▼            │
          │      └── OR gate ◀── PROBE_OUT (GP11) ─┘               RTP node ──UART── FSR node ...    │
          │          (with BLTouch)                                (resistive)       (4×8 FSR)       │
```

Serial ports, from `klipper/printer.cfg` and `[limn]` in `klipper/limn.cfg`:

| Device | Klipper name | Port |
|---|---|---|
| Melzi | `[mcu]` | `/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A5010P8Z-if00-port0` |
| RP2040 running Klipper | `[mcu rpi]` | `/dev/serial/by-id/usb-Klipper_rp2040_E661385283075A2C-if00` |
| Dock (MicroPython) | `[limn] serial` | `/dev/serial/by-id/usb-MicroPython_Board_in_FS_mode_e6625887d3390f34-if00`, 115200 |
| Linux host MCU | `[mcu host]` | `/tmp/klipper_host_mcu` (declared, unused) |

Note: `[mcu rpi]` is an RP2040, not the Raspberry Pi. Every `rpi:gpioN` pin in the configs is a GPIO of that RP2040.


## 2. Dock (RP2040, MicroPython)

`micropython/lrt_dock_mcu.py`, `micropython/nodes/dock.json`. Hop 0 of the chain, on USB to the Pi.

```
                      ┌──────────────────────────────┐
     to bed power  ◀──┤ GP7   PWR_OFF   out, 100ms   │
     switch        ◀──┤ GP8   PWR_ON    out, 100ms   │
                      │                              │
  to OR gate with  ◀──┤ GP11  PROBE_OUT PIO SM0,     │
  BLTouch → probe     │                 10ms pulse   │
                      │                              │
  to bed pogo RX   ◀──┤ GP12  UART0 TX  (down)       │
  from bed pogo TX ──▶┤ GP13  UART0 RX  (down)       │
                      │                              │
  onboard LED      ◀──┤ GP16  WS2812, 1 px, GRB      │
                      │                              │
  bed pogo DETECT  ──▶┤ GP29  ADC3   bed ID / touch  │
   (10k pull-up on    │                              │
    the Dock)         │ USB   → Pi, `[limn] serial`  │
                      └──────────────────────────────┘
```

| GPIO | Name in code | Mode | What it does |
|---|---|---|---|
| GP7 | `PIN_PWR_OFF` | out, pull-down | 100 ms pulse turns the bed's power off (`power_off()`, bed removed) |
| GP8 | `PIN_PWR_ON` | out, pull-down | 100 ms pulse turns the bed's power on (`power_on()`, bed confirmed for 1 s) |
| GP11 | `PIN_PROBE_OUT` | out, pull-down, PIO SM0 `set_base`, 100 kHz | 10 ms high pulse = probe triggered; 50 ms lockout after. OR'd with the BLTouch into the probe endstop (STRATEGY.md) |
| GP12 | UART0 TX | `dock.json` `"down": {"id": 0, "tx": 12}` | Frames down to the bed |
| GP13 | UART0 RX | `dock.json` `"down": {"id": 0, "rx": 13}` | Frames up from the bed |
| GP16 | `npx` | WS2812, 1 pixel | Status LED |
| GP29 | `ADC_DETECT` | ADC3, input | DETECT net: bed ID resistor, bed removal, and (with `"trigger": "detect"`) a bed node's touch |
| USB | `bridge` | CDC | `!LRT>>…` lines to Klipper (`ext/limn/dock.py`) |

What DETECT reads (`BEDS` in `lrt_dock_mcu.py`), 10k pull-up on the Dock, the ID resistor to GND on the bed:

| Reads (u16) | Means |
|---|---|
| 10000–13500 | BED_1 (2.2k) |
| 18000–24000 | BED_2 (4.7k) |
| 28000–36000 | BED_3 (10k) |
| 37000–42000 | BED_4 (15k) |
| 43000–47500 | BED_5 (22k) |
| 48000–53000 | BED_6 (33k) |
| > 55000 | no bed (for > 250 ms: removed) |
| > 56000, rising, while armed | a bed node's touch line (`touch_threshold`, only with `"trigger": "detect"`) |


## 3. RTP node (RP2040, MicroPython)

`micropython/lrt_resistive_touch.py`, `micropython/nodes/rtp.json`. A 4-wire resistive panel, read like the Adafruit TouchScreen library.

```
                      ┌──────────────────────────────┐
  from up (Dock or ──▶┤ GP1   UART0 RX  (up)   *     │
  previous node)   ◀──┤ GP0   UART0 TX  (up)   *     │
                      │                              │
  to DETECT via    ◀──┤ GP2   touch_pin   (planned,  │
  Schottky diode      │       not in rtp.json yet)   │
                      │                              │
  to next node RX  ◀──┤ GP4   UART1 TX  (down) *     │
  from next node TX──▶┤ GP5   UART1 RX  (down) *     │
                      │                              │
  onboard LED      ◀──┤ GP16  WS2812, 1 px, GRB      │
                      │                              │
  panel Y−         ───┤ GP29  ADC3   YM              │
  panel X+         ───┤ GP28  ADC2   XP  (+ pen IRQ) │
  panel Y+         ───┤ GP27  ADC1   YP              │
  panel X−         ───┤ GP26  ADC0   XM              │
                      │ USB   (bench only: hop 0)    │
                      └──────────────────────────────┘
   * MicroPython's default UART pins: node.json gives only the UART id.
```

| GPIO | Name in code | What it does |
|---|---|---|
| GP0 / GP1 | `"up": {"id": 0}` | UART0 TX / RX towards the Dock (default pins) |
| GP2 | `touch_pin` (`lib/touch.py`) | Planned: raises DETECT through a Schottky. Only used once `"touch_pin": 2` is in `rtp.json` |
| GP4 / GP5 | `"down": {"id": 1}` | UART1 TX / RX to the next bed node (default pins) |
| GP16 | `npx` | Status LED |
| GP26 | `XM` (ADC0) | Panel X− |
| GP27 | `YP` (ADC1) | Panel Y+ |
| GP28 | `XP` (ADC2) | Panel X+, also the pen-down IRQ |
| GP29 | `YM` (ADC3) | Panel Y− |

`PANEL_PINS = [XP, XM, YP, YM] = [28, 26, 27, 29]`, overridable with `"panel_pins"` in `node.json` (not set).

How the four panel pins are driven, per step (`get_points`, `pen_detect_on`):

| Step | XP GP28 | XM GP26 | YP GP27 | YM GP29 | Reads |
|---|---|---|---|---|---|
| X | out 1 | out 0 | ADC | ADC (hi-Z) | YP → x |
| Y | ADC | ADC (hi-Z) | out 1 | out 0 | XP → y |
| Z (pressure) | out 0 | ADC | ADC | out 1 | z1 = XM, z2 = YP |
| Pen detect (armed, idle) | in, pull-up, IRQ falling | hi-Z | hi-Z | out 0 | touch = XP low |
| Released | in | in | in | in | — |


## 4. FSR node (RP2040, MicroPython)

`micropython/lrt_fsr_array.py`, `micropython/nodes/fsr.json` (BED_5 and others) and `fsr_bed3.json` (BED_3). A 4 × 8 matrix: 8 drive columns, 4 sense rows on the ADC pins.

```
                      ┌──────────────────────────────┐
  from up          ──▶┤ GP1   UART0 RX  (up)   *     │
                   ◀──┤ GP0   UART0 TX  (up)   *     │
  to DETECT via    ◀──┤ GP2   touch_pin (planned)    │
  Schottky diode      │                              │
                      │       drive (out, idle 0)    │
  column 4         ◀──┤ GP8   col 4                  │
  column 1         ◀──┤ GP9   col 1                  │
  column 0         ◀──┤ GP10  col 0                  │
  column 3         ◀──┤ GP11  col 3  (leaks, act-6)  │
  column 2         ◀──┤ GP12  col 2                  │
  column 5         ◀──┤ GP13  col 5                  │
  column 6         ◀──┤ GP14  col 6                  │
  column 7         ◀──┤ GP15  col 7                  │
                      │                              │
  onboard LED      ◀──┤ GP16  WS2812, 1 px           │
                      │       sense (ADC)            │
  row 0  ──R_s──┬───▶┤ GP29  ADC3                   │
               47k                                  │
               GND                                  │
  row 1  ──R_s──┬───▶┤ GP28  ADC2                   │
               47k                                  │
               GND                                  │
  row 2/3 ─R_s──┬───▶┤ GP26  ADC0   (see table)     │
               47k                                  │
               GND                                  │
  row 3/2 ─R_s──┬───▶┤ GP27  ADC1   (see table)     │
               47k                                  │
               GND    │ USB   (bench only: hop 0)    │
                      └──────────────────────────────┘
   * MicroPython's default UART pins. No down UART: the FSR is the last node.
   R_s: the board's series resistors, on three of the rows (act-6: not on row 3).
   47k: the load of each row's divider, to GND (fitted 2026-10-09, `"fsr_load"`).
```

**The sense rows need a load to GND.** The scan drives one column high and the others low, and each row reads the divider of the pressed cell (column to row) and the row's load (row to GND): `V = 3.3 V × R_load / (R_load + R_cell)`. Without a load there's no divider: the row floats, and its reading depends on charge left on the line and on the ADC's sampling capacitor from the row read before it. Until 2026-10-09 the rows had none: `ADC()` turns the pad pull-downs off, and `"fsr_pull_down"` (which turns them back on) was never set. That fits what the sheet did on both sheets: a press lifting its whole column (row 3, without a series resistor, the most), row 3 reading 30–50 with the head merely over the sheet, baselines drifting by tens a minute.

**Its size: about the cell's resistance at the press you measure.** That's where `V` changes most with force. A pen's tap is a light press, so the cell is high, tens of kΩ. 47k is the default here:

| Load | Light tap (cell ~100k) | Firm press (cell ~10k) | Notes |
|---|---|---|---|
| 10k | 0.3 V | 1.65 V | the usual FSR value, for finger presses; a fine tip barely shows |
| 47k | 1.05 V | 2.7 V | the default |
| 100k | 1.65 V | 3.0 V | more for a fine tip; slower to settle into the ADC, more pickup |

The cell values are guesses: measure one cell with a meter, a pen pressing it as the taps do, and pick the load near it. Beyond ~100k the ADC's input (a few pF sampled for ~2 µs, after the mux switched from another row) settles less well. The internal pull-down (`"fsr_pull_down": true`) is ~50k but loosely specified and drifts with temperature: fine for a first test, not instead of resistors. Either side of the series resistor works: no current flows into the ADC.

With `"fsr_load"` in node.json the firmware leaves the internal pull-downs off and drops row 3's `× 0.8`. The readings' scale changes with the load: run `LRT_FSR_SURVEY` again (it sets `early` from the noise at rest), and check `respond` / `press_strength` against a ladder.

Columns, `FSR_X = [10, 9, 12, 11, 8, 13, 14, 15]` (index = column):

| Column | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|---|
| GPIO | GP10 | GP9 | GP12 | GP11 | GP8 | GP13 | GP14 | GP15 |

Rows, `fsr_y` from `node.json` (index = row):

| Row | `fsr.json` | `fsr_bed3.json` | Notes |
|---|---|---|---|
| 0 | GP29 (ADC3) | GP29 (ADC3) | |
| 1 | GP28 (ADC2) | GP28 (ADC2) | |
| 2 | GP27 (ADC1) | GP26 (ADC0) | |
| 3 | GP26 (ADC0) | GP27 (ADC1) | No series resistor on the board (act-6). Read × 0.8 without `fsr_load` |

The sense pins are set up with pull-downs, but `ADC()` turns them off. `"fsr_pull_down": true` turns them back on through `PADS_BANK0` (set in neither file); with `"fsr_load"` (BED_5, 47k fitted) they stay off. `diag()` reports both.

Scan: for each column, drive it high, read all 4 rows, drive it low (`READ_MATRIX`, 32 cells).

Every cell, as (row, col) → (sense pin, drive pin), `fsr.json`:

| | col 0 GP10 | col 1 GP9 | col 2 GP12 | col 3 GP11 | col 4 GP8 | col 5 GP13 | col 6 GP14 | col 7 GP15 |
|---|---|---|---|---|---|---|---|---|
| **row 0 GP29** | 29·10 | 29·9 | 29·12 | 29·11 | 29·8 | 29·13 | 29·14 | 29·15 |
| **row 1 GP28** | 28·10 | 28·9 | 28·12 | 28·11 | 28·8 | 28·13 | 28·14 | 28·15 |
| **row 2 GP27** | 27·10 | 27·9 | 27·12 | 27·11 | 27·8 | 27·13 | 27·14 | 27·15 |
| **row 3 GP26** | 26·10 | 26·9 | 26·12 | 26·11 | 26·8 | 26·13 | 26·14 | 26·15 |

For `fsr_bed3.json`, swap the sense pins of rows 2 and 3 (row 2 = GP26, row 3 = GP27).


## 5. The bed connector and the chain

The bed sits on 5 pogo pins (STRATEGY.md): power, GND, DETECT, TX, RX. Between bed MCUs: wires. The order of the nodes is not fixed; this is the usual one, `Dock → RTP → FSR`.

```
   Dock                        pogo                 RTP node                          FSR node
  ┌──────┐                                        ┌──────────┐                      ┌──────────┐
  │ GP12 ├── TX ─────────────── RX pogo ─────────▶┤ GP1  RX  │                      │          │
  │ GP13 ├◀─ RX ─────────────── TX pogo ──────────┤ GP0  TX  │                      │          │
  │      │                                        │ GP4  TX  ├── wire ─────────────▶┤ GP1  RX  │
  │      │                                        │ GP5  RX  ├◀─ wire ──────────────┤ GP0  TX  │
  │ GP29 ├◀─ DETECT ──┬──────── DETECT pogo ──────┼──────────┼─────┬────────────────┼──────────┤
  │ ADC3 │   10k to   │                           │ GP2 ─▶|──┼─────┤ (planned)      │ GP2 ─▶|──┤ (planned)
  │      │   3V3      ID resistor to GND (bed)    │          │     │                │          │
  │ GP7  ├─ PWR_OFF ─▶ bed power switch ─ power pogo ─▶ bed 5V/3V3 for all nodes   │          │
  │ GP8  ├─ PWR_ON  ─▶                                                                         │
  │      │            GND ──────────── GND pogo ───────── GND ─────────────────────────── GND  │
  └──────┘                                        └──────────┘                      └──────────┘
```

| Link | From | To | Baud |
|---|---|---|---|
| Dock → first node | Dock GP12 (UART0 TX) | node GP1 (UART0 RX) | 115200 (`BAUD`, `lib/link.py`) |
| first node → Dock | node GP0 (UART0 TX) | Dock GP13 (UART0 RX) | 115200 |
| RTP → next node | RTP GP4 (UART1 TX) | node GP1 (UART0 RX) | 115200 |
| next node → RTP | node GP0 (UART0 TX) | RTP GP5 (UART1 RX) | 115200 |
| touch line (planned) | each node's GP2, through a Schottky | DETECT (Dock GP29) | — |

The power switch behind PWR_ON / PWR_OFF isn't in the code; only that each takes a 100 ms pulse.


## 6. Klipper RP2040 MCU (`[mcu rpi]`)

Runs Klipper firmware. Pins from `klipper/printer.cfg`, `leds.cfg`, `buzzer.cfg`.

```
                      ┌──────────────────────────────┐
  MPU9250 SCL      ◀──┤ gpio4  software I2C SCL      │
  MPU9250 SDA      ◀─▶┤ gpio5  software I2C SDA      │
                      │                              │
  buzzer           ◀──┤ gpio9  PWM, 1 ms cycle       │
                      │                              │
  Unicorn pHAT     ◀──┤ gpio15 NeoPixel  32 px GRB   │  [neopixel picam]
  lamp             ◀──┤ gpio16 NeoPixel  30 px GRBW  │  [neopixel lamp]
  indockator       ◀──┤ gpio17 NeoPixel  30 px GRB   │  [neopixel indockator]
                      │                              │
                      │ USB → Pi, usb-Klipper_rp2040 │
                      └──────────────────────────────┘
```

| GPIO | Klipper section | Device | Settings |
|---|---|---|---|
| gpio4 | `[mpu9250]` `i2c_software_scl_pin` | MPU9250 accelerometer | `axes_map: -y, x, z`, used by `[resonance_tester]` |
| gpio5 | `[mpu9250]` `i2c_software_sda_pin` | MPU9250 | I2C address: Klipper's default for the mpu9250, 0x68 (not set in the config) |
| gpio9 | `[pwm_cycle_time beeper]` | Buzzer | `cycle_time: 0.001`, `M300` sets it per note |
| gpio15 | `[neopixel picam]` | Pimoroni Unicorn pHAT, the 8 × 4 UI matrix (README) | 32, GRB |
| gpio16 | `[neopixel lamp]` | Lamp | 30, GRBW |
| gpio17 | `[neopixel indockator]` | Dock indicator strip | 30, GRB |

The one I2C device on this MCU:

| Bus | SCL | SDA | Address | Device |
|---|---|---|---|---|
| software I2C on `rpi` | gpio4 | gpio5 | 0x68 (Klipper default) | MPU9250 |


## 7. Melzi (main Klipper MCU)

ATmega1284p, Melzi v2.0 pin map (`klipper/printer.cfg`). The `(PCB: …)` comments in the config say which driver socket each axis is on: they're not the ones the board labels.

```
                       ┌───────────────────────────────────────┐
                       │  Melzi v2.0  (ATmega1284p)            │
  shared enable  ◀─────┤ PD6   !EN   X, Y, Z                  │
                       │                                       │
  X  (Extruder ◀───────┤ PB1   STEP                            │
     socket)   ◀───────┤ PB0   !DIR                            │
  X endstop    ───────▶┤ PC2   ^!    (pull-up, inverted)       │
                       │                                       │
  Y  (Y socket)◀───────┤ PC6   STEP                            │
               ◀───────┤ PC7   DIR                             │
  Y endstop    ───────▶┤ PC3   ^!                              │
                       │                                       │
  Z  (X socket)◀───────┤ PD7   STEP                            │
               ◀───────┤ PC5   DIR                             │
  Z endstop    ───────▶┤ PC4   ^!                              │
                       │                                       │
  K  (Z socket,◀───────┤ PB3   STEP                            │
  key lock)    ◀───────┤ PB2   !DIR                            │
               ◀───────┤ PA5   !EN                             │
  K endstop    ───────▶┤ PA2   ^     (pull-up)                 │
                       │                                       │
  BLTouch      ◀───────┤ PA3   control (servo)                 │
  sensor/OR    ───────▶┤ PA4   ^     sensor (pull-up)          │
                       │                                       │
                       │ USB (FT232R) → Pi                     │
                       └───────────────────────────────────────┘
```

| Pin | Section | Function | Modifiers |
|---|---|---|---|
| PB1 | `[stepper_x]` | step | — |
| PB0 | `[stepper_x]` | dir | `!` inverted |
| PD6 | `[stepper_x]`, `[stepper_y]`, `[stepper_z]` | enable (shared) | `!` active low |
| PC2 | `[stepper_x]` | endstop | `^!` pull-up, inverted |
| PC6 | `[stepper_y]` | step | — |
| PC7 | `[stepper_y]` | dir | — |
| PC3 | `[stepper_y]` | endstop | `^!` |
| PD7 | `[stepper_z]` | step | — |
| PC5 | `[stepper_z]` | dir | — |
| PC4 | `[stepper_z]` | endstop | `^!` |
| PB3 | `[manual_stepper axis_k]` | step | — |
| PB2 | `[manual_stepper axis_k]` | dir | `!` |
| PA5 | `[manual_stepper axis_k]` | enable | `!` |
| PA2 | `[manual_stepper axis_k]` | endstop | `^` pull-up |
| PA3 | `[bltouch]` | control_pin (servo) | — |
| PA4 | `[bltouch]` | sensor_pin | `^` pull-up |

Driver sockets, from the config's comments:

| Axis | Socket on the PCB |
|---|---|
| X | Extruder |
| Y | Y |
| Z | X |
| K (key lock, `axis_k`) | Z ("dual Z") |

The Dock's PROBE_OUT reaches Klipper through an OR gate with the BLTouch (STRATEGY.md). The gate's output is on PA4, EXT header pin A4 (`projects/limn/content/electronics.md`). The rebuild is in [section 11](#11-the-probe-or-gate-rebuilt).


## 8. Raspberry Pi I2C bus 1: MCP23017 and PN532

`ext/limn/i2c.py`, `ext/limn/tool_holder.py`, `[limn]` in `klipper/limn.cfg`. Read straight from Linux (`/dev/i2c-1`), not through a Klipper MCU.

```
   Raspberry Pi                    I2C bus 1 (/dev/i2c-1)
  ┌────────────────────┐
  │ GPIO2  SDA1  pin 3 ├──────┬───────────────────────┬──────────── SDA
  │ GPIO3  SCL1  pin 5 ├──────┼──┬────────────────────┼──┬───────── SCL
  └────────────────────┘      │  │                    │  │
                         ┌────┴──┴─────────┐     ┌────┴──┴────┐
                         │ MCP23017  0x20  │     │ PN532 0x24 │
                         │                 │     │ tag reader │
                         │ GPB7 (15) ◀─ holder 41 switch      │
                         │ GPB6 (14) ◀─ holder 42 switch      │
                         │ GPB5 (13) ◀─ holder 45 switch      │
                         │ GPB4 (12) ◀─ holder 43 switch      │
                         │ GPB3 (11) ◀─ holder 44 switch      │
                         │ others: not set up                 │
                         └─────────────────┘     └────────────┘
```

GPIO2/GPIO3, header pins 3/5, are I2C bus 1 on every Pi with the 40-pin header; the code only names the bus number.

| Address | Device | Used for |
|---|---|---|
| 0x20 | MCP23017 (`tool_holder_address`) | Holder switches, read as `GPIO` (0x12) |
| 0x24 | PN532 (`tool_holder_tag_address`) | NTAG read / write of the tool tags |

MCP23017 pins, `tool_holder_pins: 15:41, 14:42, 13:45, 12:43, 11:44`. The code numbers them 0–15, port A = 0–7, port B = 8–15 (`IOCON.BANK=0`). Set up as inputs with pull-ups (`IODIR`, `GPPU`); a pin reading 0 = a tool in that holder.

| Code pin | MCP23017 pin | Holder / tool |
|---|---|---|
| 15 | GPB7 | 41 |
| 14 | GPB6 | 42 |
| 13 | GPB5 | 45 |
| 12 | GPB4 | 43 |
| 11 | GPB3 | 44 |
| 0–10 | GPA0–GPA7, GPB0–GPB2 | not used |

Note the order along the row is not monotonic in tool number: GPB5 is holder 45, GPB4 and GPB3 are 43 and 44.

All the I2C devices in the machine:

| Bus | Master | SDA / SCL | Address | Device |
|---|---|---|---|---|
| Pi I2C1 | Linux, `ext/limn/i2c.py` | GPIO2 / GPIO3 | 0x20 | MCP23017 |
| Pi I2C1 | Linux, `ext/limn/i2c.py` | GPIO2 / GPIO3 | 0x24 | PN532 |
| software I2C | Klipper `[mcu rpi]` | gpio5 / gpio4 | 0x68 (default) | MPU9250 |


## 9. All RP2040 GPIOs side by side

Every RP2040 GPIO, which node uses it and for what. `—` = unused. `(def)` = MicroPython default UART pin. `(plan)` = only once the diode is fitted and `touch_pin` set.

| GPIO | ADC | Dock | RTP | FSR (`fsr.json`) | FSR (`fsr_bed3.json`) | Klipper `rpi` |
|---|---|---|---|---|---|---|
| 0 | | — | UART0 TX up (def) | UART0 TX up (def) | UART0 TX up (def) | — |
| 1 | | — | UART0 RX up (def) | UART0 RX up (def) | UART0 RX up (def) | — |
| 2 | | — | touch_pin (plan) | touch_pin (plan) | touch_pin (plan) | — |
| 3 | | — | — (alt. touch_pin) | — (alt. touch_pin) | — (alt. touch_pin) | — |
| 4 | | — | UART1 TX down (def) | — | — | MPU9250 SCL |
| 5 | | — | UART1 RX down (def) | — | — | MPU9250 SDA |
| 6 | | — | — | — | — | — |
| 7 | | PWR_OFF | — | — | — | — |
| 8 | | PWR_ON | — | col 4 | col 4 | — |
| 9 | | — | — | col 1 | col 1 | beeper PWM |
| 10 | | — | — | col 0 | col 0 | — |
| 11 | | PROBE_OUT (PIO) | — | col 3 | col 3 | — |
| 12 | | UART0 TX down | — | col 2 | col 2 | — |
| 13 | | UART0 RX down | — | col 5 | col 5 | — |
| 14 | | — | — | col 6 | col 6 | — |
| 15 | | — | — | col 7 | col 7 | NeoPixel picam (32) |
| 16 | | WS2812 LED | WS2812 LED | WS2812 LED | WS2812 LED | NeoPixel lamp (30) |
| 17 | | — | — | — | — | NeoPixel indockator (30) |
| 18–25 | | — | — | — | — | — |
| 26 | ADC0 | — | XM (X−) | row 3 (+47k to GND) | row 2 | — |
| 27 | ADC1 | — | YP (Y+) | row 2 (+47k to GND) | row 3 | — |
| 28 | ADC2 | — | XP (X+, pen IRQ) | row 1 (+47k to GND) | row 1 | — |
| 29 | ADC3 | DETECT | YM (Y−) | row 0 (+47k to GND) | row 0 | — |

Free on every MicroPython node: GP3, GP6, GP17–GP25 (as far as the RP2040 goes; which of them the boards break out isn't in the code). GP2/GP3 stay free for the touch diode.

The MicroPython boards: all three put a 1-pixel WS2812 on GP16 and use GP29 as an ADC, as on a Waveshare RP2040-Zero (on a Raspberry Pi Pico GP29 is the VSYS divider, not a pin). The code doesn't name the board.


## 10. Loose ends found while reading

- **FSR row order.** Checked 2026-10-09: `nodes/fsr.json` (BED_5) is `[29, 28, 27, 26]` and `nodes/fsr_bed3.json` `[29, 28, 26, 27]`, as `lrt_fsr_array.py`'s comment has it; this page had them the other way round (fixed). Which physical row lacks the series resistor (act-6 says row 3: GP26 on BED_5) is worth a look while fitting the loads.
- **UART pins on the bed nodes are defaults.** `rtp.json` and `fsr*.json` give only `"id"`, so UART0 is GP0/GP1 and UART1 is GP4/GP5 because MicroPython's RP2040 port defaults to them. A firmware build with other defaults would move them silently; `"tx"`/`"rx"` in the node files would pin them down, as `dock.json` does.
- **The bed power switch** is only described in STRATEGY.md; its part isn't in the code. (The OR gate: section 11.)
- **MPU9250 address** isn't in the config, so it's Klipper's default (0x68). An AD0-high board would need `i2c_address: 105`.


## 11. The probe OR gate, rebuilt

2026-10-08. A replacement for the two-transistor gate (`projects/limn/content/electronics.md`, *The probe OR gate*). Parts are all from the JTAREA 0805 kit (`limn_endoscope/notebooks/refs/smd-kit-components.md`). Not built or tested yet.

### What it has to do

| | Dock `PROBE_OUT` (GP11) | BLTouch sensor (white) | Output → Melzi PA4 (EXT A4) |
|---|---|---|---|
| Logic | 3.3 V push-pull, 10 ms high pulse, pull-down | open drain (V3 default): held low, released for ~10 ms on trigger | high = triggered, Klipper has `sensor_pin: ^PA4` (not inverted) |
| Idle | 0 V | 0 V (sinking) | must read low: < 1.5 V (ATmega at 5 V, V_IL = 0.3 Vcc) |
| Trigger | 3.3 V | floats, needs a pull-up | must read high: > 3.0 V (V_IH = 0.6 Vcc) |

Why not the simplest gates:
- **Two diodes and a pull-down** (diode OR): the Dock's leg gives 3.3 V − 0.3 V (SS14) = 3.0 V, right on the AVR's V_IH. No margin.
- **Two NPN emitter followers** (collectors to 5 V, emitters joined, pull-down): the Dock's leg gives 3.3 − 0.7 ≈ 2.6 V, under V_IH. If the old gate was built like this, that alone would make the Dock's pulses unreliable. Worth checking on the old board before throwing it away.
- **Two NPN in parallel** (an RTL NOR) gives a solid 5 V, but inverted: Klipper would need `^!PA4`, and then a broken output wire reads "not triggered". The probe would never stop.

### The circuit: two NPN (the OR, inverted) + one PNP (inverts back, drives 5 V)

```
  +5V (Melzi EXT pin 9) ──┬───────────────────────────┬──────────────┐
                          │                           │              │
                        R5 10k                      R7 47k           │ E
                          │                           │           ┌──┴──┐
  BLTouch white ──────────┤                           ├───────────┤B Q3 │ MMBT3906 (PNP)
  (sensor)                │                           │           └──┬──┘
                        R2 10k                      R6 10k           │ C
                          │                           │              ├──────────▶ OUT → Melzi PA4 (EXT A4)
                          │       ┌──────────────┬────┘ N            │
                          │      C│             C│                 R8 2.2k
                          ├─────B Q2           B Q1 ──┬── R1 10k ── Dock GP11      │
                          │      E│             E│    │              (PROBE_OUT)   GND
                        R4 100k   │              │  R3 100k
                          │       │              │    │
                         GND     GND            GND  GND

  Q1, Q2: MMBT3904 (NPN). Collectors joined at N. Q1's base: R1 from GP11, R3 to GND.
  Q2's base: R2 from the BLTouch line, R4 to GND. Q3's base: R6 from N, R7 to +5V.
  Gate GND = Melzi GND = Dock GND (one common ground; the Dock's USB ground alone isn't enough).
```

Same thing, as a netlist:

| Part | Value (kit part) | From | To |
|---|---|---|---|
| Q1 | MMBT3904 (1AM) or S9013 (J3), NPN | C: N, E: GND | B: via R1 from Dock GP11 |
| Q2 | MMBT3904 (1AM) or S9013 (J3), NPN | C: N, E: GND | B: via R2 from BLTouch white |
| Q3 | MMBT3906 (2A) or S8550 (2TY), PNP | E: +5V, C: OUT | B: via R6 from N |
| R1 | 10k | Dock GP11 | Q1 B |
| R2 | 10k | BLTouch white | Q2 B |
| R3 | 100k | Q1 B | GND (keeps Q1 off while the Dock boots or is unplugged) |
| R4 | 100k | Q2 B | GND |
| R5 | 10k | BLTouch white | +5V (the BLTouch's open-drain pull-up; PA4's own pull-up no longer reaches it) |
| R6 | 10k | N | Q3 B |
| R7 | 47k | Q3 B | +5V (keeps Q3 off when N floats) |
| R8 | 2.2k | OUT | GND |

How it works:
- Idle: Q1, Q2 off, N floats, R7 holds Q3 off, R8 pulls OUT low. PA4's internal pull-up (20–50 kΩ) against R8: at most 5 × 2.2 / 22.2 = 0.5 V. Reads low.
- Dock pulse: 3.3 V through R1 → Ib ≈ (3.3 − 0.7) / 10k − 0.7 / 100k ≈ 0.25 mA → Q1 sinks N, Q3's base current (5 − 0.7) / 10k ≈ 0.43 mA (Q1 needs a gain of only ~2). Q3 saturates and pulls OUT to ~4.9 V. Reads high.
- BLTouch trigger: its pin lets go, R5 and R2 feed Q2's base ≈ (5 − 0.7) / 20k ≈ 0.2 mA, same as above.
- Q3 into R8: 5 V / 2.2k ≈ 2.3 mA, base 0.43 mA, forced gain 5: hard on. Switching is in µs, the pulses are 10 ms.

Fail-safe (a probe that never stops crashes the pen or the bed; one that reads triggered just errors out):

| Fault | OUT / PA4 reads | Result |
|---|---|---|
| Output wire to PA4 broken | high (PA4's `^` pull-up) | triggered: Klipper refuses to probe. Safe |
| BLTouch unplugged | high (R5 lifts Q2's base) | triggered. Safe |
| Dock unplugged / booting | low (R3, GP11's pull-down) | BLTouch still works; Dock touches lost. Fine |
| Gate's 5 V lost | low (R8) | never triggered. **Not safe**, but Klipper's BLTouch self-test (`pin_up_touch_mode_reports_triggered: true`) expects a triggered reading on deploy and stops with an error, so it should be caught at the start of a probe |

Keep `^PA4` in `printer.cfg`: the pull-up is what makes a broken wire safe. No config change.

### Bench test before wiring it in

1. 5 V and GND on the gate, inputs open: OUT ≈ 5 V (R5 → Q2 on: the open BLTouch input looks like a trigger). Correct.
2. BLTouch input to GND (as the idle BLTouch does): OUT < 0.5 V.
3. Dock input to 3.3 V: OUT > 4.5 V. Back to GND: OUT < 0.5 V.
4. On the plotter: `QUERY_PROBE` → open. `BLTOUCH_DEBUG COMMAND=pin_down`, touch the pin by hand → `QUERY_PROBE` during the touch, or just run `PROBE` over the bed. Then a Dock touch: `PROBE` over the RTP with `arm(rtp)` (STRATEGY.md), or with `"trigger": "uart"` a tap on the panel.

### Alternative: one LM339 (kit IC), fail-safe on power loss too

Diode OR into one comparator. Both inputs through an SS14 (1N5819) to node A, A to GND through 100k; R5 10k pull-up on the BLTouch line as above. LM339 on 5 V: IN+ = A, IN− = 1.0 V (a 39k / 10k divider from 5 V). Its open-collector output to PA4, with a 4.7k pull-up to 5 V. Dock high: A ≈ 3.0 V > 1.0 V → output off → pulled high. Idle: A = 0 V → output sinks → low. The BLTouch leg puts ~4.7 V on IN+, above the LM339's common-mode range (Vcc − 1.5 V), which TI allows as long as IN− stays inside it.

Unlike the transistor gate, losing its 5 V lets the output go high: triggered, safe. It costs an SOP-14 on an adapter, and the other three comparators sit unused (tie their inputs to GND).
