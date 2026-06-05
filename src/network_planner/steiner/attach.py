"""Nearest attachment point on a Steiner tree (for connectors)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from network_planner.steiner.types import SteinerTreeResult


@dataclass(frozen=True)
class TreeAttachment:
    attach_to: str
    attach_kind: Literal["steiner", "edge"]
    point: tuple[float, float]
    length_m: float
    edge_endpoints: tuple[str, str] | None = None


def _project_on_segment(
    p: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> tuple[tuple[float, float], float, float]:
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    len2 = dx * dx + dy * dy
    if len2 < 1e-18:
        return a, math.hypot(px - ax, py - ay), 0.0
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len2))
    qx, qy = ax + t * dx, ay + t * dy
    return (qx, qy), math.hypot(px - qx, py - qy), t


def nearest_attachment(
    tree: SteinerTreeResult,
    pt: tuple[float, float],
    *,
    forbid_ids: set[str] | None = None,
) -> TreeAttachment:
    """
    Closest point on tree to pt. Never returns attach_to in forbid_ids (node/terminal ids).
    Prefers steiner:* vertices; otherwise a point on an edge (not at forbidden endpoint).
    """
    forbid = forbid_ids or set()

    best: TreeAttachment | None = None

    for sid, sp in tree.steiner_points.items():
        d = math.hypot(pt[0] - sp[0], pt[1] - sp[1])
        cand = TreeAttachment(
            attach_to=sid,
            attach_kind="steiner",
            point=sp,
            length_m=d,
        )
        if best is None or cand.length_m < best.length_m:
            best = cand

    for idx, (a, b, pta, ptb) in enumerate(tree.edges):
        proj, d, t = _project_on_segment(pt, pta, ptb)
        # Prefer steiner endpoint if projection snaps there
        if t <= 1e-9:
            target, tp = a, pta
        elif t >= 1.0 - 1e-9:
            target, tp = b, ptb
        else:
            target = f"edge:{a}:{b}"
            tp = proj
            cand = TreeAttachment(
                attach_to=target,
                attach_kind="edge",
                point=tp,
                length_m=d,
                edge_endpoints=(a, b),
            )
            if best is None or cand.length_m < best.length_m:
                best = cand
            continue

        if target in forbid or not target.startswith("steiner:"):
            target = f"edge:{a}:{b}"
            tp = proj
            cand = TreeAttachment(
                attach_to=target,
                attach_kind="edge",
                point=tp,
                length_m=d,
                edge_endpoints=(a, b),
            )
        else:
            cand = TreeAttachment(
                attach_to=target,
                attach_kind="steiner",
                point=tp,
                length_m=d,
            )
        if best is None or cand.length_m < best.length_m:
            best = cand

    if best is None:
        if tree.steiner_points:
            sid = next(iter(tree.steiner_points))
            sp = tree.steiner_points[sid]
            return TreeAttachment(sid, "steiner", sp, math.hypot(pt[0] - sp[0], pt[1] - sp[1]))
        raise ValueError("empty tree has no attachment point")

    return best
