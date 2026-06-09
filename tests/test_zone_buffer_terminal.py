"""Tests for allow_terminal_in_zone_buffer (terminal in buffer_m ring)."""

from __future__ import annotations

from copy import deepcopy

import pytest
from shapely.geometry import box

from topo_network.euclid_zones import zone_terminal_ban_geometry
from topo_network.models import LocalScene, TerminalRecord, ZoneRecord
from topo_network.plan_request import PlanRequestError, load_plan_request
from topo_network.pipeline import run_plan
from topo_network.validation import validate_terminal_ban_zones
from rasterio.transform import Affine
import numpy as np

FIXTURES = __import__("pathlib").Path(__file__).resolve().parent / "fixtures"
EUCLID = FIXTURES / "plan_request_euclid.json"


def _ban_zone_with_buffer(buffer_m: float = 50.0) -> ZoneRecord:
    core = box(100.0, 100.0, 200.0, 200.0)
    effective = core.buffer(buffer_m) if buffer_m > 0 else core
    return ZoneRecord(
        "ban-test",
        effective,
        "ban",
        geometry_core=core,
        buffer_m=buffer_m,
    )


def _point_in_buffer_ring(zone: ZoneRecord) -> tuple[float, float]:
    ring = zone.geometry.difference(zone.geometry_core)
    pt = ring.representative_point()
    return float(pt.x), float(pt.y)


def _minimal_scene(zone: ZoneRecord) -> LocalScene:
    return LocalScene(
        crs_work="EPSG:32637",
        transform=Affine(10.0, 0.0, 0.0, 0.0, -10.0, 500.0),
        elevation=np.zeros((50, 40), dtype=np.float64),
        nodata=-9999.0,
        zones=[zone],
    )


def test_zone_terminal_ban_geometry_helper() -> None:
    zone = _ban_zone_with_buffer(30.0)
    assert zone_terminal_ban_geometry(zone, allow_in_buffer=False) is zone.geometry
    assert zone_terminal_ban_geometry(zone, allow_in_buffer=True) is zone.geometry_core


def test_terminal_in_core_ban_rejected_with_flag() -> None:
    zone = _ban_zone_with_buffer(50.0)
    scene = _minimal_scene(zone)
    terminal = TerminalRecord("t-core", 150.0, 150.0, "intermediate")
    assert not validate_terminal_ban_zones(
        scene, [terminal], allow_terminal_in_zone_buffer=False
    ).ok
    assert not validate_terminal_ban_zones(
        scene, [terminal], allow_terminal_in_zone_buffer=True
    ).ok


def test_terminal_in_buffer_ring_flag_false_rejected() -> None:
    zone = _ban_zone_with_buffer(50.0)
    scene = _minimal_scene(zone)
    x, y = _point_in_buffer_ring(zone)
    terminal = TerminalRecord("t-ring", x, y, "intermediate")
    assert not validate_terminal_ban_zones(
        scene, [terminal], allow_terminal_in_zone_buffer=False
    ).ok


def test_terminal_in_buffer_ring_flag_true_allowed() -> None:
    zone = _ban_zone_with_buffer(50.0)
    scene = _minimal_scene(zone)
    x, y = _point_in_buffer_ring(zone)
    terminal = TerminalRecord("t-ring", x, y, "intermediate")
    result = validate_terminal_ban_zones(
        scene, [terminal], allow_terminal_in_zone_buffer=True
    )
    assert result.ok


def test_load_zones_stores_geometry_core() -> None:
    request = {
        "project_id": "zone-core",
        "mode": "euclid",
        "terminals": [
            {"id": "a", "role": "start", "lon": 39.0, "lat": 55.94},
            {"id": "b", "role": "end", "lon": 39.01, "lat": 55.94},
        ],
        "terrain": {
            "zones": [
                {
                    "id": "ban-1",
                    "mode": "ban",
                    "buffer_m": 40,
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [39.003, 55.944],
                                [39.004, 55.944],
                                [39.004, 55.945],
                                [39.003, 55.945],
                                [39.003, 55.944],
                            ]
                        ],
                    },
                }
            ]
        },
    }
    from topo_network.plan_request import load_local_scene

    scene, _, options = load_local_scene(request)
    zone = scene.zones[0]
    assert zone.buffer_m == pytest.approx(40.0)
    assert zone.geometry_core is not None
    assert zone.geometry.area > zone.geometry_core.area
    assert options.allow_terminal_in_zone_buffer is False


def test_run_plan_terminal_in_buffer_ring_euclid() -> None:
    request = {
        "project_id": "buffer-ring-euclid",
        "mode": "euclid",
        "terminals": [
            {"id": "t-a", "role": "start", "lon": 39.0016, "lat": 55.9445},
            {"id": "t-b", "role": "end", "lon": 39.0077, "lat": 55.9429},
            {"id": "t-ring", "role": "intermediate", "lon": 39.0, "lat": 55.94},
        ],
        "options": {
            "euclid_steiner_candidates": False,
            "euclid_routing": "direct",
            "allow_terminal_in_zone_buffer": True,
        },
        "terrain": {
            "zones": [
                {
                    "id": "ban-1",
                    "mode": "ban",
                    "buffer_m": 80,
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [39.0032, 55.9538],
                                [39.0042, 55.9538],
                                [39.0042, 55.9548],
                                [39.0032, 55.9548],
                                [39.0032, 55.9538],
                            ]
                        ],
                    },
                }
            ]
        },
    }
    from topo_network.plan_request import load_local_scene
    from pyproj import Transformer

    scene, _, _ = load_local_scene(request)
    zone = next(z for z in scene.zones if z.id == "ban-1")
    ring_x, ring_y = _point_in_buffer_ring(zone)
    transformer = Transformer.from_crs(scene.crs_work, "EPSG:4326", always_xy=True)
    ring_lon, ring_lat = transformer.transform(ring_x, ring_y)
    request["terminals"][2]["lon"] = ring_lon
    request["terminals"][2]["lat"] = ring_lat

    request_no_flag = deepcopy(request)
    request_no_flag["options"]["allow_terminal_in_zone_buffer"] = False
    with pytest.raises(PlanRequestError) as exc_false:
        run_plan(request_no_flag)
    assert exc_false.value.code == "terminal_in_ban_zone"

    response = run_plan(request)
    assert response["network_tree"]["edges"]
    assert response["project_id"] == "buffer-ring-euclid"


def test_run_plan_buffer_ring_rejected_without_flag() -> None:
    request, _ = load_plan_request(EUCLID)
    request = deepcopy(request)
    request["terrain"] = {
        "zones": [
            {
                "id": "ban-small",
                "mode": "ban",
                "buffer_m": 100,
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [39.003, 55.944],
                            [39.0045, 55.944],
                            [39.0045, 55.9455],
                            [39.003, 55.9455],
                            [39.003, 55.944],
                        ]
                    ],
                },
            }
        ]
    }
    from topo_network.plan_request import load_local_scene

    scene, _, _ = load_local_scene(request)
    zone = scene.zones[0]
    ring_x, ring_y = _point_in_buffer_ring(zone)
    from pyproj import Transformer

    transformer = Transformer.from_crs(scene.crs_work, "EPSG:4326", always_xy=True)
    ring_lon, ring_lat = transformer.transform(ring_x, ring_y)
    request["terminals"].append(
        {
            "id": "t-ring",
            "role": "intermediate",
            "lon": ring_lon,
            "lat": ring_lat,
        }
    )
    with pytest.raises(PlanRequestError) as exc:
        run_plan(request)
    assert exc.value.code == "terminal_in_ban_zone"
