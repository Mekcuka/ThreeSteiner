"""Tests for terrain penalty zone categories (dry_land / swamp / floodplain)."""

from __future__ import annotations

from pathlib import Path

import pytest
from shapely.geometry import LineString, box

from topo_network.euclid_zones import penalized_edge_weight
from topo_network.plan_request import PlanRequestError, load_local_scene, load_zones
from topo_network.zone_categories import (
    LEGACY_PENALTY_MULTIPLIER,
    resolve_penalty_multiplier,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
EUCLID_ZONES = FIXTURES / "plan_request_euclid_zones.json"


def test_resolve_penalty_multiplier_category_defaults() -> None:
    assert resolve_penalty_multiplier("dry_land", explicit_multiplier=None) == 1.0
    assert resolve_penalty_multiplier("swamp", explicit_multiplier=None) == 2.0
    assert resolve_penalty_multiplier("floodplain", explicit_multiplier=None) == 3.0


def test_resolve_penalty_multiplier_explicit_override() -> None:
    assert resolve_penalty_multiplier("swamp", explicit_multiplier=5.0) == 5.0


def test_resolve_penalty_multiplier_legacy() -> None:
    assert resolve_penalty_multiplier(None, explicit_multiplier=None) == LEGACY_PENALTY_MULTIPLIER


def test_load_zones_category_swamp_default_multiplier() -> None:
    request = {
        "terrain": {
            "zones": [
                {
                    "id": "b1",
                    "mode": "penalty",
                    "category": "swamp",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [39.0, 55.0],
                                [39.001, 55.0],
                                [39.001, 55.001],
                                [39.0, 55.001],
                                [39.0, 55.0],
                            ]
                        ],
                    },
                }
            ]
        }
    }
    zones = load_zones(request, base_dir=FIXTURES, crs_work="EPSG:4326")
    assert len(zones) == 1
    assert zones[0].category == "swamp"
    assert zones[0].multiplier == 2.0


def test_load_zones_category_override_multiplier() -> None:
    request = {
        "terrain": {
            "zones": [
                {
                    "id": "b1",
                    "mode": "penalty",
                    "category": "swamp",
                    "multiplier": 5.0,
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [39.0, 55.0],
                                [39.001, 55.0],
                                [39.001, 55.001],
                                [39.0, 55.001],
                                [39.0, 55.0],
                            ]
                        ],
                    },
                }
            ]
        }
    }
    zones = load_zones(request, base_dir=FIXTURES, crs_work="EPSG:4326")
    assert zones[0].multiplier == 5.0


def test_load_zones_legacy_penalty_without_category() -> None:
    request = {
        "terrain": {
            "zones": [
                {
                    "id": "legacy",
                    "mode": "penalty",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [39.0, 55.0],
                                [39.001, 55.0],
                                [39.001, 55.001],
                                [39.0, 55.001],
                                [39.0, 55.0],
                            ]
                        ],
                    },
                }
            ]
        }
    }
    zones = load_zones(request, base_dir=FIXTURES, crs_work="EPSG:4326")
    assert zones[0].category is None
    assert zones[0].multiplier == LEGACY_PENALTY_MULTIPLIER


def test_load_zones_invalid_category() -> None:
    request = {
        "terrain": {
            "zones": [
                {
                    "id": "bad",
                    "mode": "penalty",
                    "category": "marsh",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [39.0, 55.0],
                                [39.001, 55.0],
                                [39.001, 55.001],
                                [39.0, 55.001],
                                [39.0, 55.0],
                            ]
                        ],
                    },
                }
            ]
        }
    }
    with pytest.raises(PlanRequestError) as exc:
        load_zones(request, base_dir=FIXTURES, crs_work="EPSG:4326")
    assert exc.value.code == "invalid_request"
    assert "marsh" in exc.value.message


def test_penalty_buffer_expands_cost_area() -> None:
    core = box(450.0, -10.0, 550.0, 10.0)
    buffered = ZoneRecord_from_boxes(core, buffer_m=30.0, category="floodplain")
    line_through_buffer_ring = LineString([(500.0, 50.0), (500.0, -50.0)])
    line_outside = LineString([(700.0, 50.0), (700.0, -50.0)])
    zones = [buffered]
    w_ring = penalized_edge_weight(line_through_buffer_ring, zones)
    w_outside = penalized_edge_weight(line_outside, zones)
    w_plain = line_through_buffer_ring.length
    assert w_ring > w_plain
    assert w_outside == pytest.approx(line_outside.length)


def test_euclid_fixture_swamp_category() -> None:
    scene, _, penalty = _load_penalty_zone_from_fixture()
    assert penalty.category == "swamp"
    assert penalty.multiplier == 2.0


def test_floodplain_category_increases_routing_weight() -> None:
    from topo_network.routing_graph import build_euclid_routing_graph
    from topo_network.validation import terminal_graph_id

    request = {
        "project_id": "floodplain-weight",
        "mode": "euclid",
        "terminals": [
            {"id": "s", "role": "start", "lon": 39.0016011, "lat": 55.94447649},
            {"id": "e", "role": "end", "lon": 39.00768494, "lat": 55.94285895},
        ],
        "terrain": {
            "zones": [
                {
                    "id": "poyma",
                    "mode": "penalty",
                    "category": "floodplain",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [39.0035, 55.9435],
                                [39.0058, 55.9435],
                                [39.0058, 55.9440],
                                [39.0035, 55.9440],
                                [39.0035, 55.9435],
                            ]
                        ],
                    },
                }
            ]
        },
    }
    scene, terminals, _ = load_local_scene(request, base_dir=FIXTURES)
    penalty = next(z for z in scene.zones if z.category == "floodplain")
    assert penalty.multiplier == 3.0
    start = next(t for t in terminals if t.id == "s")
    end = next(t for t in terminals if t.id == "e")
    line = LineString([(start.x_m, start.y_m), (end.x_m, end.y_m)])
    assert penalized_edge_weight(line, [penalty]) > line.length * 1.5

    routing, _ = build_euclid_routing_graph(terminals, zones=scene.zones)
    routing_plain, _ = build_euclid_routing_graph(terminals)
    u = terminal_graph_id("s")
    v = terminal_graph_id("e")
    assert routing.graph[u][v]["weight"] > routing_plain.graph[u][v]["weight"]


def ZoneRecord_from_boxes(core, *, buffer_m: float, category: str):
    from topo_network.models import ZoneRecord
    from topo_network.zone_categories import resolve_penalty_multiplier

    effective = core.buffer(buffer_m) if buffer_m > 0 else core
    mult = resolve_penalty_multiplier(category, explicit_multiplier=None)
    return ZoneRecord(
        "fp",
        effective,
        "penalty",
        multiplier=mult,
        geometry_core=core,
        buffer_m=buffer_m,
        category=category,
    )


def _load_penalty_zone_from_fixture():
    scene, terminals, _ = load_local_scene(EUCLID_ZONES, base_dir=FIXTURES)
    penalty = next(z for z in scene.zones if z.mode == "penalty")
    return scene, terminals, penalty
