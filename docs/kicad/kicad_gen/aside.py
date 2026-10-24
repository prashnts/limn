# Limn KiCad generator - set aside: drawings of ideas not in the machine now (2026-10-23). Not in gen.py's SHEETS:
# kept so an idea can come back as it was drawn. Each function draws onto a sheet at its old place.
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
#   plot_bed_sheet   the bed on three load-cell feet (docs/load-cell.md): the cell went to the toolchanger (2026-10-16)
#   rtp_node         on sheet Calibration bed: the resistive touch node and its panel, gone
#   toolhead_mcu     on sheet Toolhead: a toolhead MCU by the coupling (K, its endstop, ADXL345, ...), not explored
#   qre              on sheet Plot bed board: the QRE1113 on the toolhead (tool seated), gone from the toolchanger
import json
from . import boards
from .core import g
from .sheets_a import gnd
from .sheets_b import NODES, avdd_entry, pro_micro_mcu, touch_line, _pin_rail


def rtp_node(s):
    '''On sheet Calibration bed, first in the chain before the FSR node (whose GP0/GP1 were then UART0 to it).'''
    T1 = s.add_block(*boards.rp2040_zero('RP2040_Tiny_rtp', 'RP2040-Tiny: the RTP node (lrt_resistive_touch.py). Used pins only',
                                         'RP2040-Tiny (RTP)',
                                         [('GP0 data (PIO)', 'bidirectional'), ('GP2 probe', 'output'), None,
                                          ('GP4 UART1 TX', 'output'), ('GP5 UART1 RX', 'input'), None,
                                          ('GP26 XM', 'bidirectional'), ('GP27 YP', 'bidirectional'),
                                          ('GP28 XP', 'bidirectional'), ('GP29 YM', 'bidirectional')]))
    s.place(T1, 'U801', 'RP2040-Tiny (RTP node)', 132.08, 66.04)
    s.glabel('BED_DATA', 'U801', 'GP0 data (PIO)', stub=12.7)
    s.glabel('BED_PROBE', 'U801', 'GP2 probe', shape='output', stub=12.7)
    s.glabel('BED_PWR', 'U801', '5V', shape='input', stub=7.62)
    s.nc('U801', '3V3')
    gnd(s, 'U801', 'GND', stub=5.08)
    s.nc('U801', 'USB')
    s.label('CHAIN_TX', 'U801', 'GP4 UART1 TX', stub=12.7)
    s.label('CHAIN_RX', 'U801', 'GP5 UART1 RX', stub=12.7)
    P = s.add_block(*boards.rtp_panel())
    s.place(P, 'U802', 'resistive touch panel', 213.36, 83.82)
    for gp, pp, net in (('GP28 XP', 'X+', 'PANEL_XP'), ('GP26 XM', 'X-', 'PANEL_XM'), ('GP27 YP', 'Y+', 'PANEL_YP'), ('GP29 YM', 'Y-', 'PANEL_YM')):
        s.label(net, 'U801', gp, stub=7.62)
        s.label(net, 'U802', pp, stub=5.08)
    s.enclose(91.44, 33.02, 241.3, 106.68, 'Going: the RTP node and its panel', planned=True)


def toolhead_mcu(s):
    '''On sheet Toolhead, beside the coupling (U505), when the coupling still had EN/PWM pins.'''
    TM = s.add_block(*boards.toolhead_mcu())
    s.place(TM, 'U506', 'toolhead MCU', 340.36, 147.32, dnp=True)
    for p, net in (('TOOL_EN', 'TOOL_EN'), ('TOOL_PWM', 'TOOL_PWM')):
        s.label(net, 'U506', p, stub=5.08)
    for p in ('TOOL_ID', 'EN_5V', 'LOCK', 'USB', '5V'):
        s.nc('U506', p)
    gnd(s, 'U506', 'GND', stub=5.08)
    s.text('A toolhead MCU (K, its endstop, ADXL345, HX711, lock sensor) by the coupling.', 241.3, 190.5)



def qre(s, V='+3V3_PH'):
    '''On sheet Plot bed board (2026-10-18 to 10-23): a QRE1113 on the toolhead\'s back, 1-2 mm from a white label on
    the tool (seated, any tool), DC (its LED steady). J954 was 4 pins (in place of the 1-pin J954), CAT6 pads 2/6/7
    (white-brown = 3V3, green = QRE_OUT, brown = GND) to J952, an RC into GP28 (QRE_ADC). Footprints: R961, C957 0805.'''
    R, C = s.use('Device', 'R'), s.use('Device', 'C')
    s.place(s.use('Connector_Generic', 'Conn_01x04'), 'J954', 'MX1.25', 88.9, 132.08, on_board=False, note='MX1.25 4-pin: ID + QRE')
    _pin_rail(s, 'J954', '1', '+3V3', V)
    s.glabel('TOOL_ID', 'J954', '2', stub=7.62)
    s.label('QRE_OUT', 'J954', '3', stub=2.54)
    _pin_rail(s, 'J954', '4', 'GND', up=False)
    QRE = s.add_block(*boards.qre1113_breakout())
    s.place(QRE, 'U954', 'QRE1113', 55.88, 134.62, on_board=False)
    q = s.P('U954', 'VCC')
    s.wire(q, (g(q[0] - 2.54), q[1]), (g(q[0] - 2.54), g(q[1] - 5.08)), chamfer=0)
    s.power_at('+3V3', (g(q[0] - 2.54), g(q[1] - 5.08)), net=V)
    s.label('QRE_OUT', 'U954', 'OUT', stub=2.54)
    gnd(s, 'U954', 'GND', stub=2.54)
    s.place(R, 'R961', '1k', 200.66, 139.7, rot=90)
    s.label('QRE_OUT', 'R961', '1')
    s.place(C, 'C957', '100n', 228.6, g(139.7 + 3.81))
    gnd(s, 'C957', '2')
    s.wire(s.P('R961', '2'), s.P('C957', '1'), (238.76, 139.7))
    s.junction(s.P('C957', '1'))
    s.label_at('QRE_ADC', (238.76, 139.7), 0)


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
