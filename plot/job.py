# Limn plot - a job: what goes on the bed, drawn with what
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Saved as JSON. Paths in it are relative to the job file. An object is sliced
# in its own coordinates (mm, y up, origin at the page's bottom left); its
# placement is applied when the G-code is written, so moving or turning it
# doesn't slice it again. Anything else that changes does.
import json
import math
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


class Group(BaseModel):
    '''What to do with one colour of a drawing ('stroke #e2001a', 'fill #ffffff').'''
    model_config = ConfigDict(extra='forbid')
    tool: str | None = None         # None: not drawn
    mask: bool = False              # not drawn, but hides what is under it (white casings)
    stroke: Literal['auto', 'centerline', 'width'] = 'auto'     # width: fill the stroke's area
    fill: Literal['hatch', 'crosshatch', 'concentric', 'none'] = 'hatch'
    angle: float = 45
    border: bool = True             # fills: outline the area too
    spacing: float | None = None    # fills: instead of the tool's


class ShapePaint(BaseModel):
    '''One shape painted apart from its colour: its stroke, its fill, or both.'''
    model_config = ConfigDict(extra='forbid')
    stroke: Group | None = None
    fill: Group | None = None


class TextSpec(BaseModel):
    '''How a <text> is drawn. auto: in its own font when it is uploaded, else a line font.'''
    model_config = ConfigDict(extra='forbid')
    mode: Literal['auto', 'source', 'line', 'skip'] = 'auto'
    font: str | None = None         # source: an uploaded file, instead of the one its font-family finds
    line_font: str = 'futural'      # Hershey name, or an uploaded SVG font
    fit: Literal['cap', 'width'] = 'cap'    # line: caps as high as the source's; width: as wide too


class SurfaceSpec(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['flat', 'heightmap'] = 'flat'
    path: str | None = None
    origin: tuple[float, float] = (0, 0)
    pitch: float = 1.0


class Placement(BaseModel):
    model_config = ConfigDict(extra='forbid')
    x: float = 0
    y: float = 0
    rotate: float = 0               # degrees, counterclockwise about the object's origin

    def _cs(self):
        r = math.radians(self.rotate)
        return math.cos(r), math.sin(r)

    def apply(self, pts):
        pts = np.array(pts, float)
        c, s = self._cs()
        x, y = pts[:, 0].copy(), pts[:, 1].copy()
        pts[:, 0] = c * x - s * y + self.x
        pts[:, 1] = s * x + c * y + self.y
        return pts

    def local(self, pts):
        pts = np.array(pts, float)
        c, s = self._cs()
        x, y = pts[:, 0] - self.x, pts[:, 1] - self.y
        pts[:, 0] = c * x + s * y
        pts[:, 1] = -s * x + c * y
        return pts


class Obj(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str
    svg: str
    scale: float = 1.0
    tolerance: float = 0.02         # mm, curves flattened to within
    occlude: bool = True            # what is painted over hides what is under
    groups: dict[str, Group] = {}   # by colour key; missing ones: nearest tool by colour
    shapes: dict[str, ShapePaint] = {}  # by shape index: painted apart from their colour
    text: TextSpec = Field(default_factory=TextSpec)     # every <text>,
    texts: dict[str, TextSpec] = {}     # but these, by index
    placement: Placement = Field(default_factory=Placement)
    surface: SurfaceSpec = Field(default_factory=SurfaceSpec)


class Job(BaseModel):
    model_config = ConfigDict(extra='forbid')
    machine: str = 'limn'
    machine_overrides: dict = {}    # e.g. {"z_travel": 6, "z_max": 6.5}
    tools: str = 'tools'
    tool_overrides: dict[str, dict] = {}    # by tool: keys of tools.toml, e.g. {"T0": {"width": 0.4}}
    tool_order: list[str] | None = None
    objects: list[Obj] = []
    _root: Path = PrivateAttr(default_factory=lambda: Path('.'))

    @classmethod
    def load(cls, path):
        path = Path(path)
        job = cls(**json.loads(path.read_text()))
        job._root = path.parent
        return job

    def save(self, path):
        Path(path).write_text(self.model_dump_json(indent=2) + '\n')

    @property
    def root(self) -> Path:
        return self._root
