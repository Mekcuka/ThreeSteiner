"""Tests for GeoPackage export (этап 7, 7.7)."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd

from topo_network.export import export_plan_response_gpkg
from topo_network.pipeline import run_plan

FIXTURES = Path(__file__).resolve().parent / "fixtures"
EUCLID = FIXTURES / "plan_request_euclid.json"


def test_export_plan_response_gpkg(tmp_path: Path) -> None:
    response = run_plan(EUCLID)
    out = tmp_path / "result.gpkg"
    export_plan_response_gpkg(out, response)

    assert out.is_file()
    edges = gpd.read_file(out, layer="network_edges")
    steiner = gpd.read_file(out, layer="steiner_points")
    terminals = gpd.read_file(out, layer="terminals")

    assert len(edges) == len(response["network_tree"]["edges"])
    assert len(steiner) == len(response["network_tree"]["steiner_points"])
    assert len(terminals) == len(response["terminals"])
    assert edges.crs.to_string() == "EPSG:4326"
    assert "length_m" in edges.columns
    assert "terminal_id" in terminals.columns
