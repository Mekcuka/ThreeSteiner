"""Three-terminal Euclidean Steiner tree (Uteshev 1505.03564 / Fermat-Torricelli)."""

from __future__ import annotations

import math
from dataclasses import dataclass

from network_planner.steiner.types import SteinerTreeResult

SQRT3 = math.sqrt(3.0)


@dataclass(frozen=True)
class Point2:
    x: float
    y: float

    def dist(self, other: Point2) -> float:
        return math.hypot(self.x - other.x, self.y - other.y)


def _angle_at(p: Point2, a: Point2, b: Point2) -> float:
    """Angle APB in radians."""
    v1 = (a.x - p.x, a.y - p.y)
    v2 = (b.x - p.x, b.y - p.y)
    n1 = math.hypot(*v1)
    n2 = math.hypot(*v2)
    if n1 < 1e-12 or n2 < 1e-12:
        return math.pi
    cos_a = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
    return math.acos(cos_a)


def _triangle_area2(p1: Point2, p2: Point2, p3: Point2) -> float:
    return abs(
        (p2.x - p1.x) * (p3.y - p1.y) - (p3.x - p1.x) * (p2.y - p1.y)
    )


def _steiner_point_analytic(p1: Point2, p2: Point2, p3: Point2) -> Point2 | None:
    """Theorem 2.1 when all angles < 120°."""
    r12 = p1.dist(p2)
    r13 = p1.dist(p3)
    r23 = p2.dist(p3)
    c12 = r12 * r12 + r13 * r13 - r23 * r23
    c23 = r23 * r23 + r12 * r12 - r13 * r13
    c13 = r13 * r13 + r23 * r23 - r12 * r12
    if c12 <= 0 or c23 <= 0 or c13 <= 0:
        return None

    area2 = _triangle_area2(p1, p2, p3)
    s = area2  # doubled area in determinant sense; |S| = area2 for formula
    k1 = SQRT3 / 2 * (r12 * r12 + r13 * r13 - r23 * r23) + s
    k2 = SQRT3 / 2 * (r23 * r23 + r12 * r12 - r13 * r13) + s
    k3 = SQRT3 / 2 * (r13 * r13 + r23 * r23 - r12 * r12) + s
    denom = 2 * SQRT3 * s * s
    if denom < 1e-18:
        return None
    sx = k1 * k2 * k3 / denom * (p1.x / k1 + p2.x / k2 + p3.x / k3)
    sy = k1 * k2 * k3 / denom * (p1.y / k1 + p2.y / k2 + p3.y / k3)
    return Point2(sx, sy)


def _equilateral_outward(p1: Point2, p2: Point2, p3: Point2) -> Point2:
    """Third vertex of equilateral on p1-p2, opposite side from p3."""
    mx = (p1.x + p2.x) / 2
    my = (p1.y + p2.y) / 2
    dx = p2.x - p1.x
    dy = p2.y - p1.y
    # rotate 90° CCW and scale by sqrt(3)/2 for equilateral height
    qx = mx - SQRT3 / 2 * dy
    qy = my + SQRT3 / 2 * dx
    q = Point2(qx, qy)
    # flip if on same side as p3
    cross = (p2.x - p1.x) * (p3.y - p1.y) - (p2.y - p1.y) * (p3.x - p1.x)
    cross_q = (p2.x - p1.x) * (q.y - p1.y) - (p2.y - p1.y) * (q.x - p1.x)
    if cross * cross_q > 0:
        qx = mx + SQRT3 / 2 * dy
        qy = my - SQRT3 / 2 * dx
        q = Point2(qx, qy)
    return q


def _line_circle_intersection(
    line_a: Point2, line_b: Point2, center: Point2, radius: float
) -> list[Point2]:
    """Intersection of segment AB extended line with circle."""
    dx = line_b.x - line_a.x
    dy = line_b.y - line_a.y
    fx = line_a.x - center.x
    fy = line_a.y - center.y
    a = dx * dx + dy * dy
    if a < 1e-18:
        return []
    b = 2 * (fx * dx + fy * dy)
    c = fx * fx + fy * fy - radius * radius
    disc = b * b - 4 * a * c
    if disc < 0:
        return []
    sd = math.sqrt(disc)
    out: list[Point2] = []
    for t in ((-b - sd) / (2 * a), (-b + sd) / (2 * a)):
        out.append(Point2(line_a.x + t * dx, line_a.y + t * dy))
    return out


def _circumcenter_equilateral(p1: Point2, p2: Point2, q: Point2) -> tuple[Point2, float]:
    cx = (p1.x + p2.x + q.x) / 3
    cy = (p1.y + p2.y + q.y) / 3
    center = Point2(cx, cy)
    return center, center.dist(p1)


def _steiner_simpson(p1: Point2, p2: Point2, p3: Point2) -> Point2:
    q = _equilateral_outward(p1, p2, p3)
    center, radius = _circumcenter_equilateral(p1, p2, q)
    hits = _line_circle_intersection(q, p3, center, radius)
    if not hits:
        analytic = _steiner_point_analytic(p1, p2, p3)
        if analytic is not None:
            return analytic
        return Point2((p1.x + p2.x + p3.x) / 3, (p1.y + p2.y + p3.y) / 3)
    return min(
        hits,
        key=lambda h: h.dist(p1) + h.dist(p2) + h.dist(p3),
    )


def steiner_tree_3(
    ids: list[str],
    points: list[tuple[float, float]],
) -> SteinerTreeResult:
    if len(ids) != 3 or len(points) != 3:
        raise ValueError("steiner_tree_3 requires exactly 3 terminals")
    p1 = Point2(*points[0])
    p2 = Point2(*points[1])
    p3 = Point2(*points[2])

    angles = (
        _angle_at(p1, p2, p3),
        _angle_at(p2, p1, p3),
        _angle_at(p3, p1, p2),
    )
    two_pi_3 = 2 * math.pi / 3
    for i, ang in enumerate(angles):
        if ang >= two_pi_3 - 1e-9:
            # obtuse: still one edge per leaf via Steiner star on line
            from network_planner.steiner.collinear import steiner_tree_collinear_star

            return steiner_tree_collinear_star(
                ids, [(p1.x, p1.y), (p2.x, p2.y), (p3.x, p3.y)]
            )

    s = _steiner_simpson(p1, p2, p3)
    sid = "steiner:0"
    edges = [
        (ids[0], sid, points[0], (s.x, s.y)),
        (ids[1], sid, points[1], (s.x, s.y)),
        (ids[2], sid, points[2], (s.x, s.y)),
    ]
    length = p1.dist(s) + p2.dist(s) + p3.dist(s)
    return SteinerTreeResult(
        edges=edges,
        steiner_points={sid: (s.x, s.y)},
        length_m=length,
    )
