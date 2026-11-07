# uv run python ext/tests/test_lit.py
import json
import os
import tempfile

from fakes import FakeReactor, run_tests
from limn.lit import Lit, TOUCH, ARMED, SUM_OK, TARING
from test_dock import FakeSerial


def sample(g, flags=SUM_OK):
    return '!LRT>>data>>' + json.dumps({'values': [flags, int(g * 1000), 0, []], 'kind': 6, 'hop': 0,
                                         'state': 42}) + '>>\r\n'


def connected_lit(replies=None, log_dir=None):
    reactor = FakeReactor()
    said = []
    lit = Lit(reactor, '/dev/null', say=said.append, log_dir=log_dir or tempfile.mkdtemp())
    lit.link.serial = FakeSerial(replies)
    lit.link.timer = reactor.register_timer(lit.link._read, reactor.NOW)
    return reactor, lit, said


def test_samples_give_the_force_and_flags():
    reactor, lit, _ = connected_lit()
    lit.link.serial.incoming = (sample(2.0) + sample(4.0, SUM_OK | ARMED) + sample(99, SUM_OK | TARING)).encode()
    reactor.pause(0.05)
    assert lit.mean() == 3.0                    # the taring sample is left out
    st = lit.status(reactor.t)
    assert st['connected'] and st['adc_ok'] and not st['touch']


def test_other_hops_and_kinds_are_ignored():
    reactor, lit, _ = connected_lit()
    lit.link.serial.incoming = b'!LRT>>data>>{"values": [12, 5000, 0, []], "kind": 4, "hop": 0}>>\n' \
                               b'!LRT>>data>>{"values": [12, 5000, 0, []], "kind": 6, "hop": 1}>>\n'
    reactor.pause(0.05)
    assert lit.mean() is None


def test_tare_waits_for_its_reply():
    reactor, lit, _ = connected_lit({'tare()': '!LRT>>log>>{"text": "adc>>ok"}>>\n!LRT>>log>>{"text": "tare>>391574"}>>\n'})
    assert lit.tare() == '391574'


def test_tare_failure_and_timeout():
    reactor, lit, _ = connected_lit({'tare()': '!LRT>>log>>{"text": "tare>>failed: no samples"}>>\n'})
    try:
        lit.tare()
        assert False
    except RuntimeError:
        pass
    reactor, lit, _ = connected_lit()
    try:
        lit.threshold(3)
        assert False
    except TimeoutError:
        pass


def test_arm():
    reactor, lit, _ = connected_lit({'arm(lit)': '!LRT>>armed>>{"hop": 0, "role": "lit", "armed": true}>>\n'})
    assert lit.arm() is True
    reactor, lit, _ = connected_lit({'arm(lit)': '!LRT>>armed>>{"hop": 0, "role": "lit", "armed": false}>>\n'})
    assert lit.arm() is False


def test_log_rows_have_where_the_toolhead_was():
    d = tempfile.mkdtemp()
    reactor, lit, _ = connected_lit(log_dir=d)
    path = lit.log_start('t1', lambda t: (1.0, 2.0, 0.5, 40.0))
    assert lit.link.serial.written[-1].strip() == 'rate(100)'
    lit.link.serial.incoming = (sample(7.5, SUM_OK | TOUCH)).encode()
    reactor.pause(0.05)
    assert lit.log_stop() == (path, 1)
    assert lit.link.serial.written[-1].strip() == 'rate(25)'
    head, row = [json.loads(l) for l in open(os.path.join(d, 't1.jsonl'))]
    assert head['row'][:3] == ['t', 'g', 'flags'] and row[1:] == [7.5, SUM_OK | TOUCH, 1.0, 2.0, 0.5, 40.0]


def test_debug_lines():
    reactor, lit, said = connected_lit()
    lit.debug(0.2)
    lit.link.serial.incoming = (sample(1.0) + sample(3.0)).encode()
    reactor.pause(0.45)
    assert any('+2.00 g' in s for s in said), said
    lit.debug(0)
    n = len(said)
    reactor.pause(1.0)
    assert len(said) == n


if __name__ == '__main__':
    run_tests(globals())
