# uv run python ext/tests/test_drying.py
from fakes import run_tests
from limn.drying import Drying
from limn.leds import ToolLeds


def test_clock_starts_and_stops():
    d = Drying(idle=600)
    assert d.update({41}, 1000.0) and d.since == {41: 1000.0}
    assert not d.update({41}, 1100.0) and d.since[41] == 1000.0      # still in: the same clock
    assert d.stage(41, 1599.0) == 0 and d.stage(41, 1600.0) == 1
    assert d.stage(41, 1600.0 + 120) == 2 and d.stage(41, 1600.0 + 300) == 3
    assert d.stages(1700.0) == {41: 1}
    d.update(set(), 1800.0)                                       # a dock: in neither place for a moment
    assert not d.update({41}, 1800.5) and d.since == {41: 1000.0}  # the same clock (seen on the plotter)
    d.update(set(), 1900.0)                                       # taken out by hand: capped
    assert d.since == {41: 1000.0}
    assert d.update(set(), 1925.0) and d.since == {} and d.stages(5000.0) == {}


def test_the_clock_stands_still_while_the_pens_are_wanted():
    d = Drying(idle=600)
    d.update({41}, 0.0)
    assert not d.update({41}, 500.0, busy=True)                   # a print starts
    assert d.stages(500.0) == {}
    d.update({41}, 1000.0)                                        # busy: as before (TOOL_DRY)
    assert d.busy and d.since == {41: 500.0} and d.stages(5000.0) == {}  # never overdue meanwhile
    d.update({42}, 2000.0, busy=True)                             # a pen put in during the print
    assert d.since[42] == 2000.0
    assert d.update({41, 42}, 3000.0, busy=False)                 # done: the moved clocks are saved
    assert d.since == {41: 2500.0, 42: 3000.0}
    assert d.stage(41, 3099.0) == 0 and d.stage(41, 3100.0) == 1  # 500 s before + 600 s after
    st = d.status(3100.0)
    assert st['41'] == {'uncapped': 600, 'limit': 600.0, 'stage': 1, 'paused': False}
    # A G-code of a moment moves the clocks but isn't worth a write
    assert not d.update({41, 42}, 3105.0, busy=True) and not d.update({41, 42}, 3106.0, busy=False)
    assert d.since[41] == 2501.0
    d.update({41, 42}, 3107.0, busy=True)
    assert d.status(3107.0)['41']['paused'] and d.stages(3107.0) == {}    # an overdue pen goes quiet


def test_a_pen_of_its_own():
    d = Drying(idle=600)
    d.update({41, 42}, 0.0)
    d.limits = {41: 240 * 60}                   # dry-safe ink
    assert d.stages(700.0) == {42: 1}
    assert d.limit(41) == 240 * 60 and d.limit(42) == 600


def test_reset_and_saved():
    d = Drying(since={'41': 100.0, '42': 200.0})
    d.reset(900.0, 41)
    assert d.since == {41: 900.0, 42: 200.0}
    d.reset(1000.0)
    assert set(d.since.values()) == {1000.0}
    assert Drying(since=d.saved()).since == d.since
    st = d.status(1300.0)
    assert st['41'] == {'uncapped': 300, 'limit': 600.0, 'stage': 0, 'paused': False}


def test_leds_show_a_drying_pen():
    leds = ToolLeds({41, 42, 43, 44, 45})
    out = leds.desired(10.0, {41, 42}, True, 0, {41: 3})
    assert out['holder_41'] == 'drying_3' and out['holder_42'] == 'occupied'
    assert out['ui_tool_41'] == 'drying_3' and out['ui_alert'] == 'drying_3'
    # Several: their numbers take turns, the alert shows the worst
    a = leds.desired(10.0, {41, 42}, True, 0, {41: 1, 42: 2})
    b = leds.desired(12.0, {41, 42}, True, 0, {41: 1, 42: 2})
    assert {k for k, v in a.items() if k.startswith('ui_tool') and v} != {k for k, v in b.items() if k.startswith('ui_tool') and v}
    assert a['ui_alert'] == 'drying_2'
    # A failed check still comes first
    leds.failed(41, 10.0)
    out = leds.desired(10.0, {41, 42}, True, 0, {41: 3})
    assert out['holder_41'] == 'error' and out['ui_alert'].startswith('error')


if __name__ == '__main__':
    run_tests(globals())
