# Line widths from the phone photo (IMG_7490): darkness profiles across both blocks.
import numpy as np
from PIL import Image, ImageOps

im = ImageOps.exif_transpose(Image.open('/home/noop/limn-shot/IMG_7490.JPG')).convert('L')
a = np.asarray(im, float)
s = 4032 / 1600                                   # thumbnail -> full res


def lines(profile, min_gap):
    """Dark runs in a 1-D profile: (centre, width px) at half depth."""
    p = profile.max() - profile
    p = p / np.percentile(p, 99)
    on = p > 0.5
    runs, i = [], 0
    while i < len(on):
        if on[i]:
            j = i
            while j < len(on) and on[j]:
                j += 1
            if j - i >= 3:
                runs.append(((i + j) / 2, j - i))
            i = j + min_gap // 3
        else:
            i += 1
    return runs


def block(x0, x1, y0, y1, axis):
    """axis 0: vertical lines (profile along x); 1: horizontal lines (profile along y)."""
    sub = a[int(y0 * s):int(y1 * s), int(x0 * s):int(x1 * s)]
    if axis == 1:
        sub = sub.T
    rows = [lines(r, 30) for r in sub[::8]]
    n = int(np.median([len(r) for r in rows]))
    rows = [r for r in rows if len(r) == n]
    w = np.median(np.array([[x[1] for x in r] for r in rows]), axis=0)
    return w, len(rows)


if __name__ == '__main__':
    # Thumbnail coords of the blocks' clean middles (no first-run scribbles)
    xl, n1 = block(595, 935, 640, 760, 0)    # x lines (vertical in the photo), i17 left .. i0 right
    yl, n2 = block(1100, 1300, 590, 820, 1)  # y lines (horizontal), i17 top .. i4/5
    pitch = 1.2 / np.median(np.diff([0])) if False else None
    print('x lines', n1, 'rows:', ' '.join(f'{v:.0f}' for v in xl))
    print('y lines', n2, 'cols:', ' '.join(f'{v:.0f}' for v in yl))
