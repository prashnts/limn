# Make a board of its own for one sheet (the hub board, the Aux PCB, the beam bed): the sheet's parts that have a
# footprint, with the netlist's nets, placed in rows on the board (not routed). limn.kicad_pcb stays the plot bed
# board's: these sheets' parts are "not on board" there (sheets_b.own_board), so Update PCB never brings them in.
# Never writes over an existing board (--force does); later changes: by hand, or a sync like tools/sync.py.
#
#   python3 tools/mkboard.py hub|aux|beam|head [--force]
import re, sys, subprocess, tempfile
from pathlib import Path
import pcbnew

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from kicad_gen import perfboard  # noqa: E402

P = 2.54
# a first placement, to move: perfboards in holes from the first one (col, row; SMD at .5 bridges two holes),
# the beam bed in mm from the board's first grid point; (col, row, rotation)
LAYOUT = {
    'hub': {'U1001': (2, 1, 0), 'U1002': (12, 0, 0), 'U1003': (22, 1, 0), 'U1004': (22, 4, 0), 'J1002': (27, 0, 0),
            'J1001': (0, 7, 0), 'U1005': (0, 10, 0), 'U1006': (21, 11, 0), 'R1001': (21.5, 8, 0), 'R1002': (24.5, 8, 0),
            'F1001': (30, 13, 0), 'U1007': (33, 8, 0)},
    'aux': {'U601': (1, 1, 0), 'Q601': (11, 4, 0), 'BZ601': (16, 4, 0), 'J601': (7, 12, 0), 'U604': (10, 10, 0)},
    'beam': {'U851': (1.27, 2.54, 0), 'R860': (20.3, 1.5, 0), 'R861': (20.3, 5.0, 0),
             'R852': (25.0, 2.0, 0), 'R854': (25.0, 5.0, 0), 'Q851': (29.5, 3.5, 0), 'R853': (34.0, 2.0, 0), 'D852': (38.5, 2.0, 0),
             'R855': (25.0, 10.0, 0), 'R857': (25.0, 13.0, 0), 'Q852': (29.5, 11.5, 0), 'R856': (34.0, 10.0, 0), 'D853': (38.5, 10.0, 0),
             'R858': (25.0, 19.0, 0), 'Q853': (30.0, 19.0, 0), 'R859': (25.0, 23.0, 0), 'Q854': (30.0, 23.0, 0),
             'J851': (3.0, 28.5, 90), 'R851': (24.0, 28.5, 0)},
    'head': {'U506': (55.0, 30.0, 0), 'M502': (9.0, 13.0, 0), 'SW503': (30.0, 8.0, 0), 'C503': (25.0, 16.0, 90),
             'J502': (40.0, 6.0, 0), 'J503': (43.0, 6.0, 0), 'J504': (40.0, 10.0, 0), 'J505': (43.0, 10.0, 0),
             'H501': (34.0, 19.0, 0), 'H502': (52.0, 5.0, 0), 'H503': (56.0, 17.0, 0),
             'J501': (5.0, 28.0, 270), 'C504': (10.0, 32.0, 90), 'C505': (10.0, 36.0, 90),
             'C501': (16.0, 32.0, 90), 'C502': (16.0, 36.0, 90), 'R501': (16.0, 41.0, 90), 'D501': (16.0, 45.0, 90)},
}
BOARDS = {   # sheet name, file, title, perfboard args
    'hub': ('Hub board (USB + tool 5 V)', 'hub_board.kicad_pcb', 'Limn hub board: perfboard', {}),
    'aux': ('Aux MCU (rpi)', 'aux_board.kicad_pcb', 'Limn Aux PCB: perfboard', {}),
    'beam': ('Beam bed (XY)', 'beam_bed_board.kicad_pcb', 'Limn beam bed: the beam node',
             dict(cols=17, rows=13, margin=1.27, holes=False)),       # 43.2 x 33.0 mm, to fit the bed
    'head': ('', 'toolhead_board.kicad_pcb', 'Limn toolhead PCB: the toolchanger',        # its own project's root
             dict(cols=25, rows=21, margin=1.27, holes=False)),       # 61 x 50.8 mm: a first outline, to fit the head
}


def netlist(project='limn'):
    # kicad-cli leaves "not on board" parts out of the netlist: export from a copy with them back on
    tmp = Path(tempfile.mkdtemp())
    for f in list(HERE.glob('*.kicad_sch')) + [HERE / f'{project}.kicad_pro', HERE / 'limn.kicad_sym', HERE / 'sym-lib-table']:
        (tmp / f.name).write_text(f.read_text().replace('(on_board no)', '(on_board yes)'))
    out = tmp / 'limn.net'
    subprocess.run(['kicad-cli', 'sch', 'export', 'netlist', '--format', 'kicadsexpr', '-o', str(out),
                    str(tmp / f'{project}.kicad_sch')], check=True, capture_output=True)
    nl = out.read_text()
    comps = {}
    for m in re.finditer(r'\(comp \(ref "([^"]+)"\)(.*?)\n\s*\(tstamps "([^"]+)"\)\)', nl, re.S):
        body = m.group(2)
        fp = re.search(r'\(footprint "([^"]*)"\)', body)
        sheet = re.search(r'\(sheetpath \(names "([^"]*)"\) \(tstamps "([^"]*)"\)\)', body)
        comps[m.group(1)] = dict(value=re.search(r'\(value "([^"]*)"\)', body).group(1), fp=fp.group(1) if fp else '',
                                 dnp='(property (name "dnp")' in body, no_bom='(property (name "exclude_from_bom")' in body,
                                 sheet=sheet.group(1), path=sheet.group(2) + m.group(3))
    pinnet = {}
    for block in nl.split('(net (code ')[1:]:
        name = re.match(r'"\d+"\) \(name "([^"]*)"\)', block).group(1)
        for ref, pin in re.findall(r'\(node \(ref "([^"]+)"\) \(pin "([^"]+)"\)', block):
            pinnet[(ref, pin)] = name
    return comps, pinnet


def lib_path(lib):
    return str(HERE / 'limn.pretty') if lib == 'limn' else f'/usr/share/kicad/footprints/{lib}.pretty'


def main():
    key = sys.argv[1]
    sheet, file, title, args = BOARDS[key]
    dst = HERE / file
    if dst.exists() and '--force' not in sys.argv:
        sys.exit(f'{file} exists (a layout?): not touched; --force to write over it')
    project = file.replace('.kicad_pcb', '') if (HERE / file.replace('.kicad_pcb', '.kicad_sch')).exists() else 'limn'
    comps, pinnet = netlist(project)
    sheet = f'/{sheet}/' if sheet else '/'
    parts = sorted((r for r, c in comps.items() if c['sheet'] == sheet and c['fp']),
                   key=lambda r: (not r.startswith('U'), r[0] != 'J', r))      # modules first, then connectors
    dst.write_text(perfboard.board(title=title, **args))
    board = pcbnew.LoadBoard(str(dst))
    nets = {}

    def net(name):
        if name not in nets:
            nets[name] = pcbnew.NETINFO_ITEM(board, name)
            board.Add(nets[name])
        return nets[name]

    cols, rows, margin = args.get('cols', 38), args.get('rows', 17), args.get('margin', 3.81)
    x0, y0 = 50.8, 50.8
    right = x0 + (cols - 1) * P
    x, y, shelf = x0, y0, 0.0          # rows of parts, left to right, on the 2.54 grid; past the edge: below the board
    layout, unit = LAYOUT.get(key, {}), (1.0 if not args.get('holes', True) else P)
    y = y0 + (rows - 1) * P + margin + 5 if layout else y0     # parts with no place: below the board
    for ref in parts:
        c = comps[ref]
        lib, name = c['fp'].split(':')
        fp = pcbnew.FootprintLoad(lib_path(lib), name)
        fp.SetFPID(pcbnew.LIB_ID(lib, name))          # else the library nickname is empty: a parity mismatch
        fp.SetDNP(c['dnp'])                           # and the symbol's DNP / BOM, not the library's
        fp.SetExcludedFromBOM(c['no_bom'])
        fp.SetReference(ref)
        fp.SetValue(c['value'])
        fp.SetPath(pcbnew.KIID_PATH(c['path']))
        board.Add(fp)
        for pad in fp.Pads():
            n = pinnet.get((ref, pad.GetNumber()))
            if n:
                pad.SetNet(net(n))
        if ref in layout:
            col, row, angle = layout[ref]
            fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x0 + col * unit), pcbnew.FromMM(y0 + row * unit)))
            fp.SetOrientationDegrees(angle)
            continue
        fp.SetPosition(pcbnew.VECTOR2I(0, 0))
        box = fp.GetCourtyard(pcbnew.F_CrtYd).BBox() if fp.GetCourtyard(pcbnew.F_CrtYd).OutlineCount() else fp.GetBoundingBox(False)
        bx, by = pcbnew.ToMM(box.GetX()), pcbnew.ToMM(box.GetY())
        bw, bh = pcbnew.ToMM(box.GetWidth()), pcbnew.ToMM(box.GetHeight())
        if x > x0 and x + bw > right + P:
            x, y, shelf = x0, y + shelf + P, 0.0
        px = round((x - bx - x0) / P + 0.4999) * P + x0      # the part's origin on a grid point, its box right of x
        py = round((y - by - y0) / P + 0.4999) * P + y0
        fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(px), pcbnew.FromMM(py)))
        x = px + bx + bw + P
        shelf = max(shelf, py + by + bh - y)
    board.Save(str(dst))
    off = [r for r, c in comps.items() if c['sheet'] == sheet and not c['fp'] and not r.startswith('#')]
    print(f'wrote {file}: {len(parts)} parts, {len(nets)} nets; no footprint (off the board): {" ".join(off) or "-"}')


if __name__ == '__main__':
    main()
