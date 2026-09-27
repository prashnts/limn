# uv run python ext/tests/test_leds.py
from fakes import run_tests
from limn.leds import ToolLeds, DONE_SHOW, FLASH_SHOW, ALERT_SHOW

TOOLS = (41, 42, 43, 44, 45)
ALL = frozenset(TOOLS)


def holders(out):
    return {t: out[f'holder_{t}'] for t in TOOLS}


def digits(out):
    return {t: out[f'ui_tool_{t}'] for t in TOOLS if out[f'ui_tool_{t}']}


def traffic(out):
    return out['ui_traffic_red'], out['ui_traffic_yellow'], out['ui_traffic_green']


def test_idle_holders():
    out = ToolLeds(TOOLS).desired(0, ALL - {42, 45}, True, 42)
    assert holders(out) == {41: 'occupied', 42: 'carried', 43: 'occupied', 44: 'occupied', 45: 'missing'}
    assert digits(out) == {42: 'untagged'}
    assert traffic(out) == (None, None, None) and out['ui_alert'] is None

def test_unknown_when_unreadable():
    leds = ToolLeds(TOOLS)
    assert set(holders(leds.desired(0, None, False, 0)).values()) == {'unknown'}
    assert leds.desired(0, ALL, False, 0)['ui_alert'] == 'error'

def test_dock_sequence():
    leds = ToolLeds(TOOLS)
    leds.start(43)                                      # pre-check passed
    out = leds.desired(0, ALL, True, 0)
    assert holders(out)[43] == 'target' and digits(out) == {43: 'target'}
    assert traffic(out) == ('on', None, None)
    leds.set_phase('engage')
    out = leds.desired(1, ALL, True, 0)
    assert holders(out)[43] == 'engage' and traffic(out) == (None, 'on', None)
    leds.set_phase('leave')
    out = leds.desired(2, ALL - {43}, True, 0)
    assert holders(out)[43] == 'target' and traffic(out) == (None, None, 'blink')
    leds.done(3)                                        # post-check passed, 43 saved as carried
    out = leds.desired(3, ALL - {43}, True, 43)
    assert holders(out)[43] == 'carried' and digits(out) == {43: 'untagged'}
    assert traffic(out) == (None, None, 'on')
    assert leds.next_change(3) == 3 + DONE_SHOW
    leds.tag('ok', 43, 4)
    out = leds.desired(3 + DONE_SHOW, ALL - {43}, True, 43)
    assert traffic(out) == (None, None, None) and leds.phase is None
    assert digits(out) == {43: 'carried'} and out['ui_tag'] == 'ok'

def test_failed_check():
    leds = ToolLeds(TOOLS)
    leds.failed(44)                                     # holder 44 is not free to return 44
    out = leds.desired(0, ALL, True, 44)
    assert holders(out)[44] == 'error' and traffic(out) == ('blink', None, None)
    assert out['ui_alert'] == 'error'
    leds.set_phase('idle')
    out = leds.desired(1, ALL, True, 44)
    assert holders(out)[44] == 'occupied' and out['ui_alert'] is None

def test_manual_flash_then_settles():
    leds = ToolLeds(TOOLS)
    leds.manual({41}, 10)
    out = leds.desired(10, ALL - {41}, True, 0)
    assert holders(out)[41] == 'manual' and out['ui_alert'] == 'attention'
    assert holders(leds.desired(10 + FLASH_SHOW, ALL - {41}, True, 0))[41] == 'missing'
    assert leds.desired(10 + ALERT_SHOW, ALL - {41}, True, 0)['ui_alert'] is None

def test_tag_states():
    leds = ToolLeds(TOOLS)
    leds.tag('reading', 42, 0)
    assert leds.desired(0, ALL - {42}, True, 42)['ui_tag'] == 'reading'
    leds.tag('error', 42, 1)
    assert leds.desired(100, ALL - {42}, True, 42)['ui_tag'] == 'error'   # until the next read
    assert leds.desired(100, ALL, True, 0)['ui_tag'] is None               # or the tool is back


if __name__ == '__main__':
    run_tests(globals())
