# Limn plot - tool kinds: how a tool comes down, draws and goes up
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# A tool in tools.toml is an instance of a kind; its keys are the kind's fields.
#
# How hard a pen goes down is `press`: mm past where it first touches the paper,
# machine.z_touch (the tags are written so each pen touches there). Pressing
# lifts the Z axis within its play (GEOMETRY.md), so the lift after a stroke is
# its press, then `play.clear`, then what the play adds there (profile.Play).
# `press_max` is never passed: a fineliner is delicate. Without `press` a pen
# goes down to its `z_down` and hops `hop` over it, as before.
# The emitter (emit.py) travels between strokes, a kind only says how high it
# hops (lift), and what it does at the start of a stroke (engage), along it
# (draw) and at its end (disengage). Points are (x, y, z) with z the surface
# under the tool, 0 on paper; the kind adds its own heights.
#
# A kind of your own, in a file listed in `plugins` of tools.toml:
#
#     from plot.tools import Pen, kind
#
#     @kind('marker')
#     class Marker(Pen):
#         press: float = 0.2          # a new key for tools.toml
#
#         def down(self, ctx, z):
#             return z + self.z_down - self.press
import importlib
import importlib.util
import math
from pathlib import Path
from typing import ClassVar

import numpy as np
from pydantic import BaseModel, ConfigDict

REGISTRY: dict[str, type['Tool']] = {}


def kind(name):
    '''Register a tool kind under `name`, for `kind = "name"` in tools.toml.'''
    def register(cls):
        REGISTRY[name] = cls
        return cls
    return register


def resolve(name):
    if name in REGISTRY:
        return REGISTRY[name]
    if ':' in name:
        module, attr = name.split(':', 1)
        return getattr(importlib.import_module(module), attr)
    raise ValueError(f"no tool kind {name!r}, known: {', '.join(sorted(REGISTRY))}")


def load_plugin(path: Path):
    spec = importlib.util.spec_from_file_location(f'limn_plot_plugin_{path.stem}', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Tool(BaseModel):
    model_config = ConfigDict(extra='forbid')

    id: str
    kind: str
    name: str = ''
    color: str = '#000000'
    width: float = 0.5          # mm, the line it leaves
    overlap: float = 0.15       # fills: how much of its width neighbouring lines share
    feed: float = 3000          # mm/min, drawing
    macro: str | None = None    # picks the tool up; default: its id (T0 -> DOCK T=41)
    begin: str | None = None    # instead of the machine's tool_begin / tool_end
    end: str | None = None
    z_min: float | None = None  # narrow the machine's z limits for this tool
    z_max: float | None = None
    link: float | None = None   # stays down across gaps up to this; default half its width
    pen: str | None = None      # the pen library's key (pens.toml), from the tool's tag
    holder: int | None = None   # the holder it is in, when its tag says what it is
    source: str = 'profile'     # profile: tools.toml; tag: its tag; stale: a tag from before a hand was there
    press: float | None = None      # mm past first touch (machine.z_touch); None: z_down as it is
    press_max: float | None = None  # never more, whatever a job asks: fineliners are delicate

    @property
    def call(self):
        return self.macro or self.id

    @property
    def spacing(self):
        return self.width * (1 - self.overlap)

    @property
    def link_gap(self):
        return self.width / 2 if self.link is None else self.link

    def z_limits(self, machine):
        lo = machine.z_min if self.z_min is None else max(machine.z_min, self.z_min)
        hi = machine.z_max if self.z_max is None else min(machine.z_max, self.z_max)
        return lo, hi

    touches: ClassVar[bool] = True      # a laser doesn't: the play never comes into it
    draws: ClassVar[bool] = True        # a camera doesn't: nothing is painted with it

    @property
    def pressed(self):
        '''The press used: press, never over press_max. None: no press, z_down.'''
        if self.press is None:
            return None
        return min(self.press, self.press_max) if self.press_max is not None else self.press

    def lift(self, ctx=None, at=None):
        '''How high over the surface a short hop between strokes goes, leaving
        from `at` (x, y): where the pen was pressed, and the play lifted the axis.'''
        raise NotImplementedError

    def engage(self, ctx, p):
        raise NotImplementedError

    def draw(self, ctx, pts):
        raise NotImplementedError

    def disengage(self, ctx):
        raise NotImplementedError


@kind('pen')
class Pen(Tool):
    kind: str = 'pen'
    z_down: float = 1.0         # over the surface, touching (as the test marks: Z1)
    hop: float = 1.2            # over z_down between strokes, the mesh applied.
                                # 2026-09-29, Stabilo on BED_5: 0.8 drags, 1.0 clears
    plunge_feed: float = 300

    def pen_z(self, ctx):
        '''Over the surface, drawing: z_touch less the press, or z_down.'''
        p = self.pressed
        return self.z_down if p is None or ctx is None else ctx.m.z_touch - p

    def rise(self, ctx, at=None):
        '''How far up from drawing until the tip has let go of the paper and is
        `clear` over it: the press, the clearance, and the play's lift at `at`.'''
        p = self.pressed
        if p is None or ctx is None:
            return self.hop
        play = ctx.m.play
        return p + play.clear + (play.extra(at, p) if at is not None else play.worst(p))

    def lift(self, ctx=None, at=None):
        return self.pen_z(ctx) + self.rise(ctx, at)

    def down(self, ctx, z):
        '''z of the tool drawing over a surface at z.'''
        return z + self.pen_z(ctx)

    def engage(self, ctx, p):
        ctx.g.line(z=ctx.clamp(self, self.down(ctx, p[2])), f=self.plunge_feed)

    def draw(self, ctx, pts):
        for a, b in zip(pts[:-1], pts[1:]):
            ctx.drawn[self.id] = ctx.drawn.get(self.id, 0.0) + math.dist(a[:2], b[:2])
            ctx.g.line(x=b[0], y=b[1], z=ctx.clamp(self, self.down(ctx, b[2])), f=self.feed)

    def disengage(self, ctx):
        at = None if ctx.g.x is None or ctx.g.y is None else (ctx.g.x, ctx.g.y)
        ctx.g.rapid(z=ctx.clamp(self, ctx.g.z + self.rise(ctx, at)), f=ctx.m.feed_z)


@kind('pencil')
class Pencil(Pen):
    '''A pen whose lead wears: it goes lower the more it has drawn.'''
    kind: str = 'pencil'
    wear: float = 0.0           # mm lower per metre drawn

    def down(self, ctx, z):
        return z + self.pen_z(ctx) - self.wear * ctx.drawn.get(self.id, 0.0) / 1000


@kind('brush')
class Brush(Pen):
    '''A pen that runs dry: back to the paint well every `reload_every` mm.'''
    kind: str = 'brush'
    reload_every: float = 150
    well: tuple[float, float] = (100, 20)
    well_z: float = 0.5         # brush z in the well
    dips: int = 2

    def _load(self, ctx):
        return ctx.state.setdefault(self.id, {'load': 0.0})

    def reload(self, ctx, p):
        ctx.travel(self, (*self.well, 0.0))
        for _ in range(self.dips):
            ctx.g.line(z=ctx.clamp(self, self.well_z), f=self.plunge_feed)
            ctx.g.rapid(z=ctx.clamp(self, self.well_z + self.hop), f=ctx.m.feed_z)
        self._load(ctx)['load'] = self.reload_every
        ctx.travel(self, p)

    def engage(self, ctx, p):
        if self._load(ctx)['load'] <= 0:
            self.reload(ctx, p)
        super().engage(ctx, p)

    def draw(self, ctx, pts):
        load = self._load(ctx)
        for a, b in zip(pts[:-1], pts[1:]):
            a, b = np.asarray(a, float), np.asarray(b, float)
            # Dry part way along: draw up to there, reload, and carry on from there
            while math.dist(a[:2], b[:2]) > load['load']:
                t = load['load'] / math.dist(a[:2], b[:2])
                mid = a + (b - a) * t
                super().draw(ctx, [a, mid])
                self.disengage(ctx)
                self.reload(ctx, mid)
                super().engage(ctx, mid)
                a = mid
            super().draw(ctx, [a, b])
            load['load'] -= math.dist(a[:2], b[:2])


@kind('laser')
class Laser(Tool):
    '''Stays at its focus over the surface, on while drawing.'''
    kind: str = 'laser'
    focus: float = 5.0
    power: int = 255
    on: str = 'M3 S{power}'
    off: str = 'M5'

    touches: ClassVar[bool] = False

    def lift(self, ctx=None, at=None):
        return self.focus

    def engage(self, ctx, p):
        ctx.g.rapid(z=ctx.clamp(self, p[2] + self.focus), f=ctx.m.feed_z)
        ctx.g.raw(self.on.format(power=self.power), moves=False)

    def draw(self, ctx, pts):
        for b in pts[1:]:
            ctx.g.line(x=b[0], y=b[1], z=ctx.clamp(self, b[2] + self.focus), f=self.feed)

    def disengage(self, ctx):
        ctx.g.raw(self.off, moves=False)


@kind('camera')
class Camera(Tool):
    """A camera on a tool, for scanning (limn_cam/scan.py): it neither draws nor
    touches. Its heights are the machine's own Z, no mesh and no tag dz (they are
    cleared once it is picked up): Z8 is home. It moves sideways only at
    `clear_z` or higher, clear of everything raised on the bed, and goes down
    only over the spot it shoots, never under `z_min` (4 unless its library entry
    says). It is focused by height: at `focus_z` what lies on the bed is
    sharpest, and one shot takes `fov` mm."""
    kind: str = 'camera'
    webcam: str = ''                    # its name in Moonraker's webcams
    fov: tuple[float, float] = (16.0, 9.0)      # mm across the image (its x) and down it (its y), at focus_z
    clear_z: float = 7.5                # moving sideways: clear of the bed's raised parts (home is Z8)
    focus_z: float = 7.5                # until found: as high as it travels
    turn: float = 0.0                   # degrees the image is turned from the machine's axes
    settle: float = 0.4                 # s still before a shot (the tether, the frame the stream has queued)
    touches: ClassVar[bool] = False
    draws: ClassVar[bool] = False
    Z_TOP: ClassVar[float] = 9.8        # the Z axis's position_max 10, less a little

    def lift(self, ctx=None, at=None):
        return self.clear_z

    def z_limits(self, machine=None):
        """Machine Z, not the plot's G-code limits (those leave room for a pen's dz)."""
        lo = 4.0 if self.z_min is None else self.z_min
        hi = self.Z_TOP if self.z_max is None else min(self.z_max, self.Z_TOP)
        return lo, hi
