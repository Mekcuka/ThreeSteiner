"""PlanRequest loader L0–L9 → LocalScene (этап 7)."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import rasterio
from pyproj import CRS, Transformer
from rasterio.transform import Affine
from rasterio.windows import from_bounds, transform as window_transform
from rasterio.warp import calculate_default_transform, reproject, Resampling
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform, unary_union

from topo_network.models import LocalScene, PostProcessOptions, TerminalRecord, ZoneRecord
from topo_network.validation import validate_terminal_roles
from topo_network.zone_categories import resolve_penalty_multiplier

try:
    import pyproj as _pyproj

    os.environ["PROJ_LIB"] = _pyproj.datadir.get_data_dir()
except Exception:
    pass

_WGS84 = "EPSG:4326"


class PlanRequestError(Exception):
    """Ошибка загрузки PlanRequest (HTTP 422)."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int = 422,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status

    def to_dict(self) -> dict[str, Any]:
        return {
            "errors": [{"code": self.code, "message": self.message}],
        }


@dataclass
class PlanOptions:
    """Параметры расчёта из PlanRequest.options + terrain."""

    # Солвер Steiner-дерева: steinerpy (MIP) или nx_approx (приближение)
    solver: str = "steinerpy"
    # mode full: уклон выше → cost = ∞ на растре
    max_slope_deg: float = 30.0
    # mode full: плавное удорожание до max_slope_deg (0 = только жёсткий порог)
    slope_cost_factor: float = 1.0
    # Макс. число терминалов; иначе preflight 422 too_many_terminals
    max_points: int = 50
    # mode full: шаг subsample сетки DEM (меньше → плотнее граф, медленнее)
    candidate_stride_cells: int = 8
    # Буфер bbox вокруг терминалов (км): clip DEM (full) / рамка visibility (euclid)
    clip_buffer_km: float = 0.5
    # mode full: ширина буфера линии коридора при rasterize (м)
    corridor_buffer_m: float = 15.0
    # mode euclid: obstacle — visibility вокруг ban; direct — прямые рёбра
    euclid_routing: str = "obstacle"
    # mode euclid: доп. буфер ban-полигона перед углами obstacle:* (м)
    obstacle_buffer_m: float = 0.1
    # mode euclid: GeoSteiner efst|bb → узлы steiner:candidate:* (без бинарников — warning)
    euclid_steiner_candidates: bool = True
    # Каталог с efst/bb; None → env GEOSTEINER_HOME или PATH
    geosteiner_home: str | None = None
    # Мин. расстояние между Steiner-кандидатами и узлами visibility (м)
    steiner_candidate_spacing_m: float = 1.0
    # true: терминал допустим в кольце zones[].buffer_m; preflight по geometry_core
    allow_terminal_in_zone_buffer: bool = False
    # Hub, attach, repel, waypoint — см. PostProcessOptions в models.py
    post_process: PostProcessOptions = field(default_factory=PostProcessOptions)


@dataclass
class LoadContext:
    request: dict[str, Any]
    base_dir: Path
    mode: str
    project_id: str
    crs_work: str | None = None
    terminals_wgs84: list[dict[str, Any]] = field(default_factory=list)
    terminals: list[TerminalRecord] = field(default_factory=list)
    options: PlanOptions | None = None


def _resolve_path(base_dir: Path, path_str: str) -> Path:
    path = Path(path_str)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def load_plan_request(source: str | Path | dict[str, Any]) -> tuple[dict[str, Any], Path | None]:
    """L0 — разбор JSON PlanRequest."""
    base_dir: Path | None = None
    if isinstance(source, dict):
        request = source
    else:
        path = Path(source)
        if not path.is_file():
            raise PlanRequestError(
                "invalid_request",
                f"plan request file not found: {path}",
            )
        base_dir = path.parent.resolve()
        try:
            request = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PlanRequestError(
                "invalid_request",
                f"invalid JSON: {exc}",
            ) from exc

    if not isinstance(request, dict):
        raise PlanRequestError("invalid_request", "root must be a JSON object")

    for key in ("project_id", "mode", "terminals"):
        if key not in request:
            raise PlanRequestError("invalid_request", f"missing required field: {key}")

    if not isinstance(request["terminals"], list):
        raise PlanRequestError("invalid_request", "terminals must be a list")

    if len(request["terminals"]) < 2:
        raise PlanRequestError("invalid_request", "need at least 2 terminals")

    for idx, raw in enumerate(request["terminals"]):
        if not isinstance(raw, dict):
            raise PlanRequestError(
                "invalid_request",
                f"terminal[{idx}] must be an object",
            )
        _parse_terminal_outgoing(raw, idx)

    mode = request["mode"]
    if mode not in ("full", "euclid"):
        raise PlanRequestError("invalid_request", f"unsupported mode: {mode!r}")

    if mode == "full" and "terrain" not in request:
        raise PlanRequestError(
            "terrain_required",
            "mode full requires terrain block",
        )

    if mode == "euclid" and "terrain" in request:
        _validate_euclid_terrain(request["terrain"])

    return request, base_dir


def _validate_euclid_terrain(terrain: Any) -> None:
    """В euclid допустим только terrain.zones (без DEM и коридоров)."""
    if not isinstance(terrain, dict):
        raise PlanRequestError("invalid_request", "terrain must be an object")
    if terrain.get("elevation_raster"):
        raise PlanRequestError(
            "invalid_request",
            "elevation_raster is not supported in mode euclid; use mode full",
        )
    for key in ("corridors",):
        if key in terrain:
            raise PlanRequestError(
                "invalid_request",
                f"terrain.{key} is not supported in mode euclid",
            )


def _parse_terminal_outgoing(
    raw: dict[str, Any],
    idx: int,
) -> tuple[float | None, float | None]:
    outgoing = raw.get("outgoing")
    if outgoing is None:
        return None, None
    if not isinstance(outgoing, dict):
        raise PlanRequestError(
            "invalid_request",
            f"terminal[{idx}] outgoing must be an object",
        )
    has_bearing = "bearing_deg" in outgoing
    has_length = "length_m" in outgoing
    if has_bearing != has_length:
        raise PlanRequestError(
            "invalid_request",
            f"terminal[{idx}] outgoing requires both bearing_deg and length_m",
        )
    try:
        bearing_deg = float(outgoing["bearing_deg"])
        length_m = float(outgoing["length_m"])
    except (TypeError, ValueError) as exc:
        raise PlanRequestError(
            "invalid_request",
            f"terminal[{idx}] invalid outgoing bearing_deg/length_m",
        ) from exc
    if length_m <= 0:
        raise PlanRequestError(
            "invalid_request",
            f"terminal[{idx}] outgoing length_m must be positive",
        )
    return bearing_deg, length_m


def load_terminals_wgs84(request: dict[str, Any]) -> list[dict[str, Any]]:
    """L1 — терминалы в WGS84 (lon/lat)."""
    terminals: list[dict[str, Any]] = []
    for idx, raw in enumerate(request["terminals"]):
        if not isinstance(raw, dict):
            raise PlanRequestError("invalid_request", f"terminal[{idx}] must be object")
        for key in ("id", "role", "lon", "lat"):
            if key not in raw:
                raise PlanRequestError(
                    "invalid_request",
                    f"terminal[{idx}] missing {key}",
                )
        try:
            lon = float(raw["lon"])
            lat = float(raw["lat"])
        except (TypeError, ValueError) as exc:
            raise PlanRequestError(
                "invalid_request",
                f"terminal[{idx}] invalid lon/lat",
            ) from exc
        outgoing_bearing_deg, outgoing_length_m = _parse_terminal_outgoing(raw, idx)
        terminals.append(
            {
                "id": str(raw["id"]),
                "role": str(raw["role"]),
                "lon": lon,
                "lat": lat,
                "attachment_max_km": raw.get("attachment_max_km"),
                "outgoing_bearing_deg": outgoing_bearing_deg,
                "outgoing_length_m": outgoing_length_m,
            }
        )

    records = [
        TerminalRecord(
            t["id"],
            0.0,
            0.0,
            t["role"],
            outgoing_bearing_deg=t.get("outgoing_bearing_deg"),
            outgoing_length_m=t.get("outgoing_length_m"),
        )
        for t in terminals
    ]
    role_check = validate_terminal_roles(records)
    if not role_check.ok:
        raise PlanRequestError(
            role_check.error_codes[0],
            role_check.errors[0].message,
        )
    return terminals


def _utm_epsg_from_lonlat(lon: float, lat: float) -> str:
    zone = int((lon + 180.0) / 6.0) + 1
    if lat >= 0:
        return f"EPSG:{32600 + zone}"
    return f"EPSG:{32700 + zone}"


def resolve_crs_work(
    request: dict[str, Any],
    terminals_wgs84: list[dict[str, Any]],
) -> str:
    """L2 — рабочая CRS в метрах."""
    terrain = request.get("terrain") or {}
    raster_spec = terrain.get("elevation_raster") or {}
    raster_crs = raster_spec.get("crs")

    if raster_crs:
        crs = CRS.from_user_input(raster_crs)
        if crs.is_geographic:
            lon = sum(t["lon"] for t in terminals_wgs84) / len(terminals_wgs84)
            lat = sum(t["lat"] for t in terminals_wgs84) / len(terminals_wgs84)
            return _utm_epsg_from_lonlat(lon, lat)
        return crs.to_string()

    lon = sum(t["lon"] for t in terminals_wgs84) / len(terminals_wgs84)
    lat = sum(t["lat"] for t in terminals_wgs84) / len(terminals_wgs84)
    return _utm_epsg_from_lonlat(lon, lat)


def project_terminals(
    terminals_wgs84: list[dict[str, Any]],
    crs_work: str,
) -> list[TerminalRecord]:
    """L3 — lon/lat → x_m, y_m."""
    transformer = Transformer.from_crs(_WGS84, crs_work, always_xy=True)
    projected: list[TerminalRecord] = []
    for raw in terminals_wgs84:
        x_m, y_m = transformer.transform(raw["lon"], raw["lat"])
        projected.append(
            TerminalRecord(
                id=raw["id"],
                x_m=float(x_m),
                y_m=float(y_m),
                role=raw["role"],
                outgoing_bearing_deg=raw.get("outgoing_bearing_deg"),
                outgoing_length_m=raw.get("outgoing_length_m"),
            )
        )
    return projected


def load_elevation_raster(
    request: dict[str, Any],
    *,
    base_dir: Path,
    crs_work: str,
) -> tuple[np.ndarray, Affine, float | None]:
    """L4 — GeoTIFF высот."""
    terrain = request.get("terrain") or {}
    spec = terrain.get("elevation_raster")
    if not spec:
        raise PlanRequestError("terrain_required", "elevation_raster is required for mode full")

    path_str = spec.get("path")
    if not path_str:
        raise PlanRequestError("invalid_request", "elevation_raster.path is required")

    path = _resolve_path(base_dir, str(path_str))
    if not path.is_file():
        raise PlanRequestError("raster_not_found", f"elevation raster not found: {path}")

    nodata = spec.get("nodata")
    nodata_f = float(nodata) if nodata is not None else None

    try:
        with rasterio.open(path) as src:
            src_crs = src.crs.to_string() if src.crs else None
            if src_crs is None:
                elevation = src.read(1).astype(np.float64)
                if nodata_f is None and src.nodata is not None:
                    nodata_f = float(src.nodata)
                return elevation, src.transform, nodata_f

            if src_crs != crs_work:
                elevation = np.empty((src.height, src.width), dtype=np.float64)
                transform, width, height = calculate_default_transform(
                    src_crs,
                    crs_work,
                    src.width,
                    src.height,
                    *src.bounds,
                )
                reproject(
                    source=rasterio.band(src, 1),
                    destination=elevation,
                    src_transform=src.transform,
                    src_crs=src_crs,
                    dst_transform=transform,
                    dst_crs=crs_work,
                    resampling=Resampling.bilinear,
                    src_nodata=nodata_f,
                    dst_nodata=nodata_f,
                )
                return elevation, transform, nodata_f

            elevation = src.read(1).astype(np.float64)
            if nodata_f is None and src.nodata is not None:
                nodata_f = float(src.nodata)
            return elevation, src.transform, nodata_f
    except rasterio.RasterioIOError as exc:
        raise PlanRequestError("invalid_raster", str(exc)) from exc


def _terminal_bbox_m(
    terminals: list[TerminalRecord],
    *,
    buffer_m: float,
) -> tuple[float, float, float, float]:
    xs = [t.x_m for t in terminals]
    ys = [t.y_m for t in terminals]
    return (
        min(xs) - buffer_m,
        min(ys) - buffer_m,
        max(xs) + buffer_m,
        max(ys) + buffer_m,
    )


def clip_elevation_to_bbox(
    elevation: np.ndarray,
    transform: Affine,
    bbox_m: tuple[float, float, float, float],
) -> tuple[np.ndarray, Affine]:
    """L5 — clip растра по bbox в метрах."""
    xmin, ymin, xmax, ymax = bbox_m
    window = from_bounds(xmin, ymin, xmax, ymax, transform)
    row_off = max(0, int(math.floor(window.row_off)))
    col_off = max(0, int(math.floor(window.col_off)))
    row_end = min(elevation.shape[0], int(math.ceil(window.row_off + window.height)))
    col_end = min(elevation.shape[1], int(math.ceil(window.col_off + window.width)))
    if row_end <= row_off or col_end <= col_off:
        raise PlanRequestError("raster_extent", "clip bbox outside raster")

    clipped = elevation[row_off:row_end, col_off:col_end].copy()
    sub_window = rasterio.windows.Window(
        col_off=col_off,
        row_off=row_off,
        width=col_end - col_off,
        height=row_end - row_off,
    )
    new_transform = window_transform(sub_window, transform)
    return clipped, new_transform


def _geometry_from_geojson(obj: Any) -> BaseGeometry:
    if not isinstance(obj, dict):
        raise PlanRequestError("invalid_request", "geometry must be GeoJSON object")
    geom_type = obj.get("type")
    if geom_type == "FeatureCollection":
        geoms = []
        for feat in obj.get("features", []):
            if isinstance(feat, dict) and feat.get("geometry"):
                geoms.append(shape(feat["geometry"]))
        if not geoms:
            raise PlanRequestError("invalid_request", "empty FeatureCollection")
        return unary_union(geoms)
    if geom_type == "Feature":
        return shape(obj["geometry"])
    return shape(obj)


def _reproject_geometry(geom: BaseGeometry, src_crs: str, dst_crs: str) -> BaseGeometry:
    if src_crs == dst_crs:
        return geom
    transformer = Transformer.from_crs(src_crs, dst_crs, always_xy=True)
    return transform(transformer.transform, geom)


def _load_geometry_file(path: Path, layer: str | None) -> tuple[BaseGeometry, str | None]:
    if not path.is_file():
        raise PlanRequestError("invalid_request", f"geometry file not found: {path}")
    kwargs: dict[str, Any] = {}
    if layer:
        kwargs["layer"] = layer
    try:
        gdf = gpd.read_file(path, **kwargs)
    except Exception as exc:
        raise PlanRequestError("invalid_request", f"cannot read {path}: {exc}") from exc
    if gdf.empty:
        raise PlanRequestError("invalid_request", f"empty geometry layer: {path}")
    src_crs = gdf.crs.to_string() if gdf.crs else _WGS84
    geom = unary_union(gdf.geometry)
    return geom, src_crs


def load_zones(
    request: dict[str, Any],
    *,
    base_dir: Path,
    crs_work: str,
) -> list[ZoneRecord]:
    """L6 — зоны ban / penalty."""
    terrain = request.get("terrain") or {}
    zones_raw = terrain.get("zones") or []
    if not isinstance(zones_raw, list):
        raise PlanRequestError("invalid_request", "terrain.zones must be a list")

    zones: list[ZoneRecord] = []
    for idx, raw in enumerate(zones_raw):
        if not isinstance(raw, dict):
            raise PlanRequestError("invalid_request", f"zones[{idx}] must be object")
        zone_id = str(raw.get("id", f"zone-{idx}"))
        mode = str(raw.get("mode", "ban"))
        if mode not in ("ban", "penalty"):
            raise PlanRequestError("invalid_request", f"zones[{idx}] invalid mode: {mode!r}")
        category_raw = raw.get("category")
        category = str(category_raw) if category_raw is not None else None
        if mode == "penalty":
            explicit_mult = (
                float(raw["multiplier"]) if "multiplier" in raw else None
            )
            try:
                multiplier = resolve_penalty_multiplier(
                    category, explicit_multiplier=explicit_mult
                )
            except ValueError as exc:
                raise PlanRequestError("invalid_request", str(exc)) from exc
        else:
            multiplier = float(raw.get("multiplier", 1.0))
        buffer_m = float(raw.get("buffer_m", 0.0))

        geom: BaseGeometry | None = None
        src_crs = _WGS84

        if "geometry" in raw:
            geom = _geometry_from_geojson(raw["geometry"])
        elif "source" in raw:
            source = raw["source"]
            if not isinstance(source, dict) or "path" not in source:
                raise PlanRequestError("invalid_request", f"zones[{idx}] invalid source")
            path = _resolve_path(base_dir, str(source["path"]))
            layer = source.get("layer")
            geom, src_crs = _load_geometry_file(path, layer)
        else:
            raise PlanRequestError("invalid_request", f"zones[{idx}] needs geometry or source")

        if src_crs != crs_work:
            geom = _reproject_geometry(geom, src_crs, crs_work)
        geometry_core = geom
        if buffer_m > 0:
            # quad_segs=4: меньше дуг на углах буфера (default 16 → сотни вершин → O(n²) euclid)
            geom = geom.buffer(buffer_m, quad_segs=4)

        zones.append(
            ZoneRecord(
                zone_id,
                geom,
                mode,
                multiplier=multiplier,
                geometry_core=geometry_core,
                buffer_m=buffer_m,
                category=category if mode == "penalty" else None,
            )
        )
    return zones


def load_corridors(
    request: dict[str, Any],
    *,
    base_dir: Path,
    crs_work: str,
) -> tuple[list[Any] | None, float]:
    """L7 — коридоры (LineString)."""
    terrain = request.get("terrain") or {}
    spec = terrain.get("corridors")
    if not spec:
        return None, 0.5

    multiplier = float(spec.get("cost_multiplier", 0.5))
    lines: list[Any] = []
    src_crs = _WGS84

    if "geometry" in spec:
        geom = _geometry_from_geojson(spec["geometry"])
        if src_crs != crs_work:
            geom = _reproject_geometry(geom, src_crs, crs_work)
        lines.append(geom)
    elif "source" in spec:
        source = spec["source"]
        if not isinstance(source, dict) or "path" not in source:
            raise PlanRequestError("invalid_request", "corridors.source needs path")
        path = _resolve_path(base_dir, str(source["path"]))
        geom, src_crs = _load_geometry_file(path, source.get("layer"))
        if src_crs != crs_work:
            geom = _reproject_geometry(geom, src_crs, crs_work)
        if geom.geom_type == "MultiLineString":
            lines.extend(list(geom.geoms))
        else:
            lines.append(geom)
    else:
        return None, multiplier

    return lines or None, multiplier


def load_options(request: dict[str, Any]) -> PlanOptions:
    """L8 — options → PlanOptions."""
    terrain = request.get("terrain") or {}
    raw = request.get("options") or {}
    if not isinstance(raw, dict):
        raise PlanRequestError("invalid_request", "options must be object")

    post = PostProcessOptions(
        connector_max_km=float(raw.get("connector_max_km", 0.2)),
        steiner_radius_km=float(raw.get("steiner_radius_km", 0.0)),
        normalize_terminal_leaves=bool(raw.get("normalize_terminal_leaves", True)),
        edge_vertex_spacing_km=float(raw.get("edge_vertex_spacing_km", 0.0)),
        enforce_attachment_radius=bool(raw.get("enforce_attachment_radius", True)),
    )
    euclid_routing = str(raw.get("euclid_routing", "obstacle"))
    if request.get("mode") == "euclid":
        _validate_euclid_routing(euclid_routing)
    geosteiner_home = raw.get("geosteiner_home")
    if geosteiner_home is not None:
        geosteiner_home = str(geosteiner_home)
    return PlanOptions(
        solver=str(raw.get("solver", "steinerpy")),
        max_slope_deg=float(raw.get("max_slope_deg", 30.0)),
        slope_cost_factor=float(raw.get("slope_cost_factor", 1.0)),
        max_points=int(raw.get("max_points", 50)),
        candidate_stride_cells=int(raw.get("candidate_stride_cells", 8)),
        clip_buffer_km=float(terrain.get("clip_buffer_km", 0.5)),
        corridor_buffer_m=float(raw.get("corridor_buffer_m", 15.0)),
        euclid_routing=euclid_routing,
        obstacle_buffer_m=float(raw.get("obstacle_buffer_m", 0.1)),
        euclid_steiner_candidates=bool(raw.get("euclid_steiner_candidates", True)),
        geosteiner_home=geosteiner_home,
        steiner_candidate_spacing_m=float(raw.get("steiner_candidate_spacing_m", 1.0)),
        allow_terminal_in_zone_buffer=bool(
            raw.get("allow_terminal_in_zone_buffer", False)
        ),
        post_process=post,
    )


def _validate_euclid_routing(value: str) -> None:
    if value not in ("direct", "obstacle"):
        raise PlanRequestError(
            "invalid_request",
            "options.euclid_routing must be 'direct' or 'obstacle'",
        )


def build_local_scene(
    *,
    crs_work: str,
    transform: Affine,
    elevation: np.ndarray,
    nodata: float | None,
    zones: list[ZoneRecord],
    corridors: list[Any] | None,
    corridor_cost_multiplier: float,
    corridor_buffer_m: float,
) -> LocalScene:
    """L9 — сборка LocalScene."""
    return LocalScene(
        crs_work=crs_work,
        transform=transform,
        elevation=elevation,
        nodata=nodata,
        zones=zones,
        corridors=corridors,
        corridor_cost_multiplier=corridor_cost_multiplier,
        corridor_buffer_m=corridor_buffer_m,
    )


def build_euclid_scene(
    crs_work: str,
    *,
    zones: list[ZoneRecord] | None = None,
) -> LocalScene:
    """L9 (euclid) — минимальная LocalScene без растра; опционально terrain.zones."""
    return LocalScene(
        crs_work=crs_work,
        transform=Affine.identity(),
        elevation=np.zeros((1, 1), dtype=np.float64),
        nodata=None,
        zones=list(zones or []),
        corridors=None,
        corridor_cost_multiplier=0.5,
        corridor_buffer_m=15.0,
    )


def load_local_scene(
    source: str | Path | dict[str, Any],
    *,
    base_dir: Path | str | None = None,
) -> tuple[LocalScene, list[TerminalRecord], PlanOptions]:
    """L1–L9 — полная загрузка LocalScene из PlanRequest."""
    request, file_base = load_plan_request(source)
    if base_dir is not None:
        resolved_base = Path(base_dir).resolve()
    elif file_base is not None:
        resolved_base = file_base
    else:
        resolved_base = Path.cwd().resolve()

    terminals_wgs84 = load_terminals_wgs84(request)
    crs_work = resolve_crs_work(request, terminals_wgs84)
    terminals = project_terminals(terminals_wgs84, crs_work)
    options = load_options(request)

    if request["mode"] == "euclid":
        zones: list[ZoneRecord] = []
        if request.get("terrain"):
            zones = load_zones(request, base_dir=resolved_base, crs_work=crs_work)
        scene = build_euclid_scene(crs_work, zones=zones)
        return scene, terminals, options

    elevation, transform, nodata = load_elevation_raster(
        request,
        base_dir=resolved_base,
        crs_work=crs_work,
    )
    buffer_m = options.clip_buffer_km * 1000.0
    bbox_m = _terminal_bbox_m(terminals, buffer_m=buffer_m)
    elevation, transform = clip_elevation_to_bbox(elevation, transform, bbox_m)

    zones = load_zones(request, base_dir=resolved_base, crs_work=crs_work)
    corridors, corridor_multiplier = load_corridors(
        request,
        base_dir=resolved_base,
        crs_work=crs_work,
    )

    scene = build_local_scene(
        crs_work=crs_work,
        transform=transform,
        elevation=elevation,
        nodata=nodata,
        zones=zones,
        corridors=corridors,
        corridor_cost_multiplier=corridor_multiplier,
        corridor_buffer_m=options.corridor_buffer_m,
    )
    return scene, terminals, options
