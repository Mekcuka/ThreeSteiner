"""Геометрические ban/penalty для mode euclid (без DEM).

Ограничения:
- коридоры и slope-cost только в mode full;
- penalty — аппроксимация сэмплированием, не pixel-perfect LCP;
- перекрывающиеся penalty-зоны: product multipliers в точке (как на растре).
"""

from __future__ import annotations

from typing import Any

from shapely.geometry import LineString, Point

from topo_network.lcp import LCP_FORBIDDEN_COST
from topo_network.models import ZoneRecord

EUCLID_PENALTY_SAMPLE_M = 2.0


def zone_terminal_ban_geometry(zone: ZoneRecord, *, allow_in_buffer: bool) -> Any:
    """Геометрия ban для проверки положения терминала (core или effective)."""
    if allow_in_buffer and zone.geometry_core is not None:
        return zone.geometry_core
    return zone.geometry
EUCLID_BAN_FORBIDDEN_WEIGHT = LCP_FORBIDDEN_COST


def edge_blocked_by_ban(
    line: LineString,
    ban_zones: list[ZoneRecord],
    *,
    eps_m: float = 1e-3,
) -> bool:
    """True, если отрезок пересекает interior ban-полигона (не только точку касания)."""
    if not ban_zones:
        return False
    for zone in ban_zones:
        if zone.mode != "ban":
            continue
        if not line.intersects(zone.geometry):
            continue
        inter = line.intersection(zone.geometry)
        if inter.is_empty:
            continue
        if inter.geom_type == "Point":
            continue
        if inter.geom_type in ("Polygon", "MultiPolygon"):
            return True
        if getattr(inter, "length", 0.0) > eps_m:
            return True
    return False


def _point_penalty_multiplier(point: Point, penalty_zones: list[ZoneRecord]) -> float:
    mult = 1.0
    for zone in penalty_zones:
        if zone.mode != "penalty":
            continue
        if zone.geometry.contains(point) or zone.geometry.touches(point):
            mult *= zone.multiplier
    return mult


def penalized_edge_weight(
    line: LineString,
    penalty_zones: list[ZoneRecord],
    *,
    sample_m: float = EUCLID_PENALTY_SAMPLE_M,
) -> float:
    """Интеграл cost вдоль отрезка: weight >= length_m при penalty-зонах."""
    length_m = float(line.length)
    if length_m <= 0.0:
        return 0.0
    if not penalty_zones:
        return length_m

    step = max(sample_m, 1.0)
    n = max(2, int(length_m / step) + 1)
    total = 0.0
    prev_d = 0.0
    prev_mult = _point_penalty_multiplier(line.interpolate(0.0), penalty_zones)
    for i in range(1, n):
        d = length_m * i / (n - 1)
        pt = line.interpolate(d)
        mult = _point_penalty_multiplier(pt, penalty_zones)
        seg_len = d - prev_d
        total += seg_len * (prev_mult + mult) / 2.0
        prev_d = d
        prev_mult = mult
    return float(total)


def euclid_edge_weights(
    line: LineString,
    ban_zones: list[ZoneRecord],
    penalty_zones: list[ZoneRecord],
    *,
    penalty_sample_m: float | None = None,
) -> tuple[float, float, bool]:
    """(weight, length_m, crosses_ban) для euclid-ребра."""
    length_m = float(line.length)
    if ban_zones and edge_blocked_by_ban(line, ban_zones):
        return EUCLID_BAN_FORBIDDEN_WEIGHT, length_m, True
    if penalty_zones:
        kwargs = (
            {"sample_m": penalty_sample_m}
            if penalty_sample_m is not None
            else {}
        )
        return penalized_edge_weight(line, penalty_zones, **kwargs), length_m, False
    return length_m, length_m, False
