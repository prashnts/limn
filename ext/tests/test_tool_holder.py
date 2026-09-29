# uv run python ext/tests/test_tool_holder.py
from fakes import FakeReactor, FakeBus, FakeMCP23017, FakePN532, run_tests
from limn.i2c import build_frame, parse_frame, MCP23017
from limn.tool_holder import (ToolHolder, parse_pins, decode_holders, encode_num, decode_num,
                              encode_name)

def wait(reactor, seconds):
    reactor.pause(reactor.t + seconds)


PINS = parse_pins('15:41, 14:42, 13:45, 12:43, 11:44')


def tag_pages(dx=1.25, dy=-0.5, dz=0.05, name='Fineliner'):
    pages = {6: encode_num(dx), 7: encode_num(dy), 8: encode_num(dz)}
    data = encode_name(name)
    for i in range(5):
        pages[11 + i] = data[i * 4:i * 4 + 4]
    return pages


def make(low=(15, 14, 13, 12, 11), pages=None):
    reactor = FakeReactor()
    mcp, nfc = FakeMCP23017(low), FakePN532(pages)
    said = []
    holder = ToolHolder(reactor, FakeBus(mcp, nfc), PINS, say=said.append)
    events = []
    holder.on('ready', lambda occupied: events.append(('ready', occupied)))
    holder.on('change', lambda *args: events.append(('change',) + args))
    return reactor, holder, mcp, nfc, events, said


def test_parse_pins_and_decode():
    assert PINS == {15: 41, 14: 42, 13: 45, 12: 43, 11: 44}
    gpio = 0xFFFF & ~(1 << 15 | 1 << 12)
    assert decode_holders(gpio, PINS) == {41, 43}

def test_frames():
    frame = build_frame(bytes([0xD4, 0x02]))
    assert frame == bytes([0, 0, 0xFF, 2, 0xFE, 0xD4, 0x02, 0x2A, 0])
    assert parse_frame(b'\x00\x00' + frame + b'\x00\x00') == bytes([0xD4, 0x02])
    try:
        parse_frame(frame[:-2] + b'\x00\x00')
        assert False, 'bad checksum should raise'
    except RuntimeError:
        pass

def test_mcp_setup_keeps_other_pins():
    mcp = FakeMCP23017()
    mcp.regs[0x00], mcp.regs[0x01] = 0x00, 0x00         # someone made them outputs
    MCP23017(FakeBus(mcp)).setup_inputs(1 << 15 | 1 << 11)
    assert mcp.regs[0x01] == 0x88 and mcp.regs[0x00] == 0x00
    assert mcp.regs[0x0D] == 0x88

def test_num_encoding():
    assert encode_num(1.05) == bytes([0, 1, 5, 0])
    assert decode_num(encode_num(1.05)) == 1.05         # the old rfid.py read this back as 1.5
    assert decode_num(encode_num(-0.5)) == -0.5
    assert decode_num(encode_num(1.999)) == 2.0
    assert decode_num(bytes([0, 51, 0, 0])) == 51.0

def test_ready_then_settled_changes():
    reactor, holder, mcp, _, events, _ = make()
    holder.start()
    wait(reactor, 1)
    assert events == [('ready', {41, 42, 43, 44, 45})]
    mcp.low.discard(13)                                 # someone takes tool 45
    wait(reactor, 1)
    assert events[-1] == ('change', {41, 42, 43, 44}, set(), {45}, {45})

def test_glitch_is_ignored():
    reactor, holder, mcp, _, events, _ = make()
    holder.start()
    wait(reactor, 1)
    mcp.low.discard(13)
    wait(reactor, 0.2)                                  # one read only
    mcp.low.add(13)
    wait(reactor, 1)
    assert len(events) == 1

def test_expected_change_is_not_manual():
    reactor, holder, mcp, _, events, _ = make()
    holder.start()
    wait(reactor, 1)
    holder.expect(42, False)
    assert holder.busy()
    mcp.low.discard(14)
    wait(reactor, 1)
    assert events[-1] == ('change', {41, 43, 44, 45}, set(), {42}, set())
    assert not holder.busy()

def test_sample_and_lost_mcp():
    reactor, holder, mcp, _, _, said = make(low=(15,))
    assert holder.sample() == {41}
    mcp.fail = True
    try:
        holder.sample()
        assert False, 'should raise'
    except OSError:
        pass
    assert not holder.ok and said == ["[Tool holder] lost the MCP23017"]
    mcp.fail = False
    assert holder.sample() == {41} and holder.ok

def test_read_tag():
    reactor, holder, _, nfc, _, said = make(pages=tag_pages())
    tag = holder.read_tag()
    assert (tag.dx, tag.dy, tag.dz, tag.name) == (1.25, -0.5, 0.05, 'Fineliner')
    assert tag.uid == '04112233445566'
    assert said == ["[Tag] PN532 firmware 1.6"]

def test_no_tag():
    # It listens for the whole timeout: a tag that comes into the field late still counts.
    # 16 activations (0x10) answered "no tag" early and missed tags that were there.
    reactor, holder, _, nfc, _, _ = make(pages=None)
    holder.begin_tag_reader()
    t0 = reactor.t
    assert holder.read_tag(timeout=0.5) is None
    assert nfc.retries == 0xFF and nfc.aborted == 1 and 0.4 < reactor.t - t0 < 0.6
    assert holder.read_tag(timeout=0.5) is None and nfc.aborted == 2      # still talking after the abort

def test_partial_write():
    reactor, holder, _, nfc, _, _ = make(pages=tag_pages())
    tag = holder.write_tag(dz=-0.07)
    assert nfc.writes == [8]
    assert (tag.dx, tag.dy, tag.dz, tag.name) == (1.25, -0.5, -0.07, 'Fineliner')
    tag = holder.write_tag(name='Brush pen')
    assert nfc.writes == [8, 11, 12, 13, 14, 15] and tag.name == 'Brush pen'

def test_reference_flag():
    _, holder, _, nfc, _, _ = make(pages=tag_pages())
    assert holder.read_tag().reference is False
    nfc.pages[9] = b'\xff\x00\x12\x34'                    # whatever an old tag has there
    assert holder.read_tag().reference is False
    tag = holder.write_tag(reference=True)
    assert tag.reference and nfc.writes == [9] and (tag.dx, tag.name) == (1.25, 'Fineliner')
    assert holder.write_tag(dz=0.9).reference                # other fields leave it
    assert holder.write_tag(reference=False).reference is False

def test_format_2_pen_and_colour():
    '''A format 1 tag (offsets, name) reads with no pen and no colour; writing either
    makes it format 2 and keeps what was there: offsets, name, the reference flag.'''
    _, holder, _, nfc, _, _ = make(pages=tag_pages(name='Micron 01 Blue'))
    nfc.pages[10] = b'\x00\x11\x22\x33'                   # an old tag's leftovers: not format 2
    tag = holder.read_tag()
    assert (tag.pen, tag.color) == (None, None)
    tag = holder.write_tag(pen='mic-01', color='#1F4AA8')
    assert (tag.pen, tag.color, tag.name, tag.dx, tag.reference) == \
        ('mic-01', '#1f4aa8', 'Micron 01 Blue', 1.25, False)
    assert nfc.writes[-1] == 10, 'the colour page marks format 2: last, a half written tag stays format 1'
    assert set(nfc.writes) == {4, 5, 10} and max(nfc.pages) <= 15, 'the smallest tags end at page 15'
    tag = holder.write_tag(color='#c8102e')                  # the pen stays
    assert (tag.pen, tag.color) == ('mic-01', '#c8102e')
    tag = holder.write_tag(pen='stb-88')                 # the colour stays
    assert (tag.pen, tag.color) == ('stb-88', '#c8102e')
    assert holder.write_tag(color='').color is None and holder.read_tag().pen == 'stb-88'
    for bad in (dict(pen='Has Spaces'), dict(pen='x' * 9), dict(color='blue')):
        try:
            holder.write_tag(**bad)
            assert False, bad
        except ValueError:
            pass

def test_write_without_tag():
    reactor, holder, *_ = make(pages=None)
    try:
        holder.write_tag(dx=1)
        assert False, 'should raise'
    except RuntimeError:
        pass

def test_silent_reader_is_aborted():
    reactor, holder, _, nfc, _, _ = make(pages=tag_pages())
    holder.begin_tag_reader()
    nfc.mute = True                                     # listens forever: no reply
    t0 = reactor.t
    assert holder.read_tag(timeout=0.5) is None
    assert nfc.aborted == 1 and reactor.t - t0 < 0.6


if __name__ == '__main__':
    run_tests(globals())
