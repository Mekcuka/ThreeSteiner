"""Star Steiner tree: one internal point, each leaf degree 1."""

from __future__ import annotations

import math

from network_planner.steiner.collinear import is_collinear, steiner_tree_collinear_star
from network_planner.steiner.types import SteinerTreeResult


def steiner_tree_star(
    ids: list[str],
    points: list[tuple[float, float]],
) -> SteinerTreeResult:
    """Connect all leaves to one Steiner point."""
    if is_collinear(points):
        return steiner_tree_collinear_star(ids, points)
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    s = (cx, cy)
    sid = "steiner:0"
    edges = []
    total = 0.0
    for pid, pt in zip(ids, points, strict=True):
        d = math.hypot(pt[0] - s[0], pt[1] - s[1])
        total += d
        edges.append((pid, sid, pt, s))
    return SteinerTreeResult(
        edges=edges,
        steiner_points={sid: s},
        length_m=total,
        heuristic=True,
    )
