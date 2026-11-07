# K switch map over a wide range: 0 -> +span -> -span -> 0 (K units, 0.754 mm of rack each)
import sys, time
sys.path.insert(0, '/home/pi/claude-cell')
import penrec
from penrec import gcode
from sanity import k_switch

r = penrec.Rec(hz=25)
span, step = float(sys.argv[1]), float(sys.argv[2])
n = int(span / step)
path = [i * step for i in range(n + 1)] + [i * step for i in range(n - 1, -n - 1, -1)] + [i * step for i in range(-n + 1, 1)]
gcode('MANUAL_STEPPER STEPPER=axis_k ENABLE=1 SET_POSITION=10')
row, at = [], 0.0
for p in path:   # relative steps around 10: the config allows 0..20 only
    gcode(f'MANUAL_STEPPER STEPPER=axis_k SET_POSITION=10 MOVE={10 + p - at:.3f} SPEED=5'); at = p; time.sleep(0.1)
    row.append(f'{p:g}{"T" if k_switch(r) else "o"}')
gcode('MANUAL_STEPPER STEPPER=axis_k ENABLE=0')
print(' '.join(row))
