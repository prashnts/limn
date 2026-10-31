# Limn: the electronics in KiCad

A KiCad 9 project, `limn.kicad_pro`. The root sheet is the overview, with one sheet per role or board:

| Sheet | File | What's on it |
|---|---|---|
| Power | `power.kicad_sch` | The USB-C PD charger, the 12 V (motion, switched) and 9 V triggers. The bucks sit on their boards: LM_Buck0 by the Melzi, MP_Buck0 on the Aux PCB, MP_Buck1 on the hub board |
| Host (Pi 4) | `host.kicad_sch` | The Pi 4, its USB ports (the hub board on USB-A 3), a camera, I2C1 |
| Tool dock | `tool_dock.kicad_sch` | The MCP23017 and the 5 holder switches, the PN532 tag reader, the indockator strip |
| Melzi (motion) | `melzi.kicad_sch` | The Melzi, motors A/B, the X endstop, the EXT header, the OR gate (going), the plot bed's pull-up, LM_Buck0 (LM2596: +7V5_ZK, the motors only) |
| Toolhead | `toolhead.kicad_sch` | A2. The toolchanger as a PCB of its own (refs 50x, `toolhead_board.kicad_pcb`): the coupling (3 screws 5 V/GND/ID, 4 pogo pins D+/D-/GND/ID), the K lock's motor on 4 pogo pins, its key switch, the cell's pads (J501), 10 uF + 100 nF + an LED on +5V_TOOL, the FFC on an FPC-20P breakout (U506). The FFC (20P 0.5 mm, <= 15 cm) to a second breakout on the axis (U507, wired, no PCB): the USB-C cable to the hub board (W501, 5k1 on CC), CAT6 to LIT, the K ribbon to the Melzi. The axis: Z, the Y/Z endstops, the MPU9250, the endoscope, the BLTouch (gone). The FFC pinout and the tool classes in its notes |
| Aux MCU (rpi) | `aux.kicad_sch` | The Aux PCB, next version: a Waveshare RP2040-Zero (Klipper rpi) on the hub's DN4 (data only), MP_Buck0 (9 V to +5V_LED: the Zero, the LEDs, the buzzer), the buzzer, the MPU9250's I2C; the LEDs off the board |
| Calibration bed | `cal_bed.kicad_sch` | The bed's ID resistor, the FSR node (GP0 BED_DATA, GP2 BED_PROBE) and its 4 x 8 sheet with the row loads |
| Plot bed board | `plot_bed_board.kicad_sch` | The board of `limn.kicad_pcb` and what hangs off it (refs 95x, A2). Above: the two-strip cell (4 BF350s, one full bridge; its nets CELL_* on the head side), W951 = CAT6's bridge pairs to the board's rails (so E+/E- stay their own nets on the toolhead PCB), CAT6 through the chain (orange = E, blue = S, white-green = the tool's ID, green = its GND return on J952.6; the browns spare) to the board at the back: one ADS1220, the touch line (Q951, Q952 in series for BED_PROBE), the tool's ID line, LEDs, J957 to the hub board (the hub's DN3: 5 V on RAW, D+/D- on the Pro Micro's pads underneath; GP9 = `TOOL_5V_EN` back; +5V_TOOL_IN for the bed). Below: the bed dock's work, DETECT (GP29), BED_DATA (GP0, half-duplex), BED_PROBE (GP1), two Pololu Mini MOSFET Slide Switches on MP_Buck1 (+5V_TOOL_IN): U956 on GP4 = the bed (BED_PWR, F952), U957 on GP5 = +5V_SW on J959 (the LEDs, spare), J958, and the dock's pogo J701. Its board headers are 1x1s (J952.1, J957.4, ...), one per pin, to place each where its wiring wants |
| Hub board (USB + tool 5 V) | `hub.kicad_sch` | The FE1.1s hub on its own cable from the Pi (Adafruit USB-C breakout; the Pi powers the hub): DN1 the Melzi, DN2 the tool, DN4 the Aux MCU: data only; DN3 the plot bed board, with the hub's 5 V. The tool's 5 V: 9 V in, MP_Buck1, the Pololu switch, a polyfuse, the tool's USB-C cable on a second Adafruit breakout (U1007: +5V_TOOL, DN2) |
| Beam bed (XY) | `beam_bed.kicad_sch` | A detachable bed (refs 85x), its own PCB (`beam_bed_board.kicad_pcb`): a Waveshare RP2040-Tiny, two 940 nm IR LEDs (AO3400, 100R, pulsed from BED_PWR) and two PT1206BS (10k emitter loads into GP26/27) in an L of 15 mm slots; GP0 = BED_DATA (half-duplex UART, one wire), GP1 = BED_PROBE (the trigger, high = OK), DETECT = the ID resistor only. 0805 resistors. Z from the head's load cell |

How to read it:
- **Sheets meet through global labels** (`USB_*`, `I2C1_*`, `MOT_*`, `ENDSTOP_*`, `PROBE_*`, `BED_*`, ...) and **named power rails** (`+12V`, `+7V5_ZK`, `+9V`, `+5V_LED`, `+5V_TOOL`, `+5V_TOOL_IN`, `+5V_HUB`, `+5V_MELZI`, `+3V3_PI`, `+3V3_AUX`, `+3V3_PB`, `+3V3_PH`). All GND is one net.
- **Solid boxes**: one board or assembly. **Dashed boxes**: planned, or going; their parts are DNP.
- **Boards are blocks** with the pins Limn uses, named as the code names them. The Pro Micro is drawn with its full header in physical order. A USB link is one pin (the cable).
- **References per sheet**: power 1xx, host 2xx, tool dock 3xx, Melzi 4xx, toolhead 5xx, Aux 6xx, the dock's pogo 7xx (J701), calibration bed 8xx (the beam bed 85x), plot bed board 95x, hub board 10xx.
- **Set aside** (2026-10-23, not drawn): the bed on three load-cell feet (the old *Plot bed* sheet, refs 90x), the RTP node, a toolhead MCU, the QRE1113 on the toolhead (U954, R961, C957, GP28). Their drawing code is in `kicad_gen/aside.py`, to bring one back as it was.
- Wires turn at 45°.

Gathered from the code and the docs on 2026-10-16: `notebooks/pinout.md`, `micropython/nodes/*.json`, `klipper/*.cfg`, `projects/limn/content/electronics.md`, `docs/block-diagrams.md`, `docs/load-cell.md`, `TODO.md`.

## Regenerating

```
python3 docs/kicad/gen.py --force --check
```

`kicad_gen/` holds the drawing code: `core.py` (the writer, wires, labels, enclosures), `boards.py` (the blocks), `sheets_a.py` / `sheets_b.py` (one function per sheet), `aside.py` (what is set aside). `gen.py` keeps KiCad's settings in `limn.kicad_pro` and only rewrites its sheet list. `--check` runs ERC, `audit.py` (a net joining two signal pins of one part: the shorts ERC can't see between passive pins) and writes one SVG per sheet into `svg/`. Today (2026-10-23): ERC 0 errors 0 warnings, audit ok. R958 fitted (as traced on the PCB), TOUCH_GP on GP2 only.

Footprints: *Plot bed board* has them (perfboard: R and C in 0805 since 2026-10-23, the fuse in 1812; the modules in `limn.pretty`, written by `kicad_gen/footprints.py`, listed in `fp-lib-table`), and so do the three boards of their own below. The other sheets don't yet.

**One PCB per board.** `limn.kicad_pcb` is the plot bed board's (Update PCB from Schematic, F8). Its perfboard's copper is drawn on Dwgs.User between the hole dots (`perfboard.strips`, 2026-10-23): the top and bottom rows one strip each, the 15 rows between joined down each column in 5 groups of 3. The hub board, the Aux PCB and the beam bed are boards of their own; their parts are "not on board" in the schematic (`sheets_b.own_board`), so F8 never puts them on `limn.kicad_pcb`. Their boards are made from the netlist by `tools/mkboard.py hub|aux|beam|head`: the sheet's parts with a footprint, their nets, a first placement (not routed). It never writes over an existing board (`--force` does); open them in the PCB editor on their own (no project of their own, so no F8: a schematic change goes in by hand or a sync like `tools/sync.py`).

| Board | File | What |
|---|---|---|
| Hub board | `hub_board.kicad_pcb` | Perfboard 38 x 17 holes (as the plot bed board's; its strips not drawn yet). The FE1.1s and the USB-C breakout's pad maps are placeholders: map the real boards before soldering |
| Aux PCB | `aux_board.kicad_pcb` | Perfboard 38 x 17. MP_Buck0 drawn as the same mini buck as MP_Buck1; the LEDs (U602/U603) off the board |
| Toolhead PCB | `toolhead_board.kicad_pcb` | Its own project (`toolhead_board.kicad_pro`): the Toolhead sheet drawn again as `toolhead_board.kicad_sch` (gen.py `STANDALONE`), so the board and the schematic link (F8, cross-probing); its global labels dangle there (their other ends are in `limn.kicad_pro`). Edit the generator, not one copy. A PCB, 61 x 50.8 mm for now (a first outline: shape it to the head). The FPC-20P breakout (`limn:FPC20_breakout`, from its photo; its STEP to come), SMD pogo pins D 2.0 x 5 (`limn:Pogo_pin_D2.0_L5.0`), the K motor with its flex on 4 pogos (`limn:Stepper_slider_5mm_flex4`), the key switch (`limn:Micro_limit_sw_inline`), M3 pad holes for the screws, the cell's wires (SolderWire 1x04), 0805. STEPs from the user's models in `limn.3dshapes/` |
| Beam bed | `beam_bed_board.kicad_pcb` | A PCB, 43.2 x 33.0 mm, 1.6 mm (thinner for the bed: set it in Board Setup). 0805, the LEDs/PTs in 1206 (where they go depends on the slots), the pogo as a 1x05 2.54 mm row |

The RP2040-Zero and RP2040-Tiny (same 23 castellated holes, rows 15.24 mm apart) use Waveshare's pin numbers (GP0-15 = 1-16, GP26-29 = 17-20, 3V3 21, GND 22, 5V 23; 24 = the USB), with Waveshare's STEP models in `limn.3dshapes/` (gzipped, `.stpZ`). The library footprints point at KiCad's 3D models (`${KICAD9_3DMODEL_DIR}`): install `kicad-packages3d` to see them.

Once the schematic is edited in KiCad, regenerating overwrites the edits: don't, or move the change into the generator first.

## To fill in

- [ ] The FE1.1s breakout (which board) and its pad map: `limn:FE1.1s_USB_hub_breakout` is a placeholder (U1002).
- [ ] The Adafruit USB-C breakout's pin order (U1001: VBUS, D+, D-, GND in a row for now).
- [ ] The beam bed's pogo: its pitch and pin order (J851: a 1x05 2.54 mm row for now); where the LEDs/PTs sit against the slots; the board's thickness.
- [ ] The toolhead PCB: the K flex pads' pitch and place (3.0 mm past the motor's end, a placeholder), the key switch's tabs (from the model), the screws' size and places, the outline; the breakout's STEP (the user, 2026-10-30).
- [ ] The FFC: same-side or opposite contacts decide 1 -> 1 or 1 -> 20 between the two breakouts: check with a meter before power.
- [ ] The bed pogo connector's pin order (power, GND, DETECT, TX, RX).
- [ ] The cameras on the Pi: which is on which port, and which devices are on the hub vs straight on the Pi today.
- [ ] The buzzer circuit: gate resistor, supply, flyback diode.
- [ ] The Pico's VSYS (USB only, or the Aux PCB's LM2596 through a diode?), and where the MPU9250 gets its VCC.
- [ ] The MCP23017 breakout's RST pin.
- [x] The ADS1220 module's header order: from the photo (2026-10-18), DIP numbering, top view; footprint `limn:ADS1220_module`.
- [ ] The Pololu Mini MOSFET Slide Switch's pad map (U1006 on the hub board).
- [ ] Where the Pro Micro's D+/D- pads are underneath (footprint pads 30/31 are placeholders by the USB-C).
- [ ] `klipper/leds.cfg` for the RP2040-Zero (lamp gpio16 → 14, indockator gpio17 → 13) and the merged Dock/plot bed firmware (dock pins GP29, GP0/1, GP4 = BED_EN, GP5 = SW_5V_EN, high = on; CS2 on GP21, LED_R/LED_G gone).
- [ ] The FSR board's series resistors on the rows (values).
- [ ] The Melzi's endstop headers (2 or 3 pins), and whether the BLTouch and the OR gate are already out.
