#!/usr/bin/env bash
# Everything from one STEP export: printables (STEP/STL/shots), the site with a
# shot of every assembly, the version strips, and copies of the images in ~/limn-shot.
#   guide/overnight.sh ~/limn-shot/"Limn-Export-42 v88.step" [older exports for the strips..]
set -euo pipefail
cd "$(dirname "$0")/.."
STEP="$1"; shift
OLD=("$@")
run() { echo "== $(date +%H:%M:%S) $*"; "$@"; }

run uv run --group guide python guide/export.py "$STEP" printables --shots
run uv run --group guide python guide/build.py --step "$STEP"
# the assemblies' (transparent) shots for Printables too, then the README with them
run uv run --group guide python - "$STEP" <<'PY'
import shutil, sys
from pathlib import Path
sys.path.insert(0, 'guide')
import build, export, step
src = Path(sys.argv[1])
cat = build.Catalog(step.Step(step.load(src)))
out = Path('printables/images/assemblies'); out.mkdir(parents=True, exist_ok=True)
n = 0
for p in cat.pages.values():
    shot = Path('guide/.cache/render/site') / f'{p.slug}-alpha.png'
    if p.children and not p.part.vendor and shot.exists():
        shutil.copy2(shot, out / f'{p.slug}.png'); n += 1
print(f'{n} assembly shots in {out}')
export.readme(Path('printables'), src)
PY
if [ ${#OLD[@]} -gt 0 ]; then
  run uv run --group guide python guide/compare.py printables/compare "${OLD[@]}" "$STEP"
  run uv run --group guide python guide/build.py --step "$STEP" --no-mesh --no-shots
fi
dest=~/limn-shot/limn-renders
mkdir -p "$dest"
run cp -r printables/images/. "$dest/parts/"
[ -d printables/compare ] && run cp -r printables/compare/. "$dest/compare/"
echo "== $(date +%H:%M:%S) done"
