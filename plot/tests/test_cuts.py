# Cutting outlines into pieces (plot/cuts.py), and painting the pieces
import numpy as np
import pytest

from plot import cuts

SQUARE = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], float)      # 40 round
LINE = np.array([[0, 0], [10, 0], [20, 0]], float)


def test_an_open_path_in_pieces():
    got = cuts.pieces(LINE, False, [0.25, 0.75])
    assert [t for t, _ in got] == [0, 0.25, 0.75]
    assert got[0][1].tolist() == [[0, 0], [5, 0]]
    assert got[1][1].tolist() == [[5, 0], [10, 0], [15, 0]]
    assert got[2][1].tolist() == [[15, 0], [20, 0]]
    assert len(cuts.pieces(LINE, False, [])) == 1 and len(cuts.pieces(LINE, False, [0])) == 1


def test_a_closed_path_needs_two_cuts():
    one = cuts.pieces(SQUARE, True, [0.125])                  # opened at (5, 0), round to it
    assert len(one) == 1 and one[0][1][0].tolist() == [5, 0] and one[0][1][-1].tolist() == [5, 0]
    two = cuts.pieces(SQUARE, True, [0.125, 0.625])            # (5, 0) and (5, 10)
    assert [t for t, _ in two] == [0.125, 0.625]
    assert two[0][1].tolist() == [[5, 0], [10, 0], [10, 10], [5, 10]]
    assert two[1][1].tolist() == [[5, 10], [0, 10], [0, 0], [5, 0]]       # round past the start


def test_where_a_click_falls():
    k, t, d = cuts.nearest([LINE, SQUARE + 30], [False, True], (12, 1))
    assert (k, d) == (0, 1) and t == pytest.approx(0.6)
    k, t, d = cuts.nearest([LINE, SQUARE + 30], [False, True], (30, 35))
    assert k == 1 and t == pytest.approx(0.875) and d == 0
    assert cuts.point(SQUARE, True, 0.875).tolist() == [0, 5]
    assert cuts.key(1, 0.875) == '1@0.8750'
