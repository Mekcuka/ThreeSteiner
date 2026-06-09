"""Tests for geometric ban/penalty in mode euclid (variant B)."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import networkx as nx
import pytest
from shapely.geometry import LineString

from topo_network.euclid_zones import (
    EUCLID_BAN_FORBIDDEN_WEIGHT,
    edge_blocked_by_ban,
    penalized_edge_weight,
)
from topo_network.plan_request import PlanRequestError, load_local_scene, load_plan_request
from topo_network.pipeline import run_plan
from topo_network.routing_graph import build_euclid_routing_graph
from topo_network.validation import run_preflight, terminal_graph_id

FIXTURES = Path(__file__).resolve().parent / "fixtures"
EUCLID = FIXTURES / "plan_request_euclid.json"
EUCLID_ZONES = FIXTURES / "plan_request_euclid_zones.json"


def test_load_local_scene_euclid_with_zones() -> None:
    scene, terminals, _ = load_local_scene(EUCLID_ZONES, base_dir=FIXTURES)
    assert len(scene.zones) == 2
    assert len(terminals) == 4
    assert scene.elevation.shape == (1, 1)


def test_euclid_rejects_elevation_raster() -> None:
    request, _ = load_plan_request(EUCLID_ZONES)
    broken = deepcopy(request)
    broken["terrain"]["elevation_raster"] = {"path": "elevation_small.tif"}
    with pytest.raises(PlanRequestError) as exc:
        load_plan_request(broken)
    assert exc.value.code == "invalid_request"
    assert "elevation_raster" in exc.value.message


def test_ban_blocks_direct_edge() -> None:
    scene, terminals, _ = load_local_scene(EUCLID_ZONES, base_dir=FIXTURES)
    routing, _ = build_euclid_routing_graph(
        terminals,
        zones=scene.zones,
        euclid_routing="direct",
    )
    penalized = {
        (a, b)
        for a, b, reason in routing.skipped_pairs
        if reason == "ban_forbidden_weight"
    }
    assert penalized

    start = next(t for t in terminals if t.role == "start")
    end = next(t for t in terminals if t.role == "end")
    line = LineString([(start.x_m, start.y_m), (end.x_m, end.y_m)])
    ban_zones = [z for z in scene.zones if z.mode == "ban"]
    assert edge_blocked_by_ban(line, ban_zones)
    start_id = terminal_graph_id(start.id)
    end_id = terminal_graph_id(end.id)
    assert (start_id, end_id) in penalized or (end_id, start_id) in penalized
    assert routing.graph[start_id][end_id]["crosses_ban"]
    assert routing.graph[start_id][end_id]["weight"] >= EUCLID_BAN_FORBIDDEN_WEIGHT


def test_penalty_increases_edge_weight() -> None:
    scene, terminals, _ = load_local_scene(EUCLID_ZONES, base_dir=FIXTURES)
    routing, _ = build_euclid_routing_graph(terminals, zones=scene.zones)
    penalty_zones = [z for z in scene.zones if z.mode == "penalty"]
    mid = next(t for t in terminals if t.id == "t-mid")
    end = next(t for t in terminals if t.role == "end")
    line = LineString([(mid.x_m, mid.y_m), (end.x_m, end.y_m)])
    assert penalized_edge_weight(line, penalty_zones) > line.length

    routing_no_zones, _ = build_euclid_routing_graph(terminals)
    u = terminal_graph_id(mid.id)
    v = terminal_graph_id(end.id)
    w_with = routing.graph[u][v]["weight"]
    w_plain = routing_no_zones.graph[u][v]["weight"]
    assert w_with > w_plain


def test_run_plan_euclid_with_zones() -> None:
    response = run_plan(EUCLID_ZONES, base_dir=FIXTURES)
    assert response["project_id"] == "fixture-euclid-zones"
    assert response["mode"] == "euclid"
    assert response["network_tree"]["edges"]
    plain = run_plan(EUCLID)
    assert len(response["network_tree"]["edges"]) >= len(plain["network_tree"]["edges"])


def test_terminal_in_ban_zone_euclid() -> None:
    request, _ = load_plan_request(EUCLID_ZONES)
    broken = deepcopy(request)
    broken["terminals"][0]["lon"] = 39.0039
    broken["terminals"][0]["lat"] = 55.9438
    with pytest.raises(PlanRequestError) as exc:
        run_plan(broken, base_dir=FIXTURES)
    assert exc.value.code == "terminal_in_ban_zone"


def test_obstacle_routing_avoids_wall() -> None:
    request = {
        "project_id": "isolated-euclid",
        "mode": "euclid",
        "terminals": [
            {"id": "s", "role": "start", "lon": 39.0016011, "lat": 55.94447649},
            {"id": "e", "role": "end", "lon": 39.00768494, "lat": 55.94285895},
        ],
        "terrain": {
            "zones": [
                {
                    "id": "wall",
                    "mode": "ban",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [39.0030, 55.9435],
                                [39.0060, 55.9435],
                                [39.0060, 55.9442],
                                [39.0030, 55.9442],
                                [39.0030, 55.9435],
                            ]
                        ],
                    },
                }
            ]
        },
        "options": {"max_points": 50, "euclid_routing": "obstacle"},
    }
    response = run_plan(request, base_dir=FIXTURES)
    assert response["network_tree"]["edges"]
    assert response["metrics"]["total_cost"] < 1e9
    warnings = response.get("warnings") or []
    assert not any("crosses ban" in w.lower() for w in warnings)


def test_direct_routing_may_use_forbidden_edge() -> None:
    request = {
        "project_id": "isolated-euclid-direct",
        "mode": "euclid",
        "terminals": [
            {"id": "s", "role": "start", "lon": 39.0016011, "lat": 55.94447649},
            {"id": "e", "role": "end", "lon": 39.00768494, "lat": 55.94285895},
        ],
        "terrain": {
            "zones": [
                {
                    "id": "wall",
                    "mode": "ban",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [39.0030, 55.9435],
                                [39.0060, 55.9435],
                                [39.0060, 55.9442],
                                [39.0030, 55.9442],
                                [39.0030, 55.9435],
                            ]
                        ],
                    },
                }
            ]
        },
        "options": {"max_points": 50, "euclid_routing": "direct"},
    }
    response = run_plan(request, base_dir=FIXTURES)
    assert response["metrics"]["total_cost"] >= EUCLID_BAN_FORBIDDEN_WEIGHT


def test_user_two_bans_obstacle_routing() -> None:
    request = {
        "project_id": "fixture-euclid-scene",
        "mode": "euclid",
        "terminals": [
            {
                "id": "t-start",
                "role": "start",
                "lon": 39.00160109642316,
                "lat": 55.94447648880544,
            },
            {
                "id": "t-mid",
                "role": "intermediate",
                "lon": 39.0072047670713,
                "lat": 55.94357778592078,
            },
            {
                "id": "t-end",
                "role": "end",
                "lon": 39.00768494254051,
                "lat": 55.942858954676176,
            },
            {
                "id": "t-north",
                "role": "branch",
                "lon": 39.004002805924074,
                "lat": 55.94510538599134,
            },
        ],
        "terrain": {
            "zones": [
                {
                    "id": "ban-1",
                    "mode": "ban",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [39.004185, 55.943883],
                                [39.005622, 55.944763],
                                [39.006438, 55.944415],
                                [39.005445, 55.943892],
                                [39.004185, 55.943883],
                            ]
                        ],
                    },
                },
                {
                    "id": "ban-2",
                    "mode": "ban",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [39.002945, 55.942627],
                                [39.003375, 55.944129],
                                [39.004555, 55.944334],
                                [39.004104, 55.942363],
                                [39.002945, 55.942627],
                            ]
                        ],
                    },
                },
            ]
        },
        "options": {"max_points": 50, "euclid_routing": "obstacle"},
    }
    response = run_plan(request)
    assert response["network_tree"]["edges"]
    assert response["metrics"]["routing_edges_skipped"] == 0.0
    assert response["metrics"]["total_cost"] < 1e9
    assert 500.0 < response["metrics"]["total_length_m"] < 700.0
    warnings = response.get("warnings") or []
    assert not any("crosses ban" in w.lower() for w in warnings)


def test_visibility_routing_graph_has_obstacle_nodes() -> None:
    from topo_network.euclid_visibility import build_euclid_visibility_routing_graph

    scene, terminals, _ = load_local_scene(
        {
            "project_id": "vis-test",
            "mode": "euclid",
            "terminals": [
                {"id": "s", "role": "start", "lon": 39.0016011, "lat": 55.94447649},
                {"id": "e", "role": "end", "lon": 39.00768494, "lat": 55.94285895},
            ],
            "terrain": {
                "zones": [
                    {
                        "id": "wall",
                        "mode": "ban",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [39.0030, 55.9435],
                                    [39.0060, 55.9435],
                                    [39.0060, 55.9442],
                                    [39.0030, 55.9442],
                                    [39.0030, 55.9435],
                                ]
                            ],
                        },
                    }
                ]
            },
        }
    )
    routing, _ = build_euclid_visibility_routing_graph(
        terminals,
        zones=scene.zones,
        euclid_steiner_candidates=False,
    )
    start_id = terminal_graph_id("s")
    end_id = terminal_graph_id("e")
    assert any(nid.startswith("obstacle:") for nid in routing.nodes)
    assert not routing.graph.has_edge(start_id, end_id)
    path = nx.shortest_path(routing.graph, start_id, end_id, weight="weight")
    assert len(path) >= 3


def _floodplain_strip_request() -> dict:
    return {
        "project_id": "penalty-contour-detour",
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
                                [39.0038, 55.9430],
                                [39.0055, 55.9430],
                                [39.0055, 55.9445],
                                [39.0038, 55.9445],
                                [39.0038, 55.9430],
                            ]
                        ],
                    },
                }
            ]
        },
        "options": {
            "max_points": 50,
            "euclid_routing": "direct",
            "euclid_steiner_candidates": False,
            "solver": "steinerpy",
        },
    }


def test_penalty_contour_vertices_in_graph() -> None:
    scene, terminals, _ = load_local_scene(_floodplain_strip_request(), base_dir=FIXTURES)
    routing, _ = build_euclid_routing_graph(
        terminals,
        zones=scene.zones,
        euclid_steiner_candidates=False,
    )
    penalty_nodes = [nid for nid in routing.nodes if nid.startswith("penalty:")]
    assert penalty_nodes
    assert any(nid.startswith("penalty:poyma:") for nid in penalty_nodes)


def test_large_scene_with_buffered_zones_completes() -> None:
    """Regression: buffer_m + penalty contours must not explode visibility graph (hang)."""
    import time

    fixture = Path(__file__).parent / "_debug_hang_request.json"
    if not fixture.is_file():
        pytest.skip("debug fixture missing")
    t0 = time.perf_counter()
    response = run_plan(fixture, base_dir=fixture.parent)
    elapsed = time.perf_counter() - t0
    assert elapsed < 120.0, f"plan took too long: {elapsed:.1f}s"
    assert response["network_tree"]["edges"]
    assert response["metrics"]["ban_zones"] == 1.0


def test_penalty_contour_detour_e2e() -> None:
    from unittest.mock import patch

    import topo_network.euclid_visibility as ev

    request = _floodplain_strip_request()
    with_contour = run_plan(request, base_dir=FIXTURES)
    with patch.object(ev, "_penalty_vertices", return_value=[]):
        without = run_plan(request, base_dir=FIXTURES)

    assert with_contour["metrics"]["total_cost"] < without["metrics"]["total_cost"]
    steiner_ids = [
        p["id"] for p in with_contour["network_tree"]["steiner_points"]
    ]
    assert any(sid.startswith("penalty:poyma:") for sid in steiner_ids)
    magistral = [
        e
        for e in with_contour["network_tree"]["edges"]
        if e["length_m"] > 50
    ]
    assert len(magistral) >= 2
