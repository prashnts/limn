import hashlib
import binascii
import os

BEGIN_MARKER = b'<BEGIN_FILE>'
END_MARKER = b'<END_FILE>'

CHUNK_LEN = 512

def send_file(uart, path):
    _hash = hashlib.sha256()
    fp = open(path, 'rb')
    _hash.update(fp.read())
    fp.seek(0)


def receive_file(uart, path):
    _hash = hashlib.sha256()
    fp = open(path + '.new', 'wb')
    while True:
        data = uart.read()
        if END_MARKER in data:
            data = data.split(END_MARKER)[0]
            fp.write(data)
            _hash.update(data)
            break
        fp.write(data)
        _hash.update(data)
        print('.')
    fp.close()
    if binascii.hexlify(_hash.hexdigest()) != hash:
        raise ValueError("Hash mismatch")
    os.rename(path, path + '.old')
    os.rename(path + '.new', path)
