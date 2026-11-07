import json, sys
for l in open(sys.argv[1]):
    d = json.loads(l)
    print(f"y{d['y']:.2f} z{d['z']:.2f} max {max(abs(g) for _, g, _ in d['rows']):4.0f} |",
          ' '.join(f"{g:+.0f}{'H' if o else ''}" for x, g, o in d['rows'][::2]), '| end', d['rows'][-1][0])
