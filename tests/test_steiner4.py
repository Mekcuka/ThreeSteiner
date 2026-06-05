import math

import pytest

from network_planner.steiner.full_tree import full_tree_length_4_pairing
from network_planner.steiner.mst import mst_edges
from network_planner.steiner.point4 import steiner_tree_4


def test_paper_example_four_terminals():
    """Example 3.1 from 1505.03564 — length sqrt(115 + 62*sqrt(3))."""
    pts = [(2.0, 6.0), (1.0, 1.0), (9.0, 2.0), (6.0, 7.0)]
    expected = math.sqrt(115 + 62 * math.sqrt(3))
    est = full_tree_length_4_pairing(*pts, pairing=((0, 1), (2, 3)))
    assert est == pytest.approx(expected, rel=0.02)
    tree = steiner_tree_4(["p1", "p2", "p3", "p4"], pts)
    assert tree.length_m == pytest.approx(expected, rel=0.05)
    assert len(tree.steiner_points) == 2


def test_four_points_better_than_mst():
    pts = [(0, 0), (10, 0), (10, 10), (0, 10)]
    tree = steiner_tree_4(["a", "b", "c", "d"], pts)
    mst_len = sum(w for _, _, w in mst_edges(pts))
    assert tree.length_m <= mst_len * 1.001
