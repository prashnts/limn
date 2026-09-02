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
        state['tof_render'] = payload['tof']['render']
    if 'dock' in payload:
        state['dock_status'] = payload['dock']['docked']

PubSubManager().attach('tof', ('limn.state',), load_acts)


def generate_frame(data_matrix: np.ndarray) -> bytes:
    """
    Converts a 2D numpy array to a JPEG byte stream.

    Args:
        data_matrix: 2D array (H, W) of values. 
                    If float, expects [0, 1]. If int, expects [0, 255].
    Returns:
        bytes: JPEG encoded image.
    """
    # Normalize matrix to [0, 255] uint8 if necessary
    if data_matrix.dtype != np.uint8:
        # Simple min-max normalization
        mat_min, mat_max = data_matrix.min(), data_matrix.max()
        if mat_max > mat_min:
            normalized = (255 * (data_matrix - mat_min) / (mat_max - mat_min)).astype(np.uint8)
        else:
            normalized = np.zeros_like(data_matrix, dtype=np.uint8)
    else:
        normalized = data_matrix

    # Create PIL Image from array
    # API: Image.fromarray(obj, mode=None)
    img = Image.fromarray(normalized, mode='L') # 'L' for grayscale

    # Save to bytes buffer
    buf = io.BytesIO()
    # API: img.save(fp, format=None, **params)
    img.save(buf, format='JPEG')
    return buf.getvalue()


async def mjpeg_generator():
    while True:
        data_matrix = state['tof_render']
        frame = generate_frame(data_matrix)

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
    return StreamingResponse(
        streamer(mjpeg_generator()), 
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

if __name__ == "__main__":
    import uvicorn
    sensor_thread(Config())
    uvicorn.run(app, host="0.0.0.0", port=4219)
