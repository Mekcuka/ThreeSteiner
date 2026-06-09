"""Tests for PlanRequest loader and run_plan (этап 7)."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from topo_network.plan_request import (
    PlanRequestError,
    clip_elevation_to_bbox,
    load_corridors,
    load_elevation_raster,
    load_local_scene,
    load_plan_request,
    load_terminals_wgs84,
    load_zones,
    project_terminals,
    resolve_crs_work,
)
from topo_network.pipeline import run_plan
from topo_network.routing_graph import build_euclid_routing_graph

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SYNTHETIC = FIXTURES / "plan_request_synthetic.json"
SYNTHETIC_SHP = FIXTURES / "plan_request_synthetic_shp.json"
EUCLID = FIXTURES / "plan_request_euclid.json"
EUCLID_ZONES = FIXTURES / "plan_request_euclid_zones.json"


def _fixtures_ready() -> bool:
    required = (
        FIXTURES / "elevation_small.tif",
        SYNTHETIC,
        SYNTHETIC_SHP,
        FIXTURES / "ban_zone.shp",
        FIXTURES / "corridor.shp",
    )
    return all(p.is_file() for p in required)


@pytest.fixture(scope="session", autouse=True)
def ensure_fixtures() -> None:
    if not _fixtures_ready():
        import importlib.util

        gen_path = FIXTURES / "generate_fixtures.py"
        spec = importlib.util.spec_from_file_location("generate_fixtures", gen_path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.main()


def test_load_plan_request_valid() -> None:
    request, base = load_plan_request(SYNTHETIC)
    assert request["project_id"] == "fixture-synthetic-scene"
    assert request["mode"] == "full"
    assert base == FIXTURES.resolve()


def test_load_plan_request_invalid_json(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(PlanRequestError) as exc:
        load_plan_request(bad)
    assert exc.value.code == "invalid_request"


def test_terrain_required_without_terrain() -> None:
    request, _ = load_plan_request(SYNTHETIC)
    broken = deepcopy(request)
    del broken["terrain"]
    with pytest.raises(PlanRequestError) as exc:
        load_plan_request(broken)
    assert exc.value.code == "terrain_required"


def test_l1_l3_terminals_in_meters() -> None:
    request, _ = load_plan_request(SYNTHETIC)
    wgs = load_terminals_wgs84(request)
    crs = resolve_crs_work(request, wgs)
    terminals = project_terminals(wgs, crs)
    assert crs == "EPSG:32637"
    assert len(terminals) == 4
    assert all(t.x_m > 0 and t.y_m > 0 for t in terminals)


def test_load_zones_inline() -> None:
    request, _ = load_plan_request(SYNTHETIC)
    wgs = load_terminals_wgs84(request)
    crs = resolve_crs_work(request, wgs)
    zones = load_zones(request, base_dir=FIXTURES, crs_work=crs)
    assert len(zones) == 2
    assert {z.mode for z in zones} == {"ban", "penalty"}


def test_load_zones_from_shp() -> None:
    request, _ = load_plan_request(SYNTHETIC_SHP)
    wgs = load_terminals_wgs84(request)
    crs = resolve_crs_work(request, wgs)
    zones_shp = load_zones(request, base_dir=FIXTURES, crs_work=crs)
    request_inline, _ = load_plan_request(SYNTHETIC)
    zones_inline = load_zones(request_inline, base_dir=FIXTURES, crs_work=crs)
    assert len(zones_shp) == 2
    by_id_shp = {z.id: z for z in zones_shp}
    by_id_inl = {z.id: z for z in zones_inline}
    for zone_id in ("ban-1", "swamp"):
        assert by_id_shp[zone_id].mode == by_id_inl[zone_id].mode
        assert by_id_shp[zone_id].geometry.area == pytest.approx(
            by_id_inl[zone_id].geometry.area,
            rel=1e-3,
        )


def test_load_corridors_from_shp() -> None:
    request, _ = load_plan_request(SYNTHETIC_SHP)
    wgs = load_terminals_wgs84(request)
    crs = resolve_crs_work(request, wgs)
    lines_shp, mult_shp = load_corridors(request, base_dir=FIXTURES, crs_work=crs)
    request_inline, _ = load_plan_request(SYNTHETIC)
    lines_inl, mult_inl = load_corridors(request_inline, base_dir=FIXTURES, crs_work=crs)
    assert mult_shp == mult_inl == 0.5
    assert lines_shp is not None and lines_inl is not None
    len_shp = sum(line.length for line in lines_shp)
    len_inl = sum(line.length for line in lines_inl)
    assert len_shp == pytest.approx(len_inl, rel=1e-3)


def test_load_local_scene_shp() -> None:
    scene, terminals, options = load_local_scene(SYNTHETIC_SHP, base_dir=FIXTURES)
    scene_inline, terminals_inline, _ = load_local_scene(SYNTHETIC, base_dir=FIXTURES)
    assert len(terminals) == len(terminals_inline) == 4
    assert len(scene.zones) == len(scene_inline.zones) == 2
    assert scene.corridors is not None
    assert len(scene.corridors) == len(scene_inline.corridors)
    assert options.candidate_stride_cells == 8


def test_load_local_scene() -> None:
    scene, terminals, options = load_local_scene(SYNTHETIC, base_dir=FIXTURES)
    assert scene.elevation.shape[0] > 0
    assert scene.elevation.shape[1] > 0
    assert len(terminals) == 4
    assert len(scene.zones) == 2
    assert scene.corridors is not None
    assert options.candidate_stride_cells == 8


def test_clip_elevation_to_bbox() -> None:
    request, _ = load_plan_request(SYNTHETIC)
    wgs = load_terminals_wgs84(request)
    crs = resolve_crs_work(request, wgs)
    terminals = project_terminals(wgs, crs)
    elevation, transform, _ = load_elevation_raster(
        request,
        base_dir=FIXTURES,
        crs_work=crs,
    )
    xs = [t.x_m for t in terminals]
    ys = [t.y_m for t in terminals]
    bbox = (min(xs) - 100, min(ys) - 100, max(xs) + 100, max(ys) + 100)
    clipped, new_transform = clip_elevation_to_bbox(elevation, transform, bbox)
    assert clipped.shape[0] <= elevation.shape[0]
    assert clipped.shape[1] <= elevation.shape[1]
    assert new_transform.a == transform.a


def test_invalid_roles() -> None:
    request, _ = load_plan_request(SYNTHETIC)
    broken = deepcopy(request)
    broken["terminals"][1]["role"] = "start"
    with pytest.raises(PlanRequestError) as exc:
        load_terminals_wgs84(broken)
    assert exc.value.code == "invalid_roles"


def test_optional_roles_no_start_end() -> None:
    request, _ = load_plan_request(EUCLID)
    optional = deepcopy(request)
    for terminal in optional["terminals"]:
        terminal["role"] = "intermediate"
    records = load_terminals_wgs84(optional)
    assert len(records) == len(optional["terminals"])


def test_terminal_in_ban_zone() -> None:
    request, _ = load_plan_request(SYNTHETIC)
    broken = deepcopy(request)
    broken["terminals"][0]["lon"] = 39.0039
    broken["terminals"][0]["lat"] = 55.9438
    with pytest.raises(PlanRequestError) as exc:
        run_plan(broken, base_dir=FIXTURES)
    assert exc.value.code == "terminal_in_ban_zone"


@pytest.mark.slow
def test_run_plan_synthetic_shp() -> None:
    response = run_plan(SYNTHETIC_SHP, base_dir=FIXTURES)
    assert response["project_id"] == "fixture-synthetic-scene-shp"
    assert response["network_tree"]["edges"]
    inline = run_plan(SYNTHETIC, base_dir=FIXTURES)
    assert len(response["network_tree"]["edges"]) == len(inline["network_tree"]["edges"])


@pytest.mark.slow
def test_run_plan_synthetic() -> None:
    response = run_plan(SYNTHETIC, base_dir=FIXTURES)
    assert response["project_id"] == "fixture-synthetic-scene"
    assert response["network_tree"]["edges"]
    assert response["terminals"]
    for edge in response["network_tree"]["edges"]:
        for lon, lat in edge["geometry"]["coordinates"]:
            assert 30.0 <= lon <= 40.0
            assert 50.0 <= lat <= 60.0


def test_load_local_scene_euclid() -> None:
    scene, terminals, options = load_local_scene(EUCLID)
    assert scene.elevation.shape == (1, 1)
    assert scene.zones == []
    assert scene.corridors is None
    assert len(terminals) == 4
    assert options.solver == "steinerpy"


def test_build_euclid_routing_graph() -> None:
    _, terminals, _ = load_local_scene(EUCLID)
    routing, _ = build_euclid_routing_graph(
        terminals,
        euclid_steiner_candidates=False,
    )
    assert routing.graph.number_of_nodes() == 4
    assert routing.graph.number_of_edges() == 6
    for _, _, data in routing.graph.edges(data=True):
        assert data["weight"] == pytest.approx(data["length_m"])

    scene, terminals_z, _ = load_local_scene(EUCLID_ZONES, base_dir=FIXTURES)
    routing_z, _ = build_euclid_routing_graph(
        terminals_z,
        zones=scene.zones,
        euclid_routing="obstacle",
        euclid_steiner_candidates=False,
    )
    assert any(nid.startswith("obstacle:") for nid in routing_z.nodes)
    assert routing_z.graph.number_of_nodes() > len(terminals_z)
    assert not routing_z.skipped_pairs


def test_run_plan_euclid() -> None:
    response = run_plan(EUCLID)
    assert response["project_id"] == "fixture-euclid-scene"
    assert response["mode"] == "euclid"
    assert response["network_tree"]["edges"]
    assert "max_slope_deg" not in response["metrics"]


def test_run_plan_euclid_ban_changes_route() -> None:
    base = json.loads(EUCLID.read_text(encoding="utf-8"))
    req = deepcopy(base)
    req["terrain"] = {
        "zones": [
            {
                "id": "ban-mid-north",
                "mode": "ban",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [39.0054, 55.94415],
                            [39.0059, 55.94415],
                            [39.0059, 55.94445],
                            [39.0054, 55.94445],
                            [39.0054, 55.94415],
                        ]
                    ],
                },
            }
        ]
    }
    plain = run_plan(EUCLID)
    with_ban = run_plan(req)
    plain_len = sum(e["length_m"] for e in plain["network_tree"]["edges"])
    ban_len = sum(e["length_m"] for e in with_ban["network_tree"]["edges"])
    assert ban_len > plain_len
    assert with_ban["metrics"]["total_cost"] < 1e9
