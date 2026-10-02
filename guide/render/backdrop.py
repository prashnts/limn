"""Transparent shots onto a soft grey studio gradient, as JPEG and PNG.

    uv run python guide/render/backdrop.py in-alpha.png [..]  -> in.png (opaque) beside each
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def backdrop(src: Path, dst: Path):
    im = np.asarray(Image.open(src).convert('RGBA')).astype(np.float32) / 255
    h, w = im.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    r = np.sqrt(((xx - w / 2) / w) ** 2 + ((yy - h * 0.45) / h) ** 2)
    g = np.clip(0.99 - 0.30 * r ** 1.5, 0, 1)
    bg = np.stack([g * 0.985, g * 0.99, g], -1)
    a = im[..., 3:4]
    out = im[..., :3] * a + bg * (1 - a)
    Image.fromarray((out * 255 + 0.5).astype(np.uint8)).save(dst, optimize=True)


if __name__ == '__main__':
    for f in map(Path, sys.argv[1:]):
        backdrop(f, f.with_name(f.name.replace('-alpha', '')))
