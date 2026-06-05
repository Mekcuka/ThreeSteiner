"""Collinear terminal sets and star-on-line construction."""

from __future__ import annotations

import math

from network_planner.steiner.types import SteinerTreeResult


def is_collinear(
    points: list[tuple[float, float]],
    *,
    tol_m: float = 1.0,
) -> bool:
    if len(points) < 3:
        return True
    x0, y0 = points[0]
    x1, y1 = points[1]
    dx, dy = x1 - x0, y1 - y0
    len2 = dx * dx + dy * dy
    if len2 < 1e-12:
        return True
    for x, y in points[2:]:
        cross = abs(dx * (y - y0) - dy * (x - x0))
        if cross / math.sqrt(len2) > tol_m:
            return False
    return True


def _median_on_line(points: list[tuple[float, float]]) -> tuple[float, float]:
    """1D median along principal axis."""
    if len(points) == 1:
        return points[0]
    x0, y0 = points[0]
    x1, y1 = points[-1]
    if len(points) == 2:
        return ((x0 + x1) / 2, (y0 + y1) / 2)
    dx, dy = x1 - x0, y1 - y0
    len2_sq = dx * dx + dy * dy
    if len2_sq < 1e-12:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return (sum(xs) / len(xs), sum(ys) / len(ys))
    ts = [((p[0] - x0) * dx + (p[1] - y0) * dy) / len2_sq for p in points]
    ts.sort()
    t_med = ts[len(ts) // 2]
    return (x0 + t_med * dx, y0 + t_med * dy)


def steiner_tree_collinear_star(
    ids: list[str],
    points: list[tuple[float, float]],
) -> SteinerTreeResult:
    """Each leaf connects once to a Steiner point on the line (median)."""
    s = _median_on_line(points)
    sid = "steiner:0"
    edges = []
    total = 0.0
    for i, pid in enumerate(ids):
        px, py = points[i]
        d = math.hypot(px - s[0], py - s[1])
        total += d
        edges.append((pid, sid, points[i], s))
    return SteinerTreeResult(
        edges=edges,
        steiner_points={sid: s},
        length_m=total,
    )
