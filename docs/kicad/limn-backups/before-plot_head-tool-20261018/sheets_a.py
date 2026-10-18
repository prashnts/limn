# Limn KiCad generator - sheets: power, host, tool dock, Melzi
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# References are numbered per sheet: power 1xx, host 2xx, tool dock 3xx, Melzi 4xx.
# Solid boxes: one board or assembly. Dashed: planned, or going (DNP parts).
from . import boards
from .core import g

GND = 'GND'


def gnd(s, ref, number, stub=0):
    s.power('GND', ref, number, stub=stub)


def pins_named(s, ref, name):
    lib_id = s.refs[ref][0]
    return [k for k, v in s.pins[lib_id].items() if v[3] == name]


def power_sheet(s):
    s.title_text('POWER: one USB-C PD charger, three branches', 15.24, 15.24)
    U = s.add_block(*boards.charger())
    s.place(U, 'PS101', 'UGREEN Nexode 100W (USB-C PD)', 45.72, 80.01)
    s.nc('PS101', 'AC in')
    # 45 W: 12 V, the slide switch, motion
    T12 = s.add_block(*boards.pd_trigger(12))
    s.place(T12, 'U101', 'PD trigger 12 V (Trigger0)', 106.68, 45.72)
    s.connect('PS101', 'C0 45W', 'U101', 'USB-C', lane=-2)
    sw = s.use('Switch', 'SW_SPST')
    s.place(sw, 'SW101', 'slide switch (Bambu, 12 V 3 A)', 147.32, 43.18)
    s.connect('U101', 'OUT+', 'SW101', '1')
    gnd(s, 'U101', 'OUT-', stub=2.54)
    s.flag_at(s.out('U101', 'OUT-', 2.54))          # GND: the charger's, via the trigger
    s.power('+12V', 'SW101', '2', stub=5.08)
    s.flag_at(s.out('SW101', '2', 5.08))
    s.text('+12V (switched): the Melzi\'s VIN (sheet Melzi) and the LM2596.\nThe switch only cuts motion.', 162.56, 30.48)
    lm = s.add_block(*boards.buck('LM2596_module', 'LM2596 buck module (LM_Buck0), on the Aux PCB', 'LM2596 (LM_Buck0)'))
    s.place(lm, 'U102', 'LM2596 (LM_Buck0)', 210.82, 50.8)
    s.power('+12V', 'U102', 'IN+', stub=2.54)
    gnd(s, 'U102', 'IN-', stub=2.54)
    s.power('+7.5V', 'U102', 'OUT+', net='+7V5_ZK', stub=5.08)
    gnd(s, 'U102', 'OUT-', stub=2.54)
    s.text('+7V5_ZK: the Melzi\'s Z and K drivers (their 12 V trace cut).\nSet 7.2-7.5 V today. The A4982 wants VBB >= 8 V:\n9 V for margin (motor heat is Vref, not the supply).', 236.22, 40.64)
    s.enclose(91.44, 25.4, 300.99, 66.04, 'C0 45 W: 12 V, motion')

    # 30 W: 9 V, the MP1495s (planned)
    T9 = s.add_block(*boards.pd_trigger(9))
    s.place(T9, 'U103', 'PD trigger 9 V (Trigger1)', 106.68, 99.06)
    s.connect('PS101', 'C1 30W', 'U103', 'USB-C', lane=2)
    s.power('+9V', 'U103', 'OUT+', stub=5.08)
    gnd(s, 'U103', 'OUT-', stub=2.54)
    mp = boards.buck('MP1495_module', 'MP1495 buck, 5 V fixed (MP_Buck): 4.5-16 V in, 3 A', 'MP1495 5 V')
    MP = s.add_block(*mp)
    s.place(MP, 'U104', 'MP1495 5 V (MP_Buck0)', 167.64, 93.98)
    s.power('+9V', 'U104', 'IN+', stub=2.54)
    gnd(s, 'U104', 'IN-', stub=2.54)
    s.power('+5V', 'U104', 'OUT+', net='+5V_LED', stub=5.08)
    gnd(s, 'U104', 'OUT-', stub=2.54)
    s.text('+5V_LED: the UI matrix, the lamp, the\nindockator (and the USB hub). Today the\nLEDs run from a Pi USB port.', 195.58, 82.55)
    s.place(MP, 'U105', 'MP1495 5 V (MP_Buck1)', 167.64, 124.46)
    s.power('+9V', 'U105', 'IN+', stub=2.54)
    gnd(s, 'U105', 'IN-', stub=2.54)
    gnd(s, 'U105', 'OUT-', stub=2.54)
    MS = s.add_block(*boards.pololu_mosfet())
    s.place(MS, 'U106', 'Pololu mini MOSFET switch LV (MosfetSw_ToolCh)', 228.6, 129.54)
    s.connect('U105', 'OUT+', 'U106', 'VIN')
    s.glabel('TOOL_5V_EN', 'U106', 'CTRL', shape='input')
    gnd(s, 'U106', 'GND', stub=2.54)
    pf = s.use('Device', 'Polyfuse')
    s.place(pf, 'F101', 'polyfuse ~2 A', 264.16, 129.54, rot=90)
    s.connect('U106', 'VOUT', 'F101', '1')
    s.power('+5V', 'F101', '2', net='+5V_TOOL', stub=5.08)
    s.flag_at(s.out('F101', '2', 5.08))
    s.text('+5V_TOOL: the tool coupling (sheet Toolhead): only with the tool seen\nand the key locked; non-latching, control pulled down (off by default).', 205.74, 144.78)
    s.enclose(91.44, 76.2, 300.99, 157.48, 'C1 30 W: 9 V, 5 V branches (planned, the user\'s 2026-10-15 layout)', planned=True)

    # 22.5 W: the Pi
    s.glabel('PI_USBC', 'PS101', 'C2 22.5W', stub=10.16)
    s.text('C2 22.5 W: the Pi 4 at 5 V 3 A (sheet Host).\nNever from a 12 V -> 5 V buck.', 66.04, 170.18)

    s.title_text('NOTES', 15.24, 200.66)
    s.text('- Grounds: one ground point near the Melzi, one solid GND wire between the 9 V and 12 V branches there, so stepper\n'
           '  return never uses USB cables or signal wires. All GND on these sheets is that one net.\n'
           '- No backfeed: ~1 k in series on every line crossing supplies; USB VBUS of the Pi never tied to a buck\'s 5 V.\n'
           '- A fuse or e-fuse per branch (to do): a short anywhere trips the whole charger, every port off.\n'
           '- The charger cuts all its ports when a device is plugged into another: careful with hot-plugging.\n'
           '- 47-100 uF electrolytic at each MP1495\'s input (hot-plug ringing ~2 x Vin).\n'
           '- From docs/block-diagrams.md (the user\'s layout) and limn/TODO.md, Toolhead and harness rework.', 15.24, 205.74)


def host_sheet(s):
    s.title_text('HOST: Raspberry Pi 4', 15.24, 15.24)
    PI = s.add_block(*boards.pi4())
    s.place(PI, 'U201', 'Raspberry Pi 4', 101.6, 88.9)
    s.glabel('PI_USBC', 'U201', 'USB-C 5V', stub=7.62)
    s.flag_at(s.out('U201', 'USB-C 5V', 7.62))
    gnd(s, 'U201', '2', stub=5.08)
    s.power('+3V3', 'U201', '1 3V3', net='+3V3_PI', stub=7.62)
    s.glabel('I2C1_SDA', 'U201', '3 GPIO2 SDA1', stub=7.62)
    s.glabel('I2C1_SCL', 'U201', '5 GPIO3 SCL1', stub=7.62)
    gnd(s, 'U201', '6 GND', stub=5.08)
    s.nc('U201', 'DSI')
    s.nc('U201', 'CSI')
    s.nc('U201', 'Ethernet')
    s.text('DSI: a 4.5" display, maybe: powered from the 9 V side, not from the Pi.', 55.88, 116.84)
    s.text('I2C1 (header pins 3, 5): the holder switches and the tag reader, sheet Tool dock.', 55.88, 121.92)
    CAM = s.add_block(*boards.uvc('UVC_camera', 'USB (UVC) camera', 'UVC camera'))
    s.place(CAM, 'U203', 'UVC camera 0 (which one? ask)', 182.88, 50.8)
    s.connect('U201', 'USB-A 1', 'U203', 'USB')
    s.glabel('USB_ENDO', 'U201', 'USB-A 2', stub=10.16)
    s.text('USB_ENDO: the endoscope\'s board, on the\ntoolhead (USB-C cable in the chain).', 147.32, 66.04)
    HUB = s.add_block(*boards.usb_hub())
    s.place(HUB, 'U202', 'FE1.1s USB hub (FE11)', 182.88, 101.6)
    s.connect('U201', 'USB-A 3', 'U202', 'UP')
    s.power('+5V', 'U202', '5V', net='+5V_LED', stub=5.08)
    gnd(s, 'U202', 'GND', stub=5.08)
    for dn, net in (('DN1', 'USB_MELZI'), ('DN2', 'USB_AUX'), ('DN3', 'USB_DOCK'), ('DN4', 'USB_PLOTBED')):
        s.glabel(net, 'U202', dn, stub=7.62)
    s.text('The plotter\'s MCUs: Melzi (its VBUS not\nconnected), the Aux Pico, the bed Dock,\nthe plot bed. Today some are straight on\nthe Pi\'s ports.', 213.36, 116.84)
    s.enclose(152.4, 83.82, 271.78, 137.16, 'USB hub (planned, the user\'s layout)', planned=True)
    s.nc('U201', 'USB-A 4')
    s.text('USB-A 4: the LEDs\' 5 V for now (until the MP1495 branch is in).', 55.88, 127.0)
    s.enclose(55.88, 68.58, 132.08, 111.76, 'Raspberry Pi 4')


def tool_dock_sheet(s):
    s.title_text('TOOL DOCK: holder switches, tag reader, indockator', 15.24, 15.24)
    M = s.add_block(*boards.mcp23017())
    s.place(M, 'U301', 'Adafruit MCP23017 (0x20)', 96.52, 76.2)
    s.power('+3V3', 'U301', 'VIN', net='+3V3_PI', stub=7.62)
    gnd(s, 'U301', 'GND', stub=5.08)
    s.glabel('I2C1_SCL', 'U301', 'SCL', shape='input', stub=7.62)
    s.glabel('I2C1_SDA', 'U301', 'SDA', stub=7.62)
    for a in ('A0', 'A1', 'A2'):
        gnd(s, 'U301', a, stub=5.08)
    s.nc('U301', 'RST')
    s.nc('U301', 'GPA0-7')
    s.nc('U301', 'GPB0-2')
    sw = s.use('Switch', 'SW_Push')
    for i, (gp, tool) in enumerate((('GPB7', 41), ('GPB6', 42), ('GPB5', 45), ('GPB4', 43), ('GPB3', 44))):
        ref = f'SW{301 + i}'
        y = 63.5 + 7.62 * i
        s.place(sw, ref, f'holder {tool} (micro switch)', 142.24, y)
        s.connect('U301', gp, ref, '1', lane=2 - i)      # stepped: the wires don't overlap
        gnd(s, ref, '2', stub=2.54)
    s.text('Each holder\'s micro switch: closed = its tool home (a pin reads 0).\nPull-ups: the MCP23017\'s own (GPPU). tool_holder_pins: 15:41, 14:42,\n13:45, 12:43, 11:44 in [limn] (klipper/limn.cfg). RST: check the breakout.', 116.84, 106.68)
    s.enclose(66.04, 45.72, 210.82, 121.92, 'Tool dock (Limn Export 42): 5 holders')
    N = s.add_block(*boards.pn532())
    s.place(N, 'U302', 'PN532 (0x24, I2C mode)', 96.52, 160.02)
    s.power('+3V3', 'U302', 'VCC', net='+3V3_PI', stub=7.62)
    gnd(s, 'U302', 'GND', stub=5.08)
    s.glabel('I2C1_SDA', 'U302', 'SDA', stub=7.62)
    s.glabel('I2C1_SCL', 'U302', 'SCL', shape='input', stub=7.62)
    s.nc('U302', 'IRQ')
    s.nc('U302', 'RSTO')
    s.text('NTAG tags on the pens: dx/dy/dz on pages 6-8, the name 11-15,\nthe pen and colour (format 2) 4-5 and 10. ext/limn/tool_holder.py.', 66.04, 180.34)
    s.enclose(60.96, 139.7, 160.02, 190.5, 'Limn NFC (tag reader)')
    W = s.add_block(*boards.ws2812(30, 'WS2812 strip, 30 px, GRB: the indockator', 'WS2812 x 30 (indockator)'))
    s.place(W, 'U303', 'WS2812 x 30, GRB (indockator)', 241.3, 157.48)
    s.glabel('NEOPIXEL_INDOCK', 'U303', 'DIN', shape='input', stub=7.62)
    s.power('+5V', 'U303', '5V', net='+5V_LED', stub=7.62)
    gnd(s, 'U303', 'GND', stub=5.08)
    s.text('[neopixel indockator], rpi:gpio17 (sheet Aux MCU).\n3.3 V data into a 5 V strip: borderline (a 74AHCT125,\nor the first LED through a diode).', 205.74, 172.72)
    s.enclose(200.66, 139.7, 299.72, 190.5, 'Indockator strip')


def melzi_sheet(s):
    s.title_text('MELZI: Klipper [mcu], the motion board', 15.24, 15.24)
    MZ = s.add_block(*boards.melzi())
    s.place(MZ, 'U401', 'Melzi v2.0 (ATmega1284P, 4 x A4982)', 152.4, 101.6)
    s.power('+12V', 'U401', 'VIN 12V', stub=7.62)
    for n in pins_named(s, 'U401', 'GND'):
        gnd(s, 'U401', n, stub=5.08)
    s.power('+7.5V', 'U401', 'VMOT Z/K', net='+7V5_ZK', stub=7.62)
    s.glabel('USB_MELZI', 'U401', 'USB', stub=12.7)
    s.text('USB: the FT232R; VBUS not connected\n(the Melzi runs from its own 12 V).', 66.04, 81.28)
    sw = s.use('Switch', 'SW_Push')
    s.place(sw, 'SW401', 'X endstop (frame)', 91.44, 121.92)
    s.connect('U401', 'X-MIN PC2', 'SW401', '2')
    gnd(s, 'SW401', '1', stub=2.54)
    s.glabel('ENDSTOP_Y', 'U401', 'Y-MIN PC3', stub=10.16)
    s.glabel('ENDSTOP_Z', 'U401', 'Z-MIN PC4', stub=10.16)
    s.text('Endstops ^!PC2 / ^!PC3 / ^!PC4: pull-up, inverted.\nY and Z are on the toolhead (sheet Toolhead).', 71.12, 134.62)
    mot = s.use('Motor', 'Stepper_Motor_bipolar')
    s.place(mot, 'M401', 'NEMA 17 (CoreXY A)', 236.22, 45.72)
    s.place(mot, 'M402', 'NEMA 17 (CoreXY B)', 236.22, 81.28)
    for port, m, axis in (('E', 'M401', 'A'), ('Y', 'M402', 'B')):
        for coil_pin, mp in (('1A', '1'), ('1B', '2'), ('2A', '3'), ('2B', '4')):
            s.label(f'MOT_{axis}_{coil_pin}', 'U401', f'{port} {coil_pin}', stub=7.62)
            s.label(f'MOT_{axis}_{coil_pin}', m, mp, stub=5.08 if mp in '12' else 2.54)
    for port, axis in (('X', 'Z'), ('Z', 'K')):
        for coil_pin in ('1A', '1B', '2A', '2B'):
            s.glabel(f'MOT_{axis}_{coil_pin}', 'U401', f'{port} {coil_pin}', stub=10.16)
    s.text('Ports as on the PCB, not as Klipper names them:\nE = stepper_x (A), Y = stepper_y (B), X = stepper_z (Z),\nZ = manual_stepper axis_k (K, the key lock). Z and K on\nthe toolhead. The Z port is built for two motors in\nseries: one motor closes the loop across both headers.', 254.0, 88.9)
    # EXT header
    s.nc('U401', 'A1 PA1')
    s.glabel('ENDSTOP_K', 'U401', 'A2 PA2', stub=12.7)
    s.glabel('BLTOUCH_CTRL', 'U401', 'A3 PA3', stub=25.4)
    for p in ('SDA', 'SCL', 'TX', 'RX'):
        s.nc('U401', p)
    s.power('+5V', 'U401', 'VCC', net='+5V_MELZI', stub=5.08)
    s.glabel('PROBE_A4', 'U401', 'A4 PA4', stub=35.56)
    s.text('EXT header (JP16): A2 = ^PA2 K endstop, A3 = PA3 BLTouch\ncontrol, A4 = ^PA4 the probe pin. A1, SDA, SCL, TX, RX unused.', 101.6, 200.66)
    # the OR gate, going with the BLTouch
    OG = s.add_block(*boards.or_gate())
    s.place(OG, 'U402', 'probe OR gate (2 NPN)', 220.98, 162.56, dnp=True)
    s.glabel('PROBE_OUT', 'U402', 'IN Dock', shape='input', stub=5.08)
    s.glabel('BLTOUCH_SENSE', 'U402', 'IN BLTouch', shape='input', stub=5.08)
    s.power('+5V', 'U402', '+5V', net='+5V_MELZI', stub=5.08)
    gnd(s, 'U402', 'GND', stub=5.08)
    s.glabel('PROBE_A4', 'U402', 'OUT', stub=7.62)
    s.enclose(190.5, 144.78, 262.89, 182.88, 'Going: the OR gate (with the BLTouch)', planned=True)
    # the plot bed's touch line into the probe pin
    R = s.use('Device', 'R')
    s.place(R, 'R401', '10k', 299.72, 162.56)
    s.power('+5V', 'R401', '1', net='+5V_MELZI', stub=2.54)
    s.glabel('PROBE_A4', 'R401', '2', stub=5.08)
    s.text('The plot bed\'s touch line (open collector,\nsheet Plot bed): its pull-up here at the\nMelzi. endstop_pin: ^PA4 (or this 10k), no !.\nHigh = triggered.', 281.94, 175.26)
    s.enclose(271.78, 144.78, 345.44, 195.58, 'Plot bed touch (planned)', planned=True)
    s.enclose(60.96, 33.02, 228.6, 152.4, 'Melzi (in the controller bay)')

