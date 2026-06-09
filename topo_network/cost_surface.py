"""Построение CostRaster из LocalScene (этап 2 / фаза 2)."""

from __future__ import annotations

import numpy as np
from rasterio.features import rasterize
from shapely.geometry import Point, mapping

from topo_network.models import CostRaster, LocalScene, ZoneRecord

INF = float("inf")


def cell_sizes_m(transform) -> tuple[float, float]:
    """Размер ячейки растра в метрах (|a|, |e| для north-up affine)."""
    return (abs(transform.a), abs(transform.e))


def compute_slope_deg(
    elevation: np.ndarray,
    cell_size_x: float,
    cell_size_y: float,
    *,
    nodata_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Уклон по центральным разностям; результат в градусах."""
    dy, dx = np.gradient(elevation, cell_size_y, cell_size_x)
    slope_rad = np.arctan(np.hypot(dx, dy))
    slope_deg = np.degrees(slope_rad)
    if nodata_mask is not None:
        slope_deg = np.where(nodata_mask, np.nan, slope_deg)
    return slope_deg


def _nodata_mask(elevation: np.ndarray, nodata: float | None) -> np.ndarray:
    if nodata is None:
        return ~np.isfinite(elevation)
    return ~np.isfinite(elevation) | (elevation == nodata)


def _base_cost(cell_size_x: float, cell_size_y: float) -> float:
    """Базовая cost одной ячейки ≈ средний шаг по сетке (м)."""
    return (cell_size_x + cell_size_y) / 2.0


def _slope_multiplier(
    slope_deg: np.ndarray,
    *,
    max_slope_deg: float,
    slope_cost_factor: float,
) -> np.ndarray:
    """Множитель cost от уклона: 1 … (1 + slope_cost_factor) к max_slope_deg."""
    if slope_cost_factor <= 0:
        return np.ones_like(slope_deg, dtype=np.float64)
    ratio = np.clip(slope_deg / max(max_slope_deg, 1e-6), 0.0, 1.0)
    return 1.0 + slope_cost_factor * ratio


def _rasterize_zones(
    zones: list[ZoneRecord],
    shape: tuple[int, int],
    transform,
) -> tuple[np.ndarray, np.ndarray]:
    """Маски ban (bool) и penalty (float multiplier, 1 вне зон)."""
    ban = np.zeros(shape, dtype=bool)
    penalty = np.ones(shape, dtype=np.float64)

    ban_shapes = [(mapping(z.geometry), 1) for z in zones if z.mode == "ban"]
    if ban_shapes:
        burned = rasterize(
            ban_shapes,
            out_shape=shape,
            transform=transform,
            fill=0,
            dtype=np.uint8,
        )
        ban |= burned.astype(bool)

    for zone in zones:
        if zone.mode != "penalty":
            continue
        burned = rasterize(
            [(mapping(zone.geometry), 1)],
            out_shape=shape,
            transform=transform,
            fill=0,
            dtype=np.uint8,
        )
        mask = burned.astype(bool)
        penalty[mask] *= zone.multiplier

    return ban, penalty


def _rasterize_corridors(
    corridors: list,
    shape: tuple[int, int],
    transform,
    buffer_m: float,
) -> np.ndarray:
    """Маска ячеек внутри буфера коридоров."""
    if not corridors:
        return np.zeros(shape, dtype=bool)
    buffered = [geom.buffer(buffer_m) for geom in corridors if geom is not None]
    if not buffered:
        return np.zeros(shape, dtype=bool)
    shapes = [(mapping(g), 1) for g in buffered]
    burned = rasterize(
        shapes,
        out_shape=shape,
        transform=transform,
        fill=0,
        dtype=np.uint8,
    )
    return burned.astype(bool)


def trace_exclusion_mask(
    shape: tuple[int, int],
    transform,
    trace_geometries: list,
    *,
    buffer_m: float,
    hub_points: list[tuple[float, float]] | None = None,
    hub_clearance_m: float = 25.0,
) -> np.ndarray:
    """
    Маска ячеек, где последующие трассы строить нельзя (буфер вокруг уже
    проложенных линий). hub_points — общие узлы (start), вокруг них «окно».
    """
    if buffer_m <= 0 or not trace_geometries:
        return np.zeros(shape, dtype=bool)

    shapes: list[tuple[dict, int]] = []
    for geom in trace_geometries:
        if geom is None or geom.is_empty:
            continue
        if geom.geom_type == "LineString":
            lines = [geom]
        elif geom.geom_type == "MultiLineString":
            lines = list(geom.geoms)
        else:
            continue
        for line in lines:
            shapes.append((mapping(line.buffer(buffer_m)), 1))

    if not shapes:
        return np.zeros(shape, dtype=bool)

    mask = rasterize(
        shapes,
        out_shape=shape,
        transform=transform,
        fill=0,
        dtype=np.uint8,
    ).astype(bool)

    if hub_points and hub_clearance_m > 0:
        hub_shapes = [
            (mapping(Point(x, y).buffer(hub_clearance_m)), 1)
            for x, y in hub_points
        ]
        hub_mask = rasterize(
            hub_shapes,
            out_shape=shape,
            transform=transform,
            fill=0,
            dtype=np.uint8,
        ).astype(bool)
        mask &= ~hub_mask

    return mask


def apply_trace_exclusion(
    cost: np.ndarray,
    transform,
    trace_geometries: list,
    *,
    buffer_m: float,
    hub_points: list[tuple[float, float]] | None = None,
    hub_clearance_m: float = 25.0,
) -> np.ndarray:
    """Cost с ∞ на буфере уже проложенных трасс (для следующих LCP)."""
    cost_out = np.copy(cost)
    mask = trace_exclusion_mask(
        cost.shape,
        transform,
        trace_geometries,
        buffer_m=buffer_m,
        hub_points=hub_points,
        hub_clearance_m=hub_clearance_m,
    )
    cost_out[mask] = INF
    return cost_out


def build_cost_raster(
    scene: LocalScene,
    *,
    max_slope_deg: float = 30.0,
    slope_cost_factor: float = 1.0,
) -> CostRaster:
    """
    LocalScene → CostRaster.

    Порядок наложения (этап 2):
    1. базовая cost = размер ячейки (м);
    2. множитель уклона + ban по max_slope_deg;
    3. nodata → ∞;
    4. зоны ban → ∞, penalty → ×multiplier;
    5. коридоры → ×corridor_cost_multiplier (поверх penalty).
    """
    elevation = np.asarray(scene.elevation, dtype=np.float64)
    shape = elevation.shape
    cell_x, cell_y = cell_sizes_m(scene.transform)
    nodata_mask = _nodata_mask(elevation, scene.nodata)

    slope_deg = compute_slope_deg(
        elevation, cell_x, cell_y, nodata_mask=nodata_mask
    )

    cost = np.full(shape, _base_cost(cell_x, cell_y), dtype=np.float64)
    cost *= _slope_multiplier(
        slope_deg,
        max_slope_deg=max_slope_deg,
        slope_cost_factor=slope_cost_factor,
    )
    cost[slope_deg > max_slope_deg] = INF
    cost[nodata_mask] = INF

    ban_mask, penalty_mask = _rasterize_zones(
        scene.zones, shape, scene.transform
    )
    cost[ban_mask] = INF
    cost *= penalty_mask

    corridor_mask = _rasterize_corridors(
        scene.corridors or [],
        shape,
        scene.transform,
        scene.corridor_buffer_m,
    )
    if corridor_mask.any():
        cost[corridor_mask & np.isfinite(cost)] *= scene.corridor_cost_multiplier

    return CostRaster(
        cost=cost,
        transform=scene.transform,
        crs=scene.crs_work,
        cell_size_m=(cell_x, cell_y),
        slope_deg=slope_deg,
        nodata_mask=nodata_mask,
    )
