"""Four-terminal full Euclidean Steiner tree (Uteshev 1505.03564)."""

from __future__ import annotations

import math

from network_planner.steiner.full_tree import full_tree_length_4_pairing
from network_planner.steiner.point3 import (
    Point2,
    _circumcenter_equilateral,
    _equilateral_outward,
    _line_circle_intersection,
)
from network_planner.steiner.types import SteinerTreeResult

SQRT3 = math.sqrt(3.0)


def _equilateral_third(p1: Point2, p2: Point2, opposite: Point2) -> Point2:
    return _equilateral_outward(p1, p2, opposite)


def _build_topology(
    ids: list[str],
    p: list[Point2],
    pair_a: tuple[int, int],
    pair_b: tuple[int, int],
) -> SteinerTreeResult | None:
    i1, i2 = pair_a
    j1, j2 = pair_b
    q1 = _equilateral_third(p[i1], p[i2], p[j1])
    q2 = _equilateral_third(p[j1], p[j2], p[i1])
    c1, r1 = _circumcenter_equilateral(p[i1], p[i2], q1)
    c2, r2 = _circumcenter_equilateral(p[j1], p[j2], q2)
    hits1 = _line_circle_intersection(q1, q2, c1, r1)
    hits2 = _line_circle_intersection(q1, q2, c2, r2)
    if not hits1 or not hits2:
        return None

    best_s1, best_s2, best_d = None, None, math.inf
    for s1 in hits1:
        for s2 in hits2:
            d = s1.dist(s2)
            if d < best_d:
                best_d = d
                best_s1, best_s2 = s1, s2
    if best_s1 is None or best_s2 is None:
        return None

    sid1, sid2 = "steiner:0", "steiner:1"
    length = (
        best_s1.dist(p[i1])
        + best_s1.dist(p[i2])
        + best_s2.dist(p[j1])
        + best_s2.dist(p[j2])
        + best_s1.dist(best_s2)
    )
    edges = [
        (ids[i1], sid1, (p[i1].x, p[i1].y), (best_s1.x, best_s1.y)),
        (ids[i2], sid1, (p[i2].x, p[i2].y), (best_s1.x, best_s1.y)),
        (ids[j1], sid2, (p[j1].x, p[j1].y), (best_s2.x, best_s2.y)),
        (ids[j2], sid2, (p[j2].x, p[j2].y), (best_s2.x, best_s2.y)),
        (sid1, sid2, (best_s1.x, best_s1.y), (best_s2.x, best_s2.y)),
    ]
    return SteinerTreeResult(
        edges=edges,
        steiner_points={sid1: (best_s1.x, best_s1.y), sid2: (best_s2.x, best_s2.y)},
        length_m=length,
    )


def steiner_tree_4(
    ids: list[str],
    points: list[tuple[float, float]],
) -> SteinerTreeResult:
    if len(ids) != 4 or len(points) != 4:
        raise ValueError("steiner_tree_4 requires exactly 4 terminals")
    p = [Point2(*pt) for pt in points]

    pairings = [
        ((0, 1), (2, 3)),
        ((0, 2), (1, 3)),
        ((0, 3), (1, 2)),
    ]

    best: SteinerTreeResult | None = None
    best_len = math.inf

    for pair_a, pair_b in pairings:
        len_est = full_tree_length_4_pairing(
            points[0], points[1], points[2], points[3], pairing=(pair_a, pair_b)
        )
        built = _build_topology(ids, p, pair_a, pair_b)
        if built is None:
            continue
        use_len = min(len_est, built.length_m)
        if use_len < best_len:
            best_len = built.length_m
            best = built

    if best is None:
        from network_planner.steiner.mst import mst_edges

        mst = mst_edges(points)
        edges = []
        total = 0.0
        for i, j, w in mst:
            edges.append((ids[i], ids[j], points[i], points[j]))
            total += w
        return SteinerTreeResult(edges=edges, length_m=total, heuristic=True)

    return best
