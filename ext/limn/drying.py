# Limn - pens drying out: how long each known pen has been out of its cap
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# A pen whose tag we know (read at a dock, or scanned by hand) and that is in
# the machine, in its holder or on the carriage, is uncapped: its tip dries.
# Past `idle` seconds (`printing` while a print runs, when pens are being used)
# it is overdue, and gets worse by stages: the LEDs go from amber to red and
# blink faster (leds.py), and the machine beeps. Taking it out by hand (to cap
# it) stops its clock; docking and undocking don't.
#
# Times are wall clock (time.time()), so they survive a Klipper restart through
# the saved variables.
IDLE = 600.0            # s uncapped before a pen is overdue, nothing printing
PRINTING = 1200.0       # while printing
STAGES = (0.0, 120.0, 300.0)    # s overdue: stage 1, 2, 3


class Drying:

    def __init__(self, idle=IDLE, printing=PRINTING, since=None):
        self.idle = idle
        self.printing = printing
        self.since = {int(k): float(v) for k, v in (since or {}).items()}  # tool -> uncapped since

    def update(self, present, now):
        '''present: the known pens in the machine now -> whether anything changed.'''
        changed = False
        for tool in present:
            if tool not in self.since:
                self.since[tool] = now
                changed = True
        for tool in list(self.since):
            if tool not in present:
                del self.since[tool]
                changed = True
        return changed

    def reset(self, now, tool=None):
        for t in ([tool] if tool is not None else list(self.since)):
            if t in self.since:
                self.since[t] = now

    def limit(self, printing):
        return self.printing if printing else self.idle

    def stage(self, tool, now, printing):
        '''0: fine, 1..3: overdue, worse and worse.'''
        if tool not in self.since:
            return 0
        over = now - self.since[tool] - self.limit(printing)
        return 0 if over < 0 else sum(1 for s in STAGES if over >= s)

    def stages(self, now, printing):
        '''{tool: stage} of the overdue pens.'''
        return {t: s for t in self.since if (s := self.stage(t, now, printing))}

    def status(self, now, printing):
        return {str(t): {'uncapped': round(now - since), 'limit': self.limit(printing),
                         'stage': self.stage(t, now, printing)} for t, since in sorted(self.since.items())}

    def saved(self):
        return {str(t): round(v, 1) for t, v in self.since.items()}
