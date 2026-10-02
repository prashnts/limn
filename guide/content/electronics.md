+++
title = "Electronics"
nav = "Electronics"
order = 2
summary = "A Raspberry Pi runs Klipper; a Melzi drives the motors; RP2040s and I2C breakouts do the sensing."
+++

## Boards

| Board | Does |
|---|---|
| Raspberry Pi 4 | Klipper, Moonraker, the plot UI (port 4219). The holder switches and the tag reader sit on its I2C bus |
| Melzi ([[melzi-base]]) | The Klipper MCU for motion: steppers for A, B, Z and the K axis (the tool lock), the endstops, the BLTouch |
| RP2040 ([[raspberry-pi-pico-wh]]), Klipper's `rpi` MCU | Extra GPIO: the NeoPixels (GPIO 15, 16, 17), the buzzer (GPIO 9), and the MPU9250 on software I2C (GPIO 4, 5). It sits on the [[limn-aux-pcb]] |
| RP2040-Zero, the Dock | MicroPython. It powers the calibration beds and talks to them, and it sends the touch pulse to the probe OR gate |
| 2 × [[rp2040-tiny-v1-1]] | In the calibration bed, under the [[fsr-32-zones]] and the [[resistive-touch-panel]] |
| [[mcp23017-adafruit]] | The tool holders' switches |
| [[pn532-nfc-assembly]] | Reads the pens' tags, in the [[limn-nfc]] |
| [[bltouch]] | Probes the bed |

Power comes from a 65 W USB-C supply. A PD trigger cable takes 12 V (3 A) from it for the Melzi, and the Pi gets 5 V. The switch is a [[power-switch-board-with-2pin-xh2-54-connector-xa007|power switch board]].

## The wiring, drawn

These are cut from the Excalidraw drawing in the build notes (`guide/excalidraw.py` renders them). They are working sketches, drawn while wiring: the wires run as drawn, not as a schematic would. Where a drawing and the Klipper config disagree, the config is the one that runs, and the text says so.

<figure class="diagram"><a href="/img/drawings/wiring-overview.webp"><img src="/img/drawings/wiring-overview.webp" alt="Wiring overview"></a><figcaption>The overview. Top: the Pi's header, with the MCP23017 and the PN532 on its I2C pins (green), and USB down to the three MCUs. Middle: the Klipper MCU (an RP2040) and the Melzi. Bottom: the Limn MCU (the Dock), its power switch to the bed connector, the probe OR gate, and the toolhead harness.</figcaption></figure>

## The Melzi

The Melzi came with the donor printer. It's a Sanguinololu-style board: an ATmega AVR and four A4982 drivers, run at 12 V.

- **Which port drives what.** From `klipper/printer.cfg`:

| Melzi port | Klipper | Drives |
|---|---|---|
| E | `stepper_x` | CoreXY motor A |
| Y | `stepper_y` | CoreXY motor B |
| X | `stepper_z` | Z, the [[nema-8-ali]] on its lead screw |
| Z | `manual_stepper axis_k` | K, the tool lock ([[5mm-stepper-slider]]) |

- **Z and K run on 5 V.** The small motors (first the SRM1509, then the 5 mm linear stepper and the NEMA 8) got too hot on 12 V, and lowering VREF only made them stall. So the 12 V trace to those two drivers is cut, and they get 5 V from outside.
- **VREF**: `V_REF = I × 8 × R_SENSE`, with R_SENSE = 0.11 Ω. That's 0.616 V for the 0.7 A NEMA 17s and 0.352 V for the 0.25 A small motors. Measure it between the driver's trimmer and GND while turning the trimmer, with the board powered. Pololu's [A4988 carrier page](https://www.pololu.com/product/1182) explains current limiting well (its section *Current limiting*). The A4982 on the Melzi works the same way.
- [!] Disconnect the steppers before turning the trimmers.

- **The Z port is built for two motors** (a printer's dual Z). Its two headers are wired in series: one coil runs out through the first motor and back, then on to the second. With only one motor, that motor has to close the loop across both headers: pins as `{a x c x}` on one header and `{x b x d}` on the other. The middle wires swap between the SRM1509 and a NEMA. The Melzi's [design files](https://github.com/reprappro/melzi) (linked from the [RepRap wiki](https://reprap.org/wiki/Melzi)) show the Z headers.

- **No microstepping on Z.** The driver is hard-wired for 16 microsteps, but the AVR can't make steps fast enough for that on the lead screw. So Klipper runs Z at `microsteps: 1`, and `rotation_distance: 0.03125` (the M3 screw's 0.5 mm pitch over 16).
- [i] The bootloader was updated on 2026-02-22. It didn't fix the random restarts.

<figure class="diagram"><a href="/img/drawings/melzi-a4982-srm1509.webp"><img src="/img/drawings/melzi-a4982-srm1509.webp" alt="A4982 driver to the SRM1509"></a><figcaption>One of the Melzi's A4982 drivers (its schematic, and the datasheet's bridge) to the SRM1509's coils. The wire colours, motor to cable: 1 orange–white, 2 yellow–green, 3 brown–yellow, 4 black–blue.</figcaption></figure>

## The EXT header

The Melzi's 10-pin EXT header (JP16) carries everything that isn't a motor or an endstop:

| Pin | Klipper | Goes to |
|---|---|---|
| A1 | | the WLED strip, in the first wiring |
| A2 | `^PA2` | the K axis endstop (`axis_k`) |
| A3 | `PA3` | BLTouch control |
| A4 | `^PA4` | BLTouch sensor, through the OR gate |
| SDA, SCL, TX, RX | | drawn for I2C and the buzzer in the first wiring; unused by today's config |
| 9, 10 | | VCC, GND |

<figure class="diagram"><a href="/img/drawings/wiring-melzi-ext.webp"><img src="/img/drawings/wiring-melzi-ext.webp" alt="The EXT header, and what the first wiring put on it"></a><figcaption>The EXT header, and what the first wiring put on it.</figcaption></figure>

- [i] An older drawing had A3 and A4 the other way round. `[bltouch]` in `printer.cfg` has the sensor on PA4 and the control on PA3.

## The toolhead harness

21 wires run in the drag chain from the electronics bay to the toolhead: the Z and K motors, the Y, Z and K endstops, the BLTouch, and the MPU9250.

<figure class="diagram"><a href="/img/drawings/wiring-toolhead.webp"><img src="/img/drawings/wiring-toolhead.webp" alt="The toolhead side: probe signals, the Z and K motors, the endstops, the harness's pins"></a><figcaption>The toolhead side: probe signals, the Z and K motors, the endstops, the harness's pins.</figcaption></figure>

- The harness pins, as drawn: 1 3V3/5V, 4 stepper Z, 5 limit Z, 6 limit Y, 7 5V, 8 GND. On the tool side: 1 3V3/5V, 5 stepper K, 6 GND, 7 switch, 8 1-Wire.
- The endstops are micro switches: Y, Z top and the K lock. The build notes list two kinds, KFC-W-13W and KFC-C-15A.
- The **MPU9250** (an MPU9255, in fact) is for input shaping. Klipper's ADXL345 support wants SPI, and the Pi's I2C was simpler, so the MPU went on the `rpi` MCU's I2C instead (2026-04-11).

## The probe OR gate

The BLTouch and the calibration beds both have to stop a probe move, and Klipper has one probe input.

- A small OR gate made of two NPN transistors. Its inputs are the BLTouch's signal and the Dock's `PIN_PROBE_OUT` (GPIO 11). Its output goes to the probe pin (A4).
- Both inputs are short pulses: the BLTouch gives about 10 ms on trigger, and the Dock pulses for 10 ms (3.3 V) when a bed reports a touch. The first version was a CYD board, and it did the same.
- So `PROBE` and `BED_MESH_CALIBRATE` stop on either one, with no changes to Klipper. The touch on the bed works just like a BLTouch.
- [?] A photo of the gate as built.

## The tool holders' switches

- Each of the 5 holders in the [[limn-export-42-tool-dock]] has a micro switch: is there a pen in it or not.
- The switches go to an [[mcp23017-adafruit]] at `0x20` on the Pi's I2C bus 1. Pins to holders, from `[limn]` in `klipper/limn.cfg`:

| MCP23017 pin | 15 | 14 | 13 | 12 | 11 |
|---|---|---|---|---|---|
| Holder | 41 | 42 | 45 | 43 | 44 |

- Klipper's `limn` extension reads them (`TOOL_HOLDERS`, `TOOL_HOLDER_CHECK`).
- [i] Klipper's user has to be in the `i2c` group.

## The tag reader

- The PN532 sits in the [[limn-nfc]], on the same I2C bus (`tool_holder_tag_address: 0x24`).
- Hold a pen to the reader until it beeps, then put it into a holder within 8 s. That holder now has that pen.
- [i] It's wired for I2C. OpenSpools, which reads spool tags, wants SPI, so its code couldn't be reused.
- The tags are NTAG. The offsets live on their own pages: 6 for X, 7 for Y, 8 for Z, and 11–16 for the label.
- [?] Soldering: the PN532's I2C mode jumpers, the cable to the Pi.

## The calibration beds

A bed is a detachable plate with a [[resistive-touch-panel]] or an [[fsr-32-zones]] on it, each read by an [[rp2040-tiny-v1-1]] running MicroPython. It connects through 5 [[magnetic-pogo-pins-connector|magnetic pogo pins]]: power, GND, DETECT, TX and RX.

<figure class="diagram"><a href="/img/drawings/wiring-beds.webp"><img src="/img/drawings/wiring-beds.webp" alt="The calibration beds: the FSR's FFC pins, the touch panel's four wires, the bed MCUs and their chain to the connector"></a><figcaption>The calibration beds: the FSR's FFC pins, the touch panel's four wires, the bed MCUs and their chain to the connector.</figcaption></figure>

- **FSR**: 8 columns driven (`FSR_X = [10, 9, 12, 11, 8, 13, 14, 15]`) and 4 rows read on the ADCs (`fsr_y = [29, 28, 26, 27]`, or `[29, 28, 27, 26]` on BED_3). The sheet's 12-pin FFC goes through a 0.5 mm FFC breakout, sanded thin to fit in the 3.2 mm bed.
- **Touch panel**: X+, X−, Y+, Y− on GPIO 28, 26, 27, 29.
- **The chain**: Dock → bed MCU → bed MCU over UART. Coordinates, FSR frames, logs and firmware updates all go up and down it (`micropython/STRATEGY.md`).

![The first FSR bed wired up, on the bench](/img/notes/bed-fsr-wiring.webp)

## Power to the bed

The pogo pins make noise as they connect, and they shouldn't carry power while nothing is on them. So the Dock only powers a bed once it knows one is there.

<figure class="diagram"><a href="/img/drawings/wiring-bed-power.webp"><img src="/img/drawings/wiring-bed-power.webp" alt="The Dock's RP2040-Zero, the Pololu power switch, the connector and the bed's board"></a><figcaption>The Dock's RP2040-Zero, the Pololu power switch, the connector and the bed's board.</figcaption></figure>

- DETECT has a 10 k pull-up on the Dock. Each bed has its own ID resistor to GND, and the Dock reads it on GPIO 29 (ADC).
- When the same bed ID has read steadily for long enough, the Dock switches a Pololu power switch on (GPIO 8). It switches it off (GPIO 7) when DETECT reads "no bed" for 250 ms.
- [i] The Pololu switch turns itself on after a power cycle.
- **Touch line**: each bed MCU has a Schottky diode from GPIO 2 (or 3) to DETECT. On a touch it lifts DETECT above every bed ID (about 3.0 V). The Dock sees that edge and pulses the probe gate. It's faster than sending the touch over UART, which made the probe overshoot by about 0.7 mm.
- [?] The diodes aren't fitted on every bed yet (`notebooks/stack.md`).

## Plans on paper

Two drawings for parts that aren't built yet.

**Power and data to the tool.** The v88 toolchanger head has 4 pogo pins to the tool. In this drawing an RP2040-Zero switches 5 V to the tool through a second Pololu switch, and talks UART over the other two pins. It reads the lock with a [[qre1113-line-sensor]] (ADC 3) and has the MPU on its I2C.

<figure class="diagram"><a href="/img/drawings/wiring-tool-link.webp"><img src="/img/drawings/wiring-tool-link.webp" alt="The toolhead MCU, the lock sensor, and the four contacts to the tool"></a><figcaption>The toolhead MCU, the lock sensor, and the four contacts to the tool.</figcaption></figure>

**The BLTouch as a tool.** The bed sensors sit under the docked tools, where the BLTouch on the head can't reach them all. Another way: dock a BLTouch like a pen, with an [[rp2040-tiny-v1-1]] in it. The coupling only has three contacts (3 V, GND and 1-Wire), so the probe signal would go over IR, between an LED and a receiver.

<figure class="diagram"><a href="/img/drawings/wiring-bltouch-tool.webp"><img src="/img/drawings/wiring-bltouch-tool.webp" alt="A BLTouch tool: its coupling contacts, an RP2040-Tiny, an IR LED and receiver"></a><figcaption>A BLTouch tool: its coupling contacts, an RP2040-Tiny, an IR LED and receiver.</figcaption></figure>

**Telling a tool is there.** Before the holder switches, the coupling's own contacts were going to tell. The tool's side bridges two of its three screws with a wire ([log #4](/log/2026-04-09-detecting-tools-tool-parameters-slicing.html)), which pulls DET to GND through a resistor. The sketch also has a light sensor across GND and 3V3, like the reflective sensor that now watches the lock.

<figure class="diagram"><a href="/img/drawings/wiring-coupling-detect.webp"><img src="/img/drawings/wiring-coupling-detect.webp" alt="The coupling's contacts as a presence sensor"></a><figcaption>The coupling's three contacts, GND, DET and 3V3: resistors, and a light sensor.</figcaption></figure>

## Power budget

From the build notes, before the beds were added:

| | V | Min | Max | Notes |
|---|---|---|---|---|
| Pi 4 | 5 | 1.8 A | 3 A | 1.2 A of it for accessories and USB |
| Melzi | 12 | | | the motors |
| BLTouch | 5 | 20 mA | 300 mA | |
| MG90 servo (the first pen lift) | 5 | 220 mA | 250 mA | |

![The buzzer: a 2N7000 switching it from a GPIO](/img/notes/buzzer-circuit.webp)
