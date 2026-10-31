# Limn KiCad generator - footprints for the modules (limn.pretty), for a perfboard layout
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Pads on the 2.54 mm grid, top view (the module's components up). Pad numbers = the symbols' pin
# numbers (boards.py). Outlines are approximate (from photos): the pads are what counts.

def _font(size=1.0):
    return f'(effects (font (size {size} {size}) (thickness {size * 0.15:.3f})))'


def _fp(name, descr, ref_at, pads, outline, texts=(), smd=False, model=None):
    x1, y1, x2, y2 = outline
    out = [f'(footprint "{name}"', '\t(version 20241229)', '\t(generator "limn_gen")', '\t(layer "F.Cu")',
           f'\t(descr "{descr}")',
           f'\t(property "Reference" "REF**" (at {ref_at[0]} {ref_at[1]} 0) (layer "F.SilkS") {_font()})',
           f'\t(property "Value" "{name}" (at {ref_at[0]} {y2 + 1.5:.2f} 0) (layer "F.Fab") {_font()})',
           f'\t(attr {"smd" if smd else "through_hole"})']
    for layer, w in (('F.SilkS', 0.12), ('F.Fab', 0.1)):
        out.append(f'\t(fp_rect (start {x1} {y1}) (end {x2} {y2}) (stroke (width {w}) (type solid)) (fill no) (layer "{layer}"))')
    out.append(f'\t(fp_rect (start {x1 - 0.25:.2f} {y1 - 0.25:.2f}) (end {x2 + 0.25:.2f} {y2 + 0.25:.2f}) '
               '(stroke (width 0.05) (type solid)) (fill no) (layer "F.CrtYd"))')
    for x, y, s, size in texts:
        out.append(f'\t(fp_text user "{s}" (at {x} {y} 0) (layer "F.Fab") {_font(size)})')
    for num, x, y, kind in pads:
        if kind == 'smd':           # a connector on the module (no hole): the cable, not soldered
            out.append(f'\t(pad "{num}" smd rect (at {x} {y}) (size 1 1) (layers "F.Cu" "F.Mask"))')
        elif kind == 'pogo':        # a pogo pin's flat base (D 2.0) soldered on
            out.append(f'\t(pad "{num}" smd circle (at {x} {y}) (size 2.4 2.4) (layers "F.Cu" "F.Paste" "F.Mask"))')
        elif kind == 'slot':        # a flat solder tab through a slot
            out.append(f'\t(pad "{num}" thru_hole oval (at {x} {y}) (size 1.2 2.0) (drill oval 0.6 1.4) (layers "*.Cu" "*.Mask"))')
        elif kind == 'npth':        # a mounting hole, M3
            out.append(f'\t(pad "" np_thru_hole circle (at {x} {y}) (size 3.3 3.3) (drill 3.3) (layers "*.Cu" "*.Mask"))')
        else:
            shape = 'rect' if num == '1' else 'circle'
            d, size = (1.3, 2.4) if kind == 'big' else (1.0, 1.7)
            out.append(f'\t(pad "{num}" thru_hole {shape} (at {x} {y}) (size {size} {size}) (drill {d}) (layers "*.Cu" "*.Mask"))')
    if model:                       # (file, offset): the module's STEP in limn.3dshapes, offset in mm, y up
        f, (ox, oy, oz) = model
        out.append(f'\t(model "${{KIPRJMOD}}/limn.3dshapes/{f}" (offset (xyz {ox} {oy} {oz})) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))')
    out.append(')')
    return '\n'.join(out) + '\n'


P = 2.54


def ads1220_module():
    # top view: DRDY..DGND down the left (1-8), AGND..AIN0 up the right (9-16), rows 0.7" apart
    left = ['DRDY', 'MISO', 'MOSI', 'SCLK', 'CS', 'CLK', 'DVDD', 'DGND']
    right = ['AIN0', 'AIN1', 'AIN2', 'AIN3', 'REFN0', 'REFP0', 'AVDD', 'AGND']
    pads = [(str(i + 1), 0, round(i * P, 2), 'th') for i in range(8)]
    pads += [(str(16 - i), round(7 * P, 2), round(i * P, 2), 'th') for i in range(8)]
    texts = [(2.2, round(i * P, 2), n, 0.6) for i, n in enumerate(left)]
    texts += [(round(7 * P - 2.4, 2), round(i * P, 2), n, 0.6) for i, n in enumerate(right)]
    return _fp('ADS1220_module', 'ADS1220 breakout (purple, Wolles Elektronikkiste type), 2 x 8 pins, rows 17.78 mm '
               'apart, top view; pads = the symbol pins (DIP order)', (8.89, -3.0), pads, (-1.8, -1.8, 19.6, 19.6), texts)


def pro_micro_rp2040():
    # top view, USB-C up: 1-12 down the left, 13-24 down the right, rows 0.6" apart; 29 = the USB-C
    pads = [(str(i + 1), 0, round(i * P, 2), 'th') for i in range(12)]
    pads += [(str(i + 13), round(6 * P, 2), round(i * P, 2), 'th') for i in range(12)]
    pads.append(('29', round(3 * P, 2), -1.6, 'smd'))
    pads += [('30', round(2 * P, 2), 1.6, 'smd'), ('31', round(4 * P, 2), 1.6, 'smd')]   # D+/D- underneath: place to check
    pads += [(str(25 + i), round(3.81 + 2.54 * i, 2), 29.4, 'smd') for i in range(4)]   # the Qwiic (not wired)
    texts = [(round(3 * P, 2), 1.0, 'USB-C', 0.8), (round(3 * P, 2), 27.6, 'Qwiic (not wired)', 0.6)]
    return _fp('SparkFun_Pro_Micro_RP2040', 'SparkFun Pro Micro RP2040 (DEV-18288), 2 x 12 pins, rows 15.24 mm apart, '
               'top view; pad 29 = the USB-C, 30/31 = D+/D- underneath (wires), 25-28 = the Qwiic (connectors, not soldered)', (7.62, -4.5), pads, (-1.27, -2.54, 16.51, 30.48), texts)


def mini_buck():
    # the user's mini 3 A buck: 11 x 7 perf dots, a terminal in each corner (top view, as the photo)
    pads = [('1', round(10 * P, 2), 0, 'big'), ('2', round(10 * P, 2), round(6 * P, 2), 'big'),
            ('3', 0, 0, 'big'), ('4', 0, round(6 * P, 2), 'big')]
    texts = [(22.0, 0, 'IN+', 0.8), (22.0, round(6 * P, 2), 'IN-', 0.8), (3.4, 0, 'OUT+', 0.8),
             (3.4, round(6 * P, 2), 'OUT-', 0.8), (12.7, 7.62, 'set the 5 V jumper', 0.8)]
    return _fp('Mini_buck_3A', 'Mini 3 A adjustable buck module (default 1.25 V, jumpers 1.5/1.8/2.5/3.3/5 V), '
               '11 x 7 dots on 2.54 mm, terminals in the corners', (12.7, -3.0), pads, (-1.27, -1.27, 26.67, 16.51), texts)


def pololu_slide_switch():
    # the user's map, seen from the BACK with the switch head to the left:
    #   top    Sw0 Sw1 GND GND VOUT VOUT      middle (vertical): Sw0 Sw1 ON (for an external switch: not used)
    #   bottom  -  ON  GND GND VIN  VIN       rows 6 dots apart (12.7 mm)
    # mirrored here into the top view (KiCad's), so the head faces right. Pad numbers = the symbol's:
    # VIN 1, ON 2, GND 3, VOUT 4; Sw0/Sw1 unnumbered (no net).
    top = ['4', '4', '3', '3', '', '']             # VOUT VOUT GND GND Sw1 Sw0
    bottom = ['1', '1', '3', '3', '2', None]       # VIN VIN GND GND ON (no pin)
    pads, n = [], 0
    for row, y in ((top, 0), (bottom, round(5 * P, 2))):
        for i, num in enumerate(row):
            if num is not None:
                pads.append((num, round(i * P, 2), y, 'th'))
    names = (['VOUT', 'VOUT', 'GND', 'GND', 'Sw1', 'Sw0'], ['VIN', 'VIN', 'GND', 'GND', 'ON', ''])
    texts = [(round(i * P, 2), y + d, nm, 0.5) for (row, y, d) in ((names[0], 0, 1.6), (names[1], round(5 * P, 2), -1.6))
             for i, nm in enumerate(row) if nm]
    texts.append((6.35, 6.35, 'slide at OFF (head ->)', 0.6))
    return _fp('Pololu_Mini_MOSFET_Slide_Switch', 'Pololu Mini MOSFET Slide Switch (#2810/#2811), 0.6 x 0.6 in, '
               'top view (mirrored from the back); the middle Sw0/Sw1/ON holes not drawn', (6.35, -3.0), pads,
               (-1.27, -1.27, 13.97, 13.97), texts)


def rp2040_zero(tiny=False):
    # top view, USB up; Waveshare's numbering (boards.RP2040_ZERO_PADS): GP0-GP8 = 1-9 down the right, GP9-GP13 =
    # 10-14 along the bottom (right to left), GP14/15, GP26-29 = 15-20 up the left, then 3V3 21, GND 22, 5V 23;
    # 24 = the USB (Zero: its USB-C; Tiny: the FPC to its adapter). Holes from Waveshare's STEP (23.5 x 18 board)
    right = [(str(i + 1), round(6 * P, 2), round(i * P, 2), 'th') for i in range(9)]
    bottom = [(str(10 + i), round((5 - i) * P, 2), round(8 * P, 2), 'th') for i in range(5)]
    left = [(str(23 - i), 0, round(i * P, 2), 'th') for i in range(9)]
    edge = 1.38 if tiny else 1.33               # hole centre to the board's side / bottom edge
    top = 1.59 if tiny else 1.49
    names = ['5V', 'GND', '3V3', 'GP29', 'GP28', 'GP27', 'GP26', 'GP15', 'GP14']
    texts = [(1.9, round(i * P, 2), n, 0.6) for i, n in enumerate(names)]
    texts += [(round(6 * P - 2.0, 2), round(i * P, 2), f'GP{i}', 0.6) for i in range(9)]
    texts.append((round(3 * P, 2), 0.6, 'FPC (USB)' if tiny else 'USB-C', 0.8))
    name = 'Waveshare_RP2040_Tiny' if tiny else 'Waveshare_RP2040_Zero'
    descr = ('Waveshare RP2040-Tiny (the module, its USB on the FPC adapter)' if tiny else 'Waveshare RP2040-Zero') + \
        ', 23 castellated holes on 2.54 mm, rows 15.24 mm apart, top view; pads = Waveshare\'s pin numbers, 24 = the USB'
    pads = right + bottom + left + [('24', round(3 * P, 2), -0.5, 'smd')]
    oy = 21.91 if tiny else 22.01
    return _fp(name, descr, (7.62, -3.0), pads, (-edge, -top, round(18 - edge, 2), round(8 * P + (1.59 if tiny else 1.69), 2)),
               texts, model=(f'{name}.stpZ', (-edge, -oy, 0)))


def usb_pads(name, descr, size):
    # four wires as holes in a row, as the symbol numbers them: VBUS 1, D+ 2, D- 3, GND 4; 5 = the cable (a marker)
    w, h = size
    pads = [(str(i + 1), round(i * P, 2), 0, 'th') for i in range(4)] + [('5', round(1.5 * P, 2), round(h - 2.5, 2), 'smd')]
    texts = [(round(i * P, 2), 1.6, n, 0.5) for i, n in enumerate(['VBUS', 'D+', 'D-', 'GND'])]
    return _fp(name, descr, (round(1.5 * P, 2), -3.0), pads, (round(1.5 * P - w / 2, 2), -1.5, round(1.5 * P + w / 2, 2), round(h - 1.5, 2)), texts)


def usb_c_breakout():
    return usb_pads('Adafruit_USB_C_breakout', 'Adafruit USB-C breakout (5.1k on CC: a device): VBUS, D+, D-, GND '
                    'as holes in a row; the board\'s own pin order to check against the part', (19.0, 12.0))


def usb_cable():
    return usb_pads('USB_cable_pads', 'A USB cable cut and soldered in: VBUS, D+, D-, GND (VBUS left open where cut)', (9.5, 5.0))


def fe11s_hub():
    # pads as the symbol numbers them: 5V 1, GND 2, UP D+ 3, UP D- 4 down the left; DN1-DN4 D+/D- (5-12) down the
    # right, a gap between ports. Which breakout: not in the notes yet: map the real pads before soldering
    left = [(str(i + 1), 0, round(i * P, 2), 'th') for i in range(4)]
    right = []
    for k in range(4):
        for j in range(2):
            right.append((str(5 + 2 * k + j), round(7 * P, 2), round((3 * k + j) * P, 2), 'th'))
    texts = [(2.0, round(i * P, 2), n, 0.6) for i, n in enumerate(['5V', 'GND', 'UP D+', 'UP D-'])]
    texts += [(round(7 * P - 2.6, 2), round((3 * k + j) * P, 2), f'DN{k + 1} D{"+-"[j]}', 0.6) for k in range(4) for j in range(2)]
    return _fp('FE1.1s_USB_hub_breakout', 'FE1.1s 4-port USB hub breakout: 5V, GND, UP D+/D-, DN1-4 D+/D- as the symbol '
               'numbers them; pad positions a placeholder: map the board\'s pads', (8.89, -3.0), left + right,
               (-1.8, -1.8, 19.6, 25.9), texts)


def fpc20_breakout():
    # top view, the FFC connector at the bottom edge (the photo, ~/limn-shot/Capture d’écran 2026-10-29 à 18.02.34.png):
    # odd contacts 1-19 on the lower row right to left, even 2-20 on the upper row; the board 33 x 26 mm, the
    # header centred, two holes (~D 3.3) 17 mm down; the connector across 7-25 mm. Origin: pad 1. 21 = the FFC
    pads = [(str(n), -round((n - 1) // 2 * P, 2), 0 if n % 2 else -P, 'th') for n in range(1, 21)]
    x1, y1 = -round(9 * P + (33 - 9 * P) / 2, 2), -5.74
    x2, y2 = round(x1 + 33, 2), round(y1 + 26, 2)
    pads += [('', round(x1 + 2.9, 2), round(y1 + 17.0, 2), 'npth'), ('', round(x2 - 2.9, 2), round(y1 + 17.0, 2), 'npth'),
             ('21', round(x1 + 16.5, 2), round(y1 + 21.8, 2), 'smd')]
    texts = [(round(x1 + 16.5, 2), round(y1 + 24.5, 2), 'FFC 20P 0.5 mm in', 0.8), (-1.27, 1.8, '1', 0.6), (-1.27, -4.3, '2', 0.6),
             (round(-9 * P, 2), -4.3, '20', 0.6)]
    return _fp('FPC20_breakout', 'FPC-20P 0.5 mm to 2 x 10 DIP 2.54 mm breakout (commercial, 33 x 26 mm), top view; '
               'pads = the printed contact numbers, 21 = the FFC connector (marker); hole and connector places from '
               'the photo: check against the board', (round(x1 + 16.5, 2), round(y1 - 1.5, 2)), pads, (x1, y1, x2, y2), texts)


def pogo_pin():
    return _fp('Pogo_pin_D2.0_L5.0', 'Pogo pin, D 2.0 flat base, 5.0 mm (3.5 barrel + 1.5 plunger), soldered on its base',
               (0, -2.2), [('1', 0, 0, 'pogo')], (-1.2, -1.2, 1.2, 1.2), smd=True, model=('Pogo_pin_5mm.stpZ', (0, 0, 0)))


def micro_limit_sw_inline():
    # the user's model (micro-limit-sw-inline): the body 5.8 x 10 x 4.3, the actuator nub up, two flat tabs
    # 0.2 thick under the body at x 1.8, y 0 and -3.1 (model y up: here +3.1); the body on the board
    texts = [(-1.0, 0, 'key', 0.6)]
    return _fp('Micro_limit_sw_inline', 'Inline micro limit switch (the key\'s switch), 5.8 x 10 mm; its two tabs '
               'in slots, from the user\'s model: check against the part', (0, -6.2),
               [('1', 1.8, 3.1, 'slot'), ('2', 1.8, 0, 'slot')], (-2.9, -5.0, 2.9, 5.0), texts,
               model=('Micro_limit_sw_inline.stpZ', (0, 0, 2.15)))


def stepper_slider():
    # the 5 mm stepper slider (the K lock): its base 13.7 x 22.5 (the user's model); its flex has the four
    # pads on one side, here on four pogo pins: white (the outermost) 1, green 2, yellow 3, purple 4.
    # The pads' pitch and place on the flex: not measured yet (3.0 apart past the motor's end, a placeholder)
    ys = [round(-4.5 + i * 3.0, 2) for i in range(4)]        # 3.0 apart: D 2.4 pads keep 0.6
    pads = [(str(i + 1), 9.5, y, 'pogo') for i, y in enumerate(ys)]
    texts = [(12.4, y, c, 0.5) for y, c in zip(ys, ('white', 'green', 'yellow', 'purple'))]
    texts.append((0, 0, 'K lock motor', 0.8))
    return _fp('Stepper_slider_5mm_flex4', '5 mm micro stepper slider (the K lock), its flex on 4 pogo pins (D 2.0, '
               '5 mm; one per pad): white 1, green 2, yellow 3, purple 4; the flex pads\' pitch and place are a '
               'placeholder', (0, -12.5), pads, (-7.08, -11.25, 14.5, 11.25), texts, smd=True,
               model=('Stepper_slider_5mm.stpZ', (0, 0, 5.8)))


ALL = {'FPC20_breakout': fpc20_breakout, 'Pogo_pin_D2.0_L5.0': pogo_pin, 'Micro_limit_sw_inline': micro_limit_sw_inline,
       'Stepper_slider_5mm_flex4': stepper_slider,
       'Waveshare_RP2040_Zero': rp2040_zero, 'Waveshare_RP2040_Tiny': lambda: rp2040_zero(tiny=True),
       'Adafruit_USB_C_breakout': usb_c_breakout, 'USB_cable_pads': usb_cable, 'FE1.1s_USB_hub_breakout': fe11s_hub,
       'Pololu_Mini_MOSFET_Slide_Switch': pololu_slide_switch, 'ADS1220_module': ads1220_module, 'SparkFun_Pro_Micro_RP2040': pro_micro_rp2040, 'Mini_buck_3A': mini_buck}
