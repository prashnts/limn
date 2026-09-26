# Limn USB Bridge - lets a host drive the chain through this MCU's USB port
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# The Dock always runs it. A bed node runs it too, so that mcu.py can talk to
# the nodes below it when it is plugged in over USB without a Dock:
#   hop 0 is this MCU, hop 1 the one below it, and so on.
#
# Host -> MCU: command lines, eg. `ping()`, `frame(<hop>,<type>,<base64>)`
# MCU -> host: `!LRT>>kind>>json>>` lines, see micropython/STRATEGY.md
import sys
import json
import time
import select
import binascii
from link import Frame, T_CMD, T_HELLO, T_LOG, T_DATA, T_OTA, unpack_data

TAG = "!LRT>>"


def teeprint(info, line):
    print(TAG + info + '>>' + line + ">>")


class Bridge:

    def __init__(self, link):
        self.link = link
        self._poller = select.poll()
        self._poller.register(sys.stdin, select.POLLIN)
        self._buffer = ''

    def read_command(self):
        '''Returns one complete command line from the host, or None. Never blocks.'''
        while self._poller.poll(0):
            ch = sys.stdin.read(1)
            if not ch:
                return None     # nothing to read after all (closed stdin)
            if ch in ('\r', '\n'):
                cmd, self._buffer = self._buffer.strip(), ''
                if cmd:
                    return cmd
            elif len(self._buffer) < 1024:
                self._buffer += ch
        return None

    def command(self, cmd):
        '''Handles the commands every MCU understands. Returns True if it did.'''
        if cmd.startswith('frame(') and cmd.endswith(')'):
            try:
                self.send_frame(cmd[6:-1])
            except (ValueError, TypeError) as e:
                teeprint("error", "bad frame: " + repr(e))
            return True
        if cmd == 'stats()':
            teeprint("stats", json.dumps(self.link.stats()))
            return True
        return False

    def from_host(self, cmd, handle):
        '''On a bed node: a host is on USB. From now on it sees every frame,
        and the command goes down the chain and to this node's `handle`.'''
        self.link.tap = self.show
        if self.command(cmd):
            return
        payload = cmd.encode()
        self.link.send_down(T_CMD, payload)
        handle(Frame(T_CMD, 0, 0, payload))

    def send_frame(self, args):
        '''frame(<hop>,<type>,<base64 payload>): hop 0 is this MCU.'''
        hop, ftype, b64 = args.split(',')
        hop, ftype = int(hop), int(ftype)
        payload = binascii.a2b_base64(b64)
        if hop != 0:
            self.link.send_down(ftype, payload, hop)
        elif ftype == T_OTA:
            self.show(Frame(T_OTA, 0, 0, self.link.handle_ota(payload)))
            if self.link.ota.reset_pending:
                time.sleep_ms(100)      # let the reply reach the host
                import ota
                ota.reset()

    def show(self, frame):
        '''Prints a frame for the host. Sensor data is left to the caller on
        the Dock, which merges it for klipper.'''
        if frame.type == T_HELLO:
            role, emblem = (frame.payload.decode().split('>>', 1) + [''])[:2]
            teeprint("hello", json.dumps({'hop': frame.hop, 'role': role, 'emblem': emblem}))
        elif frame.type == T_LOG:
            teeprint("log", json.dumps({'hop': frame.hop, 'text': frame.payload.decode()}))
        elif frame.type == T_OTA:
            b64 = binascii.b2a_base64(frame.payload).decode().strip()
            teeprint("frame", json.dumps({'hop': frame.hop, 'type': frame.type, 'b64': b64}))
        elif frame.type == T_DATA:
            sample = unpack_data(frame.payload)
            if sample:
                kind, state, values = sample
                teeprint("data", json.dumps({'hop': frame.hop, 'kind': kind, 'state': state, 'values': values}))
