# Limn KiCad generator - the boards and modules, drawn as blocks
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Pins from the code and the configs (notebooks/pinout.md, micropython/nodes/*.json, klipper/*.cfg),
# the electronics page (projects/limn/content/electronics.md) and docs/block-diagrams.md. A board's
# pins are the ones Limn uses; a block isn't a full pinout unless it says so (the Pro Micro is).
# A USB link is one pin, 'USB': the cable, not its four wires.
import re
from .core import block, pin, find, Q, num, font

P, B, I, O, PI, PO = 'passive', 'bidirectional', 'input', 'output', 'power_in', 'power_out'


def charger():
    return block('USB_PD_charger', 'UGREEN Nexode 100 W GaN, 3 USB-C ports (the plotter\'s supply)',
                 left=[('AC in', P)],
                 right=[('C0 45W', P), ('C1 30W', P), ('C2 22.5W', P)], value='UGREEN Nexode 100W')


def pd_trigger(volts):
    return block(f'PD_trigger_{volts}V', f'USB-C PD trigger cable / board, asks for {volts} V',
                 left=[('USB-C', P)], right=[('OUT+', PO), ('OUT-', P)], value=f'PD trigger {volts} V')


def buck(name, desc, value):
    return block(name, desc, left=[('IN+', PI), ('IN-', P)], right=[('OUT+', PO), ('OUT-', P)], value=value)


def pololu_switch():
    return block('Pololu_power_switch', 'Pololu power switch (pushbutton type): ON / OFF pulse inputs, latching',
                 left=[('VIN', PI), ('ON', I), ('OFF', I), ('GND', P)], right=[('VOUT', PO)],
                 value='Pololu power switch')


def mini_buck():
    return buck('Mini_buck_3A', 'Mini 3 A adjustable buck module: default 1.25 V, solder jumpers 1.5/1.8/2.5/3.3/5 V; '
                '11 x 7 dots, terminals in the corners', 'Mini buck 3 A')


def qre1113_breakout():
    return block('QRE1113_breakout', 'SparkFun QRE1113 line sensor breakout, analog (ROB-09453): IR LED with its '
                 'resistor, phototransistor with a pull-up; OUT falls as a light surface comes close (from memory)',
                 left=[('VCC', PI), ('OUT', O), ('GND', P)], value='SparkFun QRE1113 (analog)')


def pololu_mosfet():
    return block('Pololu_MOSFET_switch', 'Pololu Mini MOSFET Slide Switch with reverse voltage protection (#2810 LV '
                 '1.8-16 V, #2811 SV 4.5-32 V): non-latching high side; ON above ~1 V = on, low or open = off (max 30 V); '
                 'only with its slide switch at OFF',
                 left=[('VIN', PI), ('ON', I), ('GND', P)], right=[('VOUT', PO)], value='Pololu Mini MOSFET Slide Switch')


def pi4():
    return block('Raspberry_Pi_4', 'Raspberry Pi 4: Klipper host, Moonraker, the plot UI',
                 left=[('USB-C 5V', PI), ('GND', P), None, ('1 3V3', PO), ('3 GPIO2 SDA1', B), ('5 GPIO3 SCL1', B),
                       ('6 GND', P), None, ('DSI', P)],
                 right=[('USB-A 1', P), ('USB-A 2', P), ('USB-A 3', P), ('USB-A 4', P), None, ('CSI', P), ('Ethernet', P)],
                 value='Raspberry Pi 4')


def usb_hub():
    return block('FE1.1s_USB_hub', 'FE1.1s 4-port USB 2.0 hub breakout (single TT: the full-speed MCUs share 12 Mbit/s)',
                 left=[('UP', P), ('5V', PI), ('GND', P)],
                 right=[('DN1', P), ('DN2', P), ('DN3', P), ('DN4', P)], value='FE1.1s USB hub')


def uvc(name, desc, value):
    return block(name, desc, left=[('USB', P)], value=value)


def melzi():
    ports = []
    for port, axis in (('E', 'A'), ('Y', 'B'), ('X', 'Z'), ('Z', 'K')):
        ports += [(f'{port} 1A', P), (f'{port} 1B', P), (f'{port} 2A', P), (f'{port} 2B', P), None]
    return block('Melzi_v2', 'Melzi v2.0: ATmega1284P + 4 x A4982, Klipper [mcu]. Ports as on the PCB',
                 left=[('VIN 12V', PI), ('GND', P), ('VMOT Z/K', PI), None, ('USB', P), None,
                       ('X-MIN PC2', B), ('Y-MIN PC3', B), ('Z-MIN PC4', B), ('GND', P)],
                 right=ports[:-1],
                 bottom=[('A1 PA1', B), ('A2 PA2', B), ('A3 PA3', B), ('A4 PA4', B), ('SDA', B), ('SCL', B),
                         ('TX', B), ('RX', B), ('VCC', PO), ('GND', P)],
                 value='Melzi v2.0')


def stepper_lib():
    return 'Motor', 'Stepper_Motor_bipolar'


def bltouch():
    return block('BLTouch', 'BLTouch: brown/black GND, red 5V, orange control (servo), white sensor (open drain)',
                 left=[('GND brown', P), ('+5V red', PI), ('CTRL orange', I), ('GND black', P), ('SENSE white', O)],
                 value='BLTouch')


def mpu9250():
    return block('MPU9250', 'MPU9250 (an MPU9255) breakout: input shaping, Klipper [mpu9250] at 0x68',
                 left=[('VCC', PI), ('GND', P), ('SCL', I), ('SDA', B)], value='MPU9250 (0x68)')


def or_gate():
    return block('Probe_OR_gate', 'The probe OR gate as built: two NPN, BLTouch OR Dock PROBE_OUT -> PA4',
                 left=[('IN Dock', I), ('IN BLTouch', I), ('+5V', PI), ('GND', P)], right=[('OUT', O)],
                 value='Probe OR gate (2 NPN)')


def pico():
    return block('Pico_WH', 'Raspberry Pi Pico WH on the Aux PCB: Klipper [mcu rpi]. Used pins only',
                 left=[('VBUS', PO), ('VSYS', PI), ('3V3(OUT)', PO), ('GND', P), None, ('USB', P)],
                 right=[('GP4', B), ('GP5', B), None, ('GP9', O), None, ('GP15', O), ('GP16', O), ('GP17', O)],
                 value='Pico WH (rpi)')


def rp2040_zero(name, desc, value, right_pins, left_extra=(), usb_powered=False):
    '''usb_powered: its 5V pin is the USB's VBUS, a supply for what hangs on it.'''
    return block(name, desc, left=[('5V', PO if usb_powered else PI), ('3V3', PO), ('GND', P), None, ('USB', P)] + list(left_extra),
                 right=right_pins, value=value)


def ws2812(n, desc, value, name=None):
    return block(name or f'WS2812_{n}', desc, left=[('DIN', I), ('5V', PI), ('GND', P)], value=value)


def buzzer_lib():
    return 'Device', 'Buzzer'


def mcp23017():
    return block('MCP23017_Adafruit', 'Adafruit MCP23017 breakout, I2C 0x20 (A0-A2 low); inputs with pull-ups',
                 left=[('VIN', PI), ('GND', P), ('SCL', I), ('SDA', B), ('A0', I), ('A1', I), ('A2', I), ('RST', I)],
                 right=[('GPB7', B), ('GPB6', B), ('GPB5', B), ('GPB4', B), ('GPB3', B), None,
                        ('GPA0-7', P), ('GPB0-2', P)],
                 value='MCP23017 (0x20)')


def pn532():
    return block('PN532', 'PN532 NFC module in I2C mode, 0x24 (its mode jumpers set for I2C)',
                 left=[('VCC', PI), ('GND', P), ('SDA', B), ('SCL', I)], right=[('IRQ', O), ('RSTO', O)],
                 value='PN532 (0x24)')


def endoscope():
    return block('Xitech_UVC_board', 'Xitech USB camera board 0bde:8076 (UVC, 400x400) + our sensor adapter',
                 left=[('USB', P)], right=[('VDD', PO), ('GND', P), ('VCLK', O), ('VOUT', I)],
                 value='Endoscope board (Xitech UVC)')


def endo_sensor():
    return block('Endoscope_sensor', 'The endoscope tip: image sensor (analog VOUT, one pixel per VCLK), light by fiber',
                 left=[('VDD', PI), ('GND', P), ('VCLK', I), ('VOUT', O)], value='Endoscope sensor')


def rtp_panel():
    return block('Resistive_panel', '4-wire resistive touch panel', left=[('X+', P), ('X-', P), ('Y+', P), ('Y-', P)],
                 value='4-wire resistive panel')


def fsr_sheet():
    return block('FSR_4x8', '32-zone FSR sheet, 12-pin 0.5 mm FFC: 8 drive columns, 4 sense rows',
                 left=[(f'C{i}', P) for i in range(8)], right=[(f'R{i}', P) for i in range(4)],
                 value='FSR 4 x 8 (32 zones)')


def toolhead_mcu():
    return block('Toolhead_MCU', 'Toolhead MCU (planned, 2026-10-12): RP2350/RP2040-Zero class, Klipper [mcu tool]. '
                 'K driver + endstop, ADXL345, HX711, QRE1113, the tool ID / power / data',
                 left=[('USB', P), ('5V', PI), ('GND', P)],
                 right=[('EN_5V', O), ('TOOL_EN', O), ('TOOL_PWM', O), ('TOOL_ID', I), ('LOCK', I)],
                 value='Toolhead MCU (planned)')


def tool_coupling():
    return block('Tool_coupling', 'The toolchanger coupling (planned): 5 V + GND + data pins to the tool',
                 left=[('5V', PI), ('GND', P), ('ID', P), ('EN', P), ('PWM', P), ('SPARE1', P), ('SPARE2', P)],
                 value='Tool coupling (planned)')


def ads1220_module():
    pins = [('MISO', 'tri_state', 'R'), ('MOSI', 'input', 'R'), ('SCLK', 'input', 'R'), ('CS', 'input', 'R'),
            ('DRDY', 'output', 'R'), ('CLK', 'input', 'R'), ('AVDD', 'power_in', 'T'), ('AGND', 'power_in', 'B'),
            ('DVDD', 'power_in', 'T'), ('DGND', 'power_in', 'B'), ('REFP0', 'input', 'T'), ('REFN0', 'input', 'B'),
            ('AIN0', 'input', 'L'), ('AIN1', 'input', 'L'), ('AIN2', 'input', 'L'), ('AIN3', 'input', 'L')]
    # header numbers, top view (the photo, ~/limn-shot/Pasted Image 20261015151922_566.png): DRDY, MISO, MOSI,
    # SCLK, CS, CLK, DVDD, DGND down the left = 1-8; AGND, AVDD, REFP0, REFN0, AIN3-AIN0 up the right = 9-16
    number = {'DRDY': 1, 'MISO': 2, 'MOSI': 3, 'SCLK': 4, 'CS': 5, 'CLK': 6, 'DVDD': 7, 'DGND': 8, 'AGND': 9,
              'AVDD': 10, 'REFP0': 11, 'REFN0': 12, 'AIN3': 13, 'AIN2': 14, 'AIN1': 15, 'AIN0': 16}
    out, k = [], {'L': 0, 'R': 0, 'T': 0, 'B': 0}
    for name, kind, side in pins:
        i, n = k[side], str(number[name])
        k[side] += 1
        if side == 'L':
            out.append(pin(kind, -16.51, 3.81 - 2.54 * i, 0, name, n, length=3.81))
        elif side == 'R':
            out.append(pin(kind, 16.51, 6.35 - 2.54 * i, 180, name, n, length=3.81))
        elif side == 'T':
            out.append(pin(kind, -8.89 + 6.35 * i, 16.51, 270, name, n, length=3.81))
        else:
            out.append(pin(kind, -8.89 + 6.35 * i, -16.51, 90, name, n, length=3.81))
    return _box('ADS1220_module', 'ADS1220 breakout (Wolles Elektronikkiste type): 0R DVDD-AVDD and DGND-AGND, '
                '24R on MOSI/CS/SCLK, 10k CLK-GND. Pin numbers: the header\'s, DIP order, top view',
                12.7, 12.7, out, 'ADS1220 module'), 12.7, 12.7


def pro_micro():
    '''The SparkFun Pro Micro RP2040 with every header pin in its physical order (top view, USB-C
    up): 1-12 down the left, 13-24 down the right, 25-28 the Qwiic, 29 the USB-C. Order: SparkFun's
    Pro Micro footprint as Zephyr maps it (sparkfun_pro_micro_connector.dtsi).'''
    left = [('GP0/TX', B), ('GP1/RX', B), ('GND', PI), ('GND', PI)] + [(f'GP{n}', B) for n in range(2, 10)]
    right = [('RAW', PI), ('GND', PI), ('RST', I), ('3V3', PO), ('GP29/A3', B), ('GP28/A2', B), ('GP27/A1', B),
             ('GP26/A0', B), ('GP22/SCK', B), ('GP20/CIPO', B), ('GP23/COPI', B), ('GP21/CS', B)]
    qwiic = [('GND', P), ('3V3', P), ('SDA/GP16', B), ('SCL/GP17', B)]
    pins = [pin(k, -22.86, 13.97 - 2.54 * i, 0, n, str(i + 1), length=3.81) for i, (n, k) in enumerate(left)]
    pins += [pin(k, 22.86, 13.97 - 2.54 * i, 180, n, str(i + 13), length=3.81) for i, (n, k) in enumerate(right)]
    pins += [pin(k, -10.16 + 5.08 * i, -24.13, 90, n, str(i + 25), length=5.08) for i, (n, k) in enumerate(qwiic)]
    pins.append(pin(P, 0, 24.13, 270, 'USB-C', '29', length=5.08))
    return _box('Pro_Micro_RP2040', 'SparkFun Pro Micro RP2040 (DEV-18288); pins numbered by header position, '
                '25-28 Qwiic, 29 USB-C', 19.05, 19.05, pins, 'Pro Micro RP2040'), 19.05, 19.05


def gpio_numbers(sym):
    '''GPIO number -> pin number, from pin names like GP21/CS.'''
    out = {}
    for sub in find(sym, 'symbol'):
        for p in find(sub, 'pin'):
            m = re.search(r'GP(\d+)', str(find(p, 'name')[0][1]))
            if m:
                out[int(m.group(1))] = str(find(p, 'number')[0][1])
    return out


def _box(name, desc, w, h, pins, value):
    lib_id = f'limn:{name}'
    return ['symbol', Q(lib_id), ['pin_names', ['offset', '0.762']],
            ['exclude_from_sim', 'no'], ['in_bom', 'yes'], ['on_board', 'yes'],
            ['property', Q('Reference'), Q('U'), ['at', num(-w), num(h + 3.81), '0'], font(justify='left')],
            ['property', Q('Value'), Q(value), ['at', num(-w), num(h + 1.27), '0'], font(justify='left')],
            ['property', Q('Footprint'), Q(''), ['at', '0', '0', '0'], font(hide=True)],
            ['property', Q('Datasheet'), Q(''), ['at', '0', '0', '0'], font(hide=True)],
            ['property', Q('Description'), Q(desc), ['at', '0', '0', '0'], font(hide=True)],
            ['symbol', Q(name + '_0_1'),
             ['rectangle', ['start', num(-w), num(h)], ['end', num(w), num(-h)],
              ['stroke', ['width', '0.254'], ['type', 'default']], ['fill', ['type', 'background']]]],
            ['symbol', Q(name + '_1_1')] + pins,
            ['embedded_fonts', 'no']]
