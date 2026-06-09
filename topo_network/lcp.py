"""Least Cost Path по CostRaster (scikit-image)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np
from rasterio.transform import rowcol, xy
from skimage.graph import route_through_array

LCP_FORBIDDEN_COST = 1e12


@dataclass
class LcpPathResult:
    path_rc: list[tuple[int, int]]
    weight: float
    length_m: float


def world_to_cell(
    x_m: float,
    y_m: float,
    transform,
    *,
    shape: tuple[int, int],
) -> tuple[int, int] | None:
    """Мировые метры → (row, col); None если вне растра."""
    row, col = rowcol(transform, x_m, y_m)
    rows, cols = shape
    if row < 0 or col < 0 or row >= rows or col >= cols:
        return None
    return int(row), int(col)


def cell_to_world(row: int, col: int, transform) -> tuple[float, float]:
    """Центр ячейки (row, col) → (x_m, y_m)."""
    x, y = xy(transform, row, col, offset="center")
    return float(x), float(y)


def is_finite_cell(cost: np.ndarray, row: int, col: int) -> bool:
    value = cost[row, col]
    return np.isfinite(value) and not np.isinf(value)


def snap_to_finite_cell(
    row: int,
    col: int,
    cost: np.ndarray,
    *,
    max_radius: int = 5,
) -> tuple[int, int] | None:
    """BFS до ближайшей ячейки с finite cost."""
    rows, cols = cost.shape
    if is_finite_cell(cost, row, col):
        return row, col

    visited: set[tuple[int, int]] = set()
    queue: deque[tuple[int, int, int]] = deque([(row, col, 0)])

    while queue:
        r, c, dist = queue.popleft()
        if (r, c) in visited:
            continue
        visited.add((r, c))
        if dist > max_radius:
            continue
        if is_finite_cell(cost, r, c):
            return r, c
        for dr, dc in (
            (-1, 0),
            (1, 0),
            (0, -1),
            (0, 1),
            (-1, -1),
            (-1, 1),
            (1, -1),
            (1, 1),
        ):
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols and (nr, nc) not in visited:
                queue.append((nr, nc, dist + 1))
    return None


def prepare_lcp_array(
    cost: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """inf → LCP_FORBIDDEN_COST; возвращает (lcp_cost, forbidden_mask)."""
    forbidden = ~np.isfinite(cost) | np.isinf(cost)
    lcp_cost = np.where(forbidden, LCP_FORBIDDEN_COST, cost).astype(np.float64)
    return lcp_cost, forbidden


def path_length_m(
    path_rc: list[tuple[int, int]],
    cell_size_x: float,
    cell_size_y: float,
) -> float:
    """Геометрическая длина polyline по центрам ячеек."""
    if len(path_rc) < 2:
        return 0.0
    total = 0.0
    for (r0, c0), (r1, c1) in zip(path_rc[:-1], path_rc[1:]):
        dx = (c1 - c0) * cell_size_x
        dy = (r1 - r0) * cell_size_y
        total += float(np.hypot(dx, dy))
    return total


def path_weight(
    path_rc: list[tuple[int, int]],
    cost: np.ndarray,
    forbidden: np.ndarray,
) -> float | None:
    """Сумма cost по ячейкам пути; None если путь через forbidden."""
    total = 0.0
    for row, col in path_rc:
        if forbidden[row, col]:
            return None
        total += float(cost[row, col])
    return total


def least_cost_path(
    cost: np.ndarray,
    start_rc: tuple[int, int],
    end_rc: tuple[int, int],
    *,
    cell_size_x: float,
    cell_size_y: float,
) -> LcpPathResult | None:
    """LCP между двумя ячейками; None если маршрута нет."""
    if start_rc == end_rc:
        w = float(cost[start_rc[0], start_rc[1]])
        if not np.isfinite(w) or np.isinf(w):
            return None
        return LcpPathResult(path_rc=[start_rc], weight=w, length_m=0.0)

    lcp_cost, forbidden = prepare_lcp_array(cost)
    if forbidden[start_rc[0], start_rc[1]] or forbidden[end_rc[0], end_rc[1]]:
        return None

    try:
        indices, _sk_weight = route_through_array(
            lcp_cost,
            start_rc,
            end_rc,
            fully_connected=True,
        )
    except (ValueError, IndexError):
        return None

    path_rc = [(int(r), int(c)) for r, c in indices]
    weight = path_weight(path_rc, cost, forbidden)
    if weight is None:
        return None

    length_m = path_length_m(path_rc, cell_size_x, cell_size_y)
    return LcpPathResult(path_rc=path_rc, weight=weight, length_m=length_m)
