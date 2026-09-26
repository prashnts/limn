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
    root = SIM / name
    for local, remote in mcu.files_for(node['app']):
        (root / remote).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(local, root / remote)
    (root / 'node.json').write_text(json.dumps(node))
    return root

def start(name, uarts, **popen):
    fds = {uart_id: sock.fileno() for uart_id, sock in uarts.items()}
    cmd = [sys.executable, '-u', str(SIM_MCU), '--name', name, '--root', str(SIM / name), '--sim', str(SIM)]
    for uart_id, fd in fds.items():
        cmd += ['--uart', f'{uart_id}:{fd}']
    log = open(SIM / (name + '.log'), 'w')
    popen.setdefault('stdout', log)
    return subprocess.Popen(cmd, pass_fds=list(fds.values()), stderr=log, **popen)

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
    install('rtp', 'rtp', touch_pin=2)      # as if the diodes were fitted
    install('fsr', 'fsr', touch_pin=2)
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
        samples = [d for k, d in dock.lines(0.5) if k == 'SMP' and d['5']]
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
        samples = [d for k, d in dock.lines(1) if k == 'SMP' and d['5']]
        (SIM / 'stim_rtp').unlink()
        dock.command('disarm()', 'armed')
        check('no touch_pin: no pulse, samples still arrive', pulses() == [] and len(samples) > 0)

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
        print('logs in', SIM)


if __name__ == '__main__':
    main()
