import math

import pytest

from network_planner.steiner.full_tree import full_tree_length_3
from network_planner.steiner.mst import mst_edges
from network_planner.steiner.point3 import steiner_tree_3


def test_equilateral_triangle_steiner_length():
    # Unit equilateral triangle side 1
    h = math.sqrt(3) / 2
    pts = [(0.0, 0.0), (1.0, 0.0), (0.5, h)]
    ids = ["a", "b", "c"]
    tree = steiner_tree_3(ids, pts)
    # Classic: length sqrt(3) for unit equilateral
    assert tree.length_m == pytest.approx(math.sqrt(3), rel=0.02)
    assert len(tree.steiner_points) == 1


def test_full_tree_length_3_matches():
    h = math.sqrt(3) / 2
    pts = [(0.0, 0.0), (1.0, 0.0), (0.5, h)]
    L = full_tree_length_3(*pts)
    assert L == pytest.approx(math.sqrt(3), rel=0.01)


def test_steiner_shorter_than_mst():
    h = math.sqrt(3) / 2
    pts = [(0.0, 0.0), (1.0, 0.0), (0.5, h)]
    tree = steiner_tree_3(["a", "b", "c"], pts)
    mst_len = sum(w for _, _, w in mst_edges(pts))
    assert tree.length_m < mst_len

