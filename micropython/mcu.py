# Limn MCU tool - install, inspect and update the Dock and bed MCUs
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
#   uv run micropython/mcu.py ports
#   uv run micropython/mcu.py install rtp --port /dev/cu.usbmodem1101
#   uv run micropython/mcu.py topology
#   uv run micropython/mcu.py update
#
# `install` talks to one board over USB (mpremote). Everything else talks to
# the Dock over USB, and through it to the whole chain. Without a Dock, any
# board on USB does the same for the boards below it (it is hop 0). Klipper must not hold
# the Dock's port meanwhile (on the Pi: sudo systemctl stop klipper).
import os
import sys
import json
import time
import struct
import hashlib
import binascii
import tempfile
import subprocess
import typer

from pathlib import Path
from typing import Annotated

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'lib'))
import ota
from link import T_OTA, BROADCAST

NODES = HERE / 'nodes'
COMMON = ['main.py', 'lib/link.py', 'lib/ota.py', 'lib/touch.py', 'lib/bridge.py']
CHUNK = 192
RP2040_VID = 0x2E8A
BAUD = 115200

app = typer.Typer(no_args_is_help=True)

PortOption = Annotated[str | None, typer.Option(help="Serial port, default: $LIMN_PORT or the only RP2040 connected.")]


def files_for(app_name):
    '''(local path, path on the MCU) of every file a node runs.'''
    return [(HERE / f, f) for f in COMMON + [app_name + '.py']]

def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:ota.HASH_LEN]

def load_config(name):
    path = Path(name) if name.endswith('.json') else NODES / (name + '.json')
    if not path.exists():
        choices = ', '.join(p.stem for p in sorted(NODES.glob('*.json')))
        raise typer.BadParameter(f"no node config {path}, choose from: {choices}")
    return path, json.loads(path.read_text())

def find_port(port=None):
    port = port or os.environ.get('LIMN_PORT')
    if port:
        return port
    from serial.tools import list_ports
    boards = [p.device for p in list_ports.comports() if p.vid == RP2040_VID]
    if len(boards) != 1:
        found = ', '.join(boards) or 'none'
        raise typer.BadParameter(f"pass --port, RP2040 boards found: {found}")
    return boards[0]

def wait_for_port(port, timeout=15):
    import serial
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            serial.Serial(port).close()
            return
        except (OSError, serial.SerialException):
            time.sleep(0.3)
    raise RuntimeError(f"{port} did not come back")

def warn_if_busy(port):
    '''Klipper's limn extension keeps the Dock's port open; two readers garble it.'''
    try:
        out = subprocess.run(['lsof', '-t', os.path.realpath(port)], capture_output=True, text=True).stdout
    except FileNotFoundError:
        return
    if out.split():
        print(f"warning: {port} is open by pid {', '.join(out.split())} (Klipper?)", file=sys.stderr)


class Dock:
    '''The Dock's USB serial: sends command lines, reads back !LRT>> lines.'''

    def __init__(self, stream, reopen=None):
        self.stream = stream
        self._reopen = reopen
        self._buffer = b''

    @classmethod
    def open(cls, port):
        import serial
        warn_if_busy(port)
        def connect():
            return serial.Serial(port, BAUD, timeout=0.05)
        dock = cls(connect())
        def reopen():
            dock.stream.close()
            time.sleep(1)
            wait_for_port(port)
            dock.stream = connect()
        dock._reopen = reopen
        return dock

    def send(self, cmd):
        self.stream.write((cmd + '\r\n').encode())

    def reopen(self):
        if self._reopen:
            self._reopen()
        self._buffer = b''

    def lines(self, timeout=None):
        '''Yields (kind, data) per !LRT line until `timeout` seconds pass.'''
        end = None if timeout is None else time.monotonic() + timeout
        while end is None or time.monotonic() < end:
            try:
                self._buffer += self.stream.read(self.stream.in_waiting or 1)
            except OSError:
                return      # the Dock reset under us
            while b'\n' in self._buffer:
                raw, self._buffer = self._buffer.split(b'\n', 1)
                parsed = parse_line(raw.decode(errors='replace').strip())
                if parsed:
                    yield parsed

    def command(self, cmd, kind, timeout=2):
        '''Sends a command and returns the data of the first `kind` line back.'''
        self.send(cmd)
        for k, data in self.lines(timeout):
            if k == kind:
                return data
        raise TimeoutError(f"no {kind} reply to {cmd}")

    def request(self, hop, op, body=b'', timeout=2, retries=3):
        '''One update request to the node at `hop` -> (ok, reply body).'''
        payload = bytes([op]) + body
        b64 = binascii.b2a_base64(payload).decode().strip()
        for _ in range(retries):
            self.send(f'frame({hop},{T_OTA},{b64})')
            for kind, data in self.lines(timeout):
                if kind != 'frame' or data['hop'] != hop or data['type'] != T_OTA:
                    continue
                reply = binascii.a2b_base64(data['b64'])
                if reply[0] == op | ota.REPLY:
                    return bool(reply[1]), reply[2:]
        raise TimeoutError(f"hop {hop} did not answer op {op}")

    def broadcast(self, op, body=b''):
        b64 = binascii.b2a_base64(bytes([op]) + body).decode().strip()
        self.send(f'frame({BROADCAST},{T_OTA},{b64})')

    def hellos(self, timeout=1.5):
        '''hop -> hello data, for every node that answers ping().'''
        self.send('ping()')
        found = {}
        for kind, data in self.lines(timeout):
            if kind == 'hello':
                found[data['hop']] = data
        return found

    def info(self, hop):
        ok, body = self.request(hop, ota.OP_INFO)
        if not ok:
            raise RuntimeError(f"hop {hop}: {body.decode()}")
        return json.loads(body)

def parse_line(line):
    if not line.startswith('!LRT>>'):
        return None
    kind, _, body = line[len('!LRT>>'):].partition('>>')
    body = body[:-2] if body.endswith('>>') else body
    try:
        return kind, json.loads(body)
    except ValueError:
        return kind, body


# Updates
def plan_update(info, source=HERE, force=False, config=None):
    '''-> (files to send as [(local, remote)], protected files that differ)'''
    wanted = [(source / remote, remote) for _, remote in files_for(info['app'])]
    if config:
        wanted.append((config, 'node.json'))
    send, held = [], []
    for local, remote in wanted:
        if info['files'].get(remote) == file_hash(local):
            continue
        if remote in ota.PROTECTED and not force:
            held.append(remote)
        else:
            send.append((local, remote))
    return send, held

def upload(dock, hop, local, remote, force=False):
    data = Path(local).read_bytes()
    flags = ota.F_FORCE if force else 0
    header = struct.pack('<BI', flags, len(data)) + hashlib.sha256(data).digest()
    ok, body = dock.request(hop, ota.OP_BEGIN, header + remote.encode())
    if not ok:
        raise RuntimeError(f"{remote}: {body.decode()}")
    offset = 0
    while offset < len(data):
        chunk = data[offset:offset + CHUNK]
        ok, body = dock.request(hop, ota.OP_DATA, struct.pack('<I', offset) + chunk)
        if len(body) != 4:
            raise RuntimeError(f"{remote}: {body.decode()}")
        offset = struct.unpack('<I', body)[0]
        print(f"\r  {remote}: {offset}/{len(data)}", end='', flush=True)
    ok, body = dock.request(hop, ota.OP_END)
    print(' ok' if ok else ' FAILED')
    if not ok:
        raise RuntimeError(f"{remote}: {body.decode()}")

def update_node(dock, hop, source=HERE, force=False, config=None, dry_run=False):
    '''Sends the files that differ, commits, waits for the reboot and confirms.
    Returns True if the node runs the new files.'''
    info = dock.info(hop)
    send, held = plan_update(info, source, force, config)
    name = f"hop {hop} ({info['role']})"
    for remote in held:
        print(f"{name}: {remote} differs, needs --force")
    if not send:
        print(f"{name}: up to date")
        return True
    print(f"{name}: sending {', '.join(r for _, r in send)}")
    if dry_run:
        return True

    for local, remote in send:
        upload(dock, hop, local, remote, force)
    expected = {remote: file_hash(local) for local, remote in send}
    ok, body = dock.request(hop, ota.OP_COMMIT, '\n'.join(expected).encode())
    if not ok:
        raise RuntimeError(f"{name}: commit failed: {body.decode()}")

    print(f"{name}: rebooting")
    if hop == 0:
        dock.reopen()
    info = wait_for_info(dock, hop)
    if info.get('app') is None or any(info['files'].get(r) != h for r, h in expected.items()):
        print(f"{name}: did not come back with the new files, it rolled back")
        return False
    dock.request(hop, ota.OP_CONFIRM)
    print(f"{name}: updated and confirmed")
    return True

def wait_for_info(dock, hop, timeout=30):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            return dock.info(hop)
        except (TimeoutError, RuntimeError, OSError):
            time.sleep(0.5)
    raise TimeoutError(f"hop {hop} did not come back")


# Commands
@app.command()
def ports():
    '''List connected RP2040 boards.'''
    from serial.tools import list_ports
    for p in list_ports.comports():
        if p.vid == RP2040_VID:
            print(f"{p.device}\t{p.serial_number}\t{p.description}")

@app.command()
def install(
    config: Annotated[str, typer.Argument(help="Node config in micropython/nodes/, eg. dock, rtp, fsr, fsr_bed3.")],
    port: PortOption = None,
):
    '''First install (or reinstall) over USB: bootloader, libs, app and node.json.'''
    config_path, node = load_config(config)
    port = find_port(port)

    # Move main.py away and reset, so the app (and its watchdog) does not run
    # while we copy. Works for the old firmware as well.
    print(f"{port}: parking the running app")
    park = "import os\ntry:\n    os.rename('main.py', 'main.py.parked')\nexcept OSError:\n    pass\nimport machine\nmachine.reset()"
    mpremote(port, 'exec', park, check=False)
    time.sleep(1)
    wait_for_port(port)

    prepare = "import os\ntry:\n    os.mkdir('lib')\nexcept OSError:\n    pass"
    cleanup = ("import os\nfor f in ('main.py.parked', '" + ota.PENDING + "'):\n"
               "    try:\n        os.remove(f)\n    except OSError:\n        pass")
    args = ['exec', prepare]
    for local, remote in files_for(node['app']):
        args += ['+', 'fs', 'cp', str(local), ':' + remote]
    args += ['+', 'fs', 'cp', str(config_path), ':node.json', '+', 'exec', cleanup, '+', 'reset']
    print(f"{port}: installing {config_path.stem} ({node['app']})")
    mpremote(port, *args)
    print(f"{port}: done")

@app.command()
def console(port: PortOption = None):
    '''Watch one board's own output over USB (Ctrl-] to leave). Works without the Dock.'''
    mpremote(find_port(port), 'repl', check=False)

def mpremote(port, *args, check=True):
    return subprocess.run([sys.executable, '-m', 'mpremote', 'connect', port, *args], check=check)

@app.command()
def topology(port: PortOption = None):
    '''Show the chain: position, role, board id and whether its files are current.'''
    dock = Dock.open(find_port(port))
    hellos = dock.hellos()
    print(f"{'hop':>3}  {'role':<14} {'uid':<17} files")
    for hop in sorted(set(hellos) | {0}):
        try:
            info = dock.info(hop)
        except (TimeoutError, RuntimeError) as e:
            role = hellos.get(hop, {}).get('role', '?')
            print(f"{hop:>3}  {role:<14} {'?':<17} no answer ({e})")
            continue
        send, held = plan_update(info) if info.get('app') else ([], [])
        stale = [r for _, r in send] + held
        state = 'current' if not stale else 'differs: ' + ', '.join(stale)
        if info['pending']:
            state += ' (update not confirmed)'
        print(f"{hop:>3}  {info['role'] or '?':<14} {info['uid']:<17} {state}")

@app.command()
def info(hop: int = 0, port: PortOption = None):
    '''Everything a node reports about itself, as JSON.'''
    dock = Dock.open(find_port(port))
    print(json.dumps(dock.info(hop), indent=2))

@app.command()
def stats(port: PortOption = None):
    '''Link counters of the Dock: frames, damaged, dropped, missed per hop.'''
    dock = Dock.open(find_port(port))
    print(json.dumps(dock.command('stats()', 'stats'), indent=2))

@app.command()
def send(
    cmd: Annotated[str, typer.Argument(help="eg. 'calibrate()', 'arm(rtp)', 'read_bed_id()'")],
    wait: float = 1.0,
    port: PortOption = None,
):
    '''Send a command to the Dock and print what comes back for a while.'''
    dock = Dock.open(find_port(port))
    dock.send(cmd)
    for kind, data in dock.lines(wait):
        print(kind, json.dumps(data) if not isinstance(data, str) else data)

@app.command()
def monitor(
    kind: Annotated[list[str] | None, typer.Option(help="Only these line kinds, eg. --kind data --kind hello.")] = None,
    port: PortOption = None,
):
    '''Print everything the Dock says, one JSON object per line. Ctrl-C to stop.'''
    dock = Dock.open(find_port(port))
    for k, data in dock.lines():
        if not kind or k in kind:
            print(json.dumps({'t': round(time.time(), 3), 'kind': k, 'data': data}), flush=True)

@app.command()
def update(
    hop: Annotated[list[int] | None, typer.Option(help="Only these positions (0 = Dock). Default: all.")] = None,
    config: Annotated[str | None, typer.Option(help="Also replace node.json with this config (needs one --hop).")] = None,
    force: Annotated[bool, typer.Option(help="Also replace the bootloader files (main.py, lib/ota.py).")] = False,
    dry_run: bool = False,
    port: PortOption = None,
):
    '''Update over the chain: only files that differ, farthest node first, Dock last.'''
    config_path = load_config(config)[0] if config else None
    if config and (not hop or len(hop) != 1):
        raise typer.BadParameter("--config needs exactly one --hop")
    dock = Dock.open(find_port(port))
    targets = hop or sorted(set(dock.hellos()) | {0})
    run_update(dock, targets, force=force, config=config_path, dry_run=dry_run)

def run_update(dock, targets, source=HERE, force=False, config=None, dry_run=False):
    results = {}
    dock.broadcast(ota.OP_QUIET, b'\x01')
    try:
        for hop in sorted(targets, key=lambda h: (h == 0, -h)):
            results[hop] = update_node(dock, hop, source, force, config, dry_run)
    finally:
        dock.broadcast(ota.OP_QUIET, b'\x00')
    failed = [h for h, ok in results.items() if not ok]
    if failed:
        raise typer.Exit(1)
    return results


if __name__ == "__main__":
    app()
