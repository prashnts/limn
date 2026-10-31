# Limn KiCad generator - sheets: toolhead, Aux MCU, calibration bed, beam bed, plot bed board, hub board
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# References: toolhead 5xx, Aux MCU 6xx, the dock's pogo 7xx, calibration bed 8xx (the beam bed 85x), plot bed board 95x,
# hub board 10xx. Set aside (the feet, the RTP node, a toolhead MCU): kicad_gen/aside.py.
import json
from pathlib import Path
from . import boards
from .core import g, font, num, Q, stable, find
from .sheets_a import gnd, pins_named

NODES = Path(__file__).resolve().parents[3] / 'micropython/nodes'


# The FFC between the toolchanger and the axis (decided with the user, 2026-10-29): 20 contacts, 0.5 mm, <= 15 cm;
# the same pin on both breakouts. (net, kind): kind 'g' a global label, 'gnd', '5v' (+5V_TOOL), 'o' an output label
FFC = {1: ('GND', 'gnd'), 2: ('CELL_EXC_P', 'g'), 3: ('CELL_SIG_P', 'g'), 4: ('CELL_SIG_N', 'g'), 5: ('CELL_EXC_N', 'g'),
       6: ('GND', 'gnd'), 7: ('ENDSTOP_K', 'o'), 8: ('GND', 'gnd'), 9: ('TOOL_USB_DP', 'g'), 10: ('TOOL_USB_DN', 'g'),
       11: ('GND', 'gnd'), 12: ('TOOL_ID', 'g'), 13: ('+5V_TOOL', '5v'), 14: ('+5V_TOOL', '5v'), 15: ('+5V_TOOL', '5v'),
       16: ('GND', 'gnd'), 17: ('MOT_K_1A', 'g'), 18: ('MOT_K_1B', 'g'), 19: ('MOT_K_2A', 'g'), 20: ('MOT_K_2B', 'g')}


def _ffc_pins(s, ref):
    bus = [s.P(ref, str(n)) for n, (_, kind) in FFC.items() if kind == '5v']     # 13-15 joined, one rail symbol
    d = -1 if s.away(ref, '13') == 180 else 1
    bx = g(bus[0][0] + d * 2.54)
    for p in bus:
        s.wire(p, (bx, p[1]))
    s.wire((bx, bus[0][1]), (bx, bus[1][1]))
    s.wire((bx, bus[1][1]), (bx, bus[2][1]))
    s.junction((bx, bus[1][1]))
    end = (g(bx + d * 5.08), bus[1][1])
    s.wire((bx, bus[1][1]), end)
    _tool_rail(s, end, d)
    for n, (net, kind) in FFC.items():
        if kind == 'gnd':
            gnd(s, ref, str(n), stub=2.54)
        elif kind == '5v':
            continue
        else:
            s.glabel(net, ref, str(n), shape='output' if kind == 'o' else 'bidirectional', stub=5.08)


def _tool_rail(s, end, d):
    '''+5V_TOOL on a wire's end pointing sideways (d -1: left); the name written beside it (a rotated
    power symbol\'s own value lands on the wire).'''
    s.power_at('+5V', end, ang=180 if d < 0 else 0, net='+5V_TOOL', show=False)
    s.text('+5V_TOOL', g(end[0] - 15.24) if d < 0 else g(end[0] + 5.08), end[1])


def toolhead_sheet(s, standalone=False):
    '''The toolhead (the user, 2026-10-29). The toolchanger (it hangs on the load cell) is a PCB of its own
    (toolhead_board.kicad_pcb, tools/mkboard.py head): the coupling (3 screws, 4 pogo pins), the K lock\'s motor
    on 4 pogo pins and its key switch, the cell\'s pads, a 20-pin FFC on a breakout. The FFC (<= 15 cm) ends on a
    second breakout on the axis by the cable chain, wired to the harness: a USB-C cable (the tool\'s 5 V and
    USB, to the hub board), CAT6 (the cell, the ID, to LIT), a ribbon (K, to the Melzi). The axis\'s own parts
    (Z, the endstops, the accelerometer) run in the chain to the back.
    standalone: the root of the board\'s own project (toolhead_board.kicad_sch, gen.py): the PCB\'s parts on board
    there, so the board and its schematic are linked (F8, cross-probing).'''
    s.paper = 'A2'
    R, C = s.use('Device', 'R'), s.use('Device', 'C')
    s.title_text('TOOLHEAD: the toolchanger PCB, the FFC, the axis, the drag chain', 15.24, 15.24)

    # ---- the toolchanger: its PCB
    s.title_text('LOAD CELL', 25.4, 38.1)
    s.place(s.use('Connector_Generic', 'Conn_01x04'), 'J501', 'cell pads', 63.5, 55.88)
    for n, net in zip('1234', ('CELL_EXC_P', 'CELL_SIG_P', 'CELL_SIG_N', 'CELL_EXC_N')):
        s.glabel(net, 'J501', n, stub=5.08)
    for ref, (a, b), x, v in (('C504', ('CELL_SIG_P', 'CELL_SIG_N'), 86.36, '10n C0G'),
                              ('C505', ('CELL_EXC_P', 'CELL_EXC_N'), 104.14, '100n')):
        s.place(C, ref, v, x, 55.88, dnp=True)
        s.glabel(a, ref, '1', stub=2.54)
        s.glabel(b, ref, '2', stub=2.54)
    s.text('J501: the 4 gauge wires (silicone, S+/S- and E+/E-\ntwisted), anchored, then soldered here. The bridge\n'
           'closes at the gauges (sheet Plot bed board).\nC504/C505: pads for later (C0G), not fitted.\n'
           'E- is its own wire: never joined to GND here.', 25.4, 72.39)

    s.title_text('K: THE LOCK', 25.4, 96.52)
    mot = s.use('Motor', 'Stepper_Motor_bipolar')
    s.place(mot, 'M502', '10 mm linear micro stepper (K, the key lock)', 63.5, 116.84)
    for coil_pin, mp in (('1A', '1'), ('1B', '2'), ('2A', '3'), ('2B', '4')):
        s.glabel(f'MOT_K_{coil_pin}', 'M502', mp, stub=7.62 if mp in '12' else 5.08)
    s.text('Its flex on 4 pogo pins (one per pad, all on one side):\nwhite (the outermost) 1A, green 1B, yellow 2A,\n'
           'purple 2B. Coil pairs to check with a meter; the\nJST at the Melzi may be swapped by hand.', 25.4, 134.62)
    sw = s.use('Switch', 'SW_Push')
    s.place(sw, 'SW503', 'key switch (K)', 53.34, 157.48)
    s.glabel('ENDSTOP_K', 'SW503', '1', shape='output', stub=5.08)
    gnd(s, 'SW503', '2', stub=2.54)
    s.place(C, 'C503', '10n', 91.44, 160.02)
    s.glabel('ENDSTOP_K', 'C503', '1', shape='output', stub=2.54)
    gnd(s, 'C503', '2')
    s.text('Triggered while the key is open (^PA2).\nC503: stepper hash on the line.', 25.4, 175.26)

    s.title_text('THE COUPLING', 116.84, 38.1)
    pogo = s.use('Connector_Generic', 'Conn_01x01')
    for i, (ref, net) in enumerate((('J502', 'TOOL_USB_DP'), ('J503', 'TOOL_USB_DN'), ('J504', 'GND'), ('J505', 'TOOL_ID'))):
        s.place(pogo, ref, 'pogo', 162.56, g(53.34 + 5.08 * i))
        if net == 'GND':
            gnd(s, ref, '1', stub=2.54)
        else:
            s.glabel(net, ref, '1', stub=5.08)
    hole = s.use('Mechanical', 'MountingHole_Pad')
    for ref, x, what in (('H501', 129.54, '5V'), ('H502', 147.32, 'GND'), ('H503', 165.1, 'ID')):
        s.place(hole, ref, f'screw: {what}', x, 81.28)
    s.power('+5V', 'H501', '1', net='+5V_TOOL', stub=2.54)
    gnd(s, 'H502', '1', stub=2.54)
    s.glabel('TOOL_ID', 'H503', '1', stub=2.54)
    s.text('Pogo pins: D+/D- ~3 mm apart (the pair stays\ntwisted to them), GND and the ID beside them,\n'
           'in parallel with the screws. Kinematic\nscrews: 5 V, GND, the ID.', 116.84, 101.6)

    s.title_text('TOOL 5 V', 116.84, 124.46)
    for ref, v, x in (('C501', '10u', 121.92), ('C502', '100n', 134.62)):
        s.place(C, ref, v, x, 142.24)
        s.power('+5V', ref, '1', net='+5V_TOOL')
        gnd(s, ref, '2')
    s.place(R, 'R501', '1k5', 152.4, 137.16)
    s.power('+5V', 'R501', '1', net='+5V_TOOL')
    s.place(s.use('Device', 'LED'), 'D501', 'LED', 156.21, 147.32, rot=180)
    s.wire(s.P('R501', '2'), s.P('D501', '2'))
    k = s.P('D501', '1')
    s.wire(k, (g(k[0] + 2.54), k[1]), (g(k[0] + 2.54), g(k[1] + 5.08)), chamfer=0)
    s.power_at('GND', (g(k[0] + 2.54), g(k[1] + 5.08)))
    s.text('At the 5 V and GND screws. C501 <= 10 uF: a\nPC\'s port at plug-in. D501: ~2 mA, and it\n'
           'empties C501 once the 5 V is off.', 116.84, 165.1)

    BO = s.add_block(*boards.fpc20_breakout())
    s.place(BO, 'U506', 'FPC-20P breakout (head)', 213.36, 106.68)
    _ffc_pins(s, 'U506')
    s.enclose(15.24, 27.94, 236.22, 185.42, 'The toolchanger: the toolhead PCB (rides the load cell)')

    # ---- the FFC, and its end on the axis
    BM = s.add_block(*boards.fpc20_breakout(mirror=True))
    s.place(BM, 'U507', 'FPC-20P breakout (axis)', 284.48, 106.68)
    s.wire(s.P('U506', '21'), s.P('U507', '21'))
    s.text('FFC 20P, 0.5 mm, <= 15 cm', 238.76, 104.14)
    _ffc_pins(s, 'U507')

    W = s.add_block(*boards.usb_c_cable_cut())
    s.place(W, 'W501', 'USB-C cable (3 A, USB 2.0)', 381.0, 63.5)
    v = s.P('W501', 'VBUS')
    s.wire(v, (g(v[0] - 5.08), v[1]))
    _tool_rail(s, (g(v[0] - 5.08), v[1]), -1)
    s.glabel('TOOL_USB_DP', 'W501', 'D+', stub=5.08)
    s.glabel('TOOL_USB_DN', 'W501', 'D-', stub=5.08)
    gnd(s, 'W501', 'GND', stub=2.54)
    s.label('TOOL_CC', 'W501', 'CC', stub=5.08)
    s.nc('W501', 'shield')
    s.glabel('USB_TOOL', 'W501', 'plug', stub=5.08)
    s.place(R, 'R502', '5k1', 342.9, 101.6)
    s.label('TOOL_CC', 'R502', '1', stub=2.54)
    gnd(s, 'R502', '2')
    s.text('Cut at this end, soldered to the breakout;\nthe plug in the hub board\'s USB-C (U1007).\n'
           'R502: Rd on CC, so a PC\'s USB-C port turns\nVBUS on (a test straight on the computer).\n'
           'Shield: open here (grounded at the plug).', 355.6, 93.98)

    s.title_text('THE HARNESS, FROM THIS BREAKOUT', 355.6, 124.46)
    s.text('USB-C cable: VBUS on 13-15, GND on the GND pads, D+/D- on 9/10\n(untwisted <= 1 cm), CC: R502. To the hub board.\n'
           'CAT6 UTP 32 AWG, MX1.25 at LIT (J952): orange E+ (white) / E-,\nblue S+ (white) / S-, green the ID (white) + GND (its\n'
           'return), brown spare (open at both ends).\n'
           'Ribbon 26 AWG to the Melzi: K\'s 4 wires, ENDSTOP_K, GND.', 355.6, 129.54)
    s.enclose(246.38, 27.94, 513.08, 185.42, 'On the axis by the cable chain: the FFC\'s end, wired (the breakout only)')

    # ---- the axis: in the chain, to the back
    s.title_text('THE AXIS: Z, THE ENDSTOPS, THE ACCELEROMETER (IN THE CHAIN, TO THE BACK)', 15.24, 205.74)
    s.place(mot, 'M501', 'NEMA 8, lead screw (Z)', 50.8, 236.22)
    for coil_pin, mp in (('1A', '1'), ('1B', '2'), ('2A', '3'), ('2B', '4')):
        s.glabel(f'MOT_Z_{coil_pin}', 'M501', mp, stub=7.62 if mp in '12' else 5.08)
    s.text('Z: 4 wires from the Melzi\'s X port\n(sheet Melzi), drivers at ~7.5 V.', 25.4, 256.54)
    for ref, name, value, y in (('SW501', 'ENDSTOP_Y', 'Y endstop (micro switch)', 228.6),
                                ('SW502', 'ENDSTOP_Z', 'Z top endstop (micro switch)', 241.3)):
        s.place(sw, ref, value, 124.46, y)
        s.glabel(name, ref, '1', shape='output', stub=5.08)
        gnd(s, ref, '2', stub=2.54)
    s.text('Micro switches KFC-W-13W / KFC-C-15A.', 101.6, 256.54)
    MPU = s.add_block(*boards.mpu9250())
    s.place(MPU, 'U502', 'MPU9250 (MPU9255)', 205.74, 236.22)
    s.power('+3V3', 'U502', 'VCC', net='+3V3_AUX', stub=7.62)
    gnd(s, 'U502', 'GND', stub=5.08)
    s.glabel('MPU_SCL', 'U502', 'SCL', shape='input', stub=7.62)
    s.glabel('MPU_SDA', 'U502', 'SDA', stub=7.62)
    s.text('Software I2C on the Aux MCU, 0x68.\nVCC from its 3V3: to confirm.', 182.88, 256.54)
    BT = s.add_block(*boards.bltouch())
    s.place(BT, 'U501', 'BLTouch', 294.64, 236.22, dnp=True)
    for n in pins_named(s, 'U501', 'GND brown') + pins_named(s, 'U501', 'GND black'):
        gnd(s, 'U501', n, stub=5.08)
    s.power('+5V', 'U501', '+5V red', net='+5V_MELZI', stub=7.62)
    s.glabel('BLTOUCH_CTRL', 'U501', 'CTRL orange', shape='input', stub=7.62)
    s.glabel('BLTOUCH_SENSE', 'U501', 'SENSE white', shape='output', stub=7.62)
    s.enclose(261.62, 220.98, 325.12, 256.54, 'Gone: the BLTouch (no BLTouch planned)', planned=True)
    EB = s.add_block(*boards.endoscope())
    s.place(EB, 'U503', 'Xitech USB camera board (0bde:8076)', 373.38, 236.22)
    s.glabel('USB_ENDO', 'U503', 'USB', stub=7.62)
    ES = s.add_block(*boards.endo_sensor())
    s.place(ES, 'U504', 'endoscope sensor', 444.5, 236.22)
    for k, p in enumerate(('VDD', 'VCLK', 'VOUT')):
        s.connect('U503', p, 'U504', p, lane=k - 1)
    gnd(s, 'U503', 'GND', stub=2.54)
    gnd(s, 'U504', 'GND', stub=2.54)
    s.text('Our adapter: a GND between VOUT and VCLK, short runs away from the\nstepper wires, decoupling on VDD at the sensor, never hot-plugged.\n'
           'Light: two fibers on the connector\'s optical port (an LED, planned).', 345.44, 251.46)
    s.enclose(340.36, 218.44, 477.52, 269.24, 'Endoscope camera')

    notes = [
        (15.24, 'THE FFC', 'Pin = the breakouts\' printed numbers, the same on both ends:\n'
                 '1 GND (guard), 2 E+, 3-4 S+/S-, 5 E-, 6 GND, 7 ENDSTOP_K,\n8 GND, 9-10 D+/D-, 11 GND, 12 TOOL_ID, 13-15 +5V_TOOL,\n'
                 '16 GND, 17-20 K (A1 A2 B1 B2). 0.5 mm FFC: ~0.5 A a contact,\nso 1.5 A on 13-15: the tool gets 1 A (F1001).\n'
                 'Check 1 -> 1 with a meter before power: reversed, 13-15 land\non 6-8.'),
        (152.4, 'THE TOOLS (THE ID ON THE SCREW AND THE POGO)', 'Simple: GND and the ID bridged (copper tape, a\ntemplate): there, never powered; the RFID tag says which.\n'
                 'Passive: a resistor GND-ID, powered, no link.\nActuator: a resistor >= 4.7k, powered, the half-duplex link\n'
                 '(pings; lost = gone). USB: as an actuator, D+/D- pads.\nA resistor on the screws or on the pogos, never a bridge\n'
                 'on one and a resistor on the other. High power: tethered,\nits 5 V screw open (GND kept).'),
        (297.18, 'THE TOOL 5 V', 'Read the ID with the 5 V off, then switch it on (GP9, the\nhub board\'s U1006 + F1001 1 A); off before undocking.\n'
                 'A tool with a chip on the ID line keeps it high-Z while\nunpowered (74LVC2G07 / a 2N7002): else the line clamps\n'
                 'at ~0.6 V and reads as a low band. USB pins: fine.'),
        (424.18, 'THE DRAG CHAIN', 'Toolchanger: the USB-C cable, CAT6, the K ribbon.\nThe axis: Z (4), the Y/Z endstops, the MPU9250\n'
                 '(I2C + 3V3 + GND), the endoscope\'s USB.\nEvery cable anchored on the fixed side (HS) first;\n'
                 'across the cell only the FFC (a slack U-loop).'),
    ]
    for x, head, body in notes:
        s.title_text(head, x, 287.02)
        s.text(body, x, 292.1)
    # its own PCB (toolhead_board.kicad_pcb): the toolchanger's parts; the rest is wired, off any board
    if standalone:                    # alone, the rails come from other sheets: say so (ERC)
        for ref, pin in (('C501', '1'), ('C501', '2'), ('U502', 'VCC'), ('U501', '+5V red')):
            s.flag_at(s.P(ref, pin))
    own_board(s, standalone=standalone, fps={'limn:FPC20_breakout': 'U506', 'limn:Pogo_pin_D2.0_L5.0': 'J502 J503 J504 J505',
                  'limn:Micro_limit_sw_inline': 'SW503', 'limn:Stepper_slider_5mm_flex4': 'M502',
                  'MountingHole:MountingHole_3.2mm_M3_Pad': 'H501 H502 H503',
                  'Connector_Wire:SolderWire-0.127sqmm_1x04_P3.7mm_D0.48mm_OD1mm': 'J501',
                  'Capacitor_SMD:C_0805_2012Metric': 'C501 C502 C503 C504 C505',
                  'Resistor_SMD:R_0805_2012Metric': 'R501', 'LED_SMD:LED_0805_2012Metric': 'D501'})


def aux_sheet(s):
    '''The Aux PCB, next version (the user, 2026-10-20): smaller, a Waveshare RP2040-Zero (Klipper [mcu rpi]) for
    the LEDs, the buzzer and the accelerometer's I2C, and MP_Buck0 (9 V to 5 V) for the MCU, the LEDs and the
    buzzer. LM_Buck0 moved to the Melzi (the motors only).'''
    s.title_text('AUX MCU: Klipper [mcu rpi], an RP2040-Zero on the Aux PCB', 15.24, 15.24)
    Z = s.add_block(*boards.rp2040_zero('RP2040_Zero_aux', 'Waveshare RP2040-Zero: Klipper [mcu rpi] on the Aux PCB. '
                                        'Used pins only', 'RP2040-Zero (rpi)',
                                        [('GP4 MPU_SCL', 'output'), ('GP5 MPU_SDA', 'bidirectional'), None, ('GP9 BUZZER', 'output'),
                                         None, ('GP13 INDOCK', 'output'), ('GP14 LAMP', 'output'), ('GP15 UI', 'output')]))
    s.place(Z, 'U601', 'RP2040-Zero (rpi)', 101.6, 88.9)
    _pin_rail(s, 'U601', '5V', '+5V', '+5V_LED')
    s.power('+3V3', 'U601', '3V3', net='+3V3_AUX', stub=10.16)
    gnd(s, 'U601', 'GND', stub=5.08)
    s.glabel('USB_AUX', 'U601', 'USB', stub=7.62)
    s.text('USB: the hub\'s DN4, data only (VBUS cut): the\nZero runs from MP_Buck0 on its 5V pin, which is\n'
           'its USB VBUS too: flash it on USB with 9 V off.\n+3V3_AUX: the MPU9250 (sheet Toolhead).', 35.56, 111.76)
    s.glabel('MPU_SCL', 'U601', 'GP4 MPU_SCL', shape='output', stub=12.7)
    s.glabel('MPU_SDA', 'U601', 'GP5 MPU_SDA', stub=12.7)
    s.glabel('NEOPIXEL_INDOCK', 'U601', 'GP13 INDOCK', shape='output', stub=12.7)
    fet = s.use('Transistor_FET', '2N7000')
    s.place(fet, 'Q601', '2N7000', 172.72, 76.2)
    s.connect('U601', 'GP9 BUZZER', 'Q601', 'G')
    gnd(s, 'Q601', 'S', stub=2.54)
    bz = s.use('Device', 'Buzzer')
    s.place(bz, 'BZ601', 'buzzer', 177.8, 63.5)
    s.wire(s.P('Q601', 'D'), (g(s.P('Q601', 'D')[0]), g(s.P('BZ601', '2')[1])), s.P('BZ601', '2'))
    s.power('+5V', 'BZ601', '1', net='+5V_LED', stub=5.08)
    s.text('[pwm_cycle_time beeper], gpio9, 1 ms.\nBuzzer at +5V_LED; a flyback diode\nif it is a magnetic one.', 190.5, 55.88)
    W1 = s.add_block(*boards.ws2812(32, 'Pimoroni Unicorn pHAT: 8 x 4 WS2812, GRB: the UI matrix', 'Unicorn pHAT (32 px)'))
    s.place(W1, 'U602', 'Unicorn pHAT, 32 px GRB (picam)', 297.18, 104.14)
    s.connect('U601', 'GP15 UI', 'U602', 'DIN', lane=1)
    s.power('+5V', 'U602', '5V', net='+5V_LED', stub=7.62)
    gnd(s, 'U602', 'GND', stub=5.08)
    W2 = s.add_block(*boards.ws2812(30, 'WS2812-type strip, 30 px, GRBW: the lamp', 'WS2812 x 30 GRBW (lamp)', name='WS2812_30_GRBW'))
    s.place(W2, 'U603', 'lamp, 30 px GRBW', 297.18, 132.08)
    s.connect('U601', 'GP14 LAMP', 'U603', 'DIN', lane=-1)
    s.power('+5V', 'U603', '5V', net='+5V_LED', stub=7.62)
    gnd(s, 'U603', 'GND', stub=5.08)
    s.text('GP13: the indockator, sheet Tool dock.\nAll three at +5V_LED (MP_Buck0, up to\n~3 A all white). 3.3 V data: borderline.', 266.7, 152.4)
    s.enclose(266.7, 86.36, 360.68, 144.78, 'LEDs (off the board)')
    s.place(s.use('Connector_Generic', 'Conn_01x02'), 'J601', '9 V in (Trigger1)', 43.18, 147.32)
    _pin_rail(s, 'J601', '1', '+9V')
    _pin_rail(s, 'J601', '2', 'GND', up=False)
    MP = s.add_block(*boards.buck('MP1495_module', 'MP1495 buck, 5 V fixed (MP_Buck): 4.5-16 V in, 3 A', 'MP1495 5 V'))
    s.place(MP, 'U604', 'MP1495 5 V (MP_Buck0)', 96.52, 149.86)
    _pin_rail(s, 'U604', 'IN+', '+9V')
    _pin_rail(s, 'U604', 'IN-', 'GND', up=False)
    _pin_rail(s, 'U604', 'OUT+', '+5V', '+5V_LED')
    _pin_rail(s, 'U604', 'OUT-', 'GND', up=False)
    s.text('MP_Buck0: 9 V to +5V_LED: the Zero, the buzzer, the LEDs.\n47-100 uF at its input; the LED current on its own\nwires, not past the Zero.', 127.0, 144.78)
    s.text('Pins for the new version: lamp GP16 -> GP14 (GP16 is the Zero\'s own RGB LED), indockator\n'
           'GP17 -> GP13 (no header pin on the Zero). klipper/leds.cfg changes with the board.', 30.48, 170.18)
    s.enclose(25.4, 45.72, 248.92, 162.56, 'Aux PCB (next version): Klipper rpi, MP_Buck0, the buzzer')
    # its own perfboard (aux_board.kicad_pcb); MP_Buck0 the same mini buck as MP_Buck1; the LEDs off the board
    own_board(s, {'limn:Waveshare_RP2040_Zero': 'U601', 'limn:Mini_buck_3A': 'U604',
                  'Package_TO_SOT_THT:TO-92_Inline_Wide': 'Q601', 'Buzzer_Beeper:Buzzer_12x9.5RM7.6': 'BZ601',
                  'Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical': 'J601'})


def cal_bed_sheet(s):
    s.title_text('CALIBRATION BED: the detachable FSR bed and its node', 15.24, 15.24)
    J = s.use('Connector_Generic', 'Conn_01x05')
    s.place(J, 'J801', 'pogo, bed side', 58.42, 88.9)
    for p, net in (('1', 'BED_PWR'), ('3', 'BED_DETECT'), ('4', 'BED_DATA'), ('5', 'BED_PROBE')):
        s.glabel(net, 'J801', p, stub=7.62)
    gnd(s, 'J801', '2', stub=2.54)
    R = s.use('Device', 'R')
    s.place(R, 'R801', '22k (BED_5)', 58.42, 124.46)
    s.glabel('BED_DETECT', 'R801', '1', stub=2.54)
    gnd(s, 'R801', '2', stub=2.54)
    s.text('The bed ID: BED_1 2.2k, BED_2 4.7k,\nBED_3 10k, BED_4 15k, BED_5 22k, BED_6 33k.', 25.4, 142.24)
    fsr = json.loads((NODES / 'fsr.json').read_text())
    cols = [10, 9, 12, 11, 8, 13, 14, 15]                      # FSR_X in lrt_fsr_array.py
    rows = fsr['fsr_y']
    right = [('GP0 data (PIO)', 'bidirectional'), ('GP1 probe', 'output'), None, None] + \
            [(f'GP{c} col {i}', 'output') for i, c in sorted(enumerate(cols), key=lambda t: t[1])] + [None] + \
            [(f'GP{r} row {i}', 'input') for i, r in sorted(enumerate(rows), key=lambda t: t[1])]
    T2 = s.add_block(*boards.rp2040_zero('RP2040_Tiny_fsr', 'RP2040-Tiny: the FSR node (lrt_fsr_array.py, fsr.json). Used pins only',
                                         'RP2040-Tiny (FSR)', right))
    s.place(T2, 'U803', 'RP2040-Tiny (FSR node)', 132.08, 165.1)
    s.glabel('BED_DATA', 'U803', 'GP0 data (PIO)', stub=12.7)
    s.glabel('BED_PROBE', 'U803', 'GP1 probe', shape='output', stub=12.7)   # the old UART0 RX wire (2026-10-24)
    s.glabel('BED_PWR', 'U803', '5V', shape='input', stub=7.62)
    s.nc('U803', '3V3')
    gnd(s, 'U803', 'GND', stub=5.08)
    s.nc('U803', 'USB')
    F = s.add_block(*boards.fsr_sheet())
    s.place(F, 'U804', 'FSR 4 x 8 (FFC)', 251.46, 165.1)
    for i, c in enumerate(cols):
        s.label(f'FSR_COL{i}', 'U803', f'GP{c} col {i}', stub=7.62)
        s.label(f'FSR_COL{i}', 'U804', f'C{i}', stub=5.08)
    rows_by_pin = sorted(enumerate(rows), key=lambda t: t[1])
    for k, (i, r) in enumerate(rows_by_pin):
        ref = f'R{802 + i}'
        p = s.P('U803', f'GP{r} row {i}')
        x = g(p[0] + 12.7 + 10.16 * k)
        s.place(R, ref, '47k', x, g(p[1] + 3.81))          # pin 1 on the row line
        s.wire(p, (x, p[1]), (g(x + 5.08), p[1]))
        s.junction((x, p[1]))
        gnd(s, ref, '2', stub=2.54)
        s.label_at(f'FSR_ROW{i}', (g(x + 5.08), p[1]), 0)
        s.label(f'FSR_ROW{i}', 'U804', f'R{i}', stub=5.08)
    s.text('Rows: a 47k load each to GND (BED_5, "fsr_load": 47000); the board\'s series resistor on\nthree of the rows (not row 3, act-6). Columns: FSR_X = [10, 9, 12, 11, 8, 13, 14, 15].\nBED_3 (fsr_bed3.json) swaps rows 2 and 3: GP26 / GP27.', 91.44, 226.06)
    s.enclose(91.44, 114.3, 330.2, 220.98, 'FSR bed: the FSR node and its sheet')
    s.text('The FSR node on the pogo (lib/link.py): BED_DATA on GP0 (half-duplex, one wire)\nand BED_PROBE on GP1 (high = OK, low = touched): UART0\'s two wires, as wired. DETECT: the ID resistor only.\nPower: BED_PWR, switched on the plot bed board.', 91.44, 40.64)


def beam_bed_sheet(s):
    '''The beam bed (2026-10-21): XY by two IR break-beams in an L, Z from the head's load cell. A detachable bed
    like the FSR bed (pogo, ID resistor, BED_DATA, BED_PROBE) with its own RP2040-Tiny.
    Refs 85x (the calibration beds' 8xx).'''
    s.title_text('BEAM BED: XY by two IR break-beams (Z: the head\'s load cell)', 15.24, 15.24)
    R = s.use('Device', 'R')
    J = s.use('Connector_Generic', 'Conn_01x05')
    s.place(J, 'J851', 'pogo, bed side', 58.42, 88.9)
    for p, net in (('1', 'BED_PWR'), ('3', 'BED_DETECT'), ('4', 'BED_DATA'), ('5', 'BED_PROBE')):
        s.glabel(net, 'J851', p, stub=7.62)
    gnd(s, 'J851', '2', stub=2.54)
    s.place(R, 'R851', 'BED_? (a free ID)', 58.42, 124.46)
    s.glabel('BED_DETECT', 'R851', '1', stub=2.54)
    gnd(s, 'R851', '2', stub=2.54)
    s.text('The bed ID: a free one of BED_1..6\n(the Dock\'s bands end at 33k): to pick.', 25.4, 142.24)

    T = s.add_block(*boards.rp2040_zero('RP2040_Tiny_beam', 'RP2040-Tiny: the beam node. Used pins only',
                                        'RP2040-Tiny (beam)',
                                        [('GP0 data (PIO)', 'bidirectional'), None, ('GP1 probe', 'output'), None,
                                         ('GP6 LED X', 'output'), ('GP7 LED Y', 'output'), None,
                                         ('GP26 ADC0 beam X', 'input'), ('GP27 ADC1 beam Y', 'input')]))
    s.place(T, 'U851', 'RP2040-Tiny (beam node)', 132.08, 66.04)
    for i, (p, net) in enumerate((('GP0 data (PIO)', 'BED_DATA'), ('GP1 probe', 'BED_PROBE'))):
        r = f'R{860 + i}'                    # series 100R: hot plug, and the bed unpowered while the board isn't
        s.place(R, r, '100R', g(s.P('U851', p)[0] + 7.62 + 12.7 * i), s.P('U851', p)[1], rot=90)
        s.wire(s.P('U851', p), s.P(r, '1'))
        s.glabel(net, r, '2', stub=5.08)
    s.glabel('BED_PWR', 'U851', '5V', shape='input', stub=7.62)
    v = s.P('U851', '3V3')                  # out under GND: the rail's name clear of the 5V row
    s.wire(v, (g(v[0] - 7.62), v[1]), (g(v[0] - 7.62), g(v[1] + 12.7)))
    s.power_at('+3V3', (g(v[0] - 7.62), g(v[1] + 12.7)), ang=270, net='+3V3_BEAM')
    gnd(s, 'U851', 'GND', stub=2.54)
    s.nc('U851', 'USB')
    for axis in 'XY':
        s.label(f'LED_{axis}', 'U851', f'GP{6 if axis == "X" else 7} LED {axis}', stub=7.62)
        s.label(f'BEAM_{axis}', 'U851', f'GP{26 if axis == "X" else 27} ADC{0 if axis == "X" else 1} beam {axis}', stub=7.62)
    s.text('GP0: BED_DATA, a half-duplex UART on one wire (PIO).\nGP1: BED_PROBE, high = OK; low when armed and the beam\'s\nedge is seen. On the plot bed board it is in series with\nthe touch line (Q952): Klipper\'s probe pin, no relay in\nfirmware. DETECT: the ID resistor only.\nGP28/29 (ADC2/3): free, for a second pair later.', 91.44, 99.06)

    s.title_text('IR LEDS (940 nm, 1206), pulsed', 210.82, 30.48)
    q, led = s.use('Transistor_FET', 'Q_NMOS_GSD'), s.use('Device', 'LED')
    for i, axis in enumerate('XY'):
        qx, qy = 236.22 + 45.72 * i, 81.28
        rb, rl, qr, d, rg = f'R{852 + 3 * i}', f'R{853 + 3 * i}', f'Q{851 + i}', f'D{852 + i}', f'R{854 + 3 * i}'
        s.place(q, qr, 'AO3400', qx, qy)
        s.place(led, d, f'IR 1206 940 nm ({axis})', g(qx + 2.54), g(qy - 17.78), rot=90, on_board=False,
                note=f'in the {axis} slot, behind its slit')
        s.place(R, rl, '100R', g(qx + 2.54), g(qy - 29.21))
        s.place(R, rb, '100R', g(qx - 12.7), qy, rot=90)
        s.wire(s.P(d, 'K'), s.P(qr, 'D'))
        s.wire(s.P(rl, '2'), s.P(d, 'A'))
        s.glabel('BED_PWR', rl, '1', shape='input', stub=2.54)
        node = s.P(rb, '2')
        s.wire(node, s.P(qr, 'G'))
        s.place(R, rg, '100k', node[0], g(node[1] + 6.35))
        s.wire(node, s.P(rg, '1'))
        s.junction(node)
        gnd(s, rg, '2')
        s.label(f'LED_{axis}', rb, '1', stub=2.54)
        gnd(s, qr, 'S', stub=2.54)
    s.text('AO3400: logic level, the 100k holds it off through a reset.\n~35 mA pulsed from BED_PWR (5 V): (5 - 1.3) / 100R.\nOn minus off at a few kHz cancels room light.\nX and Y on their own pins: only one lit at a time,\nso the X LED can\'t leak into the Y phototransistor.', 210.82, 101.6)

    s.title_text('PHOTOTRANSISTORS (PT1206BS)', 210.82, 119.38)
    pt = s.use('Device', 'Q_Photo_NPN')
    for i, axis in enumerate('XY'):
        px, py = 233.68 + 45.72 * i, 139.7
        qr, rl = f'Q{853 + i}', f'R{858 + i}'
        s.place(pt, qr, f'PT1206BS ({axis} beam)', px, py, on_board=False, note=f'in the {axis} slot, behind its slit')
        s.power('+3V3', qr, 'C', net='+3V3_BEAM', stub=2.54)
        e = s.P(qr, 'E')
        s.place(R, rl, '10k', e[0], g(e[1] + 7.62))
        node = (e[0], g(e[1] + 2.54))
        s.wire(e, node)
        s.wire(node, s.P(rl, '1'))
        s.wire(node, (g(node[0] + 7.62), node[1]))
        s.junction(node)
        s.label_at(f'BEAM_{axis}', (g(node[0] + 7.62), node[1]), 0)
        gnd(s, rl, '2', stub=2.54)
    s.text('Emitter follower into the ADC: more light = higher.\nLoad: 10k to start; 4k7-100k so the open beam\nreads ~2/3 of full scale with its slits in.', 210.82, 165.1)
    s.enclose(91.44, 22.86, 320.04, 180.34, 'Beam node (under the beam block)')

    s.title_text('THE BEAM BLOCK', 15.24, 190.5)
    s.text('Two slots in an L, on the bed outside the paper area (it moves with the bed). Each slot 15 mm long,\n'
           'an IR LED at one end, a PT1206BS at the other (on its side: it is top-view), each behind a slit.\n'
           'X beam: along Y, crossed by moving in X. Y beam: along X, crossed in Y. The pen does the L.\n'
           'Slits: two razor-blade edges, 0.2-0.3 mm apart, narrow across the pen\'s travel. Beam 1-2 mm over the bed:\n'
           'crossed 0.5-1.5 mm over the tip (its z from the load cell). Measure Y first, then cross X at every\n'
           'pen\'s same spot along the beam (a beam off square reads X off by its angle). Notes: limn/TODO.md, break-beam.', 15.24, 198.12)
    # its own board (thin, in the bed: beam_bed_board.kicad_pcb): 0805 resistors, off limn.kicad_pcb
    own_board(s, {'Resistor_SMD:R_0805_2012Metric': ' '.join(f'R{n}' for n in range(851, 862)),
                  'LED_SMD:LED_1206_3216Metric': 'D852 D853 Q853 Q854',
                  'Package_TO_SOT_SMD:SOT-23': 'Q851 Q852',
                  'Connector_PinHeader_2.54mm:PinHeader_1x05_P2.54mm_Vertical': 'J851',
                  'limn:Waveshare_RP2040_Tiny': 'U851'})


def own_board(s, fps, standalone=False):
    '''A sheet that is its own board (tools/mkboard.py makes its .kicad_pcb): footprints set, and every part
    "not on board", so Update PCB in limn.kicad_pro leaves limn.kicad_pcb (the plot bed board's) alone.
    standalone (the board\'s own project): only the parts without a footprint off the board.'''
    placed = set()
    for fp, refs in fps.items():
        for ref in refs.split():
            s.footprint(ref, fp)
            placed.add(stable('part', s.file, ref))
    for it in s.items:
        if standalone and it[0] == 'symbol' and str(find(it, 'uuid')[0][1]) in placed:
            continue
        if it[0] == 'symbol' and not str(it[1][1]).startswith('power:'):
            for x in it:
                if isinstance(x, list) and x[0] == 'on_board':
                    x[1] = 'no'


def pro_micro_mcu(s, ref, x, y, nets, V='+3V3_PB', raw=None, qwiic=True, usb_pads=None, glob=()):
    '''The plot bed\'s Pro Micro: `nets` maps GPIO -> net (global if in `glob`), the other GPIOs get no-connect
    flags. usb_pads: (D+, D-) global nets on the pads underneath, the USB-C then unused on the board.'''
    PM_sym, w, h = boards.pro_micro()
    PM = s.add_block(PM_sym, w, h)
    s.place(PM, ref, 'SparkFun Pro Micro RP2040 (top view, USB-C up)', x, y)
    for n, number in boards.gpio_numbers(PM_sym).items():
        if n in nets:
            (s.glabel(nets[n], ref, number, stub=15.24) if nets[n] in glob else s.label(nets[n], ref, number))
        else:
            s.nc(ref, number)
    a3, a4 = s.P(ref, '3'), s.P(ref, '4')
    s.wire(a3, (g(a3[0] - 5.08), a3[1]), (g(a4[0] - 5.08), a4[1]), a4, chamfer=0)   # the symbol sits on a corner
    s.power_at('GND', (g(a3[0] - 5.08), a3[1]), 180)
    gnd(s, ref, '14')
    v = s.P(ref, '16')
    s.wire(v, (g(v[0] + 7.62), v[1]), (g(v[0] + 7.62), g(v[1] - 12.7)))
    s.power_at('+3V3', (g(v[0] + 7.62), g(v[1] - 12.7)), net=V)
    if qwiic:
        gnd(s, ref, '25')
        s.power('+3V3', ref, '26', net=V)
    else:                                  # the Qwiic connector unused (no pads for it on a perfboard)
        s.nc(ref, '25')
        s.nc(ref, '26')
    if raw:                                # powered from a 5 V rail instead of the USB's VBUS
        r = s.P(ref, '13')
        s.wire(r, (g(r[0] + 2.54), r[1]), (g(r[0] + 2.54), g(r[1] - 10.16)), chamfer=0)
        s.power_at('+5V', (g(r[0] + 2.54), g(r[1] - 10.16)), net=raw)
    else:
        s.nc(ref, '13')
    s.nc(ref, '15')
    if usb_pads:
        s.nc(ref, '29')
        for number, net, drop in (('30', usb_pads[0], 5.08), ('31', usb_pads[1], 2.54)):   # out to the right, nested
            p = s.P(ref, number)
            end = (g(s.P(ref, '31')[0] + 17.78), g(p[1] + drop))
            s.wire(p, (p[0], end[1]), end, chamfer=0)
            s.glabel_at(net, end, 0)
    else:
        s.nc(ref, '29')                    # its USB-C: a cable to the Pi (the hub board's DN3 on the head cell's)
        s.nc(ref, '30')
        s.nc(ref, '31')


def tvs(s, ref, value, x, y, left=False):
    '''A unidirectional TVS standing up, pin 1 (K: the D_SMA / SOD-123F pad 1) on top at (x, y - 3.81).
    SMAJ3.3A on 3.3 V lines, SMF5.0A on 5 V; KiCad's SMAJ5.0A / SMF5V0A symbols.'''
    sym = s.use('Diode', 'SMF5V0A' if value.startswith('SMF') else 'SMAJ5.0A')
    s.place(sym, ref, value, x, y, rot=270)
    side_labels(s, x, y, left)
    gnd(s, ref, '2')
    return s.P(ref, '1')


def side_labels(s, x, y, left=False):
    '''The last placed part\'s Reference and Value beside it, to the right or left (a standing 2-pin part).'''
    sym = s.items[-1]
    rot = sym[2][3]                          # a field's angle follows the symbol's: keep it, text centred
    for it in sym:
        if isinstance(it, list) and it[0] == 'property' and it[1] in ('Reference', 'Value'):
            dy = -1.27 if it[1] == 'Reference' else 1.27
            off = 2.54 + 0.55 * len(it[2])
            it[3] = ['at', num(round(x - off if left else x + off, 2)), num(g(y + dy)), rot]
            it[4] = font()


def avdd_entry(s, cp, c, x, y, V='+3V3_PB'):
    '''The bulk and the ceramic cap where the 3V3 enters the analog side.'''
    s.place(s.use('Device', 'C_Polarized'), cp, '47u', x, y)
    s.place(s.use('Device', 'C'), c, '100n', g(x + 12.7), y)
    for ref in (cp, c):
        s.power('+3V3', ref, '1', net=V, show=ref == cp)
        gnd(s, ref, '2')


def touch_line(s, q_ref, rb, rpd, j, x0, y0, q_sym='Q_NPN_CBE', q_value='BC547', bed=None):
    '''GP6 -> NPN, open collector down the wire to the Melzi (its pull-up there). Title at (x0, y0).
    bed = (q, r): an AO3400 in series under the NPN, its gate from BED_PROBE_IN: the line is OK only while the
    head and the bed both say OK. A MOSFET: a base would clamp BED_PROBE at ~0.9 V and GP1 reads it too.'''
    R = s.use('Device', 'R')
    dx, dy = x0 - 322.58, y0 - 22.86       # drawn first at (322.58, 22.86)
    s.title_text('TOUCH LINE', x0, y0)
    q = s.use('Transistor_BJT', q_sym)
    s.place(q, q_ref, q_value, 363.22 + dx, 50.8 + dy)
    s.place(R, rb, '4k7', 344.17 + dx, 50.8 + dy, rot=90)
    s.label('TOUCH_GP', rb, '1')
    base = s.P(q_ref, 'B')
    node_b = (g(351.79 + dx), base[1])
    s.wire(s.P(rb, '2'), node_b, base)
    s.junction(node_b)
    s.place(R, rpd, '100k', node_b[0], g(node_b[1] + 6.35))
    s.wire(node_b, s.P(rpd, '1'))
    gnd(s, rpd, '2')
    note = ('GP6 high = the NPN conducts = the Melzi pin low = OK. A touch, a dead\nMCU (100k holds the base low) or a cut wire: the Melzi\'s pull-up\n(R401, sheet Melzi) wins = triggered.', x0, 66.04 + dy)
    if bed:
        q2, r2 = bed                       # an AO3400: SOT-23 G/S/D on the MMBT3904's B/E/C pads
        e = s.P(q_ref, 'E')
        s.place(s.use('Transistor_FET', 'Q_NMOS_GSD'), q2, 'AO3400', 363.22 + dx, g(e[1] + 12.7))
        s.wire(e, s.P(q2, 'D'))
        gnd(s, q2, 'S')
        s.place(R, r2, '1k', 344.17 + dx, s.P(q2, 'G')[1], rot=270)   # turned (the user, 2026-10-29)
        s.glabel('BED_PROBE', r2, '2', stub=0)    # as built (the user, 2026-10-24): the gate off the cable side of R969
        s.wire(s.P(r2, '1'), s.P(q2, 'G'))
        note = ('GP6 and BED_PROBE high = Q951 and Q952 conduct\n= the Melzi pin low = OK. A touch, a bed\'s\ntrigger (BED_PROBE low), a dead MCU (100k\nholds the base low) or a cut wire: the\nMelzi\'s pull-up (R401) wins = triggered.\nNo bed: R970 holds BED_PROBE high.', g(x0 + 17.78), 83.82 + dy)
    else:
        gnd(s, q_ref, 'E')
    col = s.P(q_ref, 'C')
    if j is None:                          # the line leaves through a cable drawn elsewhere
        s.wire(col, (col[0], g(col[1] - 5.08)))
        s.glabel_at('PROBE_A4', (col[0], g(col[1] - 5.08)), 90)
        s.text(*note)
        return
    J2 = s.use('Connector_Generic', 'Conn_01x02')
    s.place(J2, j, 'to the Melzi (EXT A4)', 393.7 + dx, g(col[1] - 7.62))
    j1, j2 = s.P(j, '1'), s.P(j, '2')
    s.wire(col, (col[0], j1[1]), (g(col[0] + 5.08), j1[1]), j1)
    s.glabel_at('PROBE_A4', (g(col[0] + 5.08), j1[1]), 90)
    s.wire(j2, (g(j2[0] - 5.08), j2[1]), (g(j2[0] - 5.08), g(j2[1] + 5.08)))
    s.power_at('GND', (g(j2[0] - 5.08), g(j2[1] + 5.08)))
    s.text(*note)




def _gnd_bus(s, ref, numbers):
    '''Adjacent connector pins joined, one GND below the last.'''
    bus = [s.P(ref, n) for n in numbers]
    bx = g(bus[0][0] + (-5.08 if s.away(ref, numbers[0]) == 180 else 5.08))
    for p in bus:
        s.wire(p, (bx, p[1]))
    for a, b in zip(bus, bus[1:]):
        s.wire((bx, a[1]), (bx, b[1]))
    for p in bus[1:-1]:
        s.junction((bx, p[1]))
    s.power_at('GND', (bx, bus[-1][1]))


def _pin_rail(s, ref, number, kind, net=None, up=True):
    '''A connector pin: out 2.54, then up (or down) to a rail.'''
    a = s.P(ref, number)
    dx = -2.54 if s.away(ref, number) == 180 else 2.54
    end = (g(a[0] + dx), g(a[1] + (-5.08 if up else 5.08)))
    s.wire(a, (end[0], a[1]), end, chamfer=0)
    s.power_at(kind, end, net=net)


def _rail_bus(s, ref, numbers, kind, net):
    '''Adjacent connector pins joined, the rail above the first.'''
    bus = [s.P(ref, n) for n in numbers]
    bx = g(bus[0][0] + (-5.08 if s.away(ref, numbers[0]) == 180 else 5.08))
    for p in bus:
        s.wire(p, (bx, p[1]))
    for a, b in zip(bus, bus[1:]):
        s.wire((bx, a[1]), (bx, b[1]))
    s.wire((bx, bus[0][1]), (bx, g(bus[0][1] - 5.08)))
    s.junction((bx, bus[0][1]))
    for p in bus[1:-1]:
        s.junction((bx, p[1]))
    s.power_at(kind, (bx, g(bus[0][1] - 5.08)), net=net)


def board_link(s, ref, x, y, value, tool_en=True):
    '''The link between the hub board and the plot bed board, the same 6 pins at both ends: the hub\'s DN3
    (its 5 V, D+, D-), the tool\'s 5 V enable, MP_Buck1\'s 5 V (U956/U957: the bed, +5V_SW), GND.'''
    s.place(s.use('Connector_Generic', 'Conn_01x06'), ref, value, x, y)
    _pin_rail(s, ref, '1', '+5V', '+5V_HUB')
    s.glabel('PM_USB_DP', ref, '2', stub=7.62)
    s.glabel('PM_USB_DN', ref, '3', stub=7.62)
    if tool_en:
        s.glabel('TOOL_5V_EN', ref, '4', stub=7.62)
    end = s.out(ref, '5', 7.62)
    s.wire(s.P(ref, '5'), end)
    s.power_at('+5V', end, ang=s.away(ref, '5'), net='+5V_TOOL_IN')
    _pin_rail(s, ref, '6', 'GND', up=False)


def plot_bed_board_sheet(s):
    '''The plot bed board (limn.kicad_pcb) and what hangs off it, one sheet (2026-10-23: the head cell and the
    bed dock were two). The head cell (TODO.md, the load cell in the Plot-Toolchanger-Connector): two strips,
    4 BF350s in one full bridge on Rider-HS, a CAT6 cable through the chain to the board at the back (one
    ADS1220). The board also reads the tool's ID line, turns the tool's 5 V on (the switch: on the hub board)
    and does the bed dock's work (bed_dock_part, below). Its pins as micropython/nodes/plot_bed.json: the sum
    chip, the feet chip not fitted.'''
    node = json.loads((NODES / 'plot_bed.json').read_text())
    R, C = s.use('Device', 'R'), s.use('Device', 'C')
    V = '+3V3_PH'                    # the board's 3V3 (the plot bed board, as built for the head cell)

    def p3(ref, number, stub=0, show=True):
        s.power('+3V3', ref, number, net=V, stub=stub, show=show)

    def gnd_bus(ref, numbers):
        _gnd_bus(s, ref, numbers)

    def pin_rail(ref, number, kind, net=None, up=True):
        _pin_rail(s, ref, number, kind, net, up)

    def rail_bus(ref, numbers, kind='+3V3', net=V):
        _rail_bus(s, ref, numbers, kind, net)

    s.title_text('THE BRIDGE (4 x BF350)', 22.86, 22.86)
    for x, (top, tv), (bot, bv), mid in ((33.02, ('SG951', 'BF350 1A'), ('SG952', 'BF350 1B'), 'SIG_N'),
                                         (71.12, ('SG953', 'BF350 2A'), ('SG954', 'BF350 2B'), 'SIG_P')):
        s.place(R, top, tv, x, 50.8, on_board=False, left=True, note=f'{tv}: glued on the strip, off the board')
        s.place(R, bot, bv, x, g(50.8 + 7.62), on_board=False, left=True, note=f'{bv}: glued on the strip, off the board')
        s.glabel('CELL_EXC_P', top, '1', stub=2.54)      # the head's nets (sheet Toolhead): to the rails via W951
        s.glabel('CELL_EXC_N', bot, '2', stub=2.54)
        m = s.P(top, '2')
        s.wire(m, (g(m[0] + 7.62), m[1]))
        s.junction(m)
        s.glabel_at(f'CELL_{mid}', (g(m[0] + 7.62), m[1]), 0)
    s.text('Strip 1 (lower): 1A up (inner), 1B under.\nStrip 2 (upper): 2A down (inner), 2B on top.\n'
           'Upper faces 1A + 2B: opposite arms;\n2A + 1B: the other pair.', 22.86, 81.28)

    s.text('Strips and gauges on the cell; the 4 wires to the\ntoolhead PCB\'s J501, then the FFC and CAT6\n(sheet Toolhead).', 22.86, 92.71)
    s.enclose(15.24, 17.78, 96.52, 101.6, 'At the toolhead (the cell on Rider-HS)')

    J8 = s.use('Connector_Generic', 'Conn_01x08')
    s.title_text('CAT6: THE BRIDGE PAIRS', 22.86, 111.76)
    CW = s.add_block(*boards.cat6_bridge())
    s.place(CW, 'W951', 'CAT6 UTP 32 AWG', 63.5, 129.54, on_board=False, note='the cable: one wire each, end to end')
    for name, net in (('E+ w-orange', 'CELL_EXC_P'), ('S+ w-blue', 'CELL_SIG_P'), ('S- blue', 'CELL_SIG_N'), ('E- orange', 'CELL_EXC_N')):
        s.glabel(net, 'W951', name, stub=5.08)
    pin_rail('W951', 'E+', '+3V3', V)
    s.label('SIG_P', 'W951', 'S+', stub=5.08)
    s.label('SIG_N', 'W951', 'S-', stub=5.08)
    pin_rail('W951', 'E-', 'GND', up=False)
    s.text('Its own symbol so the head\'s E+/E- stay nets of their\nown (CELL_*), out of the toolhead PCB\'s GND:\n'
           'they meet the rails only here, at J952. Off any\nboard: J952 is where it lands.', 22.86, 147.32)

    s.title_text('CAT6 UTP, 0.6-1 m', 104.14, 101.6)
    s.text('Stranded (patch) cable, through\nthe cable chain. MX1.25 here.\n\n'
           'Pad: wire = signal\n'
           '1: white-orange = E+ (3V3)\n8: orange = E- (GND)\n'
           '3: white-blue = S+ (SIG_P)\n4: blue = S- (SIG_N)\n'
           '5: white-green = TOOL_ID\n6: green = GND (the ID\'s return)\n'
           '2, 7: white-brown, brown = spare\n\n'
           'All DC.\n'
           'Head end: the axis breakout\n(sheet Toolhead).', 104.14, 106.68)
    s.title_text('TOOL 5 V + USB', 104.14, 172.72)
    s.text('A USB-C cable from the hub\nboard (U1007) to the axis\nbreakout: it passes this\nboard by.', 104.14, 177.8)

    s.place(J8, 'J952', 'CAT6', 180.34, 124.46)      # pads 2, 6, 7 spare: split to 1x1s below, without them
    pin_rail('J952', '1', '+3V3', V)
    s.label('SIG_P', 'J952', '3', stub=2.54)
    s.label('SIG_N', 'J952', '4', stub=2.54)
    s.glabel('TOOL_ID', 'J952', '5', stub=7.62)
    gnd_bus('J952', '68')                          # 6: green, the ID's return (2026-10-29)

    board_link(s, 'J957', 180.34, 180.34, 'to the hub board (J1002)', tool_en=False)   # pin 4 out (the user, 2026-10-24)
    s.text('J957: the hub\'s DN3 (5 V on RAW,\nD+/D- on the pads underneath),\nGP9 to the tool\'s switch, +5V_TOOL_IN.', 190.5, 203.2)

    s.title_text('RC FILTERS', 190.5, 22.86)      # the user's layout (KiCad, 2026-10-20): C953 straight across
    yp, yn = 43.18, 60.96
    s.place(R, 'R951', '1k', 193.04, yp, rot=90)
    s.place(R, 'R952', '1k', 193.04, yn, rot=90)
    s.label('SIG_P', 'R951', '1')
    s.label('SIG_N', 'R952', '1')
    s.place(C, 'C951', '4n7 C0G', 203.2, 50.8)
    s.place(C, 'C952', '4n7 C0G', 210.82, 64.77)
    s.place(C, 'C953', '47n', 223.52, 50.8)
    s.wire(s.P('R951', '2'), (203.2, yp))
    s.wire((203.2, yp), s.P('C951', '1'))
    s.wire((203.2, yp), (223.52, yp))
    s.wire((223.52, yp), s.P('C953', '1'))
    s.wire((223.52, yp), (241.3, yp))
    s.wire(s.P('R952', '2'), (210.82, yn))
    s.wire((210.82, yn), (223.52, yn))
    s.wire((223.52, yn), (241.3, yn))
    s.wire(s.P('C953', '2'), (223.52, yn))
    s.wire(s.P('C951', '2'), (203.2, 71.12))
    s.wire((203.2, 71.12), (210.82, 71.12))
    s.wire(s.P('C952', '2'), (210.82, 71.12))
    s.wire((210.82, 71.12), (210.82, 73.66))
    s.power_at('GND', (210.82, 73.66))
    for pt in ((203.2, yp), (223.52, yp), (210.82, yn), (223.52, yn), (210.82, 71.12)):
        s.junction(pt)
    s.label_at('AIN_P', (241.3, yp), 0)
    s.label_at('AIN_N', (241.3, yn), 0)

    s.title_text('TOOL DETECT (the coupling\'s ID line)', 190.5, 81.28)
    s.place(R, 'R956', '100R', 210.82, 106.68, rot=90)
    s.place(s.use('Diode', 'SMAJ5.0A'), 'D951', 'SMAJ3.3A', 200.66, 114.3, rot=270)
    side_labels(s, 200.66, 114.3)
    gl, xt = (g(190.5), 106.68), s.P('D951', '1')[0]
    tv_top = min((s.P('D951', '1'), s.P('D951', '2')), key=lambda p: p[1])
    tv_bot = max((s.P('D951', '1'), s.P('D951', '2')), key=lambda p: p[1])
    s.wire(gl, (xt, gl[1]))
    s.wire((xt, gl[1]), s.P('R956', '1'))
    s.wire((xt, gl[1]), tv_top)
    s.junction((xt, gl[1]))
    s.glabel_at('TOOL_ID', gl, 180)
    s.power_at('GND', tv_bot)
    node_y = s.P('R956', '2')[1]
    s.place(R, 'R957', '10k', 220.98, g(node_y - 3.81))
    s.place(R, 'R958', '1k', 231.14, g(node_y - 3.81))   # fitted (the user, 2026-10-23)
    p3('R957', '1')
    s.label('ID_PU', 'R958', '1', stub=2.54)
    s.wire(s.P('R956', '2'), (220.98, node_y))
    s.wire((220.98, node_y), (231.14, node_y))
    s.wire((231.14, node_y), (243.84, node_y))
    s.junction((220.98, node_y))
    s.junction((231.14, node_y))
    s.label_at('TOOL_ID_IN', (243.84, node_y), 0)
    s.text('Unpowered tool: its ID resistor to GND against R957, read on\nGP26 (ADC0): open = no tool, ~0 = passive, mid = power it.\n'
           'Later the same pin is the tool\'s half-duplex link (PIO), with\nR958 as the strong pull-up from GP27 (driven high only then).\n'
           'No big cap here: it is the data line too.', 190.5, 121.92)

    s.title_text('AVDD_A ENTRY', 190.5, 149.86)
    avdd_entry(s, 'C955', 'C956', 200.66, 165.1, V)

    s.title_text('TOOL 5 V', 279.4, 175.26)
    s.text('On the hub board now (sheet Hub board): MP_Buck1,\nthe Pololu switch, the fuse and the tool\'s USB-C (U1007).\nGP9 and J957\'s pin 4 (TOOL_5V_EN) are out (the user,\n2026-10-24): the hub board\'s 100k holds it off.', 279.4, 180.34)

    # INDICATORS out (the user, 2026-10-24: board space): the Pro Micro's NeoPixel instead

    spi, total = node['spi'], node['sum_adc']
    s.title_text('ADS1220 MODULE', 256.54, 22.86)
    ADS = s.add_block(*boards.ads1220_module())
    s.place(ADS, 'U951', 'ADS1220 module (the sum chip)', 284.48, 60.96)
    for name, net in (('AIN0', 'AIN_P'), ('AIN1', 'AIN_N')):
        s.label(net, 'U951', name)
    s.nc('U951', 'AIN2')
    s.nc('U951', 'AIN3')
    for name in ('AVDD', 'DVDD', 'REFP0'):
        p3('U951', name, show=name == 'AVDD')
    for name in ('AGND', 'DGND', 'REFN0'):
        gnd(s, 'U951', name)
    for name, net in (('MISO', 'CIPO'), ('MOSI', 'COPI'), ('SCLK', 'SCK'), ('CS', 'CS2'), ('DRDY', 'DRDY2')):
        s.label(net, 'U951', name)
    s.nc('U951', 'CLK')

    s.title_text('SPARKFUN PRO MICRO RP2040', 317.5, 22.86)
    pro_micro_mcu(s, 'U952', 350.52, 76.2, {spi['sck']: 'SCK', spi['mosi']: 'COPI', spi['miso']: 'CIPO',
                                            21: 'CS2', total['drdy']: 'DRDY2', 2: 'TOUCH_GP',   # the user's: GP2, not GP6
                                            26: 'TOOL_ID_IN', 27: 'ID_PU', 29: 'BED_DET_IN',   # GP3 (LED), GP9 (tool 5 V): out (the user, 2026-10-24)
                                            0: 'BED_IO', 1: 'BED_PROBE_IN', 4: 'BED_EN', 5: 'SW_5V_EN'}, V,
                  raw='+5V_HUB', qwiic=False, usb_pads=('PM_USB_DP', 'PM_USB_DN'),
                  glob={'BED_DET_IN', 'BED_IO', 'BED_PROBE_IN', 'BED_EN', 'SW_5V_EN'})
    s.text('USB: the hub\'s DN3 on J957\n(5 V on RAW). Its USB-C: only\nfor the board alone, J957 out.', 370.84, 109.22)
    touch_line(s, 'Q951', 'R954', 'R955', 'J953', 317.5, 114.3, 'Q_NPN_BEC', 'MMBT3904 / BC847 (SOT-23)', bed=('Q952', 'R959'))

    notes = [
        (22.86, 'POWER', 'The board: the hub\'s DN3 on J957 (+5V_HUB on RAW, +3V3_PH = E+).\nAlone: its own USB-C, J957 unplugged (never both: two hosts).\nThe tool\'s 5 V and its return: the hub board only, not on this board.'),
        (110.49, 'THE BRIDGE', 'One full bridge, closed at the gauges: orange = E, blue = S.\nWhite-green: the tool\'s ID. Green and the browns: spare.\nSign and grams on the bench; diag() noise with a tool going on and off.'),
        (198.12, 'THE ADC', 'The plot bed board\'s sum chip: AIN0-AIN1, 330/s, DRDY2 = the touch IRQ.\nRatiometric: REFP0/REFN0 on the 3V3 that feeds E+.\nThe feet chip (CS1/DRDY1) is not fitted: firmware reports it missing.'),
        (288.29, 'THE TOOL', 'GP26: the ID (later the link), GP27: its pull-up, GP9:\nthe tool\'s 5 V. Data pins inputs until the tool has 5 V.\nGP21: CS2 now (was GP8; no feet chip: plot_bed.json\'s feet CS),\nGP2: TOUCH_GP (was GP6). GP28 free (the QRE: set aside).'),
    ]
    for x, head, body in notes:
        s.title_text(head, x, 218.44)
        s.text(body, x, 223.52)
    s.enclose(154.94, 17.78, 408.94, 210.82, 'The plot bed board, at the back (one ADS1220)')

    s.paper = 'A2'                    # the bed dock's part below, drawn at its own place and moved down
    start = len(s.items)
    bed_dock_part(s, V)
    J = s.use('Connector_Generic', 'Conn_01x05')
    s.place(J, 'J701', 'pogo, dock side (magnetic, 5)', 353.06, 48.26, on_board=False)
    for p, net in (('1', 'BED_PWR'), ('3', 'BED_DETECT'), ('4', 'BED_DATA'), ('5', 'BED_PROBE')):
        s.glabel(net, 'J701', p, stub=7.62)
    gnd(s, 'J701', '2', stub=2.54)
    s.text('Pins: power, GND, DETECT, DATA, PROBE (their\norder on the connector: to fill in). A 5-wire\n'
           'cable to J958. The Dock MCU (lrt_dock_mcu.py)\nand its OR gate input are gone.', 302.26, 71.12)
    s.enclose(297.18, 30.48, 406.4, 96.52, 'Bed connector (at the dock)')
    s.shift(start, 0, 228.6)
    for ref, keep in (('J952', '134568'), ('J953', None), ('J957', '12356'), ('J958', None), ('J959', None)):
        s.split(ref, keep)                # 1x1 headers (the user, 2026-10-23): each pin placed where its wiring wants

    # footprints for a perfboard layout: SMD in 0805 (the user's, 2026-10-23), modules from limn.pretty
    fps = {'Resistor_SMD:R_0805_2012Metric': 'R951 R952 R954 R955 R956 R957 R958 R959',
           'Capacitor_SMD:C_0805_2012Metric': 'C951 C952 C953 C956',
           'Capacitor_THT:CP_Radial_D5.0mm_P2.50mm': 'C955',
           'Diode_SMD:D_SMA': 'D951',
           'Package_TO_SOT_SMD:SOT-23': 'Q951 Q952',
           'limn:ADS1220_module': 'U951',
           'limn:SparkFun_Pro_Micro_RP2040': 'U952'}
    for fp, refs in fps.items():
        for ref in refs.split():
            s.footprint(ref, fp)


def hub_sheet(s):
    '''The hub board (the user\'s plan, 2026-10-20): the FE1.1s hub on its own cable from the Pi (the Pi powers
    the hub), the tool\'s 5 V (MP_Buck1 from 9 V, the Pololu switch, a polyfuse) and the tool\'s USB-C cable. Data
    only to the self-powered Melzi, the tool and the Aux MCU; the plot bed board takes the hub\'s 5 V.'''
    R = s.use('Device', 'R')
    s.title_text('HUB BOARD: the USB hub and the tool\'s 5 V', 15.24, 15.24)

    s.title_text('USB IN: THE PI', 22.86, 33.02)
    UC = s.add_block(*boards.usb_pads('USB-C_breakout', 'Adafruit USB-C breakout: 5.1k on CC1/CC2 (a device), '
                                      'both D+/D- pairs joined', 'Adafruit USB-C breakout', vbus='power_out'))
    s.place(UC, 'U1001', 'Adafruit USB-C breakout', 63.5, 55.88)
    s.glabel('USB_HUB', 'U1001', 'cable', stub=7.62)
    _pin_rail(s, 'U1001', 'VBUS', '+5V', '+5V_HUB')
    s.label('UP_DP', 'U1001', 'D+', stub=5.08)
    s.label('UP_DN', 'U1001', 'D-', stub=5.08)
    gnd(s, 'U1001', 'GND', stub=5.08)
    s.text('From a Pi 4 USB-A port (sheet Host),\nan A-to-C cable. VBUS: the Pi\'s 5 V,\nall the hub needs.', 33.02, 76.2)

    s.title_text('FE1.1s HUB', 106.68, 33.02)
    HUB = s.add_block(*boards.usb_hub())
    s.place(HUB, 'U1002', 'FE1.1s USB hub breakout', 137.16, 58.42)
    _pin_rail(s, 'U1002', '5V', '+5V', '+5V_HUB')
    gnd(s, 'U1002', 'GND', stub=5.08)
    s.label('UP_DP', 'U1002', 'UP D+', stub=5.08)
    s.label('UP_DN', 'U1002', 'UP D-', stub=5.08)
    for port, dp, dn, glob in (('DN1', 'MELZI_DP', 'MELZI_DN', False), ('DN2', 'TOOL_USB_DP', 'TOOL_USB_DN', True),
                               ('DN3', 'PM_USB_DP', 'PM_USB_DN', True), ('DN4', 'AUX_DP', 'AUX_DN', False)):
        for pn, net in ((f'{port} D+', dp), (f'{port} D-', dn)):
            (s.glabel if glob else s.label)(net, 'U1002', pn, stub=5.08)
    s.text('DN1: the Melzi, DN2: the tool (U1007),\nDN3: the plot bed board (J1002), DN4: the Aux\n'
           'MCU. DN1, DN2, DN4: data only, their VBUS\npads not connected. One TT: the full-speed\n'
           'MCUs share 12 Mbit/s; the Pi Zero tool\n(high speed) has the 480.', 106.68, 83.82)

    s.title_text('USB OUT: CABLES', 200.66, 33.02)
    CAB = s.add_block(*boards.usb_pads('USB_cable_pads', 'A USB cable cut and soldered to the board: VBUS, D+, D-, GND',
                                       'USB cable (cut)'))
    s.place(CAB, 'U1003', 'USB cable to the Melzi', 223.52, 50.8)
    s.nc('U1003', 'VBUS')
    s.label('MELZI_DP', 'U1003', 'D+', stub=5.08)
    s.label('MELZI_DN', 'U1003', 'D-', stub=5.08)
    gnd(s, 'U1003', 'GND', stub=5.08)
    s.glabel('USB_MELZI', 'U1003', 'cable', stub=7.62)
    s.place(CAB, 'U1004', 'USB cable to the Aux MCU', 223.52, 81.28)
    s.nc('U1004', 'VBUS')
    s.label('AUX_DP', 'U1004', 'D+', stub=5.08)
    s.label('AUX_DN', 'U1004', 'D-', stub=5.08)
    gnd(s, 'U1004', 'GND', stub=5.08)
    s.glabel('USB_AUX', 'U1004', 'cable', stub=7.62)
    s.text('The Melzi: its own 12 V, VBUS cut.\nThe Aux MCU: MP_Buck0, VBUS cut.', 200.66, 99.06)

    s.title_text('TO THE PLOT BED BOARD', 279.4, 33.02)
    board_link(s, 'J1002', 289.56, 55.88, 'to the plot bed board (J957)')
    s.text('The hub\'s DN3 + 5 V: the Pro Micro\'s\nRAW and its D+/D- pads underneath.\n'
           'TOOL_5V_EN: GP9 back to U1006.\n+5V_TOOL_IN: the bed + LEDs\n(U956/U957 there).', 279.4, 76.2)
    s.enclose(17.78, 25.4, 340.36, 116.84, 'USB')

    s.title_text('TOOL 5 V: MP_BUCK1 FROM 9 V', 22.86, 132.08)
    s.place(s.use('Connector_Generic', 'Conn_01x02'), 'J1001', '9 V in (Trigger1)', 40.64, 152.4)
    _pin_rail(s, 'J1001', '1', '+9V')
    _pin_rail(s, 'J1001', '2', 'GND', up=False)
    BK = s.add_block(*boards.mini_buck())
    s.place(BK, 'U1005', 'Mini buck 3 A, 5 V (MP_Buck1)', 96.52, 154.94)
    _pin_rail(s, 'U1005', 'IN+', '+9V')
    _pin_rail(s, 'U1005', 'IN-', 'GND', up=False)
    _pin_rail(s, 'U1005', 'OUT+', '+5V', '+5V_TOOL_IN')
    _pin_rail(s, 'U1005', 'OUT-', 'GND', up=False)
    s.text('+9V: the PD trigger on C1 (sheet Power).\nIts 5 V jumper set; 47-100 uF at its input\n(hot-plug ringing).', 33.02, 175.26)

    MS = s.add_block(*boards.pololu_mosfet())
    s.place(MS, 'U1006', 'Pololu mini slide sw. #2810', 170.18, 154.94)
    vin, ctrl, gpin = s.P('U1006', 'VIN'), s.P('U1006', 'ON'), s.P('U1006', 'GND')
    s.wire(vin, (g(vin[0] - 2.54), vin[1]), (g(vin[0] - 2.54), g(vin[1] - 5.08)), chamfer=0)
    s.power_at('+5V', (g(vin[0] - 2.54), g(vin[1] - 5.08)), net='+5V_TOOL_IN')
    s.wire(gpin, (g(gpin[0] - 2.54), gpin[1]), (g(gpin[0] - 2.54), g(gpin[1] + 5.08)), chamfer=0)
    s.power_at('GND', (g(gpin[0] - 2.54), g(gpin[1] + 5.08)))
    t = (g(ctrl[0] - 10.16), ctrl[1])
    s.wire(ctrl, t)
    s.place(R, 'R1001', '1k', g(t[0] - 7.62), t[1], rot=90)
    s.wire(s.P('R1001', '2'), t)
    s.junction(t)
    s.glabel('TOOL_5V_EN', 'R1001', '1', stub=5.08)
    s.place(R, 'R1002', '100k', t[0], g(t[1] + 7.62), left=True)
    s.wire(t, s.P('R1002', '1'))
    gnd(s, 'R1002', '2')
    s.place(s.use('Device', 'Polyfuse'), 'F1001', 'PPTC 1812 1A 6V', g(s.P('U1006', 'VOUT')[0] + 15.24),
            s.P('U1006', 'VOUT')[1], rot=90)
    s.wire(s.P('U1006', 'VOUT'), s.P('F1001', '1'))
    f2 = s.P('F1001', '2')
    a = (g(f2[0] + 2.54), f2[1])
    s.wire(f2, a)
    s.wire(a, (a[0], g(a[1] - 5.08)))
    s.power_at('+5V', (a[0], g(a[1] - 5.08)), net='+5V_TOOL')
    s.flag_at(f2)
    s.text('On only when the host says so (key locked, the ID\nsays "power me"): GP9 on the plot bed board, over\n'
           'J1002. R1002 holds it off with the link out or\nthrough a reset. Slide switch at OFF (else always on).', 132.08, 175.26)

    UT = s.add_block(*boards.usb_pads('USB-C_breakout_tool', 'Adafruit USB-C breakout (5.1k on CC1/CC2), the tool\'s '
                                      'cable: VBUS fed from +5V_TOOL', 'Adafruit USB-C breakout'))
    s.place(UT, 'U1007', 'Adafruit USB-C breakout (the tool)', 266.7, 157.48)
    _pin_rail(s, 'U1007', 'VBUS', '+5V', '+5V_TOOL')
    s.glabel('TOOL_USB_DP', 'U1007', 'D+', stub=7.62)
    s.glabel('TOOL_USB_DN', 'U1007', 'D-', stub=7.62)
    gnd(s, 'U1007', 'GND', stub=5.08)
    s.glabel('USB_TOOL', 'U1007', 'cable', stub=7.62)
    s.text('The tool\'s USB-C cable (sheet Toolhead,\nW501; 3 A, USB 2.0): VBUS = +5V_TOOL\nafter F1001, D+/D- = DN2. The cable\n'
           'carries the 5 V and the GND the FFC\ntakes to the coupling (1 A).', 284.48, 172.72)
    s.enclose(17.78, 124.46, 340.36, 198.12, 'The tool\'s 5 V and its USB-C cable')

    notes = [
        (22.86, 'POWER', '+5V_HUB: the Pi\'s VBUS: the hub, the plot bed board\n(RAW): ~0.1-0.3 A of the Pi 4\'s\n'
                '1.2 A (all its ports together). +5V_TOOL_IN: MP_Buck1:\nthe tool (U1006, F1001), the bed and\n+5V_SW (U956/U957); never tied to +5V_HUB.'),
        (106.68, 'GROUND', 'One GND: the Pi\'s (USB), the 9 V\'s, the tool\'s\nreturn, the link\'s. The tool\'s current stays\n'
                 'on this board (U1007 to J1001); the link\'s\nGND carries only the plot bed board.'),
        (190.5, 'ON ITS OWN', 'Pi + 9 V, J1002 out: the hub and its ports\nwork, the tool stays off (R1002). The plot\n'
                'bed board alone: its own USB-C, J957 out.'),
        (274.32, 'THE TOOL (PI ZERO)', '~0.2 A measured. It enumerates when U1006\nturns on (its D+ pull-up runs from its\n'
                 'own 5 V). Shut it down over USB before\nGP9 drops its 5 V (or a read-only root).'),
    ]
    for x, head, body in notes:
        s.title_text(head, x, 213.36)
        s.text(body, x, 218.44)
    # its own perfboard (hub_board.kicad_pcb): SMD in 0805 / the fuse in 1812, modules from limn.pretty
    own_board(s, {'limn:Adafruit_USB_C_breakout': 'U1001 U1007', 'limn:FE1.1s_USB_hub_breakout': 'U1002',
                  'limn:USB_cable_pads': 'U1003 U1004', 'limn:Mini_buck_3A': 'U1005',
                  'limn:Pololu_Mini_MOSFET_Slide_Switch': 'U1006',
                  'Resistor_SMD:R_0805_2012Metric': 'R1001 R1002', 'Fuse:Fuse_1812_4532Metric': 'F1001',
                  'Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical': 'J1001',
                  'Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical': 'J1002'})

def bed_dock_part(s, V):
    '''The bed dock\'s work on the plot bed board (the user, 2026-10-20): DETECT on GP29 (ADC3), the bed chain\'s
    UART on GP0/1, two slide switches on GP4/5 (the bed\'s 5 V, +5V_SW), J958 to the pogo at the dock. Drawn below the board on
    sheet Plot bed board, at its own place (shifted there); the Pro Micro by global labels. Refs 95x.'''
    R = s.use('Device', 'R')
    s.title_text('DETECT', 86.36, 38.1)
    y = 50.8                                     # ESD at the cable, 100R, the 10k pull-up at the ADC
    s.place(R, 'R965', '100R', 106.68, y, rot=90)
    s.place(s.use('Diode', 'SMAJ5.0A'), 'D952', 'SMAJ3.3A', 96.52, g(y + 7.62), rot=270)
    side_labels(s, 96.52, g(y + 7.62))
    xt = s.P('D952', '1')[0]
    top = min((s.P('D952', '1'), s.P('D952', '2')), key=lambda p: p[1])
    bot = max((s.P('D952', '1'), s.P('D952', '2')), key=lambda p: p[1])
    s.wire((88.9, y), (xt, y))
    s.wire((xt, y), s.P('R965', '1'))
    s.wire((xt, y), top)
    s.junction((xt, y))
    s.glabel_at('BED_DETECT', (88.9, y), 180)
    s.power_at('GND', bot)
    s.place(R, 'R966', '10k', 119.38, g(y - 3.81))
    s.power('+3V3', 'R966', '1', net=V)
    s.wire(s.P('R965', '2'), (119.38, y))
    s.wire((119.38, y), (134.62, y))
    s.junction((119.38, y))
    s.glabel_at('BED_DET_IN', (134.62, y), 0)
    s.text('GP29 (ADC3): the bed\'s ID resistor against R966\n(BED_1..6 = 2.2k..33k); > 55000 = no bed.\n'
           'Only the ID: the trigger has its own wire.', 86.36, 68.58)

    s.title_text('BED DATA + BED PROBE', 86.36, 81.28)
    for i, (rs, rp, cable, mcu, pull) in enumerate((('R967', 'R968', 'BED_DATA', 'BED_IO', '4k7'),
                                                     ('R969', 'R970', 'BED_PROBE', 'BED_PROBE_IN', '10k'))):
        yy = g(101.6 + 20.32 * i)
        s.place(R, rs, '100R', 106.68, yy, rot=90)
        s.wire((88.9, yy), (96.52, yy))
        s.wire((96.52, yy), s.P(rs, '1'))
        if cable == 'BED_PROBE':                 # no TVS on BED_DATA: its nF would slow the 115200 link
            s.wire((96.52, yy), tvs(s, 'D957', 'SMAJ3.3A', 96.52, g(yy + 7.62)))
            s.junction((96.52, yy))
        s.glabel_at(cable, (88.9, yy), 180)
        s.place(R, rp, pull, 119.38, g(yy - 3.81))
        s.power('+3V3', rp, '1', net=V)
        s.wire(s.P(rs, '2'), (119.38, yy))
        s.wire((119.38, yy), (134.62, yy))
        s.junction((119.38, yy))
        s.glabel_at(mcu, (134.62, yy), 0)
    s.text('BED_DATA: a half-duplex UART on one wire (GP0, PIO open-drain,\nlib/link.py). BED_PROBE: the bed\'s trigger, high = OK, low = triggered:\n'
           'GP1 reads it, and Q952 (the touch line, above) puts it in series with\nthe touch line in hardware. R970 holds it OK with no bed.', 86.36, 144.78)

    s.title_text('SWITCHED 5 V', 172.72, 38.1)  # two slide switches on MP_Buck1 (the user, 2026-10-23: the Dock's U955 and JP951 out)
    MS = s.add_block(*boards.pololu_mosfet())
    for sw, rs, rpd, en, fuse, y in (('U956', 'R971', 'R972', 'BED_EN', 'F952', 60.96),
                                     ('U957', 'R973', 'R974', 'SW_5V_EN', 'F953', 96.52)):
        s.place(MS, sw, 'Pololu mini slide sw. #2810', 228.6, y)
        vin, ctrl, gpin = s.P(sw, 'VIN'), s.P(sw, 'ON'), s.P(sw, 'GND')
        s.wire(vin, (g(vin[0] - 2.54), vin[1]), (g(vin[0] - 2.54), g(vin[1] - 5.08)), chamfer=0)
        s.power_at('+5V', (g(vin[0] - 2.54), g(vin[1] - 5.08)), net='+5V_TOOL_IN')
        s.wire(gpin, (g(gpin[0] - 2.54), gpin[1]), (g(gpin[0] - 2.54), g(gpin[1] + 5.08)), chamfer=0)
        s.power_at('GND', (g(gpin[0] - 2.54), g(gpin[1] + 5.08)))
        t = (g(ctrl[0] - 10.16), ctrl[1])
        s.wire(ctrl, t)
        s.place(R, rs, '1k', g(t[0] - 7.62), t[1], rot=90)
        s.wire(s.P(rs, '2'), t)
        s.junction(t)
        s.glabel(en, rs, '1', stub=5.08)
        s.place(R, rpd, '100k', t[0], g(t[1] + 7.62), left=True)
        s.wire(t, s.P(rpd, '1'))
        gnd(s, rpd, '2')
        o = s.P(sw, 'VOUT')
        s.place(s.use('Device', 'Polyfuse'), fuse, 'PPTC 1812 1A 6V', g(o[0] + 10.16), o[1], rot=90)
        s.wire(o, s.P(fuse, '1'))
        s.flag_at(s.P(fuse, '2'))
    f2 = s.P('F952', '2')
    s.wire(f2, (g(f2[0] + 7.62), f2[1]))
    s.glabel_at('BED_PWR', (g(f2[0] + 7.62), f2[1]), 0, shape='output')
    f3 = s.P('F953', '2')
    s.place(s.use('Connector_Generic', 'Conn_01x02'), 'J959', '+5V Toolchanger USB', g(f3[0] + 15.24), f3[1])  # the user's name (PCB, 2026-10-24)
    a = (g(f3[0] + 5.08), f3[1])
    s.wire(f3, a)
    s.wire(a, s.P('J959', '1'))
    s.wire(a, (a[0], g(a[1] - 5.08)))
    s.junction(a)
    s.power_at('+5V', (a[0], g(a[1] - 5.08)), net='+5V_SW')
    _pin_rail(s, 'J959', '2', 'GND', up=False)
    s.text('Both on MP_Buck1 (+5V_TOOL_IN over J957). GP4: U956,\nthe bed (BED_PWR, it takes little): on once the ID reads\n'
           'steady, off on "no bed" for 250 ms. GP5: U957, +5V_SW\non J959: the LEDs and whatever else needs 5 V.\n'
           'High = on; the 100k hold each off through a reset.\nSlide switches at OFF (else always on).', 172.72, 121.92)

    s.title_text('TO THE DOCK', 30.48, 38.1)
    s.place(s.use('Connector_Generic', 'Conn_01x05'), 'J958', 'to the bed dock (pogo)', 66.04, 104.14)
    for pn, net in (('1', 'BED_PWR'), ('3', 'BED_DETECT'), ('4', 'BED_DATA'), ('5', 'BED_PROBE')):
        s.glabel(net, 'J958', pn, stub=7.62)
    gnd(s, 'J958', '2', stub=2.54)
    s.text('A 5-wire cable\nto the pogo (J701).', 30.48, 119.38)
    s.enclose(25.4, 30.48, 284.48, 157.48, 'On the plot bed board: the bed dock\'s work (refs 95x; the Pro Micro above)')
    for fp, refs in {'Resistor_SMD:R_0805_2012Metric': 'R965 R966 R967 R968 R969 R970 R971 R972 R973 R974',
                     'Diode_SMD:D_SMA': 'D952 D957', 'Fuse:Fuse_1812_4532Metric': 'F952 F953',
                     'limn:Pololu_Mini_MOSFET_Slide_Switch': 'U956 U957'}.items():
        for ref in refs.split():
            s.footprint(ref, fp)
