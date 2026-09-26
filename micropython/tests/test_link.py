# Tests for lib/link.py, run on a PC:
#   python3 micropython/tests/test_link.py
import os
import sys
import binascii

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
import link
from link import Link, Port, encode, decode, T_CMD, T_DATA, T_LOG, T_HELLO, BROADCAST


class FakeUART:
    '''Bytes written to one end show up at the `peer`.'''

    def __init__(self):
        self.peer = None
        self.inbox = b''
        self.written = b''
        self.blocked = False     # pretend the wire is still busy

    def any(self):
        return len(self.inbox)

    def read(self, n):
        data, self.inbox = self.inbox[:n], self.inbox[n:]
        return data

    def write(self, data):
        self.written += data
        if self.peer:
            self.peer.inbox += data
        return len(data)

    def txdone(self):
        return not self.blocked

def wire():
    a, b = FakeUART(), FakeUART()
    a.peer, b.peer = b, a
    return a, b

def run(*links, rounds=5):
    got = [[] for _ in links]
    for _ in range(rounds):
        for i, l in enumerate(links):
            got[i] += l.poll()
    return got


def test_roundtrip_all_bytes():
    payload = bytes(range(256)) + b'\xc0\xdb\xdc\xdd\xdb\xdc\xc0\xc0\xdb\xdd'
    raw = encode(T_DATA, 3, 200, payload)
    assert raw.count(b'\xc0') == 2           # only the two delimiters
    assert decode(raw[1:-1]) == (T_DATA, 3, 200, payload)

def test_crc_fallback_matches():
    data = b'limn' * 50
    fallback = link._crc32
    if fallback is binascii.crc32:
        # Build the pure Python version to compare against.
        src = open(link.__file__).read()
        start = src.index('    def _crc32(data):')
        end = src.index('\ntry:', start)
        scope = {}
        exec('\n'.join(l[4:] for l in src[start:end].splitlines()), scope)
        fallback = scope['_crc32']
    assert fallback(data) == binascii.crc32(data)

def test_split_reads_and_damage():
    a, b = wire()
    port = Port(b)
    good = encode(T_CMD, 1, 1, b'calibrate()')
    bad = bytearray(encode(T_CMD, 1, 2, b'ping()'))
    bad[5] ^= 0x10
    stream = good + bytes(bad) + good

    frames = []
    for i in range(len(stream)):             # one byte at a time
        a.write(stream[i:i + 1])
        frames += port.frames()
    assert [f.payload for f in frames] == [b'calibrate()', b'calibrate()']
    assert port.stats['bad'] == 1

def test_noise_without_end_is_discarded():
    a, b = wire()
    port = Port(b)
    a.write(b'\x55' * (link.MAX_FRAME + 1))
    assert port.frames() == []
    assert port.stats['bad'] == 1
    a.write(encode(T_LOG, 0, 1, b'hi'))
    assert [f.payload for f in port.frames()] == [b'hi']

def test_old_firmware_lines_are_dropped():
    # What an FSR with the old firmware sends, until it is updated.
    a, b = wire()
    port = Port(b)
    for _ in range(40):
        a.write(b'!FSR>>SMP>>BAEqAQIBWQAAAAAAAAAAAAAAAAAAAAAAAAAA>>\n')
        assert port.frames() == []
    a.write(encode(T_DATA, 0, 1, link.pack_fsr(42, [(1, 2, 500)])))
    assert [f.type for f in port.frames()] == [T_DATA]

def chain():
    '''Dock <-> n1 <-> n2'''
    d_down, n1_up = wire()
    n1_down, n2_up = wire()
    return Link(down=d_down), Link(up=n1_up, down=n1_down), Link(up=n2_up)

def test_upstream_hops_are_positions():
    dock, n1, n2 = chain()
    n1.send(T_HELLO, b'rtp>>n1')
    n2.send(T_HELLO, b'fsr>>n2')
    got, _, _ = run(dock, n1, n2)
    assert sorted((f.hop, f.payload) for f in got) == [(1, b'rtp>>n1'), (2, b'fsr>>n2')]

def test_downstream_routing():
    dock, n1, n2 = chain()
    dock.send_down(T_CMD, b'all')
    dock.send_down(T_CMD, b'first', hop=1)
    dock.send_down(T_CMD, b'second', hop=2)
    _, got1, got2 = run(dock, n1, n2)
    assert [f.payload for f in got1] == [b'all', b'first']
    assert [f.payload for f in got2] == [b'all', b'second']

def test_latest_data_wins_and_control_goes_first():
    up, peer = wire()
    node = Link(up=up)
    up.blocked = True
    for i in range(10):
        node.send(T_DATA, link.pack_rtp(42, i, i, i))
    node.send(T_LOG, b'log')
    node.send(T_HELLO, b'hello')
    node.poll()
    assert up.written == b''

    up.blocked = False
    node.poll()
    frames = Port(peer).frames()
    assert [f.type for f in frames] == [T_HELLO, T_DATA, T_LOG]
    assert link.unpack_data(frames[1].payload) == (link.RTP_ID_LM, 42, [9, 9, 9])
    assert node.up.stats['drop'] == 9

def test_data_from_different_nodes_is_kept_apart():
    dock, n1, n2 = chain()
    n1.up.uart.blocked = True
    n1.send(T_DATA, link.pack_rtp(42, 1, 1, 1))
    n2.send(T_DATA, link.pack_fsr(42, [(0, 1, 500)]))
    run(n2, n1)
    n1.up.uart.blocked = False
    got, _, _ = run(dock, n1, n2)
    assert sorted(link.unpack_data(f.payload)[0] for f in got) == [link.FSR_ID_LM, link.RTP_ID_LM]

def test_fsr_payload():
    touches = [(3, 7, 1000), (0, 0, 345)]
    assert link.unpack_data(link.pack_fsr(42, touches)) == (link.FSR_ID_LM, 42, [[3, 7, 1000], [0, 0, 345]])
    assert link.unpack_data(link.pack_fsr(12, [])) == (link.FSR_ID_LM, 12, [])
    assert link.unpack_data(link.pack_fsr(42, touches)[:-1]) is None

def test_flush_empties_queues():
    up, _ = wire()
    node = Link(up=up)
    node.send(T_CMD, b'reset()')
    node.flush()
    assert not node.busy()


if __name__ == '__main__':
    tests = [(name, fn) for name, fn in globals().items() if name.startswith('test_')]
    for name, fn in tests:
        fn()
        print('ok', name)
    print(len(tests), 'passed')
