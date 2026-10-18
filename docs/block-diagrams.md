## Power Distribution

```nomnoml
#direction: right

// Limn Power - Blocks

[Melzi |
  [StepperA]
  [StepperB]
  [BLtouch]
// note: will be removed when load cell is added ^^
  [MPU9250]
  [OrGate]
]

[LM_Buck0 |
  [StepperZ]
  [StepperK]
]

[MP_Buck0_5V]->[WS2812B_UI_4x8]
[MP_Buck0_5V]->[WS2812B_ToolHolderIndicator]
[MP_Buck0_5V]->[FE11]


[MP_Buck1_5V]->[MosfetSw_ToolCh]->[ToolCh]

[Pi4 |
  [I2C_3v3 |
    [RFIDModule]
    [Adafruit_MCP23017]
  ]
  [USBA |
    [UVCCam0]
    [UVCCam1]
    [FE11_No_VCC]
  ]
  // Possible: DSI LCD 4.5"
]

[FE11 |
    [RP2040_Load_Cell]
    [RP2040_MCU0]
    [Bed_Calibration]
    [Melzi_No_VCC]
]

[Bed_Calibration |
  [RP2040_LRT_Dock |
    [MosfetSw_LRT]
  ]
  [RP2040_FSR]
  [RP2040_RTP]
// note: won't be used anymore and removed ^^
]

[Pi4]->[Bed_Calibration]


// UGreen Nexode 100W GaN USB C supply

[USBC_Pw]->[USBC0_45W]
[USBC_Pw]->[USBC1_30W]
[USBC_Pw]->[USBC2_22.5W]

// Slide switch only here because these are motion components.
// All Power supplies will have an indicator LED.
// Device is meant to be used by experienced users + a switch on AC side can be added. 

[USBC0_45W] -> [Trigger0_12V] -> [SlideSwitch] -> [PW12V]
[PW12V] -> [Melzi]
[PW12V] -> [LM_Buck0]
[USBC2_22.5W] -> [Pi4]
[USBC1_30W] -> [Trigger1_9V] -> [PW9V]
[PW9V] -> [MP_Buck0_5V]
[PW9V] -> [MP_Buck1_5V]

// ToolChanger: 5 V + data only (12 V stays motion-only).
// These are planned:
// [ToolCh] -> [BLTouch]
// [ToolCh] -> [PiZero2W+CamHQ]
// [ToolCh] -> [PointingLaser]
// Tethered (own supply; coupling gives 5 V + EN/PWM only):
// [ToolCh] -> [Small engraving motor]
// [ToolCh] -> [1-3W Laser Diode]

// Note: Melzi -[2k]- RP2040_Load_Cell 
// Note: RP2040_Load_Cell's ADS1220s on their own filtered 3.3V, see below

```

### Load cell: the ADS1220's supply and inputs

The bridges give ~16 µV per 10 g, so the analog side gets its own quiet 3.3 V instead of the RP2040's (USB 5 V is noisy).

- **Supply:** USB 5 V → ferrite bead (~600 Ω at 100 MHz, ≥ 200 mA) → 10 µF ceramic + 47-100 µF → **low-noise LDO** to 3.3 V (LP5907 or TPS7A20 class, ~7 µV rms, SOT-23-5) → 1 µF + 100 nF at each ADS1220's AVDD. This 3.3 V feeds AVDD and the bridges' excitation only; DVDD and the RP2040 stay on the board's own 3.3 V.
- **Load:** 3 half bridges (~700 Ω each) + the completion pair: ~20 mA; 2 × ADS1220 ~0.5 mA each. Any 150 mA+ LDO is plenty.
- **Ratiometric:** excitation also into REFP0 / REFN0, so what's left of the supply's noise cancels (if Klipper's driver can select it; the custom firmware can).
- **Input RC per channel:** 1 kΩ in each leg, 47-100 nF across the pair, 1-4.7 nF from each leg to GND (the leg caps ~10x smaller than the one across, so their mismatch doesn't turn common noise into signal).
- **Ground:** AGND and DGND joined once, under the ADS1220s; the ADS1220s close to the feet, SPI (with ~33-100 Ω series) to the RP2040.
- **Wiring:** [load-cell.md](load-cell.md) (schematic, pins).


### Toolchanger Power: 5 V only (2026-10-15)

The coupling carries **5 V + GND + data, nothing else**. The motor and laser tools bring their own power (tether or battery); the coupling gives them 5 V for their logic and an enable. 12 V stays motion-only.

```nomnoml
#direction: right

[MP_Buck1_5V] -> [MosfetSw_ToolCh] -> [Polyfuse] -> [ToolCh_5V]

[MCU_Dock |
  [GPIO_EN_5V]
  [GPIO_TOOL_EN]
  [GPIO_TOOL_PWM]
  [ToolID_ADC]
  [Lock_Sensor]
]

[GPIO_EN_5V] -> [MosfetSw_ToolCh]

[ToolCh_5V] -> [Tool_5V |
  [BLTouch]
  [PiZero2W+CamHQ]
  [PointingLaser]
]

[ToolCh_5V] -> [Tool_Tethered |
  [Isolator_in]
  [AND_gate]
  [Power_stage]
]
[GPIO_TOOL_EN] -> [AND_gate]
[GPIO_TOOL_PWM] -> [Isolator_in]
[Ext_Supply] -> [Key_or_Lid] -> [Power_stage]
[AND_gate] -> [Power_stage]
```

[!NOTE]
> ToolChanger coupling provides 5V. All other tools such as 5 W laser and milling spindle: always tethered, with their own supply and their own interlock, never through the coupling.
> There's up to 3A 5V available for small tools and cameras.


What changes with it:
- **The 5 V switch: non-latching, off by default.** With one rail the #2808's latch only costs: an MCU crash leaves the tool powered. The Pololu mini MOSFET switch LV (already the bed's) or an eFuse, its control held by a GPIO with a pull-down: MCU reset or crash = tool off. [ ] Check the MOSFET switch is off with its control floating. Then the polyfuse (no current limit in it) and a soft start for the Pi Zero's inrush.
- **The 5 V from the coupling is the tethered tool's interlock.** Its power stage runs only while the coupling's 5 V is there **AND** EN is held high (a level, not a UART command, not a latch). Undocked, 5 V switched off, or the dock MCU in shutdown: off within ms, whatever the external supply does. Klipper: EN an `output_pin` (shutdown value 0), PWM a `pwm` pin (laser power / motor speed); the dock MCU raises EN only for a locked tool whose ID says "external".
- **Isolate EN/PWM in the tool** (optocoupler or digital isolator, its input side on the coupling's 5 V). Otherwise the tether's ground and the coupling's ground form a loop, and if the tether's ground is thin or breaks, the motor's/laser's current comes back through the pogo GND and the chain. Isolated, the two grounds never meet, and the isolator's input side being on the coupling's 5 V is the AND above for free.
- **Laser: a hard cut outside the software.** A key switch or the enclosure lid's switch in series with the external supply (or with EN). 1-3 W at 445 nm is Class 4: enclosure/shield and goggles regardless.
- **Pins**: 5 V, GND, and the 5 data pins: ID (ADC), EN, PWM + 2 spare (UART/I2C, or D+/D- for the Pi Zero's USB gadget; that tool doesn't need EN/PWM).

Tether vs battery:
- **Tether**: preferred for the laser and the motor. The cable stays on the tool when it's parked: route it from above (a boom, a spring retractor) or along the chain, so it doesn't drag on the key or pull the tool in the dock. The bed load cells don't see it (it pulls the carriage, not the bed).
- **Battery**: fine for small loads (pointing laser, a small camera). For the laser or the motor: mass on the head (lower accelerations, a different input-shaper result), charging in the dock (contacts again), and Li-ion beside a laser. Same 5 V + EN rule either way: undocked = off.

[ ] Bench: a tethered dummy tool (LED as the "power stage", opto on EN): pull the tool mid-run, switch the coupling 5 V off, reset the dock MCU: the LED must go off each time.


# Safety and Interlocks

The rule throughout: **anything that can hurt is off unless held on.** Held means a GPIO level, a switch closed, a tool seen and locked. A crash, reset, unplug or power cut must end in the off state, never in the last state.

## Power and electrical

- [x] Power to Pogo Pins is over a Pololu MOSFET Switch and enabled only upon detecting the Calibration Bed.
- [ ] Same for the tool coupling: 5 V only with the tool's ID seen **and** the key locked; non-latching switch, pull-down on its control (see *Toolchanger Power*).
- [x] Low voltage only inside: USB-PD (≤ 20 V), no mains in the machine; the charger is the certified part.
- [ ] A fuse or e-fuse per branch (12 V motion, each 5 V buck, tool 5 V), sized below its wire's rating. A short otherwise trips the whole PD charger: every port off, everything resets.
- [ ] After any power loss or charger cut-out, nothing starts by itself: Klipper comes up idle, tool power off, laser/motor EN low. Test it by pulling the charger mid-plot.
- [ ] Every Klipper pin that powers something: `shutdown_value: 0`, so an MCU or host fault (Klipper's comm timeout puts the MCU in shutdown) turns it off.
- [ ] Batteries in tools (if any): protected cells, charged out of the machine or in the dock only while watched.

## Stopping

- [x] Slide switch on the 12 V motion rail: the motion E-stop.
- [ ] Put it where a hand finds it without looking (front, not behind the electronics bay), labelled.
- [ ] One stop for everything: the same switch (or a second pole) also cuts the tool coupling's 5 V, so a tethered tool's EN drops with the motors. Its own supply's key stays as the second cut.
- [ ] With 12 V cut, check what falls: Z (does the lead screw hold the toolhead?), the K axis, a tool in the key.
- [ ] A software stop button too (Klipper `gcode_button` → `M112`), for the convenient case; never the only one.

## Motion: crush and pinch

- [x] Minimal crush force -- the NEMA8 and 10mm K axis motors have little torque to cause significant injury if a pen crushes on a digit or body. However the XY axes are capable of this.  With the addition of load cells we may detect this. Warning lights are placed on machine already.
  - [ ] Put a number on XY: force ≈ motor torque / pulley radius (e.g. 0.4 N·m on a 20T GT2, r ≈ 6.4 mm: ~60 N). Lower the run current to what the plots need; the motors then stall earlier.
  - [ ] The bed load cells see Z pressing on a finger on the bed (a force well above the pen's 20-40 g with no plan for it → `M112`). They don't see XY pinching against the frame.
  - [ ] Pinch points: the carriage at each axis end against the frame, belts entering pulleys, the key closing on a tool. Guard the pulleys and belt idlers; leave ≥ 25 mm at the ends or cover them.
- [ ] Proximity sensor or TOF array to detect hands -- needs to be distinguished by noise.
  - A VL53L5CX (8x8 zones) or a few VL53L0X across the front, read on the toolhead or dock MCU: pause on a near object that wasn't there at the plot's start (the toolhead's own position is known, so mask it out). Filter: N frames in a row, not one.
  - For plotting a nice-to-have; with the laser, the lid replaces it.

## Tools

- [x] Pen drying warning.
- [ ] Plotting - no special concern. Laser or cutting: air purification necessary.
  - Solvent markers (Posca, permanent) over a long plot: a room with air, not a closed box.
- [ ] Cut injury possible with sharp cutting blade and a usage protocol must be written.
  - The protocol, to start: the blade tool only goes in and out of the machine with its cap on; blade changes off the machine; parked in the dock with the tip shielded; the spring (decided 2026-10-12) limits the force on the paper (and on a finger); spent blades in a sharps tin.
- [ ] Motor (rotary engraving) tool, the next powered one:
  - Glasses on (chips, a broken bit); hair and sleeves away; no gloves near the bit.
  - EN held, not latched (coupling 5 V AND EN, *Toolchanger Power*); undocked or stopped = off. Spin up only at its working position, spin down before travel to the dock.
  - Vacuum/dust: on with the motor, interlocked like the laser's extraction below (the vacuum is the likelier first "extraction").
  - Stall: polyfuse on its supply; the load cells see a jam as force.
- [ ] Pointing laser: Class 2 only (≤ 1 mW, visible). Not the 5 mW "pointers" (Class 3R, often more than labelled).

## Laser (later, not planned now)

- [ ] Laser Shutdown Lid Detect switch.
  - In hardware: an NC switch in series with the laser's supply or its EN, opened by the lid; not only read by the MCU. A second switch to the MCU so the plot pauses cleanly. Lid open = laser off, whatever the software says.
  - The lid: acrylic or polycarbonate rated OD4+ at the module's wavelength (445-455 nm: orange); plain clear acrylic doesn't block blue.
- [ ] Laser Evacuation system power control and interlock (planned).
  - Laser EN only while the extraction runs (its tach or an airflow switch, not just "commanded on"); the fan keeps running a few minutes after the job.
- [ ] Key switch on the laser's own supply (the second cut, see *Stopping*).
- [ ] A laser-on light outside the enclosure, driven by EN itself (hardware), not by G-code.
- [ ] Fire: never unattended; a metal plate or honeycomb under the work (never the PVC cutting mat: chlorine); CO2 or ABC extinguisher in reach. Optional: a flame/smoke sensor that drops EN.
- [ ] A laser that stops moving burns through: `plot/`'s laser kind turns off (`M5`) on every error path and before every travel; Klipper's laser PWM off at start and shutdown. See TODO *Laser safety*.


# Operating Procedures

Specific to this machine; general workshop practice still applies. Each mode adds to *Common*.

## Common

1. Verify bed/dock are clear of objects, rails are clear too.
2. Verify all indicator leds (todo) are lit: Power branches, "Safe".
3. Klipper Pi is up and the UI breathes in idle.
4. (todo) Optical Calibration slots are clear and clean.
5. Know where the stop is: the slide switch (motion + tool power), and Klipper's stop in the UI.
6. Home before any move; nothing moves before homing.
7. Nothing on the carriage's path that isn't meant to be: cables, the camera tether, a ruler on the bed.
8. Hair tied, no loose sleeves, scarves or lanyards near the gantry.

## Automatic Plotting

1. All pens docked and uncapped.
2. Paper is firmly held down.
3. (todo) Purge paper zone is not full.
4. Pens in the holders their tags say; drying times set for new pens.
5. Preview the plot's bounds (frame or UI) on a new paper size or layout before the first stroke.
6. Can run unattended once started; check back at the drying beeps. Solvent markers: air in the room.

## Manual Plotting

1. Operator is familiar with this manual.
2. Only tools with RFID tags can be docked. Ones marked oversize cannot be put in holder.
3. Hands off the bed and the gantry's path while anything is enabled; jog with the motors' current in mind (XY can pinch).
4. A tool goes into the key or out of it only with the machine idle, not mid-move.
5. Blade tool: cap on in and out of the machine, blade changes off the machine.

## Development

1. Physical Proximity recommended.
2. New motion code: first run in the air (Z raised, no pen) and slow (`SET_VELOCITY_LIMIT`), a hand near the stop.
3. New or changed tool power code: bench-test the off paths first (unplug, reset, stop) with a dummy load.
4. Klipper restarts and firmware updates on the Pi only by the person at the machine.
5. Never bypass an interlock to test something else; if one must be bridged for a test, label it, and remove it the same session.

## Laser (+PPE)

1. Physical proximity required -- require a button press after closing lid.
2. Evacuation system is verified (fan, intake, exhaust, ventilation)
3. Fire extinguisher verified and close to the foot area rather than machine.
4. Mask, Laser Glasses
5. Lid interlock tested before the job: open the lid with the laser at its lowest power (or a test fire on the plate): it must go off.
6. Material known to be safe to laser: no PVC, vinyl, the cutting mat, polycarbonate, fibreglass/FR4 (fumes), nothing unidentified. A metal plate or honeycomb underneath.
7. Never leave the room while the laser is enabled; stay until the material stops smoking.
8. After: extraction runs a few more minutes; the laser's own supply keyed off.

## Laser (engraving on compatible material) (+PPE)

> Follow the "safety practices" of Creality and other exposed laser systems, i.e. no safety.

Difference: No Lid.

1. All of Laser ^.
2. Laser Glasses (wavelength matched).
3. Ventilated workshop, with air purifier and total runtime limited to allow natural airflow fix.
4. Air flow path optimization (apartment window)
5. Masks with respirator and filter.
6. Vacuum fan for sucking the air out immediately -- hooked to the toolhead.
7. Without a lid the whole room is the enclosure: everyone in it wears matched glasses, or nobody else is in it (pets included); door closed, a sign on it.
8. Nothing reflective on or near the bed (metal tools, foil, glass); the beam can't point at the window or the door.
9. The lid interlock is bypassed with a labelled key or plug made for it, never by taping or removing the switch; back to normal after the job.
10. Lowest power that does the job; short test burns first.

## Milling (+PPE)

1. Physical proximity recommended.
2. Clamping must be validated.
3. Manual or hosed vacuum.
4. Gloves, Mask, Safety Glasses.
   - Gloves only for handling bits and swarf: **off while the bit spins** (a glove caught by a rotating bit pulls the hand in).
5. Bit seated and tight; the right bit for the material; spin up before touching the work, spin down before travel to the dock.
6. Dust: wood/MDF and especially FR4 (glass fibre, toxic) need the vacuum at the bit and a P2/P3 (FFP2/3) mask; no dry sweeping or compressed air afterwards.
7. Z depth checked in the air first; the bed protected (sacrificial board) against a cut through.

## Ending a session

1. Tools docked, pens capped (or their caps on a timer).
2. Motors off (`M84`), tool power off.
3. Laser/motor supplies keyed off and unplugged; extraction finished.
4. The bed and the dock cleared of chips, blade tools in their caps.
5. Any open issue (a crash, a strange noise, a missed tag) written down in TODO before leaving.
