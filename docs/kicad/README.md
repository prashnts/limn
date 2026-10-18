# Limn: the electronics in KiCad

A KiCad 9 project, `limn.kicad_pro`. The root sheet is the overview, with one sheet per role:

| Sheet | File | What's on it |
|---|---|---|
| Power | `power.kicad_sch` | The USB-C PD charger, the 12 V (motion, switched) and 9 V triggers, the LM2596 for Z/K, MP_Buck0 (MP1495, the LEDs); MP_Buck1 moved to sheet Plot head cell |
| Host (Pi 4) | `host.kicad_sch` | The Pi 4, its USB fan-out (FE1.1s hub, planned), a camera, I2C1 |
| Tool dock | `tool_dock.kicad_sch` | The MCP23017 and the 5 holder switches, the PN532 tag reader, the indockator strip |
| Melzi (motion) | `melzi.kicad_sch` | The Melzi, motors A/B, the X endstop, the EXT header, the OR gate (going), the plot bed's pull-up |
| Toolhead | `toolhead.kicad_sch` | Z and K, the Y/Z/K endstops, the BLTouch (gone), the MPU9250, the endoscope, the coupling and a toolhead MCU (planned) |
| Aux MCU (rpi) | `aux.kicad_sch` | The Pico WH on the Aux PCB: the NeoPixels, the buzzer, the MPU9250's I2C |
| Bed dock (LRT Dock) | `bed_dock.kicad_sch` | The RP2040-Zero, DETECT, the bed's power switch, the pogo connector |
| Calibration bed | `cal_bed.kicad_sch` | The bed's ID resistor, the RTP node and panel (going), the FSR node, sheet and loads, the touch diodes (planned) |
| Plot bed (load cells) | `plot_bed.kicad_sch` | The Pro Micro, both ADS1220 modules, the three feet, filters, the sum, the touch line ([load-cell.md](../load-cell.md)) |
| Plot head cell (load cell) | `plot_head.kicad_sch` | The two-strip cell (4 BF350s, one full bridge closed on pads on HS), CAT6 through the chain (orange = E, blue = S, green = the tool's ID, brown = an LED on the head) to the plot bed board at the back: one ADS1220, the touch line, the tool's ID line (detect) and its 5 V switch + polyfuse (from MP_Buck1, `+5V_BUCK1`). `+3V3_PH`: the same board as built for the head cell; the tool's 5 V buck (MP_Buck1, a mini 3 A module, U955) |

How to read it:
- **Sheets meet through global labels** (`USB_*`, `I2C1_*`, `MOT_*`, `ENDSTOP_*`, `PROBE_*`, `BED_*`, ...) and **named power rails** (`+12V`, `+7V5_ZK`, `+9V`, `+5V_LED`, `+5V_TOOL`, `+5V_BUCK1`, `+5V_MELZI`, `+3V3_PI`, `+3V3_AUX`, `+3V3_PB`, `+3V3_PH`). All GND is one net.
- **Solid boxes**: one board or assembly. **Dashed boxes**: planned, or going; their parts are DNP.
- **Boards are blocks** with the pins Limn uses, named as the code names them. The Pro Micro is drawn with its full header in physical order. A USB link is one pin (the cable).
- **References per sheet**: power 1xx, host 2xx, tool dock 3xx, Melzi 4xx, toolhead 5xx, Aux 6xx, bed dock 7xx, calibration bed 8xx, plot bed 9xx (the head cell 95x).
- Wires turn at 45°.

Gathered from the code and the docs on 2026-10-16: `notebooks/pinout.md`, `micropython/nodes/*.json`, `klipper/*.cfg`, `projects/limn/content/electronics.md`, `docs/block-diagrams.md`, `docs/load-cell.md`, `TODO.md`.

## Regenerating

```
python3 docs/kicad/gen.py --force --check
```

`kicad_gen/` holds the drawing code: `core.py` (the writer, wires, labels, enclosures), `boards.py` (the blocks), `sheets_a.py` / `sheets_b.py` (one function per sheet). `--check` runs ERC, `audit.py` (a net joining two signal pins of one part: the shorts ERC can't see between passive pins) and writes one SVG per sheet into `svg/`. Today: ERC 0 errors 0 warnings, audit ok.

Footprints: *Plot head cell* has them (perfboard: SMD in 1206, which bridges two 2.54 mm pads; the modules in `limn.pretty`, written by `kicad_gen/footprints.py`, listed in `fp-lib-table`). The other sheets don't yet.

Once the schematic is edited in KiCad, regenerating overwrites the edits: don't, or move the change into the generator first.

## To fill in

- [ ] The toolhead harness's connector: which wire on which pin (the Excalidraw drawing has only some).
- [ ] The pogo connector's pin order (power, GND, DETECT, TX, RX).
- [ ] The cameras on the Pi: which is on which port, and which devices are on the hub vs straight on the Pi today.
- [ ] The bed's power switch: its Pololu model and where its VIN comes from (the Dock's 5 V?).
- [ ] The buzzer circuit: gate resistor, supply, flyback diode.
- [ ] The Pico's VSYS (USB only, or the Aux PCB's LM2596 through a diode?), and where the MPU9250 gets its VCC.
- [ ] The MCP23017 breakout's RST pin.
- [x] The ADS1220 module's header order: from the photo (2026-10-18), DIP numbering, top view; footprint `limn:ADS1220_module`.
- [ ] The Pololu Mini MOSFET Slide Switch's pad map (U953 on Plot head cell has no footprint yet).
- [ ] The FSR board's series resistors on the rows (values).
- [ ] The Melzi's endstop headers (2 or 3 pins), and whether the BLTouch and the OR gate are already out.
