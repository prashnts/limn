# Limn Resistive Touch

Upload to the microcontrollers. Every MCU needs the shared link library, once:
```
uv run mpremote fs mkdir :lib
uv run mpremote fs cp micropython/lib/link.py :lib/link.py
```

Then the firmware for its role:
```
uv run mpremote fs cp micropython/lrt_dock_mcu.py :main.py
uv run mpremote fs cp micropython/lrt_resistive_touch.py :main.py
uv run mpremote fs cp micropython/lrt_fsr_array.py :main.py
```

Test the link library on a PC:
```
python3 micropython/tests/test_link.py
```

See [STRATEGY.md](STRATEGY.md) for how the MCUs talk to each other.
