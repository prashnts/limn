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
    install('rtp', 'rtp')
    install('fsr', 'fsr')
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

        stats = dock.command('stats()', 'stats')
        check('no damaged frames: %s' % json.dumps(stats['down']), stats['down']['bad'] == 0)
    finally:
        for p in procs:
            p.kill()
        print('logs in', SIM)


if __name__ == '__main__':
    main()
