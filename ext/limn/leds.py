# Limn - what the tool holder and UI LEDs should show
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Only the state lives here: `desired` turns it into {led_effect name: STATE or
# None}. How a STATE looks is klipper/leds.cfg's business (_led_styles).
#
#   holder_<tool>   the dock strip, one segment per holder:
#                   occupied, carried, missing, target, engage, manual, error, unknown
#   ui_tool_<tool>  the tool's digit on the UI strip: target, untagged, carried
#   ui_traffic_*    the tool change's phase: red approach, yellow engage,
#                   green (blinking) leave, green done; red blinking: failed
#   ui_tag          reading, ok, error
#   ui_alert        attention (a hand on the holders), error
CHANGE_PHASES = ('approach', 'engage', 'leave')
DONE_SHOW = 3.0         # s the green light stays after a tool change
FLASH_SHOW = 1.5        # s a holder flashes after a hand changed it
TAG_OK_SHOW = 3.0
ALERT_SHOW = 5.0


class ToolLeds:

    def __init__(self, tools):
        self.tools = sorted(tools)
        self.phase = None           # CHANGE_PHASES, 'done', 'failed' or None
        self.active = None          # the tool being changed
        self.phase_until = 0.0
        self.flash = {}             # tool -> until
        self.alert_until = 0.0
        self.tag_state = None       # 'reading', 'ok', 'error'
        self.tag_tool = None        # the tool carried when the tag was read
        self.tag_until = 0.0

    # What happened
    def start(self, tool):
        self.phase, self.active = 'approach', tool

    def set_phase(self, phase):
        self.phase = None if phase == 'idle' else phase
        if self.phase is None:
            self.active = None

    def done(self, now):
        self.phase, self.phase_until = 'done', now + DONE_SHOW

    def failed(self, tool):
        self.phase, self.active = 'failed', tool

    def manual(self, tools, now):
        for tool in tools:
            self.flash[tool] = now + FLASH_SHOW
        self.alert_until = now + ALERT_SHOW

    def tag(self, state, tool, now):
        self.tag_state, self.tag_tool = state, tool
        self.tag_until = now + TAG_OK_SHOW

    # What to show
    def _phase(self, now):
        if self.phase == 'done' and now >= self.phase_until:
            self.phase, self.active = None, None
        return self.phase

    def next_change(self, now):
        '''When `desired` changes by itself next, None if it doesn't.'''
        times = [t for t in (self.phase_until, self.alert_until, self.tag_until, *self.flash.values()) if t > now]
        return min(times) if times else None

    def _holder(self, tool, now, phase, occupied, ok, carried):
        if not ok or occupied is None:
            return 'unknown'
        if tool == self.active:
            if phase == 'failed':
                return 'error'
            if phase in CHANGE_PHASES:
                return 'engage' if phase == 'engage' else 'target'
        if self.flash.get(tool, 0) > now:
            return 'manual'
        if tool in occupied:
            return 'occupied'
        return 'carried' if tool == carried else 'missing'

    def desired(self, now, occupied, ok, carried):
        phase = self._phase(now)
        changing = phase in CHANGE_PHASES
        out = {f'holder_{t}': self._holder(t, now, phase, occupied, ok, carried) for t in self.tools}

        out.update({f'ui_tool_{t}': None for t in self.tools})
        shown = self.active if changing else carried
        if shown in self.tools:
            if changing:
                out[f'ui_tool_{shown}'] = 'target'
            elif self.tag_state == 'ok' and self.tag_tool == carried:
                out[f'ui_tool_{shown}'] = 'carried'
            else:
                out[f'ui_tool_{shown}'] = 'untagged'

        out['ui_traffic_red'] = {'approach': 'on', 'failed': 'blink'}.get(phase)
        out['ui_traffic_yellow'] = 'on' if phase == 'engage' else None
        out['ui_traffic_green'] = {'leave': 'blink', 'done': 'on'}.get(phase)

        tag = None
        if self.tag_state == 'reading':
            tag = 'reading'
        elif self.tag_state == 'ok' and self.tag_until > now:
            tag = 'ok'
        elif self.tag_state == 'error' and self.tag_tool == carried and carried:
            tag = 'error'
        out['ui_tag'] = tag

        if phase == 'failed' or not ok:
            out['ui_alert'] = 'error'
        elif self.alert_until > now:
            out['ui_alert'] = 'attention'
        else:
            out['ui_alert'] = None
        return out
