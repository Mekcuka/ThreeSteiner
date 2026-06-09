"""Экспорт AdjustedTree в PlanResponse JSON (этап 6 / фаза 6)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import geopandas as gpd
from pyproj import Transformer
from shapely.geometry import Point, shape

from topo_network.models import AdjustedTreeResult, TerminalRecord

_WGS84 = "EPSG:4326"
_transformers: dict[str, Transformer] = {}


def _get_transformer(crs_work: str) -> Transformer:
    if crs_work not in _transformers:
        _transformers[crs_work] = Transformer.from_crs(
            crs_work,
            _WGS84,
            always_xy=True,
        )
    return _transformers[crs_work]


def meters_to_wgs84(
    x_m: float,
    y_m: float,
    crs_work: str,
) -> tuple[float, float]:
    """Локальные метры → (lon, lat) WGS84."""
    lon, lat = _get_transformer(crs_work).transform(x_m, y_m)
    return float(lon), float(lat)


def _linestring_to_geojson(
    geometry: Any,
    crs_work: str,
) -> dict[str, Any]:
    if geometry is None or geometry.is_empty:
        return {"type": "LineString", "coordinates": []}
    coords = []
    for x, y in geometry.coords:
        lon, lat = meters_to_wgs84(x, y, crs_work)
        coords.append([lon, lat])
    return {"type": "LineString", "coordinates": coords}


def build_plan_response(
    adjusted: AdjustedTreeResult,
    *,
    project_id: str,
    mode: str,
    solver: str,
    terminals: list[TerminalRecord],
    crs_work: str,
    metrics_extra: dict[str, float] | None = None,
    source_warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Собрать PlanResponse (GeoJSON в WGS84)."""
    edge_records: list[dict[str, Any]] = []
    for edge in adjusted.edges:
        edge_records.append(
            {
                "from": edge.u,
                "to": edge.v,
                "length_m": round(edge.length_m, 3),
                "cost": round(edge.weight, 3),
                "geometry": _linestring_to_geojson(edge.geometry, crs_work),
            }
        )

    steiner_points: list[dict[str, Any]] = []
    for node_id, node in adjusted.nodes.items():
        if node.kind == "terminal":
            continue
        lon, lat = meters_to_wgs84(node.x_m, node.y_m, crs_work)
        steiner_points.append({"id": node_id, "lon": lon, "lat": lat})

    terminal_records: list[dict[str, Any]] = []
    for attachment in adjusted.attachments:
        terminal_records.append(
            {
                "id": attachment.terminal_id,
                "role": attachment.role,
                "attached_to": attachment.attached_to,
                "via": attachment.via,
            }
        )

    metrics: dict[str, float] = {
        "total_length_m": round(adjusted.total_length_m, 3),
        "total_cost": round(adjusted.total_weight, 3),
    }
    if metrics_extra:
        for key, value in metrics_extra.items():
            metrics[key] = round(float(value), 3)

    warnings = list(source_warnings or []) + list(adjusted.warnings)
    seen: set[str] = set()
    unique_warnings: list[str] = []
    for warning in warnings:
        if warning not in seen:
            seen.add(warning)
            unique_warnings.append(warning)

    return {
        "project_id": project_id,
        "mode": mode,
        "solver": solver,
        "warnings": unique_warnings,
        "metrics": metrics,
        "network_tree": {
            "edges": edge_records,
            "steiner_points": steiner_points,
        },
        "terminals": terminal_records,
    }


def write_plan_response(path: str | Path, response: dict[str, Any]) -> None:
    """Записать PlanResponse в JSON (UTF-8)."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(response, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _node_coords_from_response(response: dict[str, Any]) -> dict[str, tuple[float, float]]:
    """Собрать lon/lat узлов из steiner_points и концов рёбер."""
    coords: dict[str, tuple[float, float]] = {}
    for point in response.get("network_tree", {}).get("steiner_points", []):
        coords[str(point["id"])] = (float(point["lon"]), float(point["lat"]))
    for edge in response.get("network_tree", {}).get("edges", []):
        geom = edge.get("geometry") or {}
        line_coords = geom.get("coordinates") or []
        if len(line_coords) < 2:
            continue
        start = (float(line_coords[0][0]), float(line_coords[0][1]))
        end = (float(line_coords[-1][0]), float(line_coords[-1][1]))
        coords.setdefault(str(edge["from"]), start)
        coords.setdefault(str(edge["to"]), end)
    return coords


def export_plan_response_gpkg(
    path: str | Path,
    response: dict[str, Any],
    *,
    crs: str = "EPSG:4326",
) -> None:
    """Записать PlanResponse в GeoPackage (слои edges, steiner_points, terminals)."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    project_id = str(response.get("project_id", ""))
    mode = str(response.get("mode", ""))
    solver = str(response.get("solver", ""))
    node_coords = _node_coords_from_response(response)

    edge_rows: list[dict[str, Any]] = []
    for edge in response.get("network_tree", {}).get("edges", []):
        geom = edge.get("geometry")
        if not geom:
            continue
        edge_rows.append(
            {
                "project_id": project_id,
                "mode": mode,
                "solver": solver,
                "from_id": edge.get("from"),
                "to_id": edge.get("to"),
                "length_m": edge.get("length_m"),
                "cost": edge.get("cost"),
                "geometry": shape(geom),
            }
        )
    if edge_rows:
        gpd.GeoDataFrame(edge_rows, crs=crs).to_file(out, layer="network_edges", driver="GPKG")

    steiner_rows: list[dict[str, Any]] = []
    for point in response.get("network_tree", {}).get("steiner_points", []):
        steiner_rows.append(
            {
                "project_id": project_id,
                "node_id": point.get("id"),
                "lon": point.get("lon"),
                "lat": point.get("lat"),
                "geometry": Point(float(point["lon"]), float(point["lat"])),
            }
        )
    if steiner_rows:
        gpd.GeoDataFrame(steiner_rows, crs=crs).to_file(
            out,
            layer="steiner_points",
            driver="GPKG",
        )

    terminal_rows: list[dict[str, Any]] = []
    for terminal in response.get("terminals", []):
        node_id = f"terminal:{terminal['id']}"
        coords = node_coords.get(node_id)
        if coords is None:
            continue
        terminal_rows.append(
            {
                "project_id": project_id,
                "terminal_id": terminal.get("id"),
                "role": terminal.get("role"),
                "attached_to": terminal.get("attached_to"),
                "via": terminal.get("via"),
                "geometry": Point(coords[0], coords[1]),
            }
        )
    if terminal_rows:
        gpd.GeoDataFrame(terminal_rows, crs=crs).to_file(
            out,
            layer="terminals",
            driver="GPKG",
        )
