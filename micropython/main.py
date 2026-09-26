# Limn MCU bootloader
#
# Copyright (C) 2026 Prashant Sinha <limn@noop.pw>
# This file may be distributed under the terms of the GNU GPLv3 license.
#
# Runs the app named in node.json. Rolls back an update that does not come
# up, and falls back to a rescue loop (link relay + updates only) when the app
# fails to start. `mcu.py update` leaves this file alone unless forced.
import sys
import machine
import ota
from link import load_node

node = load_node()
if ota.check_pending():
    ota.start_confirm_timer()

try:
    __import__(node['app'])
except Exception as e:
    sys.print_exception(e)
    if ota.rollback():
        machine.reset()
    print('Limn: app failed, running the rescue loop')
    ota.rescue(node)
