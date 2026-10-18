# Limn KiCad - audit the netlist ERC can't: shorts between passive pins.
#
#   kicad-cli sch export netlist --format kicadsexpr -o /tmp/limn.net docs/kicad/limn.kicad_sch
#   python3 docs/kicad/audit.py /tmp/limn.net
#
# Flags a net that joins two different pins of one part (a board's two signals, a motor's two
# coils). Power rails (+..., GND) are skipped: supply and reference pins meet there on purpose.
import re
import sys

POWER = re.compile(r'^(GND|AGND|DGND|3V3|5V|VCC|VIN|.*GND.*)$', re.I)
t = open(sys.argv[1]).read()
bad = 0
for b in t.split('(net (code')[1:]:
    name = re.search(r'\(name "([^"]*)"\)', b).group(1)
    if name.startswith('+') or name == 'GND':
        continue                # rails: a part's supply and reference pins meet there on purpose
    nodes = re.findall(r'\(ref "([^"]+)"\)\s*\(pin "([^"]+)"\)(?:\s*\(pinfunction "([^"]*)"\))?', b)
    by_ref = {}
    for ref, pin, fn in nodes:
        by_ref.setdefault(ref, []).append(fn or pin)
    for ref, fns in by_ref.items():
        sig = [f for f in fns if not POWER.match(f)]
        if len(fns) > 1 and len(set(fns)) > 1 and sig:
            print(f'{name}: {ref} pins {fns}')
            bad += 1
print('audit:', 'ok' if not bad else f'{bad} suspicious net(s)')
sys.exit(1 if bad else 0)
