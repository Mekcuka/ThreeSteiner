#!/usr/bin/env python3
"""Show how report fields (connectors, steiner_points, backbone_edges, warnings) change with inputs."""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from demo_terminal_counts import (  # noqa: E402
    SEGMENT_SPACING_M,
    ZIGZAG_AMPLITUDE_M,
    build_request,
    point_lonlat,
    run_plan,
)
from network_planner.geo.projection import LocalProjection  # noqa: E402
from network_planner.plan.pipeline import plan_from_request  # noqa: E402
from network_planner.schemas.io import (  # noqa: E402
    NodeInput,
    PlanOptions,
    PlanRequest,
    TerminalInput,
)


def _metrics(resp) -> dict:
    return {
        "backbone_m": round(resp.steiner_tree.length_m, 1),
        "total_m": round(resp.total_length_m, 1),
        "connectors": len(resp.connectors),
        "steiner_points": len(resp.steiner_tree.steiner_points),
        "backbone_edges": len(resp.steiner_tree.edges),
        "warnings": ",".join(resp.warnings) if resp.warnings else "—",
    }


def scenario_baseline_n3():
    _, resp, _ = run_plan(3)
    return "A. baseline n03 (3 terminals, 2 nodes)", _metrics(resp)


def scenario_n2_terminals():
    _, resp, _ = run_plan(2)
    return "B. fewer terminals (n=2)", _metrics(resp)


def scenario_n5_terminals():
    _, resp, _ = run_plan(5)
    return "C. more terminals (n=5)", _metrics(resp)


def scenario_3_nodes_backbone():
    """3 nodes на зигзаге → не только start/end."""
    n = 3
    lon0, lat0 = point_lonlat(n, 0)
    lon2, lat2 = point_lonlat(n, 2)
    lon4, lat4 = point_lonlat(n, 4)
    nodes = [
        NodeInput(id=uuid4(), role="start", lon=lon0, lat=lat0),
        NodeInput(id=uuid4(), role="intermediate", lon=lon2, lat=lat2),
        NodeInput(id=uuid4(), role="end", lon=lon4, lat=lat4),
    ]
    terminals = []
    for i in (1, 3):
        lon, lat = point_lonlat(n, i)
        terminals.append(TerminalInput(id=uuid4(), type="oil_pad", lon=lon, lat=lat))
    req = PlanRequest(
        nodes=nodes,
        terminals=terminals,
        options=PlanOptions(max_points=50, connector_max_km=50.0),
    )
    return "D. 3 nodes + 2 terminals on backbone", _metrics(plan_from_request(req))


def scenario_terminal_on_start_node():
    """Терминал в 2 м от start node → via node, без коннектора."""
    req = build_request(3)
    start = next(n for n in req.nodes if n.role == "start")
    req.terminals[0] = TerminalInput(
        id=uuid4(),
        type="oil_pad",
        lon=start.lon,
        lat=start.lat,
    )
    return "E. terminal snapped to start node", _metrics(plan_from_request(req))


def scenario_short_connector_max():
    req = build_request(3)
    req.options = PlanOptions(max_points=50, connector_max_km=0.001)
    return "F. connector_max_km=0.001 (1m limit)", _metrics(plan_from_request(req))


def scenario_wide_zigzag():
    req = build_request(3)
    proj = LocalProjection.from_points(
        [t.lon for t in req.terminals] + [n.lon for n in req.nodes],
        [t.lat for t in req.terminals] + [n.lat for n in req.nodes],
    )
    # увеличить поперечный зигзаг в 3 раза для всех точек
    amp = ZIGZAG_AMPLITUDE_M * 3
    n_t = 3

    def bump(lon: float, lat: float, idx: int) -> tuple[float, float]:
        x, y = proj.to_local(lon, lat)
        sign = 1.0 if idx % 2 == 0 else -1.0
        return proj.to_wgs84(x, sign * amp)

    for i, node in enumerate(req.nodes):
        idx = 0 if node.role == "start" else 4
        node.lon, node.lat = bump(node.lon, node.lat, idx)
    for i, term in enumerate(req.terminals):
        term.lon, term.lat = bump(term.lon, term.lat, i + 1)
    return "G. zigzag amplitude x3 (3 km)", _metrics(plan_from_request(req))


def scenario_tight_spacing():
    """Шаг 2 км вместо 5 км — короче магистраль и коннекторы."""
    n = 3
    proj = LocalProjection.from_points([37.62], [55.75])
    span = 2000.0 * (n + 1) / 2.0
    total = n + 2

    def pt(index: int) -> tuple[float, float]:
        x = -span + (2 * span) * index / (total - 1)
        sign = 1.0 if index % 2 == 0 else -1.0
        return proj.to_wgs84(x, sign * ZIGZAG_AMPLITUDE_M)

    nodes = [
        NodeInput(id=uuid4(), role="start", lon=pt(0)[0], lat=pt(0)[1]),
        NodeInput(id=uuid4(), role="end", lon=pt(n + 1)[0], lat=pt(n + 1)[1]),
    ]
    terminals = [
        TerminalInput(id=uuid4(), type="oil_pad", lon=pt(i)[0], lat=pt(i)[1])
        for i in range(1, n + 1)
    ]
    req = PlanRequest(
        nodes=nodes,
        terminals=terminals,
        options=PlanOptions(max_points=50, connector_max_km=50.0),
    )
    return "H. segment spacing 2 km not 5 km", _metrics(plan_from_request(req))


def main() -> None:
    rows = [
        scenario_baseline_n3(),
        scenario_n2_terminals(),
        scenario_n5_terminals(),
        scenario_3_nodes_backbone(),
        scenario_terminal_on_start_node(),
        scenario_short_connector_max(),
        scenario_wide_zigzag(),
        scenario_tight_spacing(),
    ]

    print("Vhod -> plan_from_request -> polya otcheta (kak n03.json:9-13)\n")
    print(f"{'Сценарий':<48} {'conn':>4} {'St':>3} {'edges':>5}  {'backbone':>10}  {'total':>10}  warnings")
    print("-" * 105)
    for label, m in rows:
        print(
            f"{label:<48} {m['connectors']:>4} {m['steiner_points']:>3} {m['backbone_edges']:>5}  "
            f"{m['backbone_m']:>10.1f}  {m['total_m']:>10.1f}  {m['warnings']}"
        )

    print(
        "\nNote: editing connectors/steiner_points/backbone_edges in n03.json "
        "without re-plan does nothing - outputs only."
    )
    print(f"Базовые константы демо: SEGMENT_SPACING_M={SEGMENT_SPACING_M}, ZIGZAG_AMPLITUDE_M={ZIGZAG_AMPLITUDE_M}")


if __name__ == "__main__":
    main()
