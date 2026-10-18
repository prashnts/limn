# Limn KiCad generator - sheets: toolhead, Aux MCU, bed dock, calibration bed, plot bed, plot head cell
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# References: toolhead 5xx, Aux MCU 6xx, bed dock 7xx, calibration bed 8xx, plot bed 9xx (head cell 95x).
import json
from pathlib import Path
from . import boards
from .core import g
from .sheets_a import gnd, pins_named

NODES = Path(__file__).resolve().parents[3] / 'micropython/nodes'


def toolhead_sheet(s):
    s.title_text('TOOLHEAD: what rides the drag chain', 15.24, 15.24)
    mot = s.use('Motor', 'Stepper_Motor_bipolar')
    for ref, axis, value, x in (('M501', 'Z', 'NEMA 8, lead screw (Z)', 60.96), ('M502', 'K', '10 mm linear micro stepper (K, the key lock)', 129.54)):
        s.place(mot, ref, value, x, 63.5)
        for coil_pin, mp in (('1A', '1'), ('1B', '2'), ('2A', '3'), ('2B', '4')):
            s.glabel(f'MOT_{axis}_{coil_pin}', ref, mp, stub=7.62 if mp in '12' else 5.08)
    s.text('Z and K: 4 wires each in silicone ribbons, from the Melzi\'s\nX and Z ports (sheet Melzi), drivers at ~7.5 V.', 30.48, 81.28)
    sw = s.use('Switch', 'SW_Push')
    for i, (ref, name, value) in enumerate((('SW501', 'ENDSTOP_Y', 'Y endstop (micro switch)'),
                                            ('SW502', 'ENDSTOP_Z', 'Z top endstop (micro switch)'),
                                            ('SW503', 'ENDSTOP_K', 'K: the key\'s switch (lock)'))):
        y = 101.6 + 10.16 * i
        s.place(sw, ref, value, 63.5, y)
        s.glabel(name, ref, '1', shape='output', stub=5.08)
        gnd(s, ref, '2', stub=2.54)
    s.text('Micro switches KFC-W-13W / KFC-C-15A. K: triggered while\nthe key is open (manual_stepper axis_k, ^PA2).', 30.48, 132.08)
    BT = s.add_block(*boards.bltouch())
    s.place(BT, 'U501', 'BLTouch', 175.26, 109.22, dnp=True)
    for n in pins_named(s, 'U501', 'GND brown') + pins_named(s, 'U501', 'GND black'):
        gnd(s, 'U501', n, stub=5.08)
    s.power('+5V', 'U501', '+5V red', net='+5V_MELZI', stub=7.62)
    s.glabel('BLTOUCH_CTRL', 'U501', 'CTRL orange', shape='input', stub=7.62)
    s.glabel('BLTOUCH_SENSE', 'U501', 'SENSE white', shape='output', stub=7.62)
    s.enclose(142.24, 93.98, 205.74, 129.54, 'Gone: the BLTouch (no BLTouch planned)', planned=True)
    MPU = s.add_block(*boards.mpu9250())
    s.place(MPU, 'U502', 'MPU9250 (MPU9255)', 175.26, 154.94)
    s.power('+3V3', 'U502', 'VCC', net='+3V3_AUX', stub=7.62)
    gnd(s, 'U502', 'GND', stub=5.08)
    s.glabel('MPU_SCL', 'U502', 'SCL', shape='input', stub=7.62)
    s.glabel('MPU_SDA', 'U502', 'SDA', stub=7.62)
    s.text('Software I2C on the Aux Pico (gpio4/5), 0x68.\nVCC from the Pico\'s 3V3: to confirm.\nPlanned: an ADXL345 on a toolhead MCU instead.', 199.39, 147.32)
    EB = s.add_block(*boards.endoscope())
    s.place(EB, 'U503', 'Xitech USB camera board (0bde:8076)', 274.32, 60.96)
    s.glabel('USB_ENDO', 'U503', 'USB', stub=7.62)
    ES = s.add_block(*boards.endo_sensor())
    s.place(ES, 'U504', 'endoscope sensor', 345.44, 60.96)
    for k, p in enumerate(('VDD', 'VCLK', 'VOUT')):
        s.connect('U503', p, 'U504', p, lane=k - 1)
    gnd(s, 'U503', 'GND', stub=2.54)
    gnd(s, 'U504', 'GND', stub=2.54)
    s.text('Our adapter: a GND between VOUT and VCLK, short runs away from the\nstepper wires, decoupling on VDD at the sensor, never hot-plugged.\nLight: two fibers on the connector\'s optical port (an LED, planned).', 246.38, 76.2)
    s.enclose(241.3, 43.18, 375.92, 93.98, 'Endoscope camera')
    TC = s.add_block(*boards.tool_coupling())
    s.place(TC, 'U505', 'tool coupling', 302.26, 147.32, dnp=True)
    s.power('+5V', 'U505', '5V', net='+5V_TOOL', stub=7.62)
    gnd(s, 'U505', 'GND', stub=5.08)
    s.nc('U505', 'SPARE1')
    s.nc('U505', 'SPARE2')
    TM = s.add_block(*boards.toolhead_mcu())
    s.place(TM, 'U506', 'toolhead MCU', 340.36, 147.32, dnp=True)
    for p, net in (('ID', 'TOOL_ID'), ('EN', 'TOOL_EN'), ('PWM', 'TOOL_PWM')):
        s.label(net, 'U505', p, stub=5.08)
    for p, net in (('TOOL_ID', 'TOOL_ID'), ('TOOL_EN', 'TOOL_EN'), ('TOOL_PWM', 'TOOL_PWM')):
        s.label(net, 'U506', p, stub=5.08)
    s.glabel('TOOL_5V_EN', 'U506', 'EN_5V', shape='output', stub=5.08)
    s.nc('U506', 'LOCK')
    s.nc('U506', 'USB')
    s.nc('U506', '5V')
    gnd(s, 'U506', 'GND', stub=5.08)
    s.text('5 V + GND + data only (12 V stays motion-only).\nID (ADC), EN, PWM + 2 spare (UART/I2C, or the Pi\nZero\'s USB). Tethered tools: their own supply, EN/PWM\nthrough an isolator. A toolhead MCU (K, its endstop,\nADXL345, HX711, lock sensor) is planned with it.', 241.3, 165.1)
    s.enclose(236.22, 129.54, 375.92, 195.58, 'Planned: the tool coupling (docs/block-diagrams.md)', planned=True)
    s.title_text('THE DRAG CHAIN TODAY (21 wires)', 15.24, 205.74)
    s.text('- Z motor (4), K motor (4): silicone ribbons.  - A USB-C cable: the endoscope.\n'
           '- A ribbon: the Y, Z and K endstops, the MPU9250 (I2C), the BLTouch (5), 5 V / 3V3 and GND.\n'
           '- Mostly 26 AWG (~0.134 ohm/m), a short 30 AWG piece. On 5 V the drop counts twice (GND too).\n'
           '- The harness\'s connector pins, as the Excalidraw drawing has them: 1 3V3/5V, 4 stepper Z, 5 limit Z,\n'
           '  6 limit Y, 7 5V, 8 GND; tool side: 1 3V3/5V, 5 stepper K, 6 GND, 7 switch, 8 1-Wire. To fill in.', 15.24, 210.82)


def aux_sheet(s):
    s.title_text('AUX MCU: Klipper [mcu rpi], the Pico on the Aux PCB', 15.24, 15.24)
    PC = s.add_block(*boards.pico())
    s.place(PC, 'U601', 'Raspberry Pi Pico WH (rpi)', 101.6, 88.9)
    s.glabel('USB_AUX', 'U601', 'USB', stub=7.62)
    s.power('+3V3', 'U601', '3V3(OUT)', net='+3V3_AUX', stub=7.62)
    gnd(s, 'U601', 'GND', stub=5.08)
    s.label('VBUS_AUX', 'U601', 'VBUS', stub=7.62)
    s.nc('U601', 'VSYS')
    s.text('VSYS: from USB (VBUS) today? The Aux PCB\'s LM2596\nmay feed it: through a Schottky, max 5.5 V. To check.', 35.56, 116.84)
    s.glabel('MPU_SCL', 'U601', 'GP4', shape='output', stub=12.7)
    s.glabel('MPU_SDA', 'U601', 'GP5', stub=12.7)
    s.glabel('NEOPIXEL_INDOCK', 'U601', 'GP17', shape='output', stub=12.7)
    # buzzer: a 2N7000 from gpio9
    fet = s.use('Transistor_FET', '2N7000')
    s.place(fet, 'Q601', '2N7000', 172.72, 76.2)
    s.connect('U601', 'GP9', 'Q601', 'G')
    gnd(s, 'Q601', 'S', stub=2.54)
    bz = s.use('Device', 'Buzzer')
    s.place(bz, 'BZ601', 'buzzer', 177.8, 63.5)
    s.wire(s.P('Q601', 'D'), (g(s.P('Q601', 'D')[0]), g(s.P('BZ601', '2')[1])), s.P('BZ601', '2'))
    s.label('VBUS_AUX', 'BZ601', '1', stub=5.08)
    s.text('[pwm_cycle_time beeper], gpio9, 1 ms.\nBuzzer supply and any gate / flyback\nparts: from the photo, to confirm.', 190.5, 55.88)
    W1 = s.add_block(*boards.ws2812(32, 'Pimoroni Unicorn pHAT: 8 x 4 WS2812, GRB: the UI matrix', 'Unicorn pHAT (32 px)'))
    s.place(W1, 'U602', 'Unicorn pHAT, 32 px GRB (picam)', 190.5, 104.14)
    s.connect('U601', 'GP15', 'U602', 'DIN', lane=-1)
    s.power('+5V', 'U602', '5V', net='+5V_LED', stub=7.62)
    gnd(s, 'U602', 'GND', stub=5.08)
    W2 = s.add_block(*boards.ws2812(30, 'WS2812-type strip, 30 px, GRBW: the lamp', 'WS2812 x 30 GRBW (lamp)', name='WS2812_30_GRBW'))
    s.place(W2, 'U603', 'lamp, 30 px GRBW', 190.5, 132.08)
    s.connect('U601', 'GP16', 'U603', 'DIN', lane=1)
    s.power('+5V', 'U603', '5V', net='+5V_LED', stub=7.62)
    gnd(s, 'U603', 'GND', stub=5.08)
    s.text('GP17: the indockator, sheet Tool dock.\nLEDs at 5 V (+5V_LED: the MP1495 branch,\na Pi USB port for now). 3.3 V data: borderline.', 228.6, 99.06)
    s.enclose(53.34, 45.72, 279.4, 152.4, 'Aux PCB (limn-aux-pcb)')
    s.text('Planned: the Pico goes for a smaller MCU; the MPU9250 for an ADXL345 on the toolhead.', 53.34, 160.02)


def bed_dock_sheet(s):
    s.title_text('BED DOCK: the LRT Dock, an RP2040-Zero (MicroPython)', 15.24, 15.24)
    node = json.loads((NODES / 'dock.json').read_text())
    tx, rx = node['down']['tx'], node['down']['rx']
    Z = s.add_block(*boards.rp2040_zero('RP2040_Zero_dock', 'Waveshare RP2040-Zero: the Dock (lrt_dock_mcu.py). Used pins only',
                                        'RP2040-Zero (Dock)',
                                        [('GP7 PWR_OFF', 'output'), ('GP8 PWR_ON', 'output'), None, ('GP11 PROBE_OUT', 'output'), None,
                                         (f'GP{tx} UART0 TX', 'output'), (f'GP{rx} UART0 RX', 'input'), None, ('GP29 ADC3', 'input')],
                                        usb_powered=True))
    s.place(Z, 'U701', 'RP2040-Zero (Dock)', 88.9, 88.9)
    s.glabel('USB_DOCK', 'U701', 'USB', stub=7.62)
    s.label('5V_DOCK', 'U701', '5V', stub=7.62)
    s.label('3V3_DOCK', 'U701', '3V3', stub=7.62)
    gnd(s, 'U701', 'GND', stub=5.08)
    PS = s.add_block(*boards.pololu_switch())
    s.place(PS, 'U702', 'Pololu power switch (MosfetSw_LRT)', 180.34, 63.5)
    s.connect('U701', 'GP8 PWR_ON', 'U702', 'ON', lane=1)
    s.connect('U701', 'GP7 PWR_OFF', 'U702', 'OFF', lane=-1)
    s.label('5V_DOCK', 'U702', 'VIN', stub=5.08)
    gnd(s, 'U702', 'GND', stub=5.08)
    s.glabel('BED_PWR', 'U702', 'VOUT', shape='output', stub=7.62)
    s.text('100 ms pulses: PWR_ON once a bed\'s ID reads steady,\nPWR_OFF when DETECT says "no bed" for 250 ms.\nIt turns itself on after a power cycle. VIN: the\nDock\'s 5 V? To confirm, and the switch\'s model.', 152.4, 81.28)
    R = s.use('Device', 'R')
    det = s.P('U701', 'GP29 ADC3')
    xr = g(det[0] + 45.72)
    s.place(R, 'R701', '10k', xr, g(det[1] - 3.81))      # its pin 2 on the DETECT line
    s.label('3V3_DOCK', 'R701', '1', stub=2.54)
    s.wire(det, (xr, det[1]))
    s.wire((xr, det[1]), (g(xr + 10.16), det[1]))
    s.junction((xr, det[1]))
    s.glabel_at('BED_DETECT', (g(xr + 10.16), det[1]), 0)
    s.glabel('BED_TXD', 'U701', f'GP{tx} UART0 TX', shape='output', stub=17.78)
    s.glabel('BED_RXD', 'U701', f'GP{rx} UART0 RX', shape='input', stub=17.78)
    s.glabel('PROBE_OUT', 'U701', 'GP11 PROBE_OUT', shape='output', stub=17.78)
    s.text('DETECT: the bed\'s ID resistor against this 10k (BED_1..6 =\n2.2k..33k), a removal (> 55000), a bed node\'s touch (> 56000,\nrising, armed, "trigger": "detect"). GP11: the probe pulse (10 ms),\nonly as long as the OR gate is there.', 119.38, 132.08)
    s.enclose(50.8, 45.72, 236.22, 157.48, 'Bed dock (the Dock MCU and its power switch)')
    J = s.use('Connector_Generic', 'Conn_01x05')
    s.place(J, 'J701', 'pogo, dock side (magnetic, 5)', 299.72, 101.6)
    for p, net in (('1', 'BED_PWR'), ('3', 'BED_DETECT'), ('4', 'BED_TXD'), ('5', 'BED_RXD')):
        s.glabel(net, 'J701', p, stub=7.62)
    gnd(s, 'J701', '2', stub=2.54)
    s.text('Pins: power, GND, DETECT, TX, RX\n(their order on the connector: to fill in).', 269.24, 116.84)
    s.enclose(259.08, 83.82, 350.52, 127.0, 'Bed connector')


def cal_bed_sheet(s):
    s.title_text('CALIBRATION BED: the detachable bed, its MCUs (MicroPython chain)', 15.24, 15.24)
    J = s.use('Connector_Generic', 'Conn_01x05')
    s.place(J, 'J801', 'pogo, bed side', 58.42, 88.9)
    for p, net in (('1', 'BED_PWR'), ('3', 'BED_DETECT'), ('4', 'BED_TXD'), ('5', 'BED_RXD')):
        s.glabel(net, 'J801', p, stub=7.62)
    gnd(s, 'J801', '2', stub=2.54)
    R = s.use('Device', 'R')
    s.place(R, 'R801', '22k (BED_5)', 58.42, 124.46)
    s.glabel('BED_DETECT', 'R801', '1', stub=2.54)
    gnd(s, 'R801', '2', stub=2.54)
    s.text('The bed ID: BED_1 2.2k, BED_2 4.7k,\nBED_3 10k, BED_4 15k, BED_5 22k, BED_6 33k.', 25.4, 142.24)
    rtp = json.loads((NODES / 'rtp.json').read_text())
    T1 = s.add_block(*boards.rp2040_zero('RP2040_Tiny_rtp', 'RP2040-Tiny: the RTP node (lrt_resistive_touch.py). Used pins only',
                                         'RP2040-Tiny (RTP)',
                                         [('GP0 UART0 TX', 'output'), ('GP1 UART0 RX', 'input'), ('GP2 touch', 'output'), None,
                                          ('GP4 UART1 TX', 'output'), ('GP5 UART1 RX', 'input'), None,
                                          ('GP26 XM', 'bidirectional'), ('GP27 YP', 'bidirectional'),
                                          ('GP28 XP', 'bidirectional'), ('GP29 YM', 'bidirectional')]))
    s.place(T1, 'U801', 'RP2040-Tiny (RTP node)', 132.08, 66.04)
    for p, net, shape in (('GP0 UART0 TX', 'BED_RXD', 'output'), ('GP1 UART0 RX', 'BED_TXD', 'input')):
        s.glabel(net, 'U801', p, shape=shape, stub=12.7)
    s.glabel('BED_PWR', 'U801', '5V', shape='input', stub=7.62)
    s.nc('U801', '3V3')
    gnd(s, 'U801', 'GND', stub=5.08)
    s.nc('U801', 'USB')
    s.label('CHAIN_TX', 'U801', 'GP4 UART1 TX', stub=12.7)
    s.label('CHAIN_RX', 'U801', 'GP5 UART1 RX', stub=12.7)
    D = s.use('Device', 'D_Schottky')
    s.place(D, 'D801', 'Schottky', 182.88, s.P('U801', 'GP2 touch')[1], rot=180, dnp=True)
    s.connect('U801', 'GP2 touch', 'D801', 'A')
    s.glabel('BED_DETECT', 'D801', 'K', stub=5.08)
    P = s.add_block(*boards.rtp_panel())
    s.place(P, 'U802', 'resistive touch panel', 213.36, 83.82)
    for gp, pp, net in (('GP28 XP', 'X+', 'PANEL_XP'), ('GP26 XM', 'X-', 'PANEL_XM'), ('GP27 YP', 'Y+', 'PANEL_YP'), ('GP29 YM', 'Y-', 'PANEL_YM')):
        s.label(net, 'U801', gp, stub=7.62)
        s.label(net, 'U802', pp, stub=5.08)
    s.enclose(91.44, 33.02, 241.3, 106.68, 'Going: the RTP node and its panel', planned=True)
    fsr = json.loads((NODES / 'fsr.json').read_text())
    cols = [10, 9, 12, 11, 8, 13, 14, 15]                      # FSR_X in lrt_fsr_array.py
    rows = fsr['fsr_y']
    right = [('GP0 UART0 TX', 'output'), ('GP1 UART0 RX', 'input'), ('GP2 touch', 'output'), None] + \
            [(f'GP{c} col {i}', 'output') for i, c in sorted(enumerate(cols), key=lambda t: t[1])] + [None] + \
            [(f'GP{r} row {i}', 'input') for i, r in sorted(enumerate(rows), key=lambda t: t[1])]
    T2 = s.add_block(*boards.rp2040_zero('RP2040_Tiny_fsr', 'RP2040-Tiny: the FSR node (lrt_fsr_array.py, fsr.json). Used pins only',
                                         'RP2040-Tiny (FSR)', right))
    s.place(T2, 'U803', 'RP2040-Tiny (FSR node)', 132.08, 165.1)
    s.label('CHAIN_RX', 'U803', 'GP0 UART0 TX', stub=12.7)
    s.label('CHAIN_TX', 'U803', 'GP1 UART0 RX', stub=12.7)
    s.glabel('BED_PWR', 'U803', '5V', shape='input', stub=7.62)
    s.nc('U803', '3V3')
    gnd(s, 'U803', 'GND', stub=5.08)
    s.nc('U803', 'USB')
    s.place(D, 'D802', 'Schottky', 182.88, s.P('U803', 'GP2 touch')[1], rot=180, dnp=True)
    s.connect('U803', 'GP2 touch', 'D802', 'A')
    s.glabel('BED_DETECT', 'D802', 'K', stub=5.08)
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
    s.text('The chain: Dock -> RTP -> FSR, 115200 baud (lib/link.py). Touch diodes\n(D801, D802): planned. Power: BED_PWR from the Dock\'s switch.', 254.0, 45.72)


def plot_bed_sheet(s):
    '''The load-cell board (docs/load-cell.md): Pro Micro, two ADS1220 modules, the feet, the
    filters and the sum, the touch stage. Its pins from micropython/nodes/plot_bed.json.'''
    node = json.loads((NODES / 'plot_bed.json').read_text())
    R, C = s.use('Device', 'R'), s.use('Device', 'C')
    V = '+3V3_PB'

    def p3(ref, number, stub=0, show=True):
        s.power('+3V3', ref, number, net=V, stub=stub, show=show)

    s.title_text('FEET (on the bars)', 22.86, 22.86)
    J3 = s.use('Connector_Generic', 'Conn_01x03')
    for i in range(3):
        y0 = g(38.1 + i * 27.94)
        top, bot, j = f'SG{901 + 2 * i}', f'SG{902 + 2 * i}', f'J{901 + i}'
        s.place(R, top, 'BF350 top', 33.02, y0, on_board=False, left=True, note=f'foot {i + 1}: top of the bar, off the board')
        s.place(R, bot, 'BF350 under', 33.02, g(y0 + 7.62), on_board=False, left=True, note=f'foot {i + 1}: under the bar')
        s.place(J3, j, f'foot {i + 1}', 68.58, g(y0 + 3.81))
        p3(top, '1')
        gnd(s, bot, '2')
        mid = s.P(top, '2')
        s.wire(mid, s.P(j, '2'))
        s.junction(mid)
        s.label_at(f'M{i + 1}_RAW', (g(mid[0] + 2.54), mid[1]), 0)
        p1, p3_ = s.P(j, '1'), s.P(j, '3')
        s.wire(p1, (55.88, p1[1]), (55.88, s.P(top, '1')[1]), s.P(top, '1'))
        s.wire(p3_, (55.88, p3_[1]), (55.88, s.P(bot, '2')[1]), s.P(bot, '2'))
    s.title_text('COMPLETION PAIR', 22.86, 124.46)
    s.place(R, 'R904', '350 matched', 33.02, 137.16, left=True)
    s.place(R, 'R905', '350 matched', 33.02, g(137.16 + 7.62), left=True)
    p3('R904', '1')
    gnd(s, 'R905', '2')
    mid = s.P('R904', '2')
    s.wire(mid, (g(mid[0] + 7.62), mid[1]))
    s.junction(mid)
    s.label_at('MC_RAW', (g(mid[0] + 7.62), mid[1]), 0)

    s.title_text('RC FILTERS', 88.9, 22.86)
    for i, (raw, f) in enumerate((('M1_RAW', 'M1'), ('M2_RAW', 'M2'), ('M3_RAW', 'M3'), ('MC_RAW', 'MC'))):
        y = g(38.1 + i * 22.86)
        r, c1 = f'R{906 + i}', f'C{901 + i}'
        s.place(R, r, '1k', 99.06, y, rot=90)
        s.label(raw, r, '1')
        n = s.P(r, '2')
        s.place(C, c1, '4n7 C0G', 109.22, g(y + 3.81))
        gnd(s, c1, '2')
        end = (139.7, y)
        if f != 'MC':
            c5 = f'C{905 + i}'
            s.place(C, c5, '47n', 121.92, g(y + 3.81))
            s.label('MC', c5, '2')
            s.wire(n, s.P(c1, '1'), s.P(c5, '1'), end)
            s.junction(s.P(c1, '1'))
            s.junction(s.P(c5, '1'))
        else:
            s.wire(n, s.P(c1, '1'), end)
            s.junction(s.P(c1, '1'))
        s.label_at(f, end, 0)

    s.title_text('SUM', 88.9, 132.08)
    ys = [g(144.78 + 10.16 * i) for i in range(3)]
    for i, y in enumerate(ys):
        r = f'R{910 + i}'
        s.place(R, r, '47k', 99.06, y, rot=90)
        s.label(f'M{i + 1}', r, '1')
        s.wire(s.P(r, '2'), (109.22, y))
    s.wire((109.22, ys[0]), (109.22, ys[1]), (109.22, ys[2]))
    s.junction((109.22, ys[1]))
    s.place(C, 'C908', '10n', 119.38, g(ys[0] + 3.81))
    s.label('MC', 'C908', '2')
    s.place(C, 'C909', '1n C0G', 129.54, g(ys[0] + 3.81))
    gnd(s, 'C909', '2')
    s.wire((109.22, ys[0]), s.P('C908', '1'), s.P('C909', '1'), (139.7, ys[0]))
    for pt in ((109.22, ys[0]), s.P('C908', '1'), s.P('C909', '1')):
        s.junction(pt)
    s.label_at('S', (139.7, ys[0]), 0)

    spi, feet, total = node['spi'], node['feet_adc'], node['sum_adc']
    s.title_text('ADS1220 MODULES', 160.02, 22.86)
    ADS = s.add_block(*boards.ads1220_module())
    for ref, x, y, ins, cs, drdy, what in (
            ('U902', 182.88, 60.96, {'AIN0': 'M1', 'AIN1': 'M2', 'AIN2': 'M3', 'AIN3': 'MC'}, 'CS1', 'DRDY1', 'feet'),
            ('U903', 182.88, 130.81, {'AIN0': 'S', 'AIN1': 'MC'}, 'CS2', 'DRDY2', 'sum')):
        s.place(ADS, ref, f'ADS1220 module ({what})', x, y)
        for name in ('AIN0', 'AIN1', 'AIN2', 'AIN3'):
            s.label(ins[name], ref, name) if name in ins else s.nc(ref, name)
        for name in ('AVDD', 'DVDD', 'REFP0'):
            p3(ref, name, show=name == 'AVDD')          # one rail name over the three
        for name in ('AGND', 'DGND', 'REFN0'):
            gnd(s, ref, name)
        for name, net in (('MISO', 'CIPO'), ('MOSI', 'COPI'), ('SCLK', 'SCK'), ('CS', cs), ('DRDY', drdy)):
            s.label(net, ref, name)
        s.nc(ref, 'CLK')

    s.title_text('SPARKFUN PRO MICRO RP2040', 241.3, 22.86)
    nets = {spi['sck']: 'SCK', spi['mosi']: 'COPI', spi['miso']: 'CIPO', feet['cs']: 'CS1', feet['drdy']: 'DRDY1',
            total['cs']: 'CS2', total['drdy']: 'DRDY2', node['touch_out']: 'TOUCH_GP',
            0: 'UART0_TX', 1: 'UART0_RX', 4: 'UART1_TX', 5: 'UART1_RX', 2: 'PM_I2C1_SDA', 3: 'PM_I2C1_SCL',
            26: 'ADC0', 27: 'ADC1', 28: 'ADC2', 29: 'ADC3'}
    pro_micro_mcu(s, 'U901', 274.32, 86.36, nets)
    s.title_text('AVDD_A ENTRY', 241.3, 137.16)
    avdd_entry(s, 'C910', 'C911', 251.46, 152.4)
    touch_line(s, 'Q901', 'R913', 'R914', 'J905', 322.58, 22.86)

    s.title_text('SPARE HEADERS (optional)', 322.58, 101.6)
    J8 = s.use('Connector_Generic', 'Conn_01x08')
    J6 = s.use('Connector_Generic', 'Conn_01x06')
    s.place(J8, 'J907', 'UART0 / UART1 / I2C1', 345.44, 127.0, dnp=True)
    for number, net in enumerate(('UART0_TX', 'UART0_RX', 'UART1_TX', 'UART1_RX', 'PM_I2C1_SDA', 'PM_I2C1_SCL'), 1):
        s.label(net, 'J907', str(number))
    s.place(J6, 'J908', 'ADC0-3', 383.54, 124.46, dnp=True)
    for number, net in enumerate(('ADC0', 'ADC1', 'ADC2', 'ADC3'), 1):
        s.label(net, 'J908', str(number))
    for jref, pv, pg in (('J907', '7', '8'), ('J908', '5', '6')):
        a, b = s.P(jref, pv), s.P(jref, pg)
        s.wire(a, (g(a[0] - 2.54), a[1]), (g(a[0] - 2.54), g(a[1] + 2.54)), (g(a[0] - 15.24), g(a[1] + 2.54)),
               (g(a[0] - 15.24), g(a[1] - 2.54)))
        s.power_at('+3V3', (g(a[0] - 15.24), g(a[1] - 2.54)), net=V)
        s.wire(b, (g(b[0] - 1.27), b[1]), (g(b[0] - 1.27), g(b[1] + 7.62)))
        s.power_at('GND', (g(b[0] - 1.27), g(b[1] + 7.62)))

    notes = [
        (22.86, 'FEET AND BRIDGES', 'A BF350 on top of each 6061 bar, one underneath: a half bridge.\nWired top-to-EXC+ on all three: pressing lowers the midpoint (sign -1).\nR904/R905: 2 x 350R matched, or a dummy BF350 pair on an offcut.'),
        (110.49, 'FILTERS AND THE SUM', '1k in series, 4n7 (C0G) to GND per input; 47n each foot to MC.\nS = the mean of the filtered mids: 47k each, 10n S-MC, 1n S-GND.\n47k, not 10k: ~1.3 % of a foot leaks into the others (10k: ~6 %).'),
        (198.12, 'ADCs AND SUPPLY', 'ADS #1 (feet): M1/M2/M3 vs MC, one conversion each, 20/s.\nADS #2 (sum): S vs MC, 330/s; DRDY2 is the touch IRQ.\nRatiometric: REFP0/REFN0 across the bridges\' 3V3. Module pins: not the header\'s.'),
        (288.29, 'PINS', 'From micropython/nodes/plot_bed.json. Check the Pro Micro\'s\nheader order on its silkscreen. Grounds: one star point.'),
    ]
    for x, head, body in notes:
        s.title_text(head, x, 190.5)
        s.text(body, x, 195.58)
    s.enclose(15.24, 17.78, 152.4, 182.88, 'Front end (on the board, feet off it)')
    s.enclose(154.94, 17.78, 314.96, 182.88, 'The ADCs and the MCU')


def pro_micro_mcu(s, ref, x, y, nets, V='+3V3_PB'):
    '''The plot bed\'s Pro Micro: `nets` maps GPIO -> net, the other GPIOs get no-connect flags.'''
    PM_sym, w, h = boards.pro_micro()
    PM = s.add_block(PM_sym, w, h)
    s.place(PM, ref, 'SparkFun Pro Micro RP2040 (top view, USB-C up)', x, y)
    for n, number in boards.gpio_numbers(PM_sym).items():
        s.label(nets[n], ref, number) if n in nets else s.nc(ref, number)
    a3, a4 = s.P(ref, '3'), s.P(ref, '4')
    s.wire(a3, (g(a3[0] - 5.08), a3[1]), (g(a4[0] - 5.08), a4[1]), a4, chamfer=0)   # the symbol sits on a corner
    s.power_at('GND', (g(a3[0] - 5.08), a3[1]), 180)
    gnd(s, ref, '14')
    v = s.P(ref, '16')
    s.wire(v, (g(v[0] + 7.62), v[1]), (g(v[0] + 7.62), g(v[1] - 12.7)))
    s.power_at('+3V3', (g(v[0] + 7.62), g(v[1] - 12.7)), net=V)
    gnd(s, ref, '25')
    s.power('+3V3', ref, '26', net=V)
    s.nc(ref, '13')
    s.nc(ref, '15')
    s.glabel('USB_PLOTBED', ref, '29', stub=5.08)


def avdd_entry(s, cp, c, x, y, V='+3V3_PB'):
    '''The bulk and the ceramic cap where the 3V3 enters the analog side.'''
    s.place(s.use('Device', 'C_Polarized'), cp, '47u', x, y)
    s.place(s.use('Device', 'C'), c, '100n', g(x + 12.7), y)
    for ref in (cp, c):
        s.power('+3V3', ref, '1', net=V, show=ref == cp)
        gnd(s, ref, '2')


def touch_line(s, q_ref, rb, rpd, j, x0, y0):
    '''GP6 -> NPN, open collector down the wire to the Melzi (its pull-up there). Title at (x0, y0).'''
    R = s.use('Device', 'R')
    dx, dy = x0 - 322.58, y0 - 22.86       # drawn first at (322.58, 22.86)
    s.title_text('TOUCH LINE', x0, y0)
    q = s.use('Transistor_BJT', 'Q_NPN_CBE')
    s.place(q, q_ref, 'BC547', 363.22 + dx, 50.8 + dy)
    s.place(R, rb, '4k7', 344.17 + dx, 50.8 + dy, rot=90)
    s.label('TOUCH_GP', rb, '1')
    base = s.P(q_ref, '2')
    node_b = (g(351.79 + dx), base[1])
    s.wire(s.P(rb, '2'), node_b, base)
    s.junction(node_b)
    s.place(R, rpd, '100k', node_b[0], g(node_b[1] + 6.35))
    s.wire(node_b, s.P(rpd, '1'))
    gnd(s, rpd, '2')
    gnd(s, q_ref, '3')
    J2 = s.use('Connector_Generic', 'Conn_01x02')
    col = s.P(q_ref, '1')
    s.place(J2, j, 'to the Melzi (EXT A4)', 393.7 + dx, g(col[1] - 7.62))
    j1, j2 = s.P(j, '1'), s.P(j, '2')
    s.wire(col, (col[0], j1[1]), (g(col[0] + 5.08), j1[1]), j1)
    s.glabel_at('PROBE_A4', (g(col[0] + 5.08), j1[1]), 90)
    s.wire(j2, (g(j2[0] - 5.08), j2[1]), (g(j2[0] - 5.08), g(j2[1] + 5.08)))
    s.power_at('GND', (g(j2[0] - 5.08), g(j2[1] + 5.08)))
    s.text('GP6 high = the NPN conducts = the Melzi pin low = OK. A touch, a dead\nMCU (100k holds the base low) or a cut wire: the Melzi\'s pull-up\n(R401, sheet Melzi) wins = triggered.', x0, 66.04 + dy)


def plot_head_sheet(s):
    '''The head cell (TODO.md, the load cell in the Plot-Toolchanger-Connector): two strips, 4 BF350s in
    one full bridge on Rider-HS, a CAT6 cable through the chain to the plot bed board, one ADS1220.
    The board's pins as micropython/nodes/plot_bed.json: the sum chip, the feet chip not fitted.'''
    node = json.loads((NODES / 'plot_bed.json').read_text())
    R, C = s.use('Device', 'R'), s.use('Device', 'C')
    V = '+3V3_PH'          # the plot bed board's 3V3, as built for the head cell (both sheets: one board)

    def p3(ref, number, stub=0, show=True):
        s.power('+3V3', ref, number, net=V, stub=stub, show=show)

    def p3_up(ref):               # a connector's pin 1: the rail up and clear of the labels below
        a = s.P(ref, '1')
        top = (g(a[0] - 2.54), g(a[1] - 5.08))
        s.wire(a, (top[0], a[1]), top, chamfer=0)
        s.power_at('+3V3', top, net=V)

    s.title_text('THE BRIDGE (4 x BF350)', 22.86, 22.86)
    for x, (top, tv), (bot, bv), mid in ((33.02, ('SG951', 'BF350 1A'), ('SG952', 'BF350 1B'), 'SIG_N'),
                                         (71.12, ('SG953', 'BF350 2A'), ('SG954', 'BF350 2B'), 'SIG_P')):
        s.place(R, top, tv, x, 50.8, on_board=False, left=True, note=f'{tv}: glued on the strip, off the board')
        s.place(R, bot, bv, x, g(50.8 + 7.62), on_board=False, left=True, note=f'{bv}: glued on the strip, off the board')
        p3(top, '1')
        gnd(s, bot, '2')
        m = s.P(top, '2')
        s.wire(m, (g(m[0] + 7.62), m[1]))
        s.junction(m)
        s.label_at(mid, (g(m[0] + 7.62), m[1]), 0)
    s.text('Strip 1 (lower): 1A up (inner), 1B under.\nStrip 2 (upper): 2A down (inner), 2B on top.\n'
           'Upper faces 1A + 2B: opposite arms;\n2A + 1B: the other pair.', 22.86, 68.58)

    s.title_text('NTC (optional)', 22.86, 88.9)
    s.place(s.use('Device', 'Thermistor_NTC'), 'TH951', '10k NTC', 45.72, 99.06, rot=90, on_board=False, dnp=True,
            note='glued on the strip by the gauges: temperature for the zero\'s drift')
    s.label('NTC', 'TH951', '1', stub=2.54)
    s.label('NTC_RET', 'TH951', '2', stub=2.54)

    J8 = s.use('Connector_Generic', 'Conn_01x08')
    s.title_text('PADS ON HS', 50.8, 114.3)
    s.place(J8, 'J951', 'pads on HS', 88.9, 132.08, on_board=False)
    p3_up('J951')
    for number, net in (('2', 'SIG_P'), ('3', 'SIG_N'), ('4', 'NTC'), ('7', 'NTC_RET')):
        s.label(net, 'J951', number, stub=2.54)
    s.nc('J951', '5')
    s.nc('J951', '6')
    gnd(s, 'J951', '8', stub=2.54)

    s.title_text('CAT6 UTP, 0.6-1 m', 106.68, 114.3)
    s.text('Through the cable chain. Stranded\n(patch) cable: solid core cracks.\n\n'
           'Pad: wire = signal\n'
           '1: white-orange = E+ (3V3)\n8: orange = E- (GND)\n'
           '2: white-blue = S+ (SIG_P)\n3: blue = S- (SIG_N)\n'
           '4: white-green = NTC\n7: green = NTC return\n'
           '5: white-brown = spare\n6: brown = spare\n\n'
           'Spare pair: GND at the board,\ncut and insulated at the cell.', 106.68, 119.38)

    s.place(J8, 'J952', 'CAT6 in', 175.26, 132.08)
    p3_up('J952')
    for number, net in (('2', 'SIG_P'), ('3', 'SIG_N'), ('4', 'NTC')):
        s.label(net, 'J952', number, stub=2.54)
    bus = [s.P('J952', n) for n in '5678']
    x = g(bus[0][0] - 5.08)
    for p in bus:
        s.wire(p, (x, p[1]))
    for a, b in zip(bus, bus[1:]):
        s.wire((x, a[1]), (x, b[1]))
    for p in bus[1:-1]:
        s.junction((x, p[1]))
    s.power_at('GND', (x, bus[-1][1]))

    s.title_text('RC FILTERS', 190.5, 22.86)
    for i, (raw, f) in enumerate((('SIG_P', 'AIN_P'), ('SIG_N', 'AIN_N'))):
        y = g(38.1 + i * 22.86)
        r, c1 = f'R{951 + i}', f'C{951 + i}'
        s.place(R, r, '1k', 200.66, y, rot=90)
        s.label(raw, r, '1')
        n = s.P(r, '2')
        s.place(C, c1, '4n7 C0G', 210.82, g(y + 3.81))
        gnd(s, c1, '2')
        end = (241.3, y)
        if f == 'AIN_P':
            s.place(C, 'C953', '47n', 223.52, g(y + 3.81))
            s.label('AIN_N', 'C953', '2')
            s.wire(n, s.P(c1, '1'), s.P('C953', '1'), end)
            s.junction(s.P('C953', '1'))
        else:
            s.wire(n, s.P(c1, '1'), end)
        s.junction(s.P(c1, '1'))
        s.label_at(f, end, 0)

    s.title_text('NTC DIVIDER (optional)', 190.5, 88.9)
    s.place(R, 'R953', '10k', 200.66, 104.14, dnp=True)
    p3('R953', '1')
    s.place(C, 'C954', '100n', 213.36, g(104.14 + 3.81 + 3.81), dnp=True)
    gnd(s, 'C954', '2')
    end = (228.6, s.P('R953', '2')[1])
    s.wire(s.P('R953', '2'), s.P('C954', '1'), end)
    s.junction(s.P('C954', '1'))
    s.label_at('NTC', end, 0)

    s.title_text('AVDD_A ENTRY', 190.5, 132.08)
    avdd_entry(s, 'C955', 'C956', 200.66, 147.32, V)

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
                                            total['cs']: 'CS2', total['drdy']: 'DRDY2', node['touch_out']: 'TOUCH_GP',
                                            26: 'NTC'}, V)
    touch_line(s, 'Q951', 'R954', 'R955', 'J953', 312.42, 127.0)

    notes = [
        (22.86, 'THE CELL', 'One full bridge, closed on the pads on HS (not at the board):\n4 wires out. 32 AWG twisted from each gauge to the pads,\nslack loops, tied down on HS. Sign and grams: on the bench.'),
        (110.49, 'THE CABLE', 'E+/E- one pair, S+/S- one pair. 1 m of 23-24 AWG: ~0.08 R a wire,\n<0.1 % gain (calibrated out). Analog only: no SPI or motor\nwires in this jacket. Check diag() with the motors on.'),
        (198.12, 'THE ADC', 'The plot bed board\'s sum chip: AIN0-AIN1, 330/s, DRDY2 = the touch IRQ.\nRatiometric: REFP0/REFN0 on the 3V3 that feeds E+ (+3V3_PH = +3V3_PB).\nThe feet chip (CS1/DRDY1) is not fitted: firmware reports it missing.'),
        (288.29, 'NTC', 'Optional: GP26 (ADC0) reads the NTC on the strip, for the\nzero\'s drift with K\'s motor heat. Return on its own wire.'),
    ]
    for x, head, body in notes:
        s.title_text(head, x, 190.5)
        s.text(body, x, 195.58)
    s.enclose(15.24, 17.78, 96.52, 157.48, 'On the cell (Rider-HS)')
    s.enclose(154.94, 17.78, 408.94, 182.88, 'The plot bed board (one ADS1220)')
