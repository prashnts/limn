# uv run pytest plot/tests
import textwrap

import pytest

from plot.job import Job, Obj, Placement
from plot.profile import load_machine, load_tools


def svg_text(body, w=100, h=100):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}mm" height="{h}mm" viewBox="0 0 {w} {h}">'
            + textwrap.dedent(body) + '</svg>')


@pytest.fixture
def machine():
    return load_machine()


@pytest.fixture
def tools():
    return load_tools()


@pytest.fixture
def write_svg(tmp_path):
    def write(body, w=100, h=100, name='d.svg'):
        p = tmp_path / name
        p.write_text(svg_text(body, w, h))
        return p
    return write


@pytest.fixture
def job_of(tmp_path):
    '''A job of one SVG (mm units, 1 user unit = 1 mm) at (x, y).'''
    def make(svg_path, x=10, y=40, groups=None, **kw):
        obj = Obj(id='d', svg=str(svg_path), groups=groups or {}, placement=Placement(x=x, y=y), **kw)
        job = Job(objects=[obj])
        job._root = tmp_path
        return job
    return make
