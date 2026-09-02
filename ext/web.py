import io
import asyncio
import numpy as np
import json
from PIL import Image
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from .redis import PubSubManager, PubSubMessage
from .tof import sensor_thread, Config

app = FastAPI()

state = {
    'tof_render': np.zeros((8, 8), dtype=np.uint8),
}

def load_acts(channel_name, message: PubSubMessage):
    payload = json.loads(message.payload['data'])
    if 'tof' in payload:
        state['tof_render'] = np.array(payload['tof']['render'])
    if 'dock' in payload:
        state['dock_status'] = payload['dock']['docked']


def render_ndarray_to_image(data: np.ndarray, scale: int) -> bytes:
    """
    Convert a square integer ndarray (range [-10, MAX]) into a JPEG image.
    Each array element becomes a `scale x scale` block coloured with a
    diverging palette.

    Parameters
    ----------
    data : np.ndarray
        2‑D square array of ints. Shape must be (N, N). The function works for any N,
        but the problem statement uses an 8×8 board.
    scale : int
        Block size – the output image will have dimensions N*scale × N*scale.

    Returns
    -------
    bytes
        JPEG binary data after a 180° rotation and a left‑right flip.
    """

    # ----------------------------------------------------------------------
    # 1. sanity checks & basic parameters
    # ----------------------------------------------------------------------
    if data.ndim != 2 or data.shape[0] != data.shape[1]:
        raise ValueError("data must be a square 2‑D ndarray")
    N = data.shape[0]
    M = N * scale                     # final image size (pixels)

    # ----------------------------------------------------------------------
    # 2. Build a diverging palette with at least 25 stops
    # ----------------------------------------------------------------------
    def _build_palette() -> list[tuple[int, int, int]]:
        """
        Returns a list of 25 RGB tuples forming a smooth blue‑white‑red diverging map.
        The colours are chosen manually and then linearly interpolated between the
        defined key points.
        """
        # Key stops (position, colour). Positions are in [0,1].
        key_stops = [
            (0.00, (  0,   0, 128)),   # deep blue
            (0.10, (  0, 102, 204)),
            (0.20, ( 51, 153, 255)),
            (0.30, (102, 204, 255)),
            (0.40, (173, 216, 230)),   # light blue / cyan
            (0.45, (200, 220, 240)),
            (0.50, (255, 255, 255)),   # white centre
            (0.55, (250, 235, 215)),
            (0.60, (255, 182, 193)),   # pinkish
            (0.70, (255, 105, 180)),
            (0.80, (255,  69,  0)),    # orange‑red
            (0.90, (205,  33,  33)),
            (1.00, (128,   0,   0))    # deep red
        ]

        # Interpolate to exactly 25 stops
        palette = []
        for i in range(25):
            pos = i / 24          # position of the i‑th stop
            # find surrounding key stops
            for (p0, c0), (p1, c1) in zip(key_stops[:-1], key_stops[1:]):
                if p0 <= pos <= p1:
                    t = (pos - p0) / (p1 - p0) if p1 != p0 else 0.0
                    r = int(round(c0[0] + t * (c1[0] - c0[0])))
                    g = int(round(c0[1] + t * (c1[1] - c0[1])))
                    b = int(round(c0[2] + t * (c1[2] - c0[2])))
                    palette.append((r, g, b))
                    break
        return palette

    PALETTE = _build_palette()          # length == 25

    # ----------------------------------------------------------------------
    # 3. Normalise data → colour index (0 … 24)
    # ----------------------------------------------------------------------
    flat = data.ravel()
    # Remove up to ten extreme high values for statistics
    sorted_vals = np.sort(flat)
    if len(sorted_vals) > 10:
        trimmed = sorted_vals[:-10]          # drop the ten largest elements
    else:                                    # very small board – keep everything
        trimmed = sorted_vals

    mean_val = trimmed.mean()
    std_val = trimmed.std(ddof=0)

    # Define lower and upper bounds for colour mapping.
    # Lower bound is the minimum present value (or -10 as problem states)
    v_min = data.min()
    # Upper bound: mean + 2*std – this limits influence of outliers
    v_max = mean_val + 2 * std_val

    if v_max <= v_min:          # degenerate case (all equal values)
        v_max = v_min + 1.0

    def _value_to_color(val: int) -> tuple[int, int, int]:
        """
        Map a single integer value to an RGB colour from the palette.
        Values are clipped to [v_min, v_max] and then linearly mapped onto
        the 25‑stop palette.
        """
        # Clip to the effective range
        if val < v_min:
            idx = 0
        elif val > v_max:
            idx = len(PALETTE) - 1
        else:
            ratio = (val - v_min) / (v_max - v_min)          # in [0,1]
            idx = int(round(ratio * (len(PALETTE) - 1)))
        return PALETTE[idx]

    # ----------------------------------------------------------------------
    # 4. Create the image and paint each block
    # ----------------------------------------------------------------------
    img = Image.new("RGB", (M, M))
    pixels = img.load()

    for i in range(N):
        for j in range(N):
            colour = _value_to_color(int(data[i, j]))
            # Fill a scale×scale square at the correct location
            x0 = j * scale
            y0 = i * scale
            for dy in range(scale):
                for dx in range(scale):
                    pixels[x0 + dx, y0 + dy] = colour

    # ----------------------------------------------------------------------
    # 5. Rotate / flip as required and return JPEG bytes
    # ----------------------------------------------------------------------
    # img = img.rotate(180)
    img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)

    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()

async def mjpeg_generator():
    while True:
        data_matrix = state['tof_render']
        frame = render_ndarray_to_image(data_matrix, 40)
        yield (
            b'--frame\r\n'
            b'Content-Type: image/jpeg\r\n'
            b'Content-Length: ' + str(len(frame)).encode() + b'\r\n\r\n' +
            frame + b'\r\n'
        )

async def streamer(gen):
    try:
        async for i in gen:
            yield i
            await asyncio.sleep(0.25)
    except asyncio.CancelledError:
        print("caught cancelled error")

@app.get("/tof")
async def tof_feed():
    PubSubManager().attach('tof', ('limn.state',), load_acts)
    return StreamingResponse(
        streamer(mjpeg_generator()), 
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

if __name__ == "__main__":
    import uvicorn
    sensor_thread(Config())
    uvicorn.run("ext.web:app", host="0.0.0.0", port=4219, reload=True)
