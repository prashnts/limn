# uv run python ext/tests/test_drying.py
from fakes import run_tests
from limn.drying import Drying
from limn.leds import ToolLeds


def test_clock_starts_and_stops():
    d = Drying(idle=600, printing=1200)
    assert d.update({41}, 1000.0) and d.since == {41: 1000.0}
    assert not d.update({41}, 1100.0) and d.since[41] == 1000.0      # still in: the same clock
    assert d.stage(41, 1599.0, False) == 0 and d.stage(41, 1600.0, False) == 1
    assert d.stage(41, 1600.0 + 120, False) == 2 and d.stage(41, 1600.0 + 300, False) == 3
    assert d.stage(41, 1700.0, True) == 0                         # printing: 20 minutes
    assert d.stages(1700.0, False) == {41: 1}
    d.update(set(), 1800.0)                                       # a dock: in neither place for a moment
    assert not d.update({41}, 1800.5) and d.since == {41: 1000.0}  # the same clock (seen on the plotter)
    d.update(set(), 1900.0)                                       # taken out by hand: capped
    assert d.since == {41: 1000.0}
    assert d.update(set(), 1925.0) and d.since == {} and d.stages(5000.0, False) == {}


def test_reset_and_saved():
    d = Drying(since={'41': 100.0, '42': 200.0})
    d.reset(900.0, 41)
    assert d.since == {41: 900.0, 42: 200.0}
    d.reset(1000.0)
    assert set(d.since.values()) == {1000.0}
    assert Drying(since=d.saved()).since == d.since
    st = d.status(1300.0, False)
    assert st['41'] == {'uncapped': 300, 'limit': 600.0, 'stage': 0}


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
