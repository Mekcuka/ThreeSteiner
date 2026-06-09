"""Бенчмарк demo-сцены и сравнение с эталоном (этап 6)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx

from topo_network.adjusted_tree import build_adjusted_tree
from topo_network.cost_surface import build_cost_raster
from topo_network.export import build_plan_response
from topo_network.models import PostProcessOptions
from topo_network.network_tree import build_network_tree
from topo_network.routing_graph import build_routing_graph
from topo_network.validation import run_preflight, terminal_graph_id


@dataclass
class BenchmarkSnapshot:
    scene: str
    preflight_ok: bool
    preflight_warnings: list[str]
    cost_raster: dict[str, Any]
    routing_graph: dict[str, Any]
    network_tree: dict[str, Any]
    adjusted_tree: dict[str, Any]
    plan_metrics: dict[str, Any]
    invariants: dict[str, bool | int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_demo_scene_benchmark(
    *,
    solver: str = "steinerpy",
    connector_max_km: float = 0.05,
) -> BenchmarkSnapshot:
    """Полный прогон пайплайна на синтетической demo-сцене."""
    from demo_scene import make_synthetic_scene

    scene, terminals = make_synthetic_scene()
    cost = build_cost_raster(scene, max_slope_deg=30.0, slope_cost_factor=1.0)
    routing = build_routing_graph(
        cost,
        terminals,
        corridors=scene.corridors,
        candidate_stride_cells=5,
    )
    preflight = run_preflight(
        scene,
        terminals,
        routing,
        raster_checks=True,
        zone_checks=bool(scene.zones),
    )
    tree = build_network_tree(routing, terminals, solver=solver)
    options = PostProcessOptions(
        connector_max_km=connector_max_km,
        normalize_terminal_leaves=True,
        enforce_attachment_radius=True,
    )
    adjusted = build_adjusted_tree(tree, terminals, options=options)
    plan = build_plan_response(
        adjusted,
        project_id="benchmark-demo-scene",
        mode="full",
        solver=tree.solver,
        terminals=terminals,
        crs_work=scene.crs_work,
        metrics_extra={"max_slope_deg": cost.summary()["max_slope_deg"]},
        source_warnings=tree.warnings,
    )

    start_id = terminal_graph_id("t-start")
    end_id = terminal_graph_id("t-end")
    hub_count = sum(1 for n in adjusted.nodes if n.startswith("steiner:hub:"))

    invariants: dict[str, bool | int] = {
        "preflight_ok": preflight.ok,
        "routing_connected": nx.has_path(routing.graph, start_id, end_id),
        "tree_start_end": nx.has_path(tree.tree, start_id, end_id),
        "adjusted_start_end": nx.has_path(adjusted.tree, start_id, end_id),
        "all_terminals_degree_1": all(
            adjusted.tree.degree(tid) == 1 for tid in tree.terminal_ids
        ),
        "hub_count": hub_count,
        "hub_count_min_1": hub_count >= 1,
    }

    return BenchmarkSnapshot(
        scene="demo_scene",
        preflight_ok=preflight.ok,
        preflight_warnings=preflight.warnings,
        cost_raster=cost.summary(),
        routing_graph=routing.summary(),
        network_tree=tree.summary(),
        adjusted_tree=adjusted.summary(),
        plan_metrics=plan["metrics"],
        invariants=invariants,
    )


def load_golden(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_golden(path: Path | str, snapshot: BenchmarkSnapshot | dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = snapshot.to_dict() if isinstance(snapshot, BenchmarkSnapshot) else snapshot
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _compare_numeric(
    path: str,
    expected: float,
    actual: float,
    rel_tol: float,
    abs_tol: float,
) -> list[str]:
    if abs(expected - actual) <= abs_tol:
        return []
    if expected != 0 and abs((actual - expected) / expected) <= rel_tol:
        return []
    return [f"{path}: expected {expected}, got {actual}"]


def compare_to_golden(
    actual: BenchmarkSnapshot | dict[str, Any],
    golden: dict[str, Any],
    *,
    rel_tol: float = 1e-3,
    abs_tol: float = 0.5,
) -> list[str]:
    """Сравнить метрики с эталоном; вернуть список расхождений."""
    act = actual.to_dict() if isinstance(actual, BenchmarkSnapshot) else actual
    diffs: list[str] = []

    for key in ("preflight_ok", "scene"):
        if act.get(key) != golden.get(key):
            diffs.append(f"{key}: expected {golden.get(key)!r}, got {act.get(key)!r}")

    for section in ("cost_raster", "routing_graph", "network_tree", "adjusted_tree"):
        act_sec = act.get(section, {})
        gold_sec = golden.get(section, {})
        for metric, expected in gold_sec.items():
            if metric not in act_sec:
                diffs.append(f"{section}.{metric}: missing in actual")
                continue
            actual_val = act_sec[metric]
            if isinstance(expected, (int, float)) and isinstance(actual_val, (int, float)):
                diffs.extend(
                    _compare_numeric(
                        f"{section}.{metric}",
                        float(expected),
                        float(actual_val),
                        rel_tol,
                        abs_tol,
                    )
                )
            elif expected != actual_val:
                diffs.append(
                    f"{section}.{metric}: expected {expected!r}, got {actual_val!r}"
                )

    for metric, expected in golden.get("plan_metrics", {}).items():
        actual_val = act.get("plan_metrics", {}).get(metric)
        if isinstance(expected, (int, float)) and isinstance(actual_val, (int, float)):
            diffs.extend(
                _compare_numeric(
                    f"plan_metrics.{metric}",
                    float(expected),
                    float(actual_val),
                    rel_tol,
                    abs_tol,
                )
            )
        elif expected != actual_val:
            diffs.append(
                f"plan_metrics.{metric}: expected {expected!r}, got {actual_val!r}"
            )

    for key, expected in golden.get("invariants", {}).items():
        actual_val = act.get("invariants", {}).get(key)
        if expected != actual_val:
            diffs.append(f"invariants.{key}: expected {expected!r}, got {actual_val!r}")

    return diffs
