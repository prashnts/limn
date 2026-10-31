# Limn - generates the machine's KiCad project: docs/kicad/limn.kicad_pro and its sheets
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
#   python3 docs/kicad/gen.py [--force] [--check]
#   --check: ERC, the netlist audit (audit.py) and one SVG per sheet in svg/
#
# The root sheet is the overview, one sheet per role or board: power, host, tool dock, Melzi, toolhead,
# Aux MCU, calibration bed, plot bed board, hub board, beam bed. Sheets meet through global labels (USB_*, I2C1_*,
# MOT_*, ENDSTOP_*, PROBE_*, BED_*, ...) and the named power rails (+12V, +7V5_ZK, +5V_LED, ...).
# Gathered from the code and the docs (see kicad_gen/boards.py). Once the files are edited in
# KiCad, don't regenerate over them: --force overwrites.
import json
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from kicad_gen.core import Sheet, Q, dump, font, num, u, stable  # noqa: E402
from kicad_gen import sheets_a, sheets_b                         # noqa: E402

PROJECT = 'limn'
ROOT_UUID = stable('root', 'limn.kicad_sch')

SHEETS = [  # file, name, builder, title, root position (x, y), size (w, h)
    ('power.kicad_sch', 'Power', sheets_a.power_sheet, 'Limn: power', (25.4, 50.8), (50.8, 25.4)),
    ('host.kicad_sch', 'Host (Pi 4)', sheets_a.host_sheet, 'Limn: host, Raspberry Pi 4', (114.3, 50.8), (50.8, 25.4)),
    ('melzi.kicad_sch', 'Melzi (motion)', sheets_a.melzi_sheet, 'Limn: Melzi, motion', (114.3, 109.22), (50.8, 25.4)),
    ('toolhead.kicad_sch', 'Toolhead', sheets_b.toolhead_sheet, 'Limn: toolhead PCB, the FFC and the drag chain', (114.3, 152.4), (50.8, 25.4)),
    ('aux.kicad_sch', 'Aux MCU (rpi)', sheets_b.aux_sheet, 'Limn: Aux MCU, Klipper rpi', (190.5, 109.22), (50.8, 25.4)),
    ('tool_dock.kicad_sch', 'Tool dock', sheets_a.tool_dock_sheet, 'Limn: tool dock, holders and tags', (190.5, 50.8), (50.8, 25.4)),
    ('cal_bed.kicad_sch', 'Calibration bed', sheets_b.cal_bed_sheet, 'Limn: calibration bed', (266.7, 109.22), (50.8, 25.4)),
    ('plot_bed_board.kicad_sch', 'Plot bed board', sheets_b.plot_bed_board_sheet, 'Limn: the plot bed board (head cell, tool ID, bed dock)', (190.5, 152.4), (50.8, 25.4)),
    ('hub.kicad_sch', 'Hub board (USB + tool 5 V)', sheets_b.hub_sheet, 'Limn: the hub board, USB hub + the tool\'s 5 V', (25.4, 109.22), (50.8, 25.4)),
    ('beam_bed.kicad_sch', 'Beam bed (XY)', sheets_b.beam_bed_sheet, 'Limn: the beam bed, XY by two IR break-beams', (266.7, 165.1), (50.8, 25.4)),
]


# Boards with a project of their own, so the board and its schematic link (F8, cross-probing): the same sheet,
# drawn again as that project's root. Edit the generator, not one copy: the two are written together
STANDALONE = [  # file, project, builder, title
    ('toolhead_board.kicad_sch', 'toolhead_board', sheets_b.toolhead_sheet, 'Limn: the toolhead PCB (its own project)'),
]

DESCRIPTIONS = [
    'USB-C PD charger: 12 V (motion,\nswitched), 9 V (the 5 V bucks),\nthe Pi\'s port. Rails: +12V,\n+7V5_ZK, +9V, +5V_LED, +5V_TOOL.',
    'Pi 4: the cameras, the hub\nboard (the MCUs, the tool),\nI2C1 to the tool dock.',
    'Melzi v2.0: motors A, B, Z, K,\nthe endstops, the EXT header,\nthe probe pin (PROBE_A4).',
    'The toolchanger PCB (coupling,\nK lock, cell pads, FFC), the\naxis, the drag chain.',
    'RP2040-Zero (Klipper rpi) +\nMP_Buck0: the NeoPixels, the\nbuzzer, the MPU9250\'s I2C.',
    'MCP23017 + 5 holder switches,\nthe PN532 tag reader, the\nindockator strip.',
    'The detachable bed: ID resistor,\nthe FSR node and its 4 x 8\nsheet, on the pogo.',
    'limn.kicad_pcb: the head cell\n(CAT6), ADS1220, the touch line,\ntool ID/EN, the bed dock.',
    'FE1.1s hub on the Pi\'s cable,\nMP_Buck1 + switch: the tool\'s\n5 V, its USB-C cable.',
    'RP2040-Tiny, two IR LEDs +\nPT1206BS in an L: X and Y\nedges, trigger on BED_PROBE.',
]


def sheet_block(uid, name, file, at, size, page):
    x, y = at
    w, h = size
    return ['sheet', ['at', num(x), num(y)], ['size', num(w), num(h)], ['exclude_from_sim', 'no'], ['in_bom', 'yes'],
            ['on_board', 'yes'], ['dnp', 'no'], ['fields_autoplaced', 'yes'],
            ['stroke', ['width', '0.1524'], ['type', 'solid']], ['fill', ['color', '0', '0', '0', '0.0000']],
            ['uuid', Q(uid)],
            ['property', Q('Sheetname'), Q(name), ['at', num(x), num(y - 0.7116), '0'], font(justify='left bottom')],
            ['property', Q('Sheetfile'), Q(file), ['at', num(x), num(y + h + 0.5846), '0'], font(justify='left top')],
            ['instances', ['project', Q(PROJECT), ['path', Q(f'/{ROOT_UUID}'), ['page', Q(str(page))]]]]]


def main():
    out = {}
    blocks, libs = [], {}
    for page, (file, name, build, title, at, size) in enumerate(SHEETS, 2):
        block_uuid = stable('block', file)
        s = Sheet(name, file, PROJECT, f'/{ROOT_UUID}/{block_uuid}', title)
        build(s)
        out[file] = dump(s.sexpr()) + '\n'
        blocks.append(sheet_block(block_uuid, name, file, at, size, page))
        for lib_id, sym in s.lib.items():
            if lib_id.startswith('limn:'):
                libs[lib_id] = sym

    root = Sheet('Root', 'limn.kicad_sch', PROJECT, f'/{ROOT_UUID}', 'Limn: the machine')
    root.uuid = ROOT_UUID
    root.title_text('LIMN: the electronics, one sheet per role', 15.24, 15.24)
    root.text('Open a block for its sheet. Sheets meet through global labels and named power rails.\n'
              'Solid boxes: one board or assembly. Dashed: planned, or going (its parts DNP). Wires turn at 45 degrees.\n'
              'Gathered from the code and docs (2026-10-16): notebooks/pinout.md, micropython/nodes, klipper/*.cfg,\n'
              'projects/limn/content/electronics.md, docs/block-diagrams.md, docs/load-cell.md. Missing details: marked "to fill in".',
              15.24, 22.86)
    root.enclose(17.78, 40.64, 83.82, 85.09, 'Supply')
    root.enclose(17.78, 99.06, 83.82, 143.51, 'At the back')
    root.enclose(104.14, 40.64, 172.72, 85.09, 'Host')
    root.enclose(104.14, 99.06, 248.92, 187.96, 'Motion and the toolhead')
    root.enclose(180.34, 40.64, 248.92, 85.09, 'Docks')
    root.enclose(256.54, 99.06, 330.2, 200.66, 'Beds')
    for (file, name, build, title, at, size), desc in zip(SHEETS, DESCRIPTIONS):
        root.text(desc, at[0] + 2.54, at[1] + 2.54)
    root.items.extend(blocks)
    for lib_id, sym in libs.items():          # the root needs no symbols; the library gets them
        pass
    rs = root.sexpr()
    rs.insert(-1, ['sheet_instances', ['path', Q('/'), ['page', Q('1')]]])
    out['limn.kicad_sch'] = dump(rs) + '\n'

    for file, project, build, title in STANDALONE:          # a board's own project: its sheet as the root
        uid = stable('sheet', file)
        s = Sheet('Root', file, project, f'/{uid}', title)
        build(s, standalone=True)
        rs = s.sexpr()
        rs.insert(-1, ['sheet_instances', ['path', Q('/'), ['page', Q('1')]]])
        out[file] = dump(rs) + '\n'
        pro = HERE / f'{project}.kicad_pro'
        proj = json.loads(pro.read_text()) if pro.exists() else {'meta': {'filename': f'{project}.kicad_pro', 'version': 3},
                                                                  'boards': [], 'text_variables': {}}
        proj['sheets'] = [[uid, 'Root']]
        out[pro.name] = json.dumps(proj, indent=2) + '\n'

    if (HERE / 'limn.kicad_sch').exists() and '--force' not in sys.argv:
        sys.exit(f'{HERE}/limn.kicad_sch exists (maybe edited in KiCad): --force to overwrite')
    for file, text in out.items():
        (HERE / file).write_text(text)
    lib = ['kicad_symbol_lib', ['version', '20241209'], ['generator', Q('kicad_symbol_editor')], ['generator_version', Q('9.0')]]
    for lib_id, sym in sorted(libs.items()):
        s2 = list(sym)
        s2[1] = Q(lib_id.split(':')[1])
        lib.append(s2)
    (HERE / 'limn.kicad_sym').write_text(dump(lib) + '\n')
    from kicad_gen import footprints
    pretty = HERE / 'limn.pretty'
    pretty.mkdir(exist_ok=True)
    for name, make in footprints.ALL.items():
        (pretty / f'{name}.kicad_mod').write_text(make())
    (HERE / 'fp-lib-table').write_text('(fp_lib_table\n  (version 7)\n  (lib (name "limn")(type "KiCad")'
                                       '(uri "${KIPRJMOD}/limn.pretty")(options "")(descr "Limn modules, perfboard"))\n)\n')
    if not (HERE / 'limn.kicad_pcb').exists():
        from kicad_gen import perfboard
        (HERE / 'limn.kicad_pcb').write_text(perfboard.board())
    (HERE / 'sym-lib-table').write_text('(sym_lib_table\n  (version 7)\n  (lib (name "limn")(type "KiCad")'
                                        '(uri "${KIPRJMOD}/limn.kicad_sym")(options "")(descr "Limn boards and modules"))\n)\n')
    sheets = [[ROOT_UUID, "Root"]] + [[str(b[10][1]), str(b[11][2])] for b in blocks]
    pro = HERE / 'limn.kicad_pro'             # KiCad keeps the board's settings in it: only the sheets are ours
    proj = json.loads(pro.read_text()) if pro.exists() else {'meta': {'filename': 'limn.kicad_pro', 'version': 3},
                                                              'boards': [], 'text_variables': {}}
    proj['sheets'] = sheets
    pro.write_text(json.dumps(proj, indent=2) + '\n')
    print('wrote', ', '.join(out))
    if '--check' in sys.argv:
        check()


def check():
    '''ERC, the netlist audit (shorts ERC can't see) and the SVGs in svg/, one per sheet.'''
    import re
    import shutil
    import subprocess
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    subprocess.run(['kicad-cli', 'sch', 'erc', '--severity-all', '-o', str(tmp / 'erc.rpt'), str(HERE / 'limn.kicad_sch')],
                   check=True, capture_output=True)
    print(re.search(r'ERC messages.*', (tmp / 'erc.rpt').read_text()).group(0))
    subprocess.run(['kicad-cli', 'sch', 'export', 'netlist', '--format', 'kicadsexpr', '-o', str(tmp / 'limn.net'),
                    str(HERE / 'limn.kicad_sch')], check=True, capture_output=True)
    subprocess.run([sys.executable, str(HERE / 'audit.py'), str(tmp / 'limn.net')])
    svg = HERE / 'svg'
    shutil.rmtree(svg, ignore_errors=True)
    subprocess.run(['kicad-cli', 'sch', 'export', 'svg', '-n', '-o', str(tmp / 'svg'), str(HERE / 'limn.kicad_sch')],
                   check=True, capture_output=True)
    svg.mkdir()
    names = {name: Path(file).stem for file, name, *_ in SHEETS}
    for f in (tmp / 'svg').glob('*.svg'):
        sheet = f.stem[len('limn-'):] if f.stem.startswith('limn-') else ''
        shutil.copy(f, svg / ((names.get(sheet) or 'root') + '.svg'))
    print('svg:', ', '.join(sorted(p.name for p in svg.glob('*.svg'))))


if __name__ == '__main__':
    main()
