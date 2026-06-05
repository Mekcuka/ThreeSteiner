import pytest

from network_planner.steiner.collinear import is_collinear, steiner_tree_collinear_star
from network_planner.steiner.solver import solve_steiner_tree
from network_planner.steiner.validate import leaf_degree_violations


def test_collinear_four_nodes_star():
    pts = [(0.0, 0.0), (400.0, 0.0), (800.0, 0.0), (1200.0, 0.0)]
    ids = ["a", "b", "c", "d"]
    tree = solve_steiner_tree(ids, pts)
    assert is_collinear(pts)
    assert not leaf_degree_violations(tree.edges, set(ids))
    assert len(tree.steiner_points) >= 1
    # leaf-only star on line: min sum of distances to median (not span)
    assert tree.length_m == pytest.approx(1600.0, rel=0.05)


def test_three_collinear_each_degree_one():
    pts = [(-400.0, 0.0), (0.0, 0.0), (400.0, 0.0)]
    tree = steiner_tree_collinear_star(["a", "b", "c"], pts)
    assert not leaf_degree_violations(tree.edges, {"a", "b", "c"})


def test_four_non_collinear_leaves():
    pts = [(0, 0), (10, 0), (10, 10), (0, 10)]
    tree = solve_steiner_tree(["a", "b", "c", "d"], pts)
    assert not leaf_degree_violations(tree.edges, set("abcd"))

