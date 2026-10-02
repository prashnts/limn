# Limn in CAD: v6 → v11 → v46 → v88

Four Fusion exports (`~/limn-shot/Limn-Export-42 v*.step`), compared design by design with
`guide/stepdiff.py`. That script matches designs by name, then compares count, place and shape (bodies + faces
by surface type). Renders of each stage are in `compare/`.

| Export | Date | Size |
|---|---|---:|
| v6 | 2026-04-24 18:11 | 152 MB |
| v11 | 2026-04-24 18:21 | 152 MB |
| v46 | 2026-08-03 22:45 | 87 MB |
| v88 | 2026-10-01 23:57 | 95 MB |

![The whole machine, v11 / v46 / v88](compare/limn.png)

## v6 → v11: colours only

Same parts, same shapes, ten minutes apart. Only some of the appearance assignments (`STYLED_ITEM`) differ.

## v11 → v46 (April → August): sensing, a new UI, the camera rethought

- **The camera moved.** The Pi Camera 3 swivel on its KevStand arm (`Limn-Camera-V3`, the hinge parts, the
  NeoPixel ring, the lens plate) is gone. An ArduCam UB0240 USB webcam took its place, in a new
  `Limn-Camera-Y-Endstop` on the right axis: camera and Y endstop in one part.
- **An LED UI.** New `Limn-LED-UI`: a Pimoroni Unicorn pHAT in `Limn-UI-Case`, with a two-part diffuser
  (`Diffused`, `LED-blocker`) and an icon mat (`Diffuser`, `Icons`, multi-colour). The WS2812B strip and
  `Limn-wled-bottom` left the tool LED indicators.
- **The calibration bed.** New `Limn-Export-42_Paper-Bracket` under the bed: `Limn-Calibration-Base`, a resistive
  base, a CYD 2.8" display (ESP32), a magnetic pogo connector, and `Limn-Touch-probe-Connector-Body` on the bed.
- **The paper sliders became bumpers:** `Limn-Bumper-Left/Middle/Right`.
- **Cable ducts got covers** (`Limn-Duct-Cover`, `-2`). The drag chain went from 4 links to 13.
- **Belts modelled properly:** Belt-A is two bodies plus a `Belt-Movable`; v11's Belt-A was one odd body.
- **Tools:** a sixth key and `ActiveTool` (a Stabilo pen in the toolhead, to show a docked tool), and 4
  `Limn-Tool-Plate-Spacer`s under the keys.
- **Gone from the model:** the Waveshare CM4-NANO-B + CM4 in `Limn-CM4-Case`. The Hackaday list now says a
  Raspberry Pi 4. The Aux-PCB (Pico W, LM2596, buzzer) is missing from v46 but back in v88: most likely hidden at
  export.

## v46 → v88 (August → October): the toolchanger lock, probes, a dock that knows

- **Toolchanger lock redone** (`plot-lock`). The lock gear and pin (`Plot-Lock-Gear-Ass`, `plot-lock-pin`,
  three self-tapping screws) are replaced by `K-Gear`, a `K-Pin` (cap + bottom), a `2x12 K-Dowel` and a
  **QRE1113 line sensor** to see the lock. `plot-toolch-base` and `Plot-Extruder-Cover` were reshaped
  around them.
- **Pogo pins to the tool:** four 5 mm pogo pins in the toolchanger head (data to the tool).
- **More on the Z rider:** a **VL53L5X ToF** sensor (`TOF-Holder`), a `Scope Holder` for the endoscope, and on the
  toolhead an `Endoscope Shim` and an `LED Light Shim`.
- **The dock senses tools:** each of the 5 `Plot-Tool-Dock-Item`s now holds a micro switch (reshaped, wider), and
  an **MCP23017** reads them. New `Dock Base` (`DockBase2mm`, `limn-middle-holder2`). The tools carry their keys
  inside their own assemblies now. `ActiveTool` and the pen are gone.
- **Calibration bed, second take:** an **FSR 32-zone** array with a 12-pin FFC adapter, two **RP2040-Tiny**, and a
  `Resistive Touch Panel` instead of the resistive base. `Limn-Calibration-Base` and the touch-probe connector were
  reshaped to fit.
- **Removed:** the hinged KlipperScreen (the screen, `Limn-KlipperS-Hinge-Bearing`, spring shoes, 3 magnets), the
  bed LED plates A/B, `Limn-Z42-Top-Cover`, and the ArduCam from the Y endstop. `Limn-Camera-Y-Endstop` got
  smaller.
- **New, unnamed:** `Composant1318` (`Cam-Base` + `Cam-Conn`) at the top level. Its name is Fusion's default
  (French): worth renaming before publishing.

## Worth fixing before Printables

- Generic names: `Component4/5/6` and `cat` (the inlays on the tool brackets), `Composant1318`, `end`
  (the QRE1113). Their file names come from their assembly (`plot-tool-bracket-component5`).
- `limm-klipper-pi` (`Limn-CM4-Case`) has no bodies in v88, so no case is exported.
- Some components' names and design names disagree (`Limn-Paper-Slider-Left` is design `Limn-Bumper-Left`). The
  files use the design's name.
- The Hackaday list and v88 disagree on a few counts: 3 RP2040 (CAD: 2 RP2040-Tiny), the M2.5x5 coupling screws
  and the magnets (not in the CAD). See `guide/components.toml`.

---

## The raw diff (`guide/stepdiff.py v11 v46 v88`)

Sizes in this listing come from the STEP's points, surface origins included, so they're rough. `parts.csv`
measures the meshes instead.


# Limn-Export-42 v11 → Limn-Export-42 v46

## Added (27)

- ActiveTool  in Limn-Export-42
- ArduCam UB0240 webcam (bought)  in Limn-Camera-Y-Endstop
- Belt-A-2  in Belt-A
- Belt-Movable  in Belt-A
- CYD 2.8 USB C (bought)  in Limn-Export-42_Paper-Bracket
- Diffused  in Limn-UI-LED-diffuser
- Diffuser  in Limn-UI-2-Mat
- Icons  in Limn-UI-2-Mat
- LED-blocker  in Limn-UI-LED-diffuser
- Limn-Bumper-Left  in Limn-PCB-Bumper
- Limn-Bumper-Middle  in Limn-PCB-Bumper
- Limn-Bumper-Right  in Limn-PCB-Bumper
- Limn-Calibration-Base  in Limn-Export-42_Paper-Bracket
- Limn-Camera-Y-Endstop  in Limn-Axis-Right-Pulleys
- Limn-Duct-Cover  in Limn-Cable-Duct - Left
- Limn-Duct-Cover-2  in Limn-Cable-Duct - Right
- Limn-Export-42_Paper-Bracket  in Plotter-Bed
- Limn-LED-UI  in Limn-LED-UI-Conn
- Limn-LED-UI-Conn  in Limn-Extras
- Limn-Tool-Plate-Spacer ×4  in Limn-ToolHead-Key-Basic
- Limn-Touch-probe-Connector-Body  in Plotter-Bed
- Limn-UI-2-Mat  in Limn-LED-UI
- Limn-UI-Case  in Limn-LED-UI
- Limn-UI-LED-diffuser  in Limn-LED-UI
- Magnetic Pogo Pins Connector (bought)  in Limn-Export-42_Paper-Bracket
- ResistiveBase (bought)  in Limn-Export-42_Paper-Bracket
- Unicorn PHAT  in Limn-LED-UI

## Removed (35)

- Adafruit neopixel ring (bought)  from Pi-Cam-3--Swivel
- ball-joint-base (bought)  from Pi-Cam-3--Swivel
- Camera Moudule 3 (bought)  from Pi-Cam-3--Swivel
- Clip-Bot  from KevStand-Base
- Clip-Top  from KevStand-Base
- Component112  from Plot-Dock-Base-2
- FFC (bought)  from Limn-CM4-Case
- KevStand-Base  from Limn-Camera-V3
- KY-006 Buzzer (bought)  from Limn-Aux-PCB
- Limn-A5-Paper-Frame-Base  from Paper-Bracket
- Limn-Aux-PCB ×2  from Limn-Aux-PCB, Limn-Extras
- Limn-Cam-Hinge-Part  from Limn-Camera-V3
- Limn-Cam-Holder-Hinge  from Limn-Camera-V3
- Limn-Camera-V3  from Limn-Extras
- Limn-CM4-Case-F  from Limn-CM4-Case
- Limn-Paper-Slider-Left  from Limn-PCB-Bumper
- Limn-Paper-Slider-Right  from Limn-PCB-Bumper
- Limn-PicoWBase  from Limn-Aux-PCB
- Limn-wled-bottom  from Limn-Tool-LED-Indicators
- limn_2_Limn-Screen-Tool-Holder  from Limn-Hinged-Screen
- LM2596_DC-DC_BUCK CONVERTER (bought)  from Limn-Aux-PCB
- M4 Bolt - Coarse thread (bought)  from KevStand-Base
- Optics Lens Threaded Plate (bought)  from Pi-Cam-3--Swivel
- PCBs  from Limn-Aux-PCB
- Perf Board (bought) ×2  from Limn-Aux-PCB
- PH-1x5 Header (bought) ×4  from Limn-Aux-PCB
- Pi-Cam-3--Swivel  from Limn-Camera-V3
- pi-cam-3-swivel-lens-top  from Pi-Cam-3--Swivel
- Pin (bought)  from KevStand-Base
- Raspberry_Pi_Pico_WH (bought)  from Limn-Aux-PCB
- RaspberryPi_CM4 (bought)  from Limn-CM4-Case
- Spring (bought)  from KevStand-Base
- Steel Rod (bought)  from KevStand-Base
- Waveshare CM4-NANO-B (bought)  from Limn-CM4-Case
- WS2812B Small 30 LED (bought)  from Limn-Tool-LED-Indicators

## Reshaped (3)

- Belt-A: bodies 1→2, size 9331.47×422.88×34.87 → 267.04×180.44×6 mm, faces 34→12
- Belt-B: faces 34→24
- Component5: bodies 8→2, size 0.48×13.51×4.95 → 0.4×1.2×25 mm, faces 214→12

## Count (10)

- [F] Limn-plot-tool-object-stabio: 1 → 2
- ChainLink: 4 → 13
- Component4: 2 → 3
- Component5: 3 → 4
- Limn-Tool-Dock-Plate: 5 → 6
- Limn-ToolHead-Key-Basic: 5 → 6
- M3 Carbon Steel Square Nut - AB015: 2 → 1
- M3x25 SHCS Machine Screw - AA041: 4 → 3
- M3x5 BHCS Machine Screw - AA171: 13 → 15
- Plot-Tool-Bracket-Stabilo: 1 → 2

## Moved (6)

- [F] Limn-plot-tool-object-stabio: Tool-Dock → ActiveTool, Tool-Dock
- Belt-B: Limn → Belt-A
- Limn-ToolHead-Key-Basic: Tool-Dock → ActiveTool, Tool-Dock
- M3 Carbon Steel Square Nut - AB015: Limn-Camera-V3, Limn-Z-Axis-Motor → Limn-Z-Axis-Motor
- M3x25 SHCS Machine Screw - AA041: Limn-Belt-Tensioner, Limn-Camera-V3, Limn-Hinged-Screen → Limn-Belt-Tensioner, Limn-Hinged-Screen
- PEN Stabilo: Limn-Export-42 → ActiveTool


# Limn-Export-42 v46 → Limn-Export-42 v88

## Added (32)

- 2x12 K-Dowel  in plot-lock
- Cam-Base  in Composant1318
- Cam-Conn  in Composant1318
- Composant1318  in Limn-Export-42
- Dock Base  in Plot-Dock-Base-2
- DockBase2mm  in Dock Base
- Endoscope Shim  in Limn-ToolHead
- FFC Adapter 12p (bought)  in Limn-Export-42_Paper-Bracket
- FSR 32 Zones (bought)  in Limn-Export-42_Paper-Bracket
- K-Gear (bought)  in plot-lock
- K-Pin  in plot-lock
- K-Pin-Bot (bought)  in K-Pin
- K-Pin-Cap (bought)  in K-Pin
- KY-006 Buzzer (bought)  in Limn-Aux-PCB
- LED Light Shim  in Limn-ToolHead
- Limn-Aux-PCB ×2  in Limn-Aux-PCB, Limn-Extras
- Limn-Export-42_Tool-Dock  in Limn
- limn-middle-holder2  in Dock Base
- Limn-PicoWBase  in Limn-Aux-PCB
- LM2596_DC-DC_BUCK CONVERTER (bought)  in Limn-Aux-PCB
- MCP23017 Adafruit (bought)  in Limn-Export-42_Tool-Dock
- PCBs  in Limn-Aux-PCB
- Perf Board (bought) ×2  in Limn-Aux-PCB
- PH-1x5 Header (bought) ×4  in Limn-Aux-PCB
- Pogo Pin 5mm (bought) ×4  in Limn-Toolchanger-Head
- QRE1113 Line sensor (bought)  in plot-lock
- Raspberry_Pi_Pico_WH (bought)  in Limn-Aux-PCB
- Resistive Touch Panel (bought)  in Limn-Export-42_Paper-Bracket
- RP2040-Tiny V1.1 (bought) ×2  in Limn-Export-42_Paper-Bracket
- Scope Holder  in Limn-Z-Axis-Rider
- TOF-Holder  in Limn-Z-Axis-Rider
- VL53L5X TOF (bought)  in Limn-Z-Axis-Rider

## Removed (18)

- 3x4 mm - FB002 (bought) ×3  from Limn-Hinged-Screen
- [F1] Limn-KlipperS-Hinge-Bearing  from Limn-Hinged-Screen
- ActiveTool  from Limn-Export-42
- ArduCam UB0240 webcam (bought)  from Limn-Camera-Y-Endstop
- BT2.5x5 SHCS Self Tapping Screw - AA195 (bought)  from plot-lock
- BT2x5 SHCS Self Tapping Screw - AA191 (bought) ×2  from plot-lock
- KlipperScreen (bought)  from Limn-Hinged-Screen
- Limn-Bed-LED-Plate-A  from Limn-LEDs
- Limn-Bed-LED-Plate-B  from Limn-LEDs
- Limn-Hinge-Spring-Shoe-A  from Limn-Hinged-Screen
- Limn-Hinge-Spring-Shoe-C  from Limn-Hinged-Screen
- Limn-Hinged-Screen  from Limn-Bottom-Middle
- Limn-Z42-Top-Cover  from Limn-Y-Axis
- PEN Stabilo (bought)  from ActiveTool
- Plot-Lock-Gear-Ass  from plot-lock
- plot-lock-pin  from plot-lock
- ResistiveBase (bought)  from Limn-Export-42_Paper-Bracket
- Tool-Dock  from Limn

## Reshaped (7)

- Component5: bodies 2→8, size 0.4×1.2×25 → 0.48×13.51×4.95 mm, faces 12→214
- Limn-Calibration-Base: size 183.1×242×13.24 → 185×242×27.94 mm, faces 2178→2162
- Limn-Camera-Y-Endstop: size 66.93×84.38×38.84 → 43.04×76.53×36.49 mm, faces 304→234
- Limn-Touch-probe-Connector-Body: size 42.5×36.9×5.06 → 42.5×42.9×5.06 mm, faces 163→169
- Plot-Extruder-Cover: size 12.19×35.1×31.18 → 12.19×35.1×38.24 mm, faces 216→241
- Plot-Tool-Dock-Item: size 28.15×200×31.12 → 30.61×200×31.25 mm, faces 91→139
- plot-toolch-base: size 15.27×44.17×38.19 → 13.37×46.16×42.23 mm, faces 438→583

## Count (9)

- [F] Limn-plot-tool-object-stabio: 2 → 1
- Component4: 3 → 2
- Component5: 4 → 3
- Limn-Tool-Dock-Plate: 6 → 5
- Limn-ToolHead-Key-Basic: 6 → 5
- M3x25 SHCS Machine Screw - AA041: 3 → 2
- M3x5 BHCS Machine Screw - AA171: 15 → 13
- micro-limit-sw-inline: 1 → 6
- Plot-Tool-Bracket-Stabilo: 2 → 1

## Moved (10)

- [F] Limn-plot-tool-object-stabio: ActiveTool, Tool-Dock → Limn-Export-42_Tool-Dock
- [F] Limn-plot-tool-object-staedtler: Tool-Dock → Limn-Export-42_Tool-Dock
- Limn-Laser-Pointer-Tool: Tool-Dock → Limn-Export-42_Tool-Dock
- Limn-ToolHead-Key-Basic: ActiveTool, Tool-Dock → Limn-Laser-Pointer-Tool, Plot-Cutter-Tool, Plot-Tool-Bracket, [F] Limn-plot-tool-object-stabio, [F] Limn-plot-tool-object-staedtler
- M3x25 SHCS Machine Screw - AA041: Limn-Belt-Tensioner, Limn-Hinged-Screen → Limn-Belt-Tensioner
- micro-limit-sw-inline: Limn-Toolchanger-Head → Limn-Toolchanger-Head, Plot-Tool-Dock-Item
- Plot-Cutter-Tool: Tool-Dock → Limn-Export-42_Tool-Dock
- Plot-Dock-Base-2: Tool-Dock → Limn-Export-42_Tool-Dock
- Plot-Tool-Bracket: Plot-Cutter-Tool, Tool-Dock → Limn-Export-42_Tool-Dock, Plot-Cutter-Tool
- Plot-Tool-Dock-Item: Tool-Dock → Limn-Export-42_Tool-Dock

