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
    '''What to do with one colour of a drawing ('stroke #e2001a', 'fill #ffffff').
    None: as its tool draws (tools.DRAW: the job's draw settings, the tool's own).'''
    model_config = ConfigDict(extra='forbid')
    tool: str | None = None         # None: not drawn
    mask: bool = False              # not drawn, but hides what is under it (white casings)
    stroke: Literal['auto', 'centerline', 'width'] | None = None     # width: fill the stroke's area
    fill: Literal['hatch', 'crosshatch', 'concentric', 'none'] | None = None
    angle: float | None = None
    border: bool | None = None      # fills: outline the area too
    spacing: float | None = None    # fills: instead of the tool's
    inset: bool | None = None       # fills: kept the tool's `bleed` inside its own edge (smooth corners)


class ShapePaint(BaseModel):
    '''One shape painted apart from its colour: its stroke, its fill, or both; or only
    its fill's margin and border, whatever draws it.'''
    model_config = ConfigDict(extra='forbid')
    stroke: Group | None = None
    fill: Group | None = None
    inset: bool | None = None       # its fill kept its tool's bleed inside its edge
    border: bool | None = None      # its fill outlined (along that inner edge, with the inset)


class ShapeSet(BaseModel):
    '''Shapes of a drawing grouped by hand: painted together, over their colours' layers
    (a shape's own paint still wins). Only how they are drawn: the shapes themselves stay.'''
    model_config = ConfigDict(extra='forbid')
    name: str
    shapes: list[int] = []          # shape indexes
    stroke: Group | None = None
    fill: Group | None = None
    inset: bool | None = None       # as ShapePaint's
    border: bool | None = None


class TextSpec(BaseModel):
    '''How a <text> is drawn. auto: in its own font when it is uploaded, else a line font.'''
    model_config = ConfigDict(extra='forbid')
    mode: Literal['auto', 'source', 'line', 'skip'] = 'auto'
    font: str | None = None         # source: an uploaded file, instead of the one its font-family finds
    line_font: str = 'futural'      # Hershey name, or an uploaded SVG font
    fit: Literal['cap', 'width'] = 'cap'    # line: caps as high as the source's; width: as wide too


class RasterSpec(BaseModel):
    '''What becomes of a drawing's <image>s (raster.py): left out, or made into lines.'''
    model_config = ConfigDict(extra='forbid')
    mode: Literal['skip', 'dither', 'lines', 'halftone'] = 'skip'
    separate: Literal['one', 'cmyk', 'pens', 'palette'] = 'one'     # one colour; cyan, magenta, yellow and black;
                                                    # the pens'; the picture's own colours (a pen each)
    colours: int = Field(4, ge=1, le=12)            # palette: how many of the picture's colours
    pens: list[str] = []            # separate onto these tools; empty: every one that draws
    pitch: float | None = Field(None, gt=0.02)  # mm as plotted between lines, dither cells, a dot's turns; None: its pen's
    cell: float | None = Field(None, gt=0.1)    # halftone: mm between dots; None: from its pen's width
    colour: str = Field('#000000', pattern=r'^#[0-9a-fA-F]{6}$')    # 'one': its colour's layer draws it
    gamma: float = Field(1.0, gt=0.1, lt=5)  # over 1: lighter, more paper
    paper: float = Field(0.1, ge=0, lt=1)   # darkness up to this is the paper: no ink (a light background)
    invert: bool = False


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
    sets: list[ShapeSet] = []       # shapes grouped by hand; the later set wins for a shape in two
    group: str | None = None        # drawings of one group move and hide together (the UI)
    raster: RasterSpec = Field(default_factory=RasterSpec)  # its <image>s: left out, or made into lines
    images: dict[str, RasterSpec] = {}  # but these, by image index: their own (raster.spec_of)
    text: TextSpec = Field(default_factory=TextSpec)     # every <text>,
    texts: dict[str, TextSpec] = {}     # but these, by index
    placement: Placement = Field(default_factory=Placement)
    surface: SurfaceSpec = Field(default_factory=SurfaceSpec)
    # Regions where nothing of it is drawn (eg. over what is printed there already):
    # polygons in the drawing's mm at scale 1, y up, like its shapes before the scale
    masks: list[list[tuple[float, float]]] = []


class PlanPen(BaseModel):
    '''A pen the plot is planned with, scanned or not: T5, T6, .. (job.pens), painted like
    the tools in the holders. When the plot is made it goes to the plotter as a tool in a
    holder of the same pen and colour, or is swapped into a holder by hand mid-plot, once
    that holder's own pen is done (profile.plan_pens).'''
    model_config = ConfigDict(extra='forbid')
    pen: str | None = None          # the pen library's key (pens.toml); None: a plain pen of `width`
    color: str = Field('#000000', pattern=r'^#[0-9a-fA-F]{6}$')
    name: str = ''                  # '': the library's short name and the colour's
    width: float | None = Field(None, gt=0)     # instead of the library's
    use: str | None = None          # drawn by this tool in a holder as it is (T2): no swap
    holder: int | None = None       # swapped into this holder; None (and no `use`): a holder of the
                                    # same pen and colour, else swapped into one whose pen is done first
    calibrate: bool = False         # probed on the bed's sensor once it is in, whatever its tag says


class Job(BaseModel):
    model_config = ConfigDict(extra='forbid')
    machine: str = 'limn'
    machine_overrides: dict = {}    # e.g. {"z_travel": 6, "z_max": 6.5}
    tools: str = 'tools'
    tool_overrides: dict[str, dict] = {}    # by tool: keys of tools.toml, e.g. {"T0": {"width": 0.4}}
    draw: dict = {}                 # how every tool draws (tools.DRAW), e.g. {"feed": 2000, "bleed": 0.3};
                                    # a tool's tool_overrides win
    tool_order: list[str] | None = None
    pens: dict[str, PlanPen] = {}   # the plan's own pens, by tool id: T5, T6, .. (after the holders')
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
