# Limn - tool alignment with the resistive touch panel (BED_3)
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Calibration, with the reference tool (T4):
#   1. BLTouch z over a grid on the panel (ref_z_panel). The bed meshes are
#      LRT_MESH_CALIBRATE's, taken just before.
#   2. Three touches -> raw panel to plotter transform (Atmel AVR341).
#   3. The reference tool probes the same grid: where the panel sees it at
#      each point (ref_samples). This is what other tools are compared with,
#      point by point, so the transform only needs to be roughly right.
# Another tool probes the grid again; the difference to ref_samples is its offset.
import random

import numpy as np

from .geometry import (ProbeValue, gen_bb_grid, rtp_raw_xy, touch_transform,
                       apply_transform, spread, rtp_reference_z, rtp_tool_offsets)
from .samples import RTP, S_SAMPLE


class Rtp:

    def __init__(self, machine, dock, samples, cfg):
        self.machine = machine
        self.dock = dock
        self.samples = samples
        self.cfg = cfg

    def grid(self):
        return gen_bb_grid(**self.cfg['grid'], z_park=self.cfg['z_park'])

    def probe_at(self, coord):
        '''Probes down at `coord` (x, y, park z). The probe endstop is the
        BLTouch or the panel's touch pulse, whichever comes first.
        -> (probe result, N x 2 raw panel readings in plotter axis order)'''
        self.dock.send('arm(rtp)')
        self.machine.move(*coord)
        self.samples.start()
        try:
            result = self.machine.probe()
        finally:
            recorded = self.samples.stop()
            self.machine.move(*coord)
            self.dock.send('disarm()')
        raw = [rtp_raw_xy(s.values) for s in recorded if s.kind == RTP and s.state == S_SAMPLE]
        return result, np.array(raw, dtype=float).reshape(-1, 2)

    def probe_mesh(self, coords):
        '''BLTouch z at each point, the probe moved over the point.'''
        x_offset, y_offset, z_offset = self.machine.probe_offsets()
        offset = np.array([x_offset, y_offset, -z_offset])
        data = []
        for ix, coord in enumerate(coords):
            self.machine.say(f"[LRT] MESH_PROBE [{ix + 1}/{len(coords)}]")
            result, _ = self.probe_at((np.array(coord) - offset).tolist())
            data.append(ProbeValue(*coord, result.test_x, result.test_y, result.test_z))
        return data

    def fit_touch(self):
        '''Three points, each the median of a few touches -> transform params.'''
        z_park = self.cfg['z_park']
        data = []
        for k, (x, y) in enumerate(self.cfg['touch_points']):
            coord = (x, y, z_park)
            touches = []
            for _ in range(self.cfg['touch_samples']):
                _, raw = self.probe_at(coord)
                if len(raw):
                    touches.append(np.median(raw, axis=0))
            if not touches:
                raise RuntimeError(f"[LRT] the panel saw no touch at {coord}")
            self.machine.gcode_run("_BUZZ_TOUCH")
            touch = np.median(touches, axis=0)
            data.append((coord, touch))
            self.machine.say(f"[LRT][{k + 1}/{len(self.cfg['touch_points'])}] got {touch.round(2)}")
        return touch_transform(data)

    def probe_points(self, coords, touch_params, n_samples):
        '''Where the panel sees the tool at each point: n_samples steady probes
        per point, median. Gives up on a point after 3 * n_samples probes.'''
        max_spread = self.cfg['max_spread']
        data = []
        for ix, coord in enumerate(coords):
            self.machine.say(f"[LRT] TOOL_PROBE [{ix + 1}/{len(coords)}]")
            frames = []
            for _ in range(3 * n_samples):
                result, raw = self.probe_at(coord)
                xy = apply_transform(touch_params, raw)
                probe_spread = spread(xy)
                if probe_spread < max_spread:
                    frames.append(xy)
                self.machine.say(f"[LRT] probed [{len(frames)}/{n_samples}] spread={probe_spread:.3f}")
                if len(frames) < n_samples:
                    continue
                xy = np.concatenate(frames)
                if spread(xy) < max_spread:
                    tx, ty = np.median(xy, axis=0)
                    data.append(ProbeValue(*coord, float(tx), float(ty), result.test_z))
                    self.machine.gcode_run("_BUZZ_TOUCH")
                    break
                self.machine.say(f"[LRT] VARIANCE HIGH, retrying... (spread={spread(xy):.3f})")
                self.machine.gcode_run("_BUZZ_ERR")
                frames.pop(0)
            else:
                raise RuntimeError(f"[LRT] no steady touch at {coord} after {3 * n_samples} probes")
        self.machine.say(f"lrt_data = {data}")
        return data

    def calibrate(self):
        '''With the reference tool (T4). -> profile for the [limn] section.'''
        run = self.machine.gcode_run
        run("UNDOCK")
        run("G28")
        run("_CLEAR_OFFSETS")
        ref_z_panel = self.probe_bed_z()
        run("T4")
        return self.calibrate_reference(ref_z_panel)

    def probe_bed_z(self):
        '''BLTouch z over the reference grid, no tool on the carriage -> ref_z_panel.'''
        ref_z_panel = self.probe_mesh(self.grid())
        self.machine.gcode_run("_BUZZ_DOOP")
        self.machine.say("[LRT] Z mesh collected")
        return ref_z_panel

    def bed_z_update(self, profile, ref_z_panel):
        '''The profile with a new bed z only: the reference tool's points stay.'''
        return {'ref_z_panel': ref_z_panel}

    def calibrate_reference(self, ref_z_panel):
        '''The reference tool on the carriage, ref_z_panel just probed -> profile.'''
        run = self.machine.gcode_run
        run("SET_LED_EFFECT EFFECT=ui_alert_blink REPLACE=1")
        touch_params = self.fit_touch()
        self.machine.say(f"[LRT] touch_params={touch_params}")
        run("SET_LED_EFFECT EFFECT=ui_alert_blink STOP=1")

        ref_samples = self.probe_points(self.grid(), touch_params, self.cfg['ref_samples'])
        tool_z = rtp_reference_z(ref_samples, ref_z_panel)
        run(f"WRITE_TOOL_TAG DX=0 DY=0 DZ={tool_z:.3f} REFERENCE=1")
        return {
            'touch_params': list(touch_params),
            'ref_samples': ref_samples,
            'ref_z_panel': ref_z_panel,
            'ref_z_paper': gen_bb_grid(**self.cfg['paper_grid']),
        }

    def probe_tool(self, profile):
        '''The docked tool against the reference grid -> (dx, dy, dz).'''
        self.machine.gcode_run("_CLEAR_OFFSETS")
        ixs = list(range(len(profile['ref_samples'])))
        random.shuffle(ixs)
        ixs = ixs[:self.cfg['tool_points']]
        ref_samples = [profile['ref_samples'][i] for i in ixs]
        ref_z_panel = [profile['ref_z_panel'][i] for i in ixs]
        coords = [(r.mx, r.my, self.cfg['z_park']) for r in ref_samples]
        samples = self.probe_points(coords, profile['touch_params'], self.cfg['tool_samples'])
        dx, dy, dz = rtp_tool_offsets(samples, ref_samples, ref_z_panel)
        self.machine.say(f"[LRT] offsets dx={dx} dy={dy} dz={dz}")
        return dx, dy, dz
