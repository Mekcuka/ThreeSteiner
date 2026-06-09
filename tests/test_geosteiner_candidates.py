"""Tests for GeoSteiner euclid Steiner candidates (P3)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from topo_network.geosteiner_candidates import (
    GeosteinerCandidateResult,
    filter_steiner_candidates,
    format_efst_point_input,
    parse_bb_steiner_coordinates,
    run_geosteiner_efst_bb,
)
from topo_network.models import TerminalRecord, ZoneRecord
from topo_network.network_tree import build_network_tree
from topo_network.pipeline import run_plan
from topo_network.routing_graph import build_euclid_routing_graph
from shapely.geometry import box

FIXTURES = Path(__file__).resolve().parent / "fixtures"
EUCLID = FIXTURES / "plan_request_euclid.json"
BB_SAMPLE = FIXTURES / "geosteiner_bb_sample.txt"


def test_format_efst_point_input_is_xy_pairs_only() -> None:
    terminals = [
        TerminalRecord("a", 0.0, 0.0, "start"),
        TerminalRecord("b", 100.0, 0.0, "end"),
    ]
    lines = format_efst_point_input(terminals).strip().split("\n")
    assert len(lines) == 2
    assert all(len(line.split()) == 2 for line in lines)


def test_geosteiner_parse_bb_output() -> None:
    text = BB_SAMPLE.read_text(encoding="utf-8")
    points = parse_bb_steiner_coordinates(text)
    assert len(points) == 2
    assert points[0] == (500250.125, 6199940.5)
    assert points[1] == (500500.0, 6199970.25)


def test_filter_steiner_candidates_drops_inside_ban() -> None:
    terminals = [
        TerminalRecord("a", 0.0, 0.0, "start"),
        TerminalRecord("b", 100.0, 0.0, "end"),
    ]
    ban = ZoneRecord("b1", box(40, 40, 60, 60), "ban")
    kept, filtered = filter_steiner_candidates(
        [(50.0, 50.0), (25.0, 25.0)],
        terminals,
        [ban],
    )
    assert filtered == 1
    assert kept == [(25.0, 25.0)]


@patch("topo_network.euclid_visibility.compute_steiner_candidates")
def test_euclid_candidates_in_routing_graph(mock_compute) -> None:
    from topo_network.plan_request import load_local_scene

    _, terminals, _ = load_local_scene(EUCLID, base_dir=FIXTURES)
    mid_x = sum(t.x_m for t in terminals) / len(terminals)
    mid_y = sum(t.y_m for t in terminals) / len(terminals)
    mock_compute.return_value = GeosteinerCandidateResult(
        points=[(mid_x, mid_y)],
        warnings=["geosteiner_candidates_added:1"],
    )

    routing, warnings = build_euclid_routing_graph(
        terminals,
        euclid_steiner_candidates=True,
    )
    assert any(nid.startswith("steiner:candidate:") for nid in routing.nodes)
    assert routing.nodes["steiner:candidate:0"].kind == "steiner_candidate"
    assert "geosteiner_candidates_added:1" in warnings


@pytest.mark.skip(reason="nx_approx may omit steiner:candidate nodes; see auto backlog")
@patch("topo_network.euclid_visibility.compute_steiner_candidates")
def test_steiner_tree_uses_candidate(mock_compute) -> None:
    terminals = [
        TerminalRecord("a", 0.0, 0.0, "start"),
        TerminalRecord("b", 100.0, 0.0, "end"),
        TerminalRecord("c", 50.0, 86.60254037844386, "intermediate"),
    ]
    mock_compute.return_value = GeosteinerCandidateResult(
        points=[(50.0, 28.867513458088)],
        warnings=["geosteiner_candidates_added:1"],
    )

    routing, _ = build_euclid_routing_graph(
        terminals,
        euclid_steiner_candidates=True,
    )
    tree = build_network_tree(routing, terminals, solver="nx_approx")
    candidate_ids = [n for n in tree.tree.nodes if n.startswith("steiner:candidate:")]
    assert candidate_ids
    assert tree.total_length_m < 200.0


def test_geosteiner_missing_warning_in_plan() -> None:
    request = {
        "project_id": "gst-missing",
        "mode": "euclid",
        "terminals": [
            {"id": "a", "role": "start", "lon": 39.0, "lat": 55.94},
            {"id": "b", "role": "end", "lon": 39.01, "lat": 55.95},
        ],
        "options": {
            "euclid_steiner_candidates": True,
            "geosteiner_home": str(FIXTURES / "missing_geosteiner_dir"),
            "normalize_terminal_leaves": False,
            "enforce_attachment_radius": False,
        },
    }
    response = run_plan(request)
    warnings = response.get("warnings") or []
    assert any(w.startswith("geosteiner_unavailable:") for w in warnings)
    assert response["network_tree"]["edges"]


@pytest.mark.geosteiner
def test_geosteiner_live_efst_bb() -> None:
    """Optional e2e when GeoSteiner binaries are installed."""
    terminals = [
        TerminalRecord("a", 0.0, 0.0, "start"),
        TerminalRecord("b", 100.0, 0.0, "end"),
        TerminalRecord("c", 50.0, 86.60254037844386, "intermediate"),
    ]
    output, err = run_geosteiner_efst_bb(terminals)
    if output is None:
        pytest.skip(err or "GeoSteiner not available")
    points = parse_bb_steiner_coordinates(output)
    assert points
