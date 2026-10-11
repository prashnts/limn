# Limn - pens drying out: how long each known pen has been out of its cap
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# A pen whose tag we know (read at a dock, or scanned by hand) and that is in
# the machine, in its holder or on the carriage, is uncapped: its tip dries.
# Its clock only runs while the machine leaves the pens alone: a print, G-code
# running (a calibration, a move) or a tool change stops every clock (`busy`), so
# a pen is never overdue while the pens are wanted. Past `idle` seconds of that
# it is overdue; a pen of the library can have its own (`dry` in pens.toml, in
# `limits`), and gets worse by stages: the LEDs go from amber to red and blink
# faster (leds.py), and the machine beeps. Taking it out by hand (to cap it)
# stops its clock for good; docking and undocking don't.
#
# Times are wall clock (time.time()), so they survive a Klipper restart through
# the saved variables: `since` is when the pen was uncapped, moved on by the
# time the machine was busy since.
IDLE = 600.0            # s uncapped, the machine idle, before a pen is overdue
STAGES = (0.0, 120.0, 300.0)    # s overdue: stage 1, 2, 3
SAVE_BUSY = 60.0        # s busy worth saving the moved clocks for, once idle again
GONE = 20.0             # s out of the machine before its clock stops: a dock or undock
                        # has the pen in neither the holder nor the carriage for a moment


class Drying:

    def __init__(self, idle=IDLE, since=None, gone=GONE):
        self.idle = idle
        self.gone = gone
        self.since = {int(k): float(v) for k, v in (since or {}).items()}  # tool -> uncapped since
        self.away = {}              # tool -> not in the machine since
        self.limits = {}            # tool -> its own idle limit, s (its pen's `dry`)
        self.busy = False           # the pens are wanted: the clocks stand still
        self._busy_from = None
        self._at = None             # the last update

    def update(self, present, now, busy=None):
        '''present: the known pens in the machine now; busy: the pens are wanted
        (None: as before) -> whether anything changed that is worth saving.'''
        busy = self.busy if busy is None else busy
        changed = False
        if self.busy and self._at is not None:
            for tool in self.since:
                self.since[tool] += now - self._at
        if busy and not self.busy:
            self._busy_from = now
        elif self.busy and not busy:            # a G-code of a moment isn't worth a write
            changed = now - self._busy_from >= SAVE_BUSY
        self.busy, self._at = busy, now
        for tool in present:
            self.away.pop(tool, None)
            if tool not in self.since:
                self.since[tool] = now
                changed = True
        for tool in list(self.since):
            if tool not in present and now - self.away.setdefault(tool, now) >= self.gone:
                del self.since[tool]
                del self.away[tool]
                changed = True
        return changed

    def reset(self, now, tool=None):
        for t in ([tool] if tool is not None else list(self.since)):
            if t in self.since:
                self.since[t] = now

    def limit(self, tool=None):
        return self.limits.get(tool, self.idle)

    def stage(self, tool, now):
        '''0: fine (or the pens are wanted), 1..3: overdue, worse and worse.'''
        if tool not in self.since or self.busy:
            return 0
        over = now - self.since[tool] - self.limit(tool)
        return 0 if over < 0 else sum(1 for s in STAGES if over >= s)

    def stages(self, now):
        '''{tool: stage} of the overdue pens.'''
        return {t: s for t in self.since if (s := self.stage(t, now))}

    def status(self, now):
        return {str(t): {'uncapped': round(now - since), 'limit': self.limit(t),
                         'stage': self.stage(t, now), 'paused': self.busy}
                for t, since in sorted(self.since.items())}

    def saved(self):
        return {str(t): round(v, 1) for t, v in self.since.items()}
