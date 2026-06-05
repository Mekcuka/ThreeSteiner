"""Minimum spanning tree (Prim) for terminal indices."""

from __future__ import annotations

import math


def mst_edges(
    points: list[tuple[float, float]],
) -> list[tuple[int, int, float]]:
    """Return undirected MST edges (i, j, length) with i < j."""
    n = len(points)
    if n < 2:
        return []
    in_tree = [False] * n
    dist = [math.inf] * n
    parent = [-1] * n
    dist[0] = 0.0
    edges: list[tuple[int, int, float]] = []

    for _ in range(n):
        u = min((i for i in range(n) if not in_tree[i]), key=lambda i: dist[i])
        in_tree[u] = True
        if parent[u] >= 0:
            v = parent[u]
            w = math.hypot(
                points[u][0] - points[v][0],
                points[u][1] - points[v][1],
            )
            edges.append((min(u, v), max(u, v), w))
        for v in range(n):
            if in_tree[v]:
                continue
            w = math.hypot(
                points[u][0] - points[v][0],
                points[u][1] - points[v][1],
            )
            if w < dist[v]:
                dist[v] = w
                parent[v] = u

    return edges
