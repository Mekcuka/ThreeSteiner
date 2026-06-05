"""Validate leaf degree in Steiner trees."""

from __future__ import annotations


def vertex_degrees(
    edges: list[tuple[str, str, tuple[float, float], tuple[float, float]]],
) -> dict[str, int]:
    deg: dict[str, int] = {}
    for a, b, _, _ in edges:
        deg[a] = deg.get(a, 0) + 1
        deg[b] = deg.get(b, 0) + 1
    return deg


def leaf_degree_violations(
    edges: list[tuple[str, str, tuple[float, float], tuple[float, float]]],
    leaf_ids: set[str],
    *,
    max_degree: int = 1,
) -> dict[str, int]:
    """Return leaf ids with degree > max_degree."""
    deg = vertex_degrees(edges)
    return {
        vid: deg[vid]
        for vid in leaf_ids
        if deg.get(vid, 0) > max_degree
    }
