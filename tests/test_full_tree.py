import math

import pytest

from network_planner.steiner.full_tree import full_tree_length_3, full_tree_length_n


def test_length_n_three_roots():
    h = math.sqrt(3) / 2
    pts = [(0.0, 0.0), (1.0, 0.0), (0.5, h)]
    # assignment matching CCW order for paper formula
    L = full_tree_length_n(pts, [4, 2, 0])
    assert L is not None
    assert L == pytest.approx(full_tree_length_3(*pts), rel=0.05)
