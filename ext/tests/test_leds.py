# uv run python ext/tests/test_leds.py
from fakes import run_tests
from limn.leds import ToolLeds, DONE_SHOW, ALERT_SHOW, ERROR_NEW, ACTIVITY_TURN, NOTICE_TURNS

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
    assert traffic(out) == (None, None, None) and out['ui_alert'] == 'warn'     # 45 is unaccounted for

def test_unknown_when_unreadable():
    leds = ToolLeds(TOOLS)
    assert set(holders(leds.desired(0, None, False, 0)).values()) == {'unknown'}
    assert leds.desired(0, ALL, False, 0)['ui_alert'] == 'error'
    leds.lost(10)
    assert leds.desired(10, ALL, False, 0)['ui_alert'] == 'error_new'
    assert leds.desired(10 + ERROR_NEW, ALL, False, 0)['ui_alert'] == 'error'

def test_dock_sequence():
    leds = ToolLeds(TOOLS)
    leds.start(43)                                      # pre-check passed
    out = leds.desired(0, ALL, True, 0)
    assert holders(out)[43] == 'occupied' and digits(out) == {43: 'target'}
    assert traffic(out) == ('on', None, None) and out['ui_alert'] == 'busy_approach'
    leds.set_phase('engage')
    out = leds.desired(1, ALL, True, 0)
    assert holders(out)[43] == 'occupied' and traffic(out) == (None, 'on', None)
    assert out['ui_alert'] == 'busy_engage'
    leds.set_phase('leave')
    out = leds.desired(2, ALL - {43}, True, 0)
    assert holders(out)[43] == 'missing' and traffic(out) == (None, None, 'blink')
    leds.done(3)                                        # post-check passed, 43 saved as carried
    out = leds.desired(3, ALL - {43}, True, 43)
    assert holders(out)[43] == 'carried' and digits(out) == {43: 'untagged'}
    assert traffic(out) == (None, None, 'on') and out['ui_alert'] == 'success'
    assert leds.next_change(3) == 3 + DONE_SHOW
    leds.tag('reading', 43, 3.5)
    assert leds.desired(3.5, ALL - {43}, True, 43)['ui_alert'] == 'reading'
    leds.tag('ok', 43, 4)
    out = leds.desired(3 + DONE_SHOW, ALL - {43}, True, 43)
    assert traffic(out) == (None, None, None) and leds.phase is None
    assert digits(out) == {43: 'carried'} and out['ui_tag'] == 'ok'
    assert out['ui_alert'] == 'ready'

def test_failed_check():
    leds = ToolLeds(TOOLS)
    leds.failed(44, 0)                                  # holder 44 is not free to return 44
    out = leds.desired(0, ALL, True, 44)
    assert holders(out)[44] == 'error' and traffic(out) == ('blink', None, None)
    assert out['ui_alert'] == 'error_new'
    assert leds.desired(ERROR_NEW, ALL, True, 44)['ui_alert'] == 'error'
    leds.set_phase('idle')
    out = leds.desired(ERROR_NEW + 1, ALL, True, 44)
    assert holders(out)[44] == 'occupied' and out['ui_alert'] == 'ok'

def test_manual_change_alert_calms_down():
    leds = ToolLeds(TOOLS)
    leds.manual({41}, 10)
    out = leds.desired(10, ALL - {41}, True, 0)
    assert holders(out)[41] == 'missing' and out['ui_alert'] == 'attention_fast'
    moods = [leds.desired(10 + t, ALL - {41}, True, 0)['ui_alert'] for t in (1, 2, 4, ALERT_SHOW)]
    assert moods == ['attention_fast', 'attention', 'attention_slow', 'warn']   # calms down, 41 still gone
    assert leds.next_change(10.1) == 11.5

def test_ok_when_all_home():
    leds = ToolLeds(TOOLS)
    assert leds.desired(0, ALL, True, 0)['ui_alert'] == 'ok'
    assert leds.desired(0, ALL - {41}, True, 41)['ui_alert'] == 'ok'          # carried, tag not read yet

def test_tag_states():
    leds = ToolLeds(TOOLS)
    leds.tag('reading', 42, 0)
    assert leds.desired(0, ALL - {42}, True, 42)['ui_tag'] == 'reading'
    leds.tag('error', 42, 1)
    assert leds.desired(100, ALL - {42}, True, 42)['ui_tag'] == 'error'   # until the next read
    assert leds.desired(100, ALL, True, 0)['ui_tag'] is None               # or the tool is back


def stage(out):
    '''What columns 4-8 show: a digit or an icon, never both.'''
    d = digits(out)
    assert not (d and out['ui_icon']), out
    return d or out['ui_icon']

def test_an_activity_takes_turns_with_the_tool():
    leds = ToolLeds(TOOLS)
    leds.tag('ok', 42, 0)
    seen = [stage(leds.desired(t, ALL - {42}, True, 42, activity='probe')) for t in (100, 100 + ACTIVITY_TURN)]
    assert seen == ['probe', {42: 'carried'}]
    assert leds.desired(100, ALL - {42}, True, 42, activity='probe')['ui_alert'] == 'working'
    assert leds.next_change(100) == 100 + ACTIVITY_TURN       # redrawn for the next turn
    # No tool on the carriage (meshing): the icon alone, held
    assert {stage(leds.desired(t, ALL, True, 0, activity='mesh')) for t in (100, 102.5, 105)} == {'mesh'}
    # A tool change in it: the change's own lights
    leds.start(43)
    out = leds.desired(100, ALL, True, 0, activity='calibrate')
    assert stage(out) == {43: 'target'} and traffic(out) == ('on', None, None)

def test_wipe_the_sheet_is_held_until_done():
    leds = ToolLeds(TOOLS)
    outs = [leds.desired(t, ALL - {42}, True, 42, activity='wipe') for t in (10, 12.5, 15)]
    assert {stage(o) for o in outs} == {'wipe'} and outs[0]['ui_alert'] == 'waiting'
    assert stage(leds.desired(16, ALL - {42}, True, 42, activity='wiped')) == 'wiped'

def test_full_sheet_by_turns_then_gone():
    leds = ToolLeds(TOOLS)
    shown = [stage(leds.desired(t, ALL - {42}, True, 42, sheet_full=True)) for t in (0, NOTICE_TURNS[0])]
    assert shown == [{42: 'untagged'}, 'paper']
    assert leds.desired(0, ALL - {42}, True, 42, sheet_full=True)['ui_alert'] == 'warn'
    assert stage(leds.desired(0, ALL, True, 0, sheet_full=True)) == 'paper'        # no tool: the page alone
    assert stage(leds.desired(0, ALL, True, 0)) is None and leds.next_change(0) is None    # still: no redraws

def test_plot_progress_up_column_7():
    leds = ToolLeds(TOOLS)
    out = leds.desired(0, ALL - {42}, True, 42, progress=0.0)
    assert out['ui_progress'] == 'p0' and out['ui_alert'] == 'plotting' and stage(out) == {42: 'untagged'}
    assert leds.desired(0, ALL - {42}, True, 42, progress=0.5)['ui_progress'] == 'p4'
    assert leds.desired(0, ALL - {42}, True, 42, progress=1.0)['ui_progress'] == 'p8'
    assert leds.desired(0, ALL - {42}, True, 42)['ui_progress'] is None
    # An icon over the stage (a pen probed mid-plot) takes column 7 too
    assert leds.desired(0, ALL - {42}, True, 0, activity='probe', progress=0.5)['ui_progress'] is None


if __name__ == '__main__':
    run_tests(globals())
