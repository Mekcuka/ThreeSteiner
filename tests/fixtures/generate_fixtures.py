"""Generate test fixtures for plan_request loader."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

try:
    import pyproj

    os.environ["PROJ_LIB"] = pyproj.datadir.get_data_dir()
except Exception:
    pass

import rasterio

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from demo_scene import (
    BAN_BOX,
    CELL_M,
    CORRIDOR_WAYPOINTS,
    ORIGIN_X,
    ORIGIN_Y,
    PENALTY_BOX,
    ROWS,
    COLS,
    make_elevation,
)
from shapely.geometry import LineString, box

FIXTURES = Path(__file__).resolve().parent


def _box_polygon_wgs(coords_fn, box: tuple[float, float, float, float]) -> list[list[float]]:
    xmin, ymin, xmax, ymax = box
    ring = [
        (xmin, ymin),
        (xmax, ymin),
        (xmax, ymax),
        (xmin, ymax),
        (xmin, ymin),
    ]
    return [list(coords_fn(x, y)) for x, y in ring]


def write_elevation_tif(path: Path) -> None:
    from rasterio.transform import from_origin

    elevation = make_elevation(ROWS, COLS)
    transform = from_origin(ORIGIN_X, ORIGIN_Y, CELL_M, CELL_M)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Без embedded CRS — избегаем конфликтов PROJ/GDAL на Windows; CRS берётся из JSON.
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=ROWS,
        width=COLS,
        count=1,
        dtype=elevation.dtype,
        transform=transform,
        nodata=-9999.0,
    ) as dst:
        dst.write(elevation, 1)


def write_plan_request_synthetic(path: Path, *, tif_name: str = "elevation_small.tif") -> None:
    from pyproj import Transformer

    transformer = Transformer.from_crs("EPSG:32637", "EPSG:4326", always_xy=True)
    terminals = [
        ("t-start", 500_100.0, 6_199_900.0, "start"),
        ("t-mid", 500_450.0, 6_199_800.0, "intermediate"),
        ("t-end", 500_480.0, 6_199_720.0, "end"),
        ("t-north", 500_250.0, 6_199_970.0, "branch"),
    ]

    def to_wgs(x: float, y: float) -> tuple[float, float]:
        lon, lat = transformer.transform(x, y)
        return float(lon), float(lat)

    ban_coords = _box_polygon_wgs(to_wgs, BAN_BOX)
    pen_coords = _box_polygon_wgs(to_wgs, PENALTY_BOX)
    corr_coords = [list(to_wgs(x, y)) for x, y in CORRIDOR_WAYPOINTS]

    payload = {
        "project_id": "fixture-synthetic-scene",
        "mode": "full",
        "terminals": [
            {
                "id": tid,
                "type": "oil_pad",
                "role": role,
                "lon": to_wgs(x, y)[0],
                "lat": to_wgs(x, y)[1],
            }
            for tid, x, y, role in terminals
        ],
        "terrain": {
            "elevation_raster": {
                "path": tif_name,
                "crs": "EPSG:32637",
                "nodata": -9999,
            },
            "clip_buffer_km": 0.15,
            "zones": [
                {
                    "id": "ban-1",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [ban_coords],
                    },
                    "mode": "ban",
                },
                {
                    "id": "swamp",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [pen_coords],
                    },
                    "mode": "penalty",
                    "multiplier": 5.0,
                },
            ],
            "corridors": {
                "geometry": {
                    "type": "LineString",
                    "coordinates": corr_coords,
                },
                "cost_multiplier": 0.5,
            },
        },
        "options": {
            "solver": "steinerpy",
            "connector_max_km": 0.05,
            "steiner_radius_km": 0.0,
            "max_slope_deg": 30,
            "slope_cost_factor": 1.0,
            "normalize_terminal_leaves": True,
            "edge_vertex_spacing_km": 0.0,
            "max_points": 50,
            "candidate_stride_cells": 8,
            "corridor_buffer_m": 20.0,
        },
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_shapefile_fixtures() -> None:
    """L6.2 / L7.1 — Shapefile-фикстуры (EPSG:32637, как demo_scene)."""
    import geopandas as gpd

    crs = "EPSG:32637"
    gpd.GeoDataFrame({"id": ["ban-1"]}, geometry=[box(*BAN_BOX)], crs=crs).to_file(
        FIXTURES / "ban_zone.shp"
    )
    gpd.GeoDataFrame({"id": ["swamp"]}, geometry=[box(*PENALTY_BOX)], crs=crs).to_file(
        FIXTURES / "penalty_zone.shp"
    )
    gpd.GeoDataFrame(
        {"id": ["corr-1"]},
        geometry=[LineString(CORRIDOR_WAYPOINTS)],
        crs=crs,
    ).to_file(FIXTURES / "corridor.shp")


def write_plan_request_synthetic_shp(path: Path, *, tif_name: str = "elevation_small.tif") -> None:
    """PlanRequest с зонами/коридором из `.shp` вместо inline GeoJSON."""
    from pyproj import Transformer

    transformer = Transformer.from_crs("EPSG:32637", "EPSG:4326", always_xy=True)
    terminals = [
        ("t-start", 500_100.0, 6_199_900.0, "start"),
        ("t-mid", 500_450.0, 6_199_800.0, "intermediate"),
        ("t-end", 500_480.0, 6_199_720.0, "end"),
        ("t-north", 500_250.0, 6_199_970.0, "branch"),
    ]

    def to_wgs(x: float, y: float) -> tuple[float, float]:
        lon, lat = transformer.transform(x, y)
        return float(lon), float(lat)

    payload = {
        "project_id": "fixture-synthetic-scene-shp",
        "mode": "full",
        "terminals": [
            {
                "id": tid,
                "type": "oil_pad",
                "role": role,
                "lon": to_wgs(x, y)[0],
                "lat": to_wgs(x, y)[1],
            }
            for tid, x, y, role in terminals
        ],
        "terrain": {
            "elevation_raster": {
                "path": tif_name,
                "crs": "EPSG:32637",
                "nodata": -9999,
            },
            "clip_buffer_km": 0.15,
            "zones": [
                {
                    "id": "ban-1",
                    "source": {"path": "ban_zone.shp"},
                    "mode": "ban",
                },
                {
                    "id": "swamp",
                    "source": {"path": "penalty_zone.shp"},
                    "mode": "penalty",
                    "multiplier": 5.0,
                },
            ],
            "corridors": {
                "source": {"path": "corridor.shp"},
                "cost_multiplier": 0.5,
            },
        },
        "options": {
            "solver": "steinerpy",
            "connector_max_km": 0.05,
            "steiner_radius_km": 0.0,
            "max_slope_deg": 30,
            "slope_cost_factor": 1.0,
            "normalize_terminal_leaves": True,
            "edge_vertex_spacing_km": 0.0,
            "max_points": 50,
            "candidate_stride_cells": 8,
            "corridor_buffer_m": 20.0,
        },
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_zones_inline_only(path: Path) -> None:
    payload = {
        "project_id": "fixture-inline-only",
        "mode": "full",
        "terminals": [
            {
                "id": "t-start",
                "role": "start",
                "lon": 39.00160110,
                "lat": 55.94447649,
            },
            {
                "id": "t-end",
                "role": "end",
                "lon": 39.00768494,
                "lat": 55.94285895,
            },
        ],
        "terrain": {
            "elevation_raster": {"path": "elevation_small.tif", "crs": "EPSG:32637"},
            "zones": [],
        },
        "options": {"max_points": 50},
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    write_elevation_tif(FIXTURES / "elevation_small.tif")
    write_shapefile_fixtures()
    write_plan_request_synthetic(FIXTURES / "plan_request_synthetic.json")
    write_plan_request_synthetic_shp(FIXTURES / "plan_request_synthetic_shp.json")
    write_zones_inline_only(FIXTURES / "zones_inline_only.json")
    print("fixtures written to", FIXTURES)


if __name__ == "__main__":
    main()
