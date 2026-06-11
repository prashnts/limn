import board
import busio
import typer

from typing import Annotated
from dataclasses import dataclass
from itertools import batched
from adafruit_pn532.i2c import PN532_I2C


app = typer.Typer()


def encode_num(x: float):
    # Packs a float into a 4byte array.
    val = [
        0 if x >= 0 else 1, # sign
        abs(int(x)), # integer
        abs(round((x - int(x)) * 100)), # Fraction rounded up to two digits
        0, # reserved
    ]
    return bytearray(val)

def decode_num(val: bytearray):
     sign = '-' if val[0] == 1 else ''
     return float(f'{sign}{val[1]}.{val[2]}')

def get_nfc(retries: int = 3):
    try:
        i2c = busio.I2C(board.SCL, board.SDA)
        pn532 = PN532_I2C(i2c, debug=False)
        ic, ver, rev, support = pn532.firmware_version
        print(f"RFID<<< PN532 - FW:{ver}.{rev}")
        pn532.SAM_configuration()
        return pn532
    except Exception as e:
        if retries > 0:
            print("RFID<<< INIT ERROR, RETRYING...")
            return get_nfc(retries - 1)
        else:
            raise RuntimeError("RFID<<< INIT FAILED")

@dataclass
class TagData:
    uid: str
    x: float
    y: float
    z: float
    name: str


@app.command()
def write_tag(
    x: Annotated[float | None, typer.Option] = None,
    y: Annotated[float | None, typer.Option] = None,
    z: Annotated[float | None, typer.Option] = None,
    name: Annotated[str | None, typer.Option] = None,
):
    pn532 = get_nfc()
    try:
        uid = pn532.read_passive_target(timeout=2)
        if uid is None:
            print("RFID>>>NoTag<<<")
            return
        print("RFID>>>WriteTag uid={uid.hex()}<<<")
        if x is not None:
            pn532.ntag2xx_write_block(6, encode_num(x))
        if y is not None:
            pn532.ntag2xx_write_block(7, encode_num(y))
        if z is not None:
            pn532.ntag2xx_write_block(8, encode_num(z))
        if name is not None:
            tagname = name.ljust(20)[:20].encode()
            blk = 11
            for batch in batched(tagname, 4):
                pn532.ntag2xx_write_block(blk, bytearray(batch))
                blk += 1

        print("RFID>>>WriteOk<<<")
    except Exception as e:
        print("RFID>>>WriteError<<<")

@app.command()
def read_tag(timeout: float = 0.5, retries: int = 3):
    pn532 = get_nfc()
    try:
        uid = pn532.read_passive_target(timeout=timeout)
        if uid is None:
            print("RFID>>>None<<<")
            return

        xb = pn532.ntag2xx_read_block(6)
        yb = pn532.ntag2xx_read_block(7)
        zb = pn532.ntag2xx_read_block(8)
        name_b = b''
        for i in range(11, 16):
            name_b += pn532.ntag2xx_read_block(i)

        tag_data = TagData(
            uid=uid.hex(),
            x=decode_num(xb),
            y=decode_num(yb),
            z=decode_num(zb),
            name=name_b.decode().strip('\x00').strip() or '<unknown>',
        )
        # Output format optimized for gcode parsing.
        tag_str = f"TAG>>>{tag_data.x}||{tag_data.y}||{tag_data.z}||{tag_data.name}<<<"
        print(tag_str)
        return tag_data
    except Exception as e:
        if retries > 0:
            print("RFID>>>retrying...<<<")   
            return read_tag(timeout, retries - 1)


if __name__ == "__main__":
    app()
