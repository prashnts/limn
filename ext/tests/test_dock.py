# uv run python ext/tests/test_dock.py
import base64

from fakes import FakeReactor, run_tests
from limn.dock import Dock, Lines, parse_line


class FakeSerial:
    '''Answers some commands with a line, like the Dock would.'''

    def __init__(self, replies=None):
        self.replies = replies or {}
        self.written = []
        self.incoming = b''

    @property
    def in_waiting(self):
        return len(self.incoming)

    def read(self, n):
        data, self.incoming = self.incoming[:n], self.incoming[n:]
        return data

    def write(self, data):
        self.written.append(data.decode())
        reply = self.replies.get(data.decode().strip())
        if reply:
            self.incoming += reply.encode()

    def close(self):
        pass


def connected_dock(replies=None):
    reactor = FakeReactor()
    dock = Dock(reactor, '/dev/null', say=lambda msg: None)
    dock.serial = FakeSerial(replies)
    dock.timer = reactor.register_timer(dock._read, reactor.NOW)
    return reactor, dock


def test_parse_line():
    assert parse_line('!LRT>>hello>>{"hop": 1, "role": "rtp"}>>') == ('hello', {'hop': 1, 'role': 'rtp'})
    assert parse_line('!LRT>>power>>turned on>>') == ('power', 'turned on')
    assert parse_line('!LRT>>read_bed_id>>["BED_3", [1]]>>\r') == ('read_bed_id', ['BED_3', [1]])
    assert parse_line('Waiting for command...') is None
    assert parse_line('') is None

def test_lines_across_chunks():
    lines = Lines()
    assert lines.feed(b'!LRT>>pi') == []
    assert lines.feed(b'ng>>t=1>>\r\n!LRT>>da') == ['!LRT>>ping>>t=1>>']
    assert lines.feed(b'ta>>{}>>\n\xff\xfe\n') == ['!LRT>>data>>{}>>', '']

def test_listeners_get_their_kind():
    reactor, dock = connected_dock()
    seen = []
    dock.on('data', seen.append)
    dock.serial.incoming = b'!LRT>>data>>{"hop": 2, "kind": 4}>>\n!LRT>>ping>>t=1>>\n'
    reactor.pause(0.1)
    assert seen == [{'hop': 2, 'kind': 4}]

def test_request_gets_its_reply():
    reactor, dock = connected_dock({'read_bed_id()': '!LRT>>read_bed_id>>["BED_5", null]>>\r\n'})
    assert dock.request('read_bed_id()', 'read_bed_id') == ['BED_5', None]

def test_request_times_out():
    reactor, dock = connected_dock()
    try:
        dock.request('read_bed_id()', 'read_bed_id', timeout=1)
        assert False, 'should time out'
    except TimeoutError:
        pass
    assert 0.9 <= reactor.t < 1.2

def test_send_to_one_node():
    reactor, dock = connected_dock()
    dock.send_to(2, 'matrix(on)')
    line = dock.serial.written[-1].strip()
    hop, ftype, b64 = line[len('frame('):-1].split(',')
    assert (hop, ftype, base64.b64decode(b64)) == ('2', '2', b'matrix(on)')


if __name__ == '__main__':
    run_tests(globals())
