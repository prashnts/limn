# Tool holders, toolhead wiring and the endoscope

## Tool holders and tags

The tool holders' switches (MCP23017) and the tool tags (PN532), read by the extension (`ext/limn/tool_holder.py`) straight off the Pi's I2C bus (`tool_holder_*` in `[limn]`).

- Commands: `TOOL_HOLDERS`, `TOOL_HOLDER_CHECK T= EXPECT=occupied|empty`, `TOOL_TAG_READ`, `TOOL_TAG_WRITE [DX= DY= DZ= NAME= REFERENCE=0|1]`. Klipper's user needs to be in the `i2c` group.
- Pens can also be scanned by hand: hold the pen to the reader until it beeps, then put it into a holder within 8 s. That holder has that pen (`TOOL_TAGS`, the web UI) until a hand empties it again; docking and undocking don't. Between tool changes the reader listens every 2 s (every 5 s while printing, `tool_holder_scan_idle` / `tool_holder_scan_printing` in `[limn]`, 0: off), and every 0.5 s for a minute after a hand was on the holders.
- A tool with no holder (the Pi camera, `limn_endoscope/picam`) is docked by hand: `DOCK_MANUAL` (or a hand on the holders) to listen fast, hold its tag to the reader until it beeps, then push it onto the carriage within 20 s: the key's switch (`manual_stepper axis_k`) triggering docks it (`currently_docked_tool` 90, its tag's offsets, `printer.limn.manual`). Until it is taken off the dock is off limits: moves past X 110 fail (`manual_dock_x_max`), and `DOCK`, `UNDOCK`, `TOOL_SCAN`, `TOOL_TAG_READ/WRITE` and `BED_MESH_CALIBRATE` refuse. Take it off by hand, then `DOCK_CLEAR`, or hold it to the reader again. A camera whose pen (`pens.toml`) has a URL for `webcam` is then a camera of the plot tool's Scan tab.

## Cable chain

To the toolhead, open on one side (ventilated):

- Z: NEMA 8 stepper, its 4 wires in a silicone ribbon.
- K: 10 mm linear micro stepper, its 4 wires in a silicone ribbon.
- The stepper drivers run at 5V.
- A USB-C cable.
- A ribbon with the endstops, the accelerometer and future toolhead sensors.
- Mostly 26 AWG, with a short 30 AWG piece. 26 AWG is ~0.134 ohm/m (~2.2 A chassis rating), 30 AWG ~0.34 ohm/m (~0.86 A). A 30 AWG piece only a few cm long can carry more than that: the thicker wire at its ends draws the heat away. On 5V the voltage drop is the limit: the GND wire carries the same current, so count the run twice; doubling 5V and GND halves the drop.
- Planned: pogo pins on the toolhead, tool power through the coupling (see *Toolhead rework* in `TODO.md`).

## Endoscope camera

On the toolhead, reclaimed from single-use medical endoscopes:

- USB decoder board `0bde:8076` "Xitech USB Camera", UVC, 400x400 only (YUYV or MJPG, 30 fps). In crowsnest: `[cam endocam]`, ustreamer, port 8082 (`/webcam3/`), device `/dev/v4l/by-id/usb-Xitech_USB_Camera_20240610-video-index0`. The Fluidd webcam entry "axiscam" points at `/webcam3/` too, so it shows the endoscope. Crowsnest doesn't reopen a camera that was unplugged: restart it.
- The sensor has 4 wires to the board through our adapter: VDD, GND, VCLK, VOUT. VOUT is raw analog: one pixel's level per VCLK tick, no sync like composite video. The board drives the clock, samples VOUT and builds the frames. A bad contact on VOUT/VCLK shows as a camera that enumerates and streams nothing. Adapter rules: a GND between VOUT and VCLK, short runs away from the stepper wires, decoupling on VDD near the sensor, never plug the sensor in while the board is powered.
- The board's potentiometer is in the clock path (traced from photos, 2026-10-02), not on the LED driver. Its job is unconfirmed: likely the sampling phase (an RC delay) or the clock's edges/swing. See TODO.md.
- No LEDs at the tip: light goes in through two fibers on the connector's optical port, ~1 cm from the camera connector. Each fiber end is Ø0.9 mm, 1.40 mm apart (hand-measured, ±0.1-0.2 mm; render: `~/limn-shot/endo-connector-model-20261001.png`). A 1W LED shone at it lights objects 5-10 mm from the tip. Couple a small flat emitter (~2 mm, covering both fibers) to within ~0.1 mm of the face; a collimating lens doesn't help. The fibers are likely plastic: keep a hot LED off the face.
- LED power: ~3.0V × 350 mA ≈ 1 W at the LED; from 24V through a buck constant-current driver ~50 mA, from 5V 0.25-0.35 A. Switched on only for snapshots (on/off, not PWM: the camera shows PWM as bands).
