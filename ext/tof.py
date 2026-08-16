import sys
import time
import json
import board
import digitalio
import redis
from pathlib import Path
from dataclasses import dataclass, field
from pydantic import BaseModel
from adafruit_pn532.i2c import PN532_I2C
from adafruit_mcp230xx.mcp23017 import MCP23017

_here = Path(__file__).parent / 'tof_bin'

sys.path.append(_here.as_posix())

from _vl53lxcx import (
    DATA_DISTANCE_MM,
    DATA_TARGET_STATUS,
    RESOLUTION_8X8,
    STATUS_VALID,
    VL53L5CX,
)


class Config(BaseModel):
    buzzer_enable: bool = True
    buzzer_address: str = '0x1e'

    tof_enable: bool = True
    dock_status_enable: bool = True

    seesaw_enable: bool = True
    seesaw_address: str = '0x49'


@dataclass
class ToFSensor:
    # Add: 0x29
    tof: VL53L5CX = None
    distance_mm: list[int] = None
    masked_distance_mm: list[int] = None
    grid: int = 7
    render: list[list[int]] = None
    updated_at: float = 0.0
    update_frequency: int = 1
    _n_update: int = 0

    def update(self):
        if self._n_update < self.update_frequency:
            self._n_update += 1
            return
        self._n_update = 0

        if not self.tof:
            return
        if self.tof.check_data_ready():
            results = self.tof.get_ranging_data()
            distance_mm = results.distance_mm
            target_status = results.target_status
            grid = 7

            masked_distance_mm = [d if status == STATUS_VALID else 0 for d, status in zip(distance_mm, target_status)]

            self.distance_mm = distance_mm
            self.masked_distance_mm = masked_distance_mm
            self.updated_at = time.monotonic()
            if distance_mm != self.distance_mm:
                self.distance_mm = distance_mm
                self.masked_distance_mm = masked_distance_mm

            d_max = max(masked_distance_mm)
            render = []
            row = []
            for i, d in enumerate(masked_distance_mm):
                scaled = int((d / d_max) * 255) if d_max > 0 else 0
                row.append(scaled)
                if (i & grid) == grid:
                    render.append(row)
                    row = []
            self.render = render

    def serialize(self) -> dict:
        if not self.tof:
            return {}
        return {
            'distance_mm': self.distance_mm,
            'masked_distance_mm': self.masked_distance_mm,
            'updated_at': self.updated_at,
            'render': self.render,
            'grid': self.grid,
        }

    @classmethod
    def setup(cls, bus: board.I2C, conf: Config, **kwargs):
        if not conf.tof_enable:
            return cls(**kwargs)
        try:
            tof = VL53L5CX(bus)

            if not tof.is_alive():
                raise ValueError("VL53L8CX not detected")

            tof.init()
            tof.resolution = RESOLUTION_8X8
            tof.ranging_freq = 10
            tof.start_ranging({DATA_DISTANCE_MM, DATA_TARGET_STATUS})
            return cls(tof, **kwargs)
        except Exception as e:
            print(f"[VL53L5CX] not found: {e}")
            return cls(**kwargs)


@dataclass
class DockStatusSensor:
    # Add: 0x29
    mcp: MCP23017 = None

    pin_tool_map = {
        15: 41,
        14: 42,
        13: 45,
        12: 43,
        11: 44,
    }

    current_tools: list[int] = field(default_factory=list)

    updated_at: float = 0.0
    update_frequency: int = 10
    _n_update: int = 0

    @classmethod
    def setup(cls, bus: board.I2C, conf: Config, **kwargs):
        if not conf.dock_status_enable:
            return cls(**kwargs)
        try:
            mcp = MCP23017(bus)
            return cls(mcp, **kwargs)
        except Exception as e:
            print(f"[MCP23017] not found: {e}")
            return cls(**kwargs)

    def update(self):
        if not self.mcp:
            return

        pins = self.pin_tool_map.keys()

        values = []
        for p, tool_id in self.pin_tool_map.items():
            pin = self.mcp.get_pin(p)
            pin.switch_to_input(pullup=True)
            pin.direction = digitalio.Direction.INPUT
            pin.pull = digitalio.Pull.UP
            if not pin.value:
                values.append(tool_id)

        self.current_tools = values
        self.updated_at = time.monotonic()
        return values

    def serialize(self) -> dict:
        if not self.mcp:
            return {}
        return {
            'docked': self.current_tools,
            'updated_at': self.updated_at,
        }




def setup(conf: Config = None):
    if conf is None:
        conf = Config()     # use default conf
    i2c = board.I2C()  # uses board.SCL and board.SDA
    bus_devs = i2c.scan()
    print("[i2c devices detected] ", [hex(x) for x in bus_devs if x])

    return {
        # 'buzzer': Buzzer.setup(i2c, conf),
        'tof': ToFSensor.setup(i2c, conf),
        'dock': DockStatusSensor.setup(i2c, conf),
    }

def sensor_loop(sensors: dict, conf: Config, callback=None):
    while True:
        payload = {
            "_v": "lim1",
            "updated_at": time.monotonic(),
        }
        for name, sensor in sensors.items():
            if sensor:
                try:
                    sensor.update()
                    payload[name] = sensor.serialize()
                except Exception as e:
                    print(f"[DI Remote] Error updating sensor {name}: {e}")

        if callback:
            acts = callback(payload) or []
            # print(acts)
            for (actuator, cmd, hash_) in acts:
                try:
                    sensors[actuator].act(cmd, hash_)
                except:
                    print(f'Could not actuate {actuator=} for {cmd=}')
        else:
            print(payload)
        time.sleep(0.001)

def render_distance_grid(
    data: list[list[int | float]],
    max_val: float | None = None,
    min_val: float | None = None,
) -> str:
    """Render a 2D distance array as a 2x2-enlarged ANSI true-color grid.

    kagi/ki_quick

    Args:
        data:    2D list of numeric distance values.
        max_val: Explicit upper bound for the color scale. Defaults to max(data).
        min_val: Explicit lower bound for the color scale. Defaults to min(data).

    Returns:
        A string of ANSI-escaped lines. print() it to see the grid.
    """

    def _lerp(a: float, b: float, t: float) -> float:
        return a + (b - a) * t

    def _color(t: float) -> tuple[int, int, int]:
        """Map t in [0, 1] to an RGB triple via a 5-stop ramp.

        Stops:  black → blue → cyan → green → yellow → red
        (low distances = dark/blue, high = red/white)


        """
        t = max(0.0, min(1.0, t))
        stops = [
            (0.0, (0, 0, 0)),
            (0.2, (30, 0, 120)),
            (0.4, (0, 120, 180)),
            (0.6, (0, 180, 80)),
            (0.8, (220, 200, 0)),
            (1.0, (255, 80, 0)),
        ]
        for i in range(len(stops) - 1):
            t0, c0 = stops[i]
            t1, c1 = stops[i + 1]
            if t <= t1:
                span = t1 - t0 if t1 != t0 else 1.0
                local = (t - t0) / span
                return (
                    int(_lerp(c0[0], c1[0], local)),
                    int(_lerp(c0[1], c1[1], local)),
                    int(_lerp(c0[2], c1[2], local)),
                )
        return stops[-1][1]  # clamp

    # --- normalize ----------------------------------------------------
    flat = [v for row in data for v in row]
    lo = min_val if min_val is not None else min(flat)
    hi = max_val if max_val is not None else max(flat)
    span = hi - lo if hi != lo else 1.0

    # --- build output -------------------------------------------------
    lines: list[str] = []
    for row in data:
        t_vals = [(v - lo) / span for v in row]
        for _ in range(2):  # 2x vertical enlargement
            line = ""
            for t in t_vals:
                r, g, b = _color(t)
                line += f"\x1b[48;2;{r};{g};{b}m {t} "  # 2 spaces = 2x horizontal
            line += "\x1b[0m"
            lines.append(line)

    return "\n".join(lines)

def main():
    db = redis.Redis(host='localhost', port=6379, db=0)
    def publish(channel: str, action: str, payload: dict = {}):
        db.publish(channel, json.dumps({'_action': action, **payload}))

    def callback(payload):
        publish('limn.telemetry', action='update', payload={'data': json.dumps(payload)})
        tof_render = payload['tof']['render']
        print(payload['dock']['docked'])
        if tof_render:
            print(render_distance_grid(tof_render))

    sensor_loop(setup(Config()), Config(), callback)


if __name__ == "__main__":
    main()
