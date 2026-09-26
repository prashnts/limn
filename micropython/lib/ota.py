# Limn OTA - firmware update over the chain
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Requests arrive as T_OTA frames, payload = op:u8 + body. Every request gets
# one reply: op | REPLY, ok:u8, body. Driven by micropython/mcu.py.
#
#   INFO                                 -> json: role, app, uid, files, pending
#   BEGIN   flags:u8 size:u32 sha256 path -> starts writing path.new
#   DATA    offset:u32 bytes             -> offset:u32 expected next
#   END                                  -> checks size and sha256
#   COMMIT  paths joined by \n           -> path -> path.bak, path.new -> path, reset
#   CONFIRM                              -> keeps the update, drops the .bak files
#   QUIET   on:u8                        -> stop / resume sensor data and logs
#
# A committed update must be confirmed: until then every boot is counted, and
# after MAX_BOOTS (or CONFIRM_MS without a confirm) the old files come back.
import os
import json
import struct
import hashlib
import binascii

OP_INFO    = 0
OP_BEGIN   = 1
OP_DATA    = 2
OP_END     = 3
OP_COMMIT  = 4
OP_CONFIRM = 5
OP_QUIET   = 6
REPLY      = 0x80

F_FORCE = 0x1           # BEGIN flag: allow replacing PROTECTED files

PENDING    = 'ota_pending.json'
MAX_BOOTS  = 3
CONFIRM_MS = 60000
HASH_LEN   = 16         # hex chars of sha256 reported by INFO
PROTECTED  = ('main.py', 'lib/ota.py')   # the bootloader: a bad copy needs USB to fix
SKIP       = ('.new', '.bak', PENDING)

_confirm_timer = None


def reset():
    import machine
    machine.reset()

def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False

def _is_dir(path):
    return os.stat(path)[0] & 0x4000

def _remove(path):
    if _exists(path):
        os.remove(path)

def _makedirs(path):
    parts = path.split('/')[:-1]
    for i in range(len(parts)):
        folder = '/'.join(parts[:i + 1])
        if folder and not _exists(folder):
            os.mkdir(folder)

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fp:
        while True:
            chunk = fp.read(512)
            if not chunk:
                break
            h.update(chunk)
    return h.digest()

def list_files(root='', folder=''):
    '''Relative paths of every file under root, without update leftovers.'''
    files = []
    where = (root + folder).rstrip('/')
    for name in (os.listdir(where) if where else os.listdir()):
        path = folder + name
        if any(path.endswith(s) for s in SKIP):
            continue
        if _is_dir(root + path):
            files += list_files(root, path + '/')
        else:
            files.append(path)
    return files

def _load_pending(root):
    try:
        with open(root + PENDING) as fp:
            return json.load(fp)
    except (OSError, ValueError):
        return None

def _save_pending(root, pending):
    with open(root + PENDING, 'w') as fp:
        json.dump(pending, fp)


# Boot time, called from main.py
def check_pending(root=''):
    '''Counts a boot of an unconfirmed update. Returns True while it waits for
    a confirm, rolls back (and returns False) once it used up its boots.'''
    pending = _load_pending(root)
    if pending is None:
        return False
    pending['boots'] += 1
    if pending['boots'] > MAX_BOOTS:
        print('ota: update not confirmed, rolling back')
        rollback(root)
        return False
    _save_pending(root, pending)
    return True

def start_confirm_timer():
    '''Resets if no confirm arrives in time, so a silent node still rolls back.'''
    global _confirm_timer
    from machine import Timer
    _confirm_timer = Timer(-1)
    _confirm_timer.init(period=CONFIRM_MS, mode=Timer.ONE_SHOT, callback=lambda t: reset())

def rollback(root=''):
    '''Restores the files of an unconfirmed update. Returns False if none.'''
    pending = _load_pending(root)
    if pending is None:
        return False
    for path in pending['files']:
        if path in pending['new']:
            _remove(root + path)
        elif _exists(root + path + '.bak'):
            _remove(root + path)
            os.rename(root + path + '.bak', root + path)
    _remove(root + PENDING)
    return True

def rescue(node, root=''):
    '''Link relay + updates only, for when the app does not start.'''
    import time
    from link import from_config, T_CMD, T_HELLO
    link = from_config(node)
    link.root = root
    hello = ('rescue:' + node.get('role', '?') + '>>app failed to start').encode()
    link.send(T_HELLO, hello)
    while True:
        for frame in link.poll():
            if frame.type == T_CMD and frame.payload == b'ping()':
                link.send(T_HELLO, hello)
        time.sleep_ms(1)


class Receiver:
    '''Update requests for one node.'''

    def __init__(self, link):
        self.link = link
        self.root = link.root
        self.reset_pending = False
        self._fp = None
        self._path = None
        self._size = 0
        self._sha = None
        self._offset = 0
        self._staged = []       # paths with a verified .new

    def handle(self, payload):
        op = payload[0] if payload else OP_INFO
        try:
            ok, body = self._run(op, payload[1:])
        except Exception as e:
            ok, body = False, repr(e).encode()
        return bytes([op | REPLY, 1 if ok else 0]) + body

    def _run(self, op, body):
        if op == OP_INFO:
            return True, self.info()
        if op == OP_BEGIN:
            return self.begin(body)
        if op == OP_DATA:
            return self.data(body)
        if op == OP_END:
            return self.end()
        if op == OP_COMMIT:
            return self.commit(body.decode().split('\n'))
        if op == OP_CONFIRM:
            return self.confirm()
        if op == OP_QUIET:
            self.link.quiet = bool(body and body[0])
            return True, b''
        return False, b'unknown op'

    def info(self):
        try:
            import machine
            uid = binascii.hexlify(machine.unique_id()).decode()
        except (ImportError, AttributeError):
            uid = '?'
        try:
            from link import load_node
            node = load_node(self.root)
        except (OSError, ValueError):
            node = {}
        files = {}
        for path in list_files(self.root):
            files[path] = binascii.hexlify(sha256_file(self.root + path)).decode()[:HASH_LEN]
        return json.dumps({
            'role': node.get('role'),
            'app': node.get('app'),
            'uid': uid,
            'pending': _load_pending(self.root) is not None,
            'files': files,
        }).encode()

    def begin(self, body):
        flags, self._size = struct.unpack_from('<BI', body)
        self._sha = bytes(body[5:37])
        path = body[37:].decode()
        if not path or path.startswith('/') or '..' in path:
            return False, b'bad path'
        if path in PROTECTED and not flags & F_FORCE:
            return False, b'protected, needs force'
        if self._fp:
            self._fp.close()
        _makedirs(self.root + path)
        self._path = path
        self._fp = open(self.root + path + '.new', 'wb')
        self._offset = 0
        if path in self._staged:
            self._staged.remove(path)
        return True, b''

    def data(self, body):
        offset = struct.unpack_from('<I', body)[0]
        chunk = body[4:]
        if self._fp is None:
            return False, b'no file open'
        if offset + len(chunk) == self._offset:
            pass                # repeated chunk, its ack got lost
        elif offset != self._offset:
            return False, struct.pack('<I', self._offset)
        else:
            self._fp.write(chunk)
            self._offset += len(chunk)
        return True, struct.pack('<I', self._offset)

    def end(self):
        if self._fp is None:
            return False, b'no file open'
        self._fp.close()
        self._fp = None
        new = self.root + self._path + '.new'
        if self._offset != self._size or sha256_file(new) != self._sha:
            _remove(new)
            return False, b'size or sha256 mismatch'
        self._staged.append(self._path)
        return True, b''

    def commit(self, paths):
        missing = [p for p in paths if p not in self._staged]
        if missing:
            return False, ('not staged: ' + ' '.join(missing)).encode()
        new = [p for p in paths if not _exists(self.root + p)]
        for path in paths:
            full = self.root + path
            if path not in new:
                _remove(full + '.bak')
                os.rename(full, full + '.bak')
            os.rename(full + '.new', full)
        _save_pending(self.root, {'files': paths, 'new': new, 'boots': 0})
        self._staged = []
        self.reset_pending = True
        return True, b''

    def confirm(self):
        pending = _load_pending(self.root)
        if pending is None:
            return True, b'nothing pending'
        for path in pending['files']:
            _remove(self.root + path + '.bak')
        _remove(self.root + PENDING)
        if _confirm_timer:
            _confirm_timer.deinit()
        return True, b''
