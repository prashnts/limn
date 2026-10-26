# End to end: Dock <-> RTP <-> FSR as three processes (tests/sim_mcu.py),
# driven by mcu.py exactly like on the real chain. Run on a PC:
#   uv run python micropython/tests/test_chain.py
import os
import sys
import json
import time
import shutil
import socket
import tempfile
import threading
import subprocess

from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import mcu
import ota
import typer
from link import T_CMD

SIM = Path(tempfile.mkdtemp(prefix='limn-sim-'))
SIM_MCU = HERE / 'sim_mcu.py'


class PipeSerial:
    '''The Dock process' stdin/stdout, shaped like a pyserial port.'''

    def __init__(self, proc):
        self.proc = proc
        self.buffer = b''
        self.lock = threading.Lock()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        while True:
            data = os.read(self.proc.stdout.fileno(), 4096)
            if not data:
                return
            with self.lock:
                self.buffer += data

    @property
    def in_waiting(self):
        return len(self.buffer)

    def read(self, n):
        end = time.monotonic() + 0.05
        while not self.buffer and time.monotonic() < end:
            time.sleep(0.002)
        with self.lock:
            data, self.buffer = self.buffer[:n], self.buffer[n:]
        return data

    def write(self, data):
        self.proc.stdin.write(data)
        self.proc.stdin.flush()

    def close(self):
        pass


def install(name, config, **overrides):
    '''What `mcu.py install` does, into a folder.'''
    node = json.loads((mcu.NODES / (config + '.json')).read_text())
    node.update(overrides)
    for key in [k for k, v in node.items() if v is None]:
        node.pop(key)
    root = SIM / name
    for local, remote in mcu.files_for(node['app']):
        (root / remote).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(local, root / remote)
    (root / 'node.json').write_text(json.dumps(node))
    return root

def start(name, uarts, wires=None, **popen):
    fds = {uart_id: sock.fileno() for uart_id, sock in uarts.items()}
    wire_fds = {pin: sock.fileno() for pin, sock in (wires or {}).items()}
    cmd = [sys.executable, '-u', str(SIM_MCU), '--name', name, '--root', str(SIM / name), '--sim', str(SIM)]
    for uart_id, fd in fds.items():
        cmd += ['--uart', f'{uart_id}:{fd}']
    for pin, fd in wire_fds.items():
        cmd += ['--wire', f'{pin}:{fd}']
    log = open(SIM / (name + '.log'), 'w')
    popen.setdefault('stdout', log)
    return subprocess.Popen(cmd, pass_fds=list(fds.values()) + list(wire_fds.values()), stderr=log, **popen)

def source_with(changes):
    '''A copy of micropython/ with some files changed, to update from.'''
    src = SIM / ('src-%d' % time.monotonic_ns())
    shutil.copytree(mcu.HERE, src, ignore=shutil.ignore_patterns('tests', '__pycache__'))
    for path, text in changes.items():
        (src / path).write_text(text)
    return src

def pulses():
    path = SIM / 'pulses'
    return path.read_text().splitlines() if path.exists() else []

def wait_for(check, timeout=15, what=''):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        result = check()
        if result:
            return result
        time.sleep(0.2)
    raise AssertionError('timed out waiting for ' + what)

def check(name, ok):
    print(('ok   ' if ok else 'FAIL ') + name)
    if not ok:
        raise SystemExit(1)


def main():
    install('dock', 'dock', trigger='detect')
    # The beds as they were for the Dock: UART0 on the pogo, the DETECT diodes fitted
    install('rtp', 'rtp', touch_pin=2, up={'id': 0}, probe_pin=None)
    install('fsr', 'fsr', touch_pin=2, up={'id': 0}, probe_pin=None)
    dock_rtp = socket.socketpair()
    rtp_fsr = socket.socketpair()
    procs = [
        start('fsr', {0: rtp_fsr[1]}),
        start('rtp', {0: dock_rtp[1], 1: rtp_fsr[0]}),
        start('dock', {0: dock_rtp[0]}, stdin=subprocess.PIPE, stdout=subprocess.PIPE),
    ]
    dock = mcu.Dock(PipeSerial(procs[-1]))

    try:
        hellos = wait_for(lambda: (h := dock.hellos()) and len(h) == 2 and h, what='both nodes')
        check('topology: rtp at hop 1, fsr at hop 2',
              {hop: h['role'] for hop, h in hellos.items()} == {1: 'rtp', 2: 'fsr'})
        infos = {hop: dock.info(hop) for hop in (0, 1, 2)}
        check('info: roles and files',
              [infos[h]['role'] for h in (0, 1, 2)] == ['dock', 'rtp', 'fsr']
              and all(not mcu.plan_update(i)[0] for i in infos.values()))

        # Trigger path
        dock.command('arm(rtp)', 'armed')
        time.sleep(0.3)
        (SIM / 'stim_rtp').touch()
        wait_for(pulses, 3, 'a probe pulse')
        samples = [d for k, d in dock.lines(0.5) if k == 'data' and d['kind'] == 5]
        (SIM / 'stim_rtp').unlink()
        time.sleep(0.3)
        check('armed rtp touch -> one 10ms pulse', [p.split()[1] for p in pulses()] == ['999'])
        check('rtp samples still arrive while touched', len(samples) > 0)

        (SIM / 'pulses').unlink()
        (SIM / 'stim_fsr').touch()
        time.sleep(0.8)
        (SIM / 'stim_fsr').unlink()
        check('fsr touch while rtp is armed -> no pulse', pulses() == [])
        dock.command('disarm()', 'armed')

        # Without touch_pin (no diode yet) arming is ignored, samples still flow.
        node = json.loads((SIM / 'rtp' / 'node.json').read_text())
        node.pop('touch_pin')
        src_config = SIM / 'rtp_no_diode.json'
        src_config.write_text(json.dumps(node))
        mcu.run_update(dock, [1], config=src_config)
        (SIM / 'pulses').unlink(missing_ok=True)
        dock.command('arm(rtp)', 'armed')
        time.sleep(0.3)
        (SIM / 'stim_rtp').touch()
        samples = [d for k, d in dock.lines(1) if k == 'data' and d['kind'] == 5]
        (SIM / 'stim_rtp').unlink()
        dock.command('disarm()', 'armed')
        check('no touch_pin: no pulse, samples still arrive', pulses() == [] and len(samples) > 0)

        # FSR matrix mode: every cell every frame, tagged with the FSR's hop
        dock.send('matrix(on)')
        frames = [d for k, d in dock.lines(1) if k == 'data' and d['kind'] == 4 and d['state'] == 43]
        dock.send('matrix(off)')
        time.sleep(0.3)
        check('matrix mode: 32 cells from hop 2', frames and all(len(d['values']) == 32 and d['hop'] == 2 for d in frames))

        # Updates
        rtp_app = (mcu.HERE / 'lrt_resistive_touch.py').read_text() + '\n# updated\n'
        src = source_with({'lrt_resistive_touch.py': rtp_app})
        mcu.run_update(dock, [1], source=src)
        info = dock.info(1)
        check('update rtp: new file, confirmed',
              info['files']['lrt_resistive_touch.py'] == mcu.file_hash(src / 'lrt_resistive_touch.py')
              and not info['pending'])

        broken = 'raise RuntimeError("broken on purpose")\n'
        src = source_with({'lrt_fsr_array.py': broken})
        try:
            mcu.run_update(dock, [2], source=src)
            rolled_back = False
        except typer.Exit:
            rolled_back = True
        info = dock.info(2)
        check('broken fsr update rolls back',
              rolled_back and info['files']['lrt_fsr_array.py'] == mcu.file_hash(mcu.HERE / 'lrt_fsr_array.py')
              and not info['pending'])
        check('fsr still answers after rollback', wait_for(lambda: 2 in dock.hellos(), what='fsr hello'))

        src = source_with({'main.py': (mcu.HERE / 'main.py').read_text() + '\n# changed\n'})
        send, held = mcu.plan_update(dock.info(1), src)
        check('bootloader is held back without --force', held == ['main.py'] and 'main.py' not in [r for _, r in send])

        dock_app = (mcu.HERE / 'lrt_dock_mcu.py').read_text() + '\n# updated\n'
        src = source_with({'lrt_dock_mcu.py': dock_app})
        mcu.run_update(dock, [0], source=src)
        info = dock.info(0)
        check('update the dock itself',
              info['files']['lrt_dock_mcu.py'] == mcu.file_hash(src / 'lrt_dock_mcu.py')
              and not info['pending'])

        # Errors are reported and the loop keeps going
        wait_for(lambda: 2 in dock.hellos(), what='fsr back after the dock update')
        bad = mcu.binascii.b2a_base64(b'arm(\xff)').decode().strip()
        dock.send(f'frame(2,{T_CMD},{bad})')
        logs = [d for k, d in dock.lines(1.5) if k == 'log' and d['hop'] == 2]
        check('node error is reported', any('error>>' in d['text'] for d in logs))
        check('node keeps running after an error', wait_for(lambda: 2 in dock.hellos(), what='fsr hello'))

        dock.send('diag()')
        logs = [d['text'] for k, d in dock.lines(1.5) if k == 'log' and d['hop'] == 2]
        check('diag reports the fsr pads', sum('diag>>gpio' in t for t in logs) == 4)

        (SIM / 'stim_fsr').touch()
        dock.send('calibrate()')
        logs = [d['text'] for k, d in dock.lines(8) if k == 'log' and d['hop'] == 2]
        (SIM / 'stim_fsr').unlink()
        check('calibration with the sheet pressed keeps the old baseline',
              any('timed out' in t for t in logs) and any('keeping the previous' in t for t in logs))

        stats = dock.command('stats()', 'stats')
        check('no damaged frames: %s' % json.dumps(stats['down']), stats['down']['bad'] == 0)
    finally:
        for p in procs:
            p.kill()
    bench()
    plot_bed()
    lit()
    lit_chain()
    print('logs in', SIM)

def bench():
    '''RTP -> FSR on the bench: no Dock, the host on the RTP's USB.'''
    install('bench_rtp', 'rtp')
    install('bench_fsr', 'fsr', up={'id': 0}, probe_pin=None)     # behind the RTP: a UART
    wire = socket.socketpair()
    nothing = socket.socketpair()           # the RTP's pogo wire, not connected
    procs = [
        start('bench_fsr', {0: wire[1]}),
        start('bench_rtp', {1: wire[0]}, wires={0: nothing[0]}, stdin=subprocess.PIPE, stdout=subprocess.PIPE),
    ]
    rtp = mcu.Dock(PipeSerial(procs[-1]))
    try:
        hellos = wait_for(lambda: (h := rtp.hellos()) and 1 in h and h, what='fsr through the rtp')
        check('bench: rtp is hop 0, fsr hop 1', {hop: h['role'] for hop, h in hellos.items()} == {0: 'rtp', 1: 'fsr'})

        (SIM / 'stim_fsr').touch()
        data = [d for k, d in rtp.lines(1) if k == 'data' and d['hop'] == 1]
        (SIM / 'stim_fsr').unlink()
        check('bench: fsr data shows up on the rtp usb', len(data) > 0 and data[0]['kind'] == 4)

        mcu.run_update(rtp, [1], config=mcu.NODES / 'fsr_bed3.json')
        info = rtp.info(1)
        check('bench: fsr switched to fsr_bed3 through the rtp',
              info['files']['node.json'] == mcu.file_hash(mcu.NODES / 'fsr_bed3.json') and not info['pending'])
    finally:
        for p in procs:
            p.kill()

def press(*feet):
    (SIM / 'stim_plot_bed').write_text(json.dumps({'feet': list(feet)}))

def touch_out(name='plot_bed'):
    path = SIM / ('touch_out_' + name)
    return path.read_text() if path.exists() else None

def samples(bed, timeout=0.6):
    '''Plot bed data lines -> [{state, flags, g, feet_g}]'''
    out = []
    for k, d in bed.lines(timeout):
        if k == 'data' and d['kind'] == 6:
            flags, sum_mg, _, feet = d['values']
            out.append({'state': d['state'], 'flags': flags, 'g': sum_mg / 1000, 'feet_g': [mg / 1000 for mg, _ in feet]})
    return out

def logs_until(bed, needle, timeout=6):
    found = []
    for k, d in bed.lines(timeout):
        if k == 'log':
            found.append(d['text'])
            if needle in d['text']:
                break
    return found

def plot_bed():
    '''The plot bed on USB alone: load cells, touch line, calibration, updates.'''
    from link import LOAD_TOUCH, LOAD_ARMED, LOAD_CAL, LOAD_SUM_OK, LOAD_FEET_OK
    root = install('plot_bed', 'plot_bed')
    press(0, 0, 0)
    procs = [start('plot_bed', {}, stdin=subprocess.PIPE, stdout=subprocess.PIPE)]
    bed = mcu.Dock(PipeSerial(procs[0]))
    try:
        hellos = wait_for(lambda: bed.hellos(), what='plot bed hello')
        check('plot bed: hello at hop 0', hellos[0]['role'] == 'plot_bed')
        check('plot bed: touch line ok after the boot tare', wait_for(lambda: touch_out() == '1', what='line ok'))
        got = samples(bed)
        check('plot bed: streams samples, both ADCs ok, ~0 g',
              len(got) > 5 and all(s['flags'] & LOAD_SUM_OK and s['flags'] & LOAD_FEET_OK for s in got)
              and abs(got[-1]['g']) < 1)

        press(10, 10, 10)       # 30 g by the estimate
        check('plot bed: a press drops the touch line', wait_for(lambda: touch_out() == '0', timeout=2, what='touch'))
        got = samples(bed)
        check('plot bed: touched flag and ~30 g (estimate)',
              got and got[-1]['flags'] & LOAD_TOUCH and 27 < got[-1]['g'] < 33 and not got[-1]['flags'] & LOAD_CAL)
        press(0, 0, 0)
        check('plot bed: release raises it again', wait_for(lambda: touch_out() == '1', timeout=2, what='release'))

        bed.send('stall(2000)')
        time.sleep(0.3)
        press(10, 10, 10)
        dropped = wait_for(lambda: touch_out() == '0', timeout=1.2, what='touch while stalled')
        press(0, 0, 0)
        check('plot bed: the touch line works while the main loop is stalled (IRQ)', dropped)
        wait_for(lambda: touch_out() == '1', timeout=4, what='release after the stall')
        time.sleep(2)           # the stall's end: commands are handled again

        bed.send('threshold(40)')
        press(10, 10, 10)
        time.sleep(0.5)
        check('plot bed: threshold(40) ignores 30 g', touch_out() == '1')
        press(0, 0, 0)
        bed.send('threshold(5)')

        bed.send('tare()')
        logs_until(bed, 'tare>>')
        press(50, 50, 50)
        time.sleep(0.3)
        bed.send('calibrate(150)')
        logs = logs_until(bed, 'calibrate>>')
        got = samples(bed)
        check('plot bed: calibrate(150) -> ~170 counts/g on the sum, ~510 a foot',
              any('calibrate>>sum 1' in t for t in logs) and got and got[-1]['flags'] & LOAD_CAL
              and 147 < got[-1]['g'] < 153 and all(48 < g < 52 for g in got[-1]['feet_g']))
        check('plot bed: cal.json written', json.loads((root / 'cal.json').read_text())['sum'] > 100)

        press(100, 0, 0)
        time.sleep(0.3)
        bed.send('calibrate(100, 1)')
        logs = logs_until(bed, 'calibrate>>')
        check('plot bed: calibrate(100, 1) weighs foot 1 alone', any('calibrate>>foot 1 5' in t for t in logs))
        press(0, 0, 0)
        bed.send('calibrate(100, 2)')
        logs = logs_until(bed, 'calibrate>>')
        check('plot bed: no weight over the foot -> refused', any('calibrate>>failed' in t for t in logs))

        wait_for(lambda: touch_out() == '1', timeout=3, what='line ok')
        bed.send('arm(plot_bed)')
        lines = [(k, d) for k, d in bed.lines(1.5)]
        armed = [d for k, d in lines if k == 'armed']
        check('plot bed: arm tares, then says armed', armed and armed[0]['armed'] is True)
        got = samples(bed)
        check('plot bed: armed flag in the samples', got and got[-1]['flags'] & LOAD_ARMED)
        bed.send('arm(rtp)')
        time.sleep(0.2)
        bed.send('disarm()')
        got = [d for k, d in bed.lines(1) if k == 'armed']
        check('plot bed: disarm', got and got[0]['armed'] is False)

        bed.send('diag()')
        logs = logs_until(bed, 'diag>>noise foot3')
        check('plot bed: diag reports both ADCs and the noise',
              any('diag>>sum adc: ok' in t for t in logs) and any('diag>>feet adc: ok' in t for t in logs)
              and sum('diag>>noise' in t for t in logs) == 4)

        (SIM / 'stim_dead_sum').touch()
        check('plot bed: the sum ADC stops -> touch line fails safe',
              wait_for(lambda: touch_out() == '0', timeout=2, what='fail safe'))
        (SIM / 'stim_dead_sum').unlink()
        check('plot bed: ...and comes back once the ADC does', wait_for(lambda: touch_out() == '1', timeout=10, what='recovery'))

        app = (mcu.HERE / 'lrt_plot_bed.py').read_text() + '\n# updated\n'
        src = source_with({'lrt_plot_bed.py': app})
        mcu.run_update(bed, [0], source=src)
        info = bed.info(0)
        check('plot bed: update over USB, confirmed, ads1220 shipped, cal.json kept',
              info['files']['lrt_plot_bed.py'] == mcu.file_hash(src / 'lrt_plot_bed.py') and not info['pending']
              and 'lib/ads1220.py' in info['files'] and 'cal.json' in info['files'])
        got = wait_for(lambda: samples(bed), what='samples after the update')
        check('plot bed: still calibrated after the update', got[-1]['flags'] & LOAD_CAL)

        running = mcu.file_hash(src / 'lrt_plot_bed.py')
        src = source_with({'lrt_plot_bed.py': 'raise RuntimeError("broken on purpose")\n'})
        try:
            mcu.run_update(bed, [0], source=src)
            rolled_back = False
        except typer.Exit:
            rolled_back = True
        info = bed.info(0)
        check('plot bed: broken update rolls back',
              rolled_back and info['files']['lrt_plot_bed.py'] == running and not info['pending'])
    finally:
        for p in procs:
            p.kill()

    # The app fails to start with nothing to roll back: the rescue loop still
    # takes an update over USB.
    root = install('plot_bed_rescue', 'plot_bed')
    (root / 'lrt_plot_bed.py').write_text('raise RuntimeError("broken on purpose")\n')
    procs = [start('plot_bed_rescue', {}, stdin=subprocess.PIPE, stdout=subprocess.PIPE)]
    bed = mcu.Dock(PipeSerial(procs[0]))
    try:
        hellos = wait_for(lambda: bed.hellos(), what='rescue hello')
        check('plot bed: rescue loop answers on USB', hellos[0]['role'] == 'rescue:plot_bed')
        mcu.run_update(bed, [0])
        hellos = wait_for(lambda: bed.hellos(), what='hello after the rescue')
        check('plot bed: rescued by an update over USB', hellos[0]['role'] == 'plot_bed')
    finally:
        for p in procs:
            p.kill()


def lit():
    '''LIT (the plot bed board) on USB alone: the cell, the touch line, the bed dock.'''
    from link import LOAD_TOUCH, LOAD_CAL, LOAD_SUM_OK
    install('lit', 'lit')
    (SIM / 'stim_lit').write_text(json.dumps({'g': 0}))
    pogo = socket.socketpair()              # no bed on the other end
    procs = [start('lit', {}, wires={0: pogo[0]}, stdin=subprocess.PIPE, stdout=subprocess.PIPE)]
    board = mcu.Dock(PipeSerial(procs[0]))
    weigh = lambda g: (SIM / 'stim_lit').write_text(json.dumps({'g': g}))
    try:
        hellos = wait_for(lambda: board.hellos(), what='lit hello')
        check('lit: hello at hop 0', hellos[0]['role'] == 'lit')
        check('lit: touch line ok after the boot tare', wait_for(lambda: touch_out('lit') == '1', what='line ok'))
        got = samples(board)
        check('lit: streams samples, ADC ok, ~0 g, no feet',
              len(got) > 5 and all(s['flags'] & LOAD_SUM_OK for s in got) and abs(got[-1]['g']) < 1
              and got[-1]['feet_g'] == [])

        weigh(20)
        check('lit: a press drops the touch line', wait_for(lambda: touch_out('lit') == '0', timeout=2, what='touch'))
        got = samples(board)
        check('lit: touched flag and ~20 g (estimate)', got and got[-1]['flags'] & LOAD_TOUCH and 18 < got[-1]['g'] < 22)
        weigh(0)
        check('lit: release raises it again', wait_for(lambda: touch_out('lit') == '1', timeout=2, what='release'))

        board.send('stall(2000)')
        time.sleep(0.3)
        weigh(20)
        dropped = wait_for(lambda: touch_out('lit') == '0', timeout=1.2, what='touch while stalled')
        weigh(0)
        check('lit: the touch line works while the main loop is stalled (IRQ)', dropped)
        wait_for(lambda: touch_out('lit') == '1', timeout=4, what='release after the stall')
        time.sleep(2)

        board.send('tare()')
        logs_until(board, 'tare>>')
        weigh(100)
        time.sleep(0.3)
        board.send('calibrate(100)')
        logs = logs_until(board, 'calibrate>>')
        got = samples(board)
        check('lit: calibrate(100) -> ~236 counts/g',
              any('calibrate>>23' in t for t in logs) and got and got[-1]['flags'] & LOAD_CAL and 97 < got[-1]['g'] < 103)
        weigh(0)
        wait_for(lambda: touch_out('lit') == '1', timeout=3, what='line ok')

        (SIM / 'stim_lit_bed').write_text('40000')          # BED_4
        lines = list(board.lines(2))
        check('lit: a bed is seen, then powered after a second',
              any(k == 'bed_detected' and d[0] == 'BED_4' for k, d in lines)
              and any(k == 'power' and d['on'] for k, d in lines))
        bed = board.command('read_bed_id()', 'read_bed_id')
        check('lit: read_bed_id', bed[0] == 'BED_4' and bed[2]['placed'] == 1 and bed[2]['powered'])
        (SIM / 'stim_lit_probe').touch()
        got = [d for k, d in board.lines(0.5) if k == 'bed_probe']
        (SIM / 'stim_lit_probe').unlink()
        check('lit: the bed\'s trigger is reported', got and got[0]['ok'] is False)
        (SIM / 'stim_lit_bed').unlink()
        lines = list(board.lines(1))
        check('lit: bed removed -> power off', any(k == 'bed_removed' for k, d in lines)
              and any(k == 'power' and not d['on'] for k, d in lines))

        board.send('diag()')
        logs = logs_until(board, 'diag>>noise')
        check('lit: diag reports the ADC, the bed, the tool and the noise',
              any('diag>>adc: ok' in t for t in logs) and any('diag>>bed NONE' in t and 'tool none' in t for t in logs)
              and any('diag>>noise rms' in t for t in logs))

        (SIM / 'stim_dead_cell').touch()
        check('lit: the ADC stops -> touch line fails safe', wait_for(lambda: touch_out('lit') == '0', timeout=2, what='fail safe'))
        (SIM / 'stim_dead_cell').unlink()
        check('lit: ...and comes back once the ADC does', wait_for(lambda: touch_out('lit') == '1', timeout=10, what='recovery'))
    finally:
        for p in procs:
            p.kill()


def probe_out(name):
    path = SIM / ('probe_out_' + name)
    return path.read_text() if path.exists() else None

def probe_lows(name):
    path = SIM / ('probe_low_' + name)
    return len(path.read_text().splitlines()) if path.exists() else 0

def lit_chain():
    '''LIT -> RTP on the pogo's one wire (BED_DATA half duplex, BED_PROBE) -> FSR on a UART.'''
    # 330/s: three simulated boards can't keep up with LIT's 600 (the chip does)
    install('lit_c', 'lit', cell_adc=dict(json.loads((mcu.NODES / 'lit.json').read_text())['cell_adc'], sps=330))
    install('rtp_c', 'rtp')
    install('fsr_c', 'fsr_bed3')
    (SIM / 'stim_lit').write_text(json.dumps({'g': 0}))
    pogo = socket.socketpair()
    rtp_fsr = socket.socketpair()
    procs = [
        start('fsr_c', {0: rtp_fsr[1]}),
        start('rtp_c', {1: rtp_fsr[0]}, wires={0: pogo[1]}),
        start('lit_c', {}, wires={0: pogo[0]}, stdin=subprocess.PIPE, stdout=subprocess.PIPE),
    ]
    board = mcu.Dock(PipeSerial(procs[-1]))
    try:
        wait_for(lambda: board.hellos(), what='lit hello')
        board.send('ping()')
        got = [d for k, d in board.lines(1.5) if k == 'hello']
        check('one wire: nothing from the bed while it is off', all(d['hop'] == 0 for d in got))

        (SIM / 'stim_lit_bed').write_text('31000')      # BED_3
        wait_for(lambda: any(k == 'power' and d['on'] for k, d in board.lines(0.5)), timeout=5, what='bed power')
        hellos = wait_for(lambda: (h := board.hellos()) and len(h) == 3 and h, what='rtp and fsr through the wire')
        check('one wire: rtp at hop 1, fsr at hop 2 behind it',
              {hop: h['role'] for hop, h in hellos.items()} == {0: 'lit', 1: 'rtp', 2: 'fsr'})
        check('BED_PROBE high (OK) at rest', probe_out('rtp_c') == '1')

        board.send('arm(rtp)')         # passed down; LIT only answers arm(lit) itself
        time.sleep(0.3)
        (SIM / 'stim_rtp').touch()
        dropped = wait_for(lambda: probe_lows('rtp_c') == 1, timeout=2, what='BED_PROBE low')
        samples = [d for k, d in board.lines(0.5) if k == 'data' and d['kind'] == 5]
        (SIM / 'stim_rtp').unlink()
        check('armed rtp touch -> BED_PROBE low, samples through the wire', dropped and samples and samples[0]['hop'] == 1)
        check('...and back high after the hold', wait_for(lambda: probe_out('rtp_c') == '1', timeout=2, what='release'))
        board.send('disarm()')
        time.sleep(0.3)

        (SIM / 'stim_fsr').touch()
        time.sleep(0.8)
        check('fsr touch, nothing armed -> BED_PROBE stays high', probe_lows('rtp_c') == 1)
        board.send('arm(fsr)')
        dropped = wait_for(lambda: probe_lows('rtp_c') > 1, timeout=2, what='relayed touch')
        (SIM / 'stim_fsr').unlink()
        board.send('disarm()')
        check('armed fsr behind the rtp -> relayed on the rtp\'s BED_PROBE', dropped)

        board.send('matrix(on)')
        frames = [d for k, d in board.lines(1.5) if k == 'data' and d['kind'] == 4 and d['state'] == 43]
        board.send('matrix(off)')
        time.sleep(0.3)
        check('one wire: fsr matrix frames from hop 2 keep flowing (%d in 1.5 s)' % len(frames),
              len(frames) > 10 and all(len(d['values']) == 32 and d['hop'] == 2 for d in frames))

        rtp_app = (mcu.HERE / 'lrt_resistive_touch.py').read_text() + '\n# updated\n'
        src = source_with({'lrt_resistive_touch.py': rtp_app})
        mcu.run_update(board, [1], source=src)
        info = board.info(1)
        check('update over the one wire: confirmed',
              info['files']['lrt_resistive_touch.py'] == mcu.file_hash(src / 'lrt_resistive_touch.py') and not info['pending'])
        wait_for(lambda: len(board.hellos()) == 3, what='chain back after the update')

        stats = board.command('stats()', 'stats')
        check('one wire: no damaged frames, no lost turns: %s' % json.dumps(stats['down']),
              stats['down']['bad'] == 0 and stats['down']['lost'] == 0)

        (SIM / 'stim_lit_bed').unlink()
        wait_for(lambda: any(k == 'power' and not d['on'] for k, d in board.lines(0.5)), timeout=3, what='bed off')
        board.send('ping()')
        got = [d for k, d in board.lines(1.5) if k == 'hello']
        check('bed off: the turns stop, only lit answers', got and all(d['hop'] == 0 for d in got))
    finally:
        for p in procs:
            p.kill()

if __name__ == '__main__':
    if sys.argv[1:] == ['plot_bed']:
        plot_bed()
        print('logs in', SIM)
    elif sys.argv[1:] == ['lit']:
        lit()
        lit_chain()
        print('logs in', SIM)
    else:
        main()
