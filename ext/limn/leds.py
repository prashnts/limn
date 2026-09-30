# Limn - what the tool holder and UI LEDs should show
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Only the state lives here: `desired` turns it into {led_effect name: STATE or
# None}. How a STATE looks is klipper/leds.cfg's business (_led_styles).
#
#   holder_<tool>   the dock strip, one segment per holder, status only:
#                   occupied, carried / missing (empty: its tool is on the
#                   carriage / nobody's), error (a check failed there), unknown
#   ui_tool_<tool>  the tool's digit on the UI strip: target, untagged, carried
#   ui_traffic_*    the tool change's phase: red approach, yellow engage,
#                   green (blinking) leave, green done; red blinking: failed
#   ui_tag          reading, ok, error; a tag held to the reader by hand: listening
#                   (a hand was on the holders), scanned (into a holder, quick),
#                   taken (a holder took it), late (it didn't)
#   ui_alert        the machine's mood, most urgent first; its colour turns
#                   its meaning around, its speed says how fresh or urgent:
#                   error_new, error              red: a check failed, holders unreadable
#                   busy_approach/engage/leave    blue spinner: a tool change, faster near the holder
#                   reading                       cyan spinner: a tag read or write
#                   success                       green blink: a tool change just went well
#                   attention_fast/_/_slow        amber, slowing down: a hand was on the holders
#                   warn                          amber breathing: a tool is unaccounted for, a bad tag
#                   ready                         green breathing: carrying a tool with its tag read
#                   ok                            dim green, slow: all tools home
CHANGE_PHASES = ('approach', 'engage', 'leave')
DONE_SHOW = 3.0         # s the green light stays after a tool change
TAG_OK_SHOW = 3.0
ALERT_SHOW = 5.0        # s the alert calms down over after a hand change
ATTENTION_STEPS = ((1.5, 'attention_fast'), (3.5, 'attention'), (ALERT_SHOW, 'attention_slow'))
ERROR_NEW = 3.0         # s a new error flashes fast


class ToolLeds:

    def __init__(self, tools):
        self.tools = sorted(tools)
        self.phase = None           # CHANGE_PHASES, 'done', 'failed' or None
        self.active = None          # the tool being changed
        self.phase_until = 0.0
        self.alert_at = None        # a hand was on the holders
        self.error_at = None        # a check failed, or the holders stopped answering
        self.tag_state = None       # 'reading', 'ok', 'error'
        self.tag_tool = None        # the tool carried when the tag was read
        self.tag_until = 0.0
        self.hand_state = None      # 'listening', 'scanned', 'taken', 'late'
        self.hand_until = 0.0

    # What happened
    def start(self, tool):
        self.phase, self.active = 'approach', tool

    def set_phase(self, phase):
        self.phase = None if phase == 'idle' else phase
        if self.phase is None:
            self.active = None

    def done(self, now):
        self.phase, self.phase_until = 'done', now + DONE_SHOW

    def failed(self, tool, now):
        self.phase, self.active = 'failed', tool
        self.error_at = now

    def lost(self, now):
        self.error_at = now

    def manual(self, tools, now):
        self.alert_at = now

    def tag(self, state, tool, now):
        self.tag_state, self.tag_tool = state, tool
        self.tag_until = now + TAG_OK_SHOW

    def hand(self, state, now, until):
        self.hand_state, self.hand_until = state, until

    # What to show
    def _phase(self, now):
        if self.phase == 'done' and now >= self.phase_until:
            self.phase, self.active = None, None
        return self.phase

    def next_change(self, now):
        '''When `desired` changes by itself next, None if it doesn't.'''
        times = [self.phase_until, self.tag_until, self.hand_until]
        if self.alert_at is not None:
            times += [self.alert_at + after for after, _ in ATTENTION_STEPS]
        if self.error_at is not None:
            times.append(self.error_at + ERROR_NEW)
        times = [t for t in times if t > now]
        return min(times) if times else None

    def _alert(self, now, phase, holders, ok, carried):
        if phase == 'failed' or not ok:
            fresh = self.error_at is not None and now - self.error_at < ERROR_NEW
            return 'error_new' if fresh else 'error'
        if phase in CHANGE_PHASES:
            return 'busy_' + phase
        if self.tag_state == 'reading':
            return 'reading'
        if phase == 'done':
            return 'success'
        if self.alert_at is not None:
            for after, state in ATTENTION_STEPS:
                if now < self.alert_at + after:
                    return state
        if 'missing' in holders.values() or (self.tag_state == 'error' and self.tag_tool == carried and carried):
            return 'warn'
        if carried and self.tag_state in ('ok', 'reading') and self.tag_tool == carried:
            return 'ready'
        return 'ok'

    def _holder(self, tool, now, phase, occupied, ok, carried):
        if not ok or occupied is None:
            return 'unknown'
        if tool == self.active and phase == 'failed':
            return 'error'
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
        elif self.hand_state and now < self.hand_until:
            tag = self.hand_state
        elif self.tag_state == 'ok' and self.tag_until > now:
            tag = 'ok'
        elif self.tag_state == 'error' and self.tag_tool == carried and carried:
            tag = 'error'
        out['ui_tag'] = tag

        holders = {t: out[f'holder_{t}'] for t in self.tools}
        out['ui_alert'] = self._alert(now, phase, holders, ok, carried)
        return out


# Fluidd's tool buttons (T0..): the dot is the holder's state, the carried tool is highlighted
# (no dot: empty; the carried tool's button is highlighted instead)
BUTTON_COLORS = {'occupied': '4CAF50', 'error': 'F44336', 'unknown': '9C27B0'}


def tool_buttons(states, carried):
    """{holder_<tool>: state} -> {tool: {'color': hex, 'active': bool}}"""
    return {int(name.split('_')[1]): {'color': BUTTON_COLORS.get(state, ''),
                                      'active': int(name.split('_')[1]) == carried}
            for name, state in states.items() if name.startswith('holder_')}
