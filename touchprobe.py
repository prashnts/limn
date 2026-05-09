import board
import busio
import typer
import serial
import re

from typing import Annotated
from dataclasses import dataclass
from itertools import batched
from adafruit_pn532.i2c import PN532_I2C


app = typer.Typer()


def get_port(portstr: str):
    port, baud = portstr.split(',')
    return serial.Serial(port, baudrate=int(baud), timeout=2)


def _parse_touch(line: str):
    pattern = r'.*xpt2046.* Touchscreen Update \[(\d+), (\d+)\], z = (\d+)'
    match = re.match(pattern, line)
    if match:
        x, y, z = match.groups()
        return int(x), int(y), int(z)
    return None


@app.command()
def read_touch(portstr: str = '/dev/ttyUSB1,112500', max_attempts: int = 15):
    ser = get_port(portstr)
    sample_count = 4
    attempt = 0
    samples = []
    try:
        while True:
            line = ser.readline().decode().strip()
            attempt += 1
            if touchpt := _parse_touch(line):
                samples.append(touchpt)
            if len(samples) >= sample_count:
                # Average the samples to reduce noise.
                avg_x = sum(s[0] for s in samples) / len(samples)
                avg_y = sum(s[1] for s in samples) / len(samples)
                avg_z = sum(s[2] for s in samples) / len(samples)
                print(f"TOUCH>>>ok||{avg_x}||{avg_y}||{avg_z}<<<")
                return avg_x, avg_y, avg_z
            if attempt >= max_attempts:
                print("TOUCH>>>timeout||0||0||0<<<")
                return None
    finally:
        ser.close()

if __name__ == "__main__":
    app()
