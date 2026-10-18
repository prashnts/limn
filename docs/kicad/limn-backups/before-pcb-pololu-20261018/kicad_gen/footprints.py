# Limn KiCad generator - footprints for the modules (limn.pretty), for a perfboard layout
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Pads on the 2.54 mm grid, top view (the module's components up). Pad numbers = the symbols' pin
# numbers (boards.py). Outlines are approximate (from photos): the pads are what counts.

def _font(size=1.0):
    return f'(effects (font (size {size} {size}) (thickness {size * 0.15:.3f})))'


def _fp(name, descr, ref_at, pads, outline, texts=(), smd=False):
    x1, y1, x2, y2 = outline
    out = [f'(footprint "{name}"', '\t(version 20241229)', '\t(generator "limn_gen")', '\t(layer "F.Cu")',
           f'\t(descr "{descr}")',
           f'\t(property "Reference" "REF**" (at {ref_at[0]} {ref_at[1]} 0) (layer "F.SilkS") {_font()})',
           f'\t(property "Value" "{name}" (at {ref_at[0]} {y2 + 1.5:.2f} 0) (layer "F.Fab") {_font()})',
           '\t(attr through_hole)']
    for layer, w in (('F.SilkS', 0.12), ('F.Fab', 0.1)):
        out.append(f'\t(fp_rect (start {x1} {y1}) (end {x2} {y2}) (stroke (width {w}) (type solid)) (fill no) (layer "{layer}"))')
    out.append(f'\t(fp_rect (start {x1 - 0.25:.2f} {y1 - 0.25:.2f}) (end {x2 + 0.25:.2f} {y2 + 0.25:.2f}) '
               '(stroke (width 0.05) (type solid)) (fill no) (layer "F.CrtYd"))')
    for x, y, s, size in texts:
        out.append(f'\t(fp_text user "{s}" (at {x} {y} 0) (layer "F.Fab") {_font(size)})')
    for num, x, y, kind in pads:
        if kind == 'smd':           # a connector on the module (no hole): the cable, not soldered
            out.append(f'\t(pad "{num}" smd rect (at {x} {y}) (size 1 1) (layers "F.Cu" "F.Mask"))')
        else:
            shape = 'rect' if num == '1' else 'circle'
            d, size = (1.3, 2.4) if kind == 'big' else (1.0, 1.7)
            out.append(f'\t(pad "{num}" thru_hole {shape} (at {x} {y}) (size {size} {size}) (drill {d}) (layers "*.Cu" "*.Mask"))')
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
    pads += [(str(25 + i), round(3.81 + 2.54 * i, 2), 29.4, 'smd') for i in range(4)]   # the Qwiic (not wired)
    texts = [(round(3 * P, 2), 1.0, 'USB-C', 0.8), (round(3 * P, 2), 27.6, 'Qwiic (not wired)', 0.6)]
    return _fp('SparkFun_Pro_Micro_RP2040', 'SparkFun Pro Micro RP2040 (DEV-18288), 2 x 12 pins, rows 15.24 mm apart, '
               'top view; pad 29 = the USB-C, 25-28 = the Qwiic (connectors, not soldered)', (7.62, -4.5), pads, (-1.27, -2.54, 16.51, 30.48), texts)


def mini_buck():
    # the user's mini 3 A buck: 11 x 7 perf dots, a terminal in each corner (top view, as the photo)
    pads = [('1', round(10 * P, 2), 0, 'big'), ('2', round(10 * P, 2), round(6 * P, 2), 'big'),
            ('3', 0, 0, 'big'), ('4', 0, round(6 * P, 2), 'big')]
    texts = [(22.0, 0, 'IN+', 0.8), (22.0, round(6 * P, 2), 'IN-', 0.8), (3.4, 0, 'OUT+', 0.8),
             (3.4, round(6 * P, 2), 'OUT-', 0.8), (12.7, 7.62, 'set the 5 V jumper', 0.8)]
    return _fp('Mini_buck_3A', 'Mini 3 A adjustable buck module (default 1.25 V, jumpers 1.5/1.8/2.5/3.3/5 V), '
               '11 x 7 dots on 2.54 mm, terminals in the corners', (12.7, -3.0), pads, (-1.27, -1.27, 26.67, 16.51), texts)


ALL = {'ADS1220_module': ads1220_module, 'SparkFun_Pro_Micro_RP2040': pro_micro_rp2040, 'Mini_buck_3A': mini_buck}
