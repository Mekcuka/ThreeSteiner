"""Tests for demo-scene benchmark (stage 6)."""

from __future__ import annotations

from pathlib import Path

import networkx as nx

from demo_scene import make_synthetic_scene, terminal_node_id
from topo_network.benchmark import (
    compare_to_golden,
    load_golden,
    run_demo_scene_benchmark,
)
from topo_network.validation import run_preflight


ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "examples" / "out" / "benchmark_demo_scene.golden.json"


def test_run_demo_scene_benchmark_invariants():
    snapshot = run_demo_scene_benchmark()
    assert snapshot.preflight_ok
    assert snapshot.invariants["routing_connected"]
    assert snapshot.invariants["all_terminals_degree_1"]
    assert snapshot.invariants["hub_count_min_1"]


def test_preflight_with_routing():
    scene, terminals = make_synthetic_scene()
    from topo_network import build_cost_raster, build_routing_graph

    cost = build_cost_raster(scene)
    routing = build_routing_graph(cost, terminals, corridors=scene.corridors)
    result = run_preflight(scene, terminals, routing)
    assert result.ok
    start_id = terminal_node_id("t-start")
    end_id = terminal_node_id("t-end")
    assert nx.has_path(routing.graph, start_id, end_id)


def test_golden_file_matches_current_pipeline():
    if not GOLDEN.is_file():
        import pytest

        pytest.skip(f"missing golden (dev only): {GOLDEN}")
    snapshot = run_demo_scene_benchmark()
    golden = load_golden(GOLDEN)
    diffs = compare_to_golden(snapshot, golden)
    assert not diffs, "\n".join(diffs)
