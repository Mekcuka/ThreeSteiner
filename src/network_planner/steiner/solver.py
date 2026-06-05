"""Orchestrate Euclidean Steiner tree for n terminals."""

from __future__ import annotations

import math

from network_planner.steiner.attach import nearest_attachment
from network_planner.steiner.collinear import is_collinear, steiner_tree_collinear_star
from network_planner.steiner.point3 import steiner_tree_3
from network_planner.steiner.point4 import steiner_tree_4
from network_planner.steiner.star import steiner_tree_star
from network_planner.steiner.types import SteinerTreeResult


def solve_steiner_tree(
    ids: list[str],
    points: list[tuple[float, float]],
) -> SteinerTreeResult:
    """Build Steiner tree connecting all leaves (each degree 1) in the plane."""
    n = len(ids)
    if n != len(points):
        raise ValueError("ids and points length mismatch")
    if n < 2:
        raise ValueError("need at least 2 terminals")
    if n == 2:
        w = math.hypot(points[0][0] - points[1][0], points[0][1] - points[1][1])
        return SteinerTreeResult(
            edges=[(ids[0], ids[1], points[0], points[1])],
            length_m=w,
        )
    if is_collinear(points):
        return steiner_tree_collinear_star(ids, points)
    if n == 3:
        return steiner_tree_3(ids, points)
    if n == 4:
        return steiner_tree_4(ids, points)
    return _solve_n_ge_5(ids, points)


def _solve_n_ge_5(ids: list[str], points: list[tuple[float, float]]) -> SteinerTreeResult:
    n = len(ids)
    if n == 5:
        best: SteinerTreeResult | None = None
        best_len = math.inf
        leaf_set = set(ids)
        for solo in range(5):
            rest = [i for i in range(5) if i != solo]
            t4 = steiner_tree_4(
                [ids[i] for i in rest],
                [points[i] for i in rest],
            )
            solo_id = ids[solo]
            solo_pt = points[solo]
            att = nearest_attachment(t4, solo_pt, forbid_ids=leaf_set)
            total = t4.length_m + att.length_m
            if total < best_len:
                edges = list(t4.edges) + [
                    (solo_id, att.attach_to, solo_pt, att.point),
                ]
                best_len = total
                best = SteinerTreeResult(
                    edges=edges,
                    steiner_points=dict(t4.steiner_points),
                    length_m=total,
                    heuristic=t4.heuristic,
                )
        if best:
            return best

    return steiner_tree_star(ids, points)
