# Clip-paths, masks and gradient fills
import numpy as np
import pytest

from plot import svg
from plot.job import Group, RasterSpec
from plot.slicer import slice_object


def test_clip_path_cuts_shapes_and_isnt_drawn(write_svg, tools, job_of):
    p = write_svg('''
        <defs><clipPath id="c"><rect x="0" y="0" width="50" height="100"/></clipPath></defs>
        <g clip-path="url(#c)">
          <path d="M10 50 H90" stroke="#000000" stroke-width="1"/>
          <rect x="20" y="20" width="60" height="20" fill="#000000"/>
        </g>''')
    d = svg.load(p)
    assert len(d.shapes) == 2 and all(s.clip is not None for s in d.shapes)
    assert d.shapes[0].clip.area == pytest.approx(5000, rel=1e-3)
    job = job_of(p, groups={'stroke #000000': Group(tool='T0'), 'fill #000000': Group(tool='T0')})
    out = slice_object(job.objects[0], tools, drawing=d)
    xs = np.vstack(out.paths['T0'])[:, 0]
    assert xs.max() <= 50 + 1e-6                # nothing past the clip (local x = page x at scale 1)


def test_mask_is_where_it_is_light_and_its_shapes_arent_drawn(write_svg):
    # Sketch's export: the mask beside what it masks, its fill on the <mask>
    p = write_svg('''
        <defs><path id="r" d="M0 0 H40 V40 H0 Z"/></defs>
        <g transform="translate(10 10)">
          <mask id="m" fill="white"><use href="#r"/></mask>
          <use fill="#d8d8d8" href="#r"/>
          <circle cx="40" cy="40" r="20" fill="#ff0000" mask="url(#m)"/>
        </g>''')
    d = svg.load(p)
    fills = [s.fill for s in d.shapes]
    assert fills == ['#d8d8d8', '#ff0000']       # not the mask's white square
    clip = d.shapes[1].clip
    assert clip.bounds == pytest.approx((10, 10, 50, 50), abs=1e-4)     # in page mm: its group's translate


def test_gradient_fill_is_a_picture_of_it_in_its_shape(write_svg, tools, job_of):
    p = write_svg('''
        <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#000000"/></linearGradient></defs>
        <rect x="10" y="10" width="80" height="40" fill="url(#g)" stroke="#ff0000" stroke-width="1"/>''')
    d = svg.load(p)
    assert d.skipped == {}
    im, = d.images
    assert im.gradient and im.clip.area == pytest.approx(3200, rel=1e-3)
    dark = im.dark
    assert dark[:, 0].mean() < 0.05 and dark[:, -1].mean() > 0.95      # white on the left, black on the right
    assert np.all(np.diff(dark.mean(axis=0)) >= -1e-3)
    sh, = d.shapes                              # its outline stays a shape, over the picture
    assert sh.stroke == '#ff0000' and sh.fill is None and sh.index > im.index
    job = job_of(p, groups={'stroke #000000': Group(tool='T0'), 'stroke #ff0000': Group(tool='T3')},
                 raster=RasterSpec(mode='lines'))
    out = slice_object(job.objects[0], tools, drawing=d)
    pts = np.vstack(out.paths['T0'])
    assert pts[:, 0].min() >= 10 - 1e-6 and pts[:, 0].max() <= 90 + 1e-6     # within the shape
    left, right = (pts[:, 0] < 50).sum(), (pts[:, 0] >= 50).sum()
    assert right > left                         # more ink where it is darker


def test_radial_gradient_with_a_transform(write_svg):
    p = write_svg('''
        <defs><radialGradient id="g" gradientTransform="translate(0.5,0.5),scale(0.5),translate(-0.5,-0.5)">
          <stop offset="0" stop-color="#000000"/><stop offset="100%" stop-color="#000000" stop-opacity="0"/></radialGradient></defs>
        <circle cx="50" cy="50" r="40" fill="url(#g)"/>''')
    im, = svg.load(p).images
    h, w = im.dark.shape
    assert im.dark[h // 2, w // 2] > 0.9 and im.dark[h // 2, 0] < 0.05     # dark in the middle, none at the edge



def test_sketch_flipped_image(write_svg):
    # Sketch: a picture flipped in its app is an <image> with a <g transform> inside (browsers ignore it)
    import base64, io
    from PIL import Image
    px = Image.new('RGB', (10, 10), 'white')
    px.putpixel((2, 1), (0, 0, 0))                  # a dark pixel near the top
    buf = io.BytesIO()
    px.save(buf, 'PNG')
    href = 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()
    p = write_svg(f'''<image x="0" y="0" width="10" height="10" href="{href}">
        <g transform="translate(5, 5) scale(-1, 1) rotate(-180) translate(-5, -5)"></g></image>''')
    im, = svg.load(p).images
    a, b, c, d, e, f = im.matrix
    u, v = 2.5, 1.5                                 # that pixel's middle: now near the bottom, as Sketch shows it
    assert (a * u + c * v + e, b * u + d * v + f) == pytest.approx((2.5, 8.5), abs=1e-3)
