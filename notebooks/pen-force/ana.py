# Load a pen-draw log: marks, cell samples (t, g) and the toolhead at any time.
import json, sys


def load(path):
    L = [json.loads(l) for l in open(path)]
    meta, sync = L[0]['meta'], L[0]['sync']
    c = [x[1:] for x in L[1:] if x[0] == 'c']
    q = sorted(x[1:] for x in L[1:] if x[0] == 'q')
    off = sum(p - e for e, p in sync) / len(sync)

    def pos(t):
        pt = t + off
        for s in q:
            if s[0] <= pt <= s[0] + s[1]:
                d = pt - s[0]; dist = s[2] * d + 0.5 * s[3] * d * d
                return [s[4][i] + s[5][i] * dist for i in range(3)], s[2] + s[3] * d
        return None, 0
    return meta, c, pos


if __name__ == '__main__':
    meta, c, pos = load(sys.argv[1])
    for k in meta['marks'][int(sys.argv[2]):int(sys.argv[3])]:
        print(k['label'], k['kind'])
        for i, (t, g, fl) in enumerate(x for x in c if k['t0'] <= x[0] <= k['t1']):
            p, v = pos(t)
            if p and i % int(sys.argv[4] if len(sys.argv) > 4 else 3) == 0:
                print(f'{t - k["t0"]:6.2f} {g:7.1f}  x{p[0]:6.2f} y{p[1]:6.2f} z{p[2]:6.3f} v{v:5.1f}')
