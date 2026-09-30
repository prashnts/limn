# Limn cam - what needs an image library, behind one small interface
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# The rest of limn_cam is numpy. What an image library does better goes
# through a Backend: `components` (connected blobs of a mask) and `markers`
# (ArUco tags). OpenCV when it is there; numpy alone does components only.
#
#   get('auto') | get('opencv') | get('numpy')
from dataclasses import dataclass

import numpy as np


@dataclass
class Blob:
    area: int               # pixels
    mass: float             # sum of the weights over it
    centre: tuple           # (x, y), weighted
    box: tuple              # x0, y0, x1, y1


@dataclass
class Marker:
    id: int
    corners: np.ndarray     # (4, 2) pixels, the tag's own order (top-left first, clockwise)

    @property
    def centre(self):
        return self.corners.mean(axis=0)

    @property
    def size(self):
        '''Mean side, pixels.'''
        return float(np.mean(np.linalg.norm(self.corners - np.roll(self.corners, 1, axis=0), axis=1)))


def _blobs(labels, n, weights):
    ys, xs = np.nonzero(labels)
    ids = labels[ys, xs]
    w = weights[ys, xs]
    count = lambda v: np.bincount(ids, v, minlength=n + 1)
    area, mass = np.bincount(ids, minlength=n + 1), count(w)
    cx, cy = count(xs * w), count(ys * w)
    box = np.full((n + 1, 4), [1 << 30, 1 << 30, -1, -1])
    np.minimum.at(box[:, 0], ids, xs)
    np.minimum.at(box[:, 1], ids, ys)
    np.maximum.at(box[:, 2], ids, xs)
    np.maximum.at(box[:, 3], ids, ys)
    out = []
    for k in np.nonzero(area)[0]:
        if k == 0:
            continue
        m = mass[k] or 1e-9
        out.append(Blob(int(area[k]), float(mass[k]), (float(cx[k] / m), float(cy[k] / m)), tuple(int(v) for v in box[k])))
    return out


class NumpyBackend:
    name = 'numpy'

    def label(self, mask):
        '''8-connected labels of a boolean mask -> (labels, count).'''
        labels = np.zeros(mask.shape, int)
        n = 0
        h, w = mask.shape
        for y0, x0 in zip(*np.nonzero(mask)):
            if labels[y0, x0]:
                continue
            n += 1
            labels[y0, x0] = n
            stack = [(y0, x0)]
            while stack:
                y, x = stack.pop()
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        yy, xx = y + dy, x + dx
                        if 0 <= yy < h and 0 <= xx < w and mask[yy, xx] and not labels[yy, xx]:
                            labels[yy, xx] = n
                            stack.append((yy, xx))
        return labels, n

    def components(self, mask, weights):
        labels, n = self.label(mask)
        return _blobs(labels, n, weights)

    def markers(self, gray, dictionary=None):
        raise NotImplementedError('ArUco markers need the opencv backend (opencv-python-headless)')


class OpencvBackend(NumpyBackend):
    name = 'opencv'
    DICTIONARIES = ('DICT_4X4_50', 'DICT_5X5_100', 'DICT_6X6_250', 'DICT_ARUCO_ORIGINAL', 'DICT_APRILTAG_36h11')

    def __init__(self):
        import cv2
        self.cv2 = cv2

    def components(self, mask, weights):
        n, labels = self.cv2.connectedComponents(mask.astype(np.uint8), connectivity=8)
        return _blobs(labels, n - 1, weights)

    def markers(self, gray, dictionary=None):
        '''ArUco tags in a gray image (0..1 or 0..255). dictionary: a cv2.aruco
        name; None tries the usual ones and keeps the first that finds any.'''
        cv2 = self.cv2
        img = gray if gray.dtype == np.uint8 else np.clip(gray * (255 if gray.max() <= 1.5 else 1), 0, 255).astype(np.uint8)
        for name in ([dictionary] if dictionary else self.DICTIONARIES):
            det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, name)),
                                          cv2.aruco.DetectorParameters())
            corners, ids, _ = det.detectMarkers(img)
            if ids is not None and len(ids):
                return [Marker(int(i), c.reshape(4, 2)) for i, c in zip(ids.ravel(), corners)]
        return []


def get(name='auto'):
    if name in ('auto', 'opencv'):
        try:
            return OpencvBackend()
        except ImportError:
            if name == 'opencv':
                raise
    return NumpyBackend()
