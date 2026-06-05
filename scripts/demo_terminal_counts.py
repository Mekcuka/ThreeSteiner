#!/usr/bin/env python3
"""Demo: zigzag terminals; first=start, last=end; export GeoJSON."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from network_planner.geo.projection import LocalProjection
from network_planner.plan.pipeline import plan_from_request
from network_planner.schemas.io import (
    PlanOptions,
    PlanRequest,
    PlanResponse,
    TerminalInput,
)

COUNTS = [2, 3, 4, 5, 6, 7, 8, 9, 15]
CENTER_LON, CENTER_LAT = 37.62, 55.75
SEGMENT_SPACING_M = 5000.0
ZIGZAG_AMPLITUDE_M = 1000.0
LAYOUT = "zigzag"


def _proj() -> LocalProjection:
    return LocalProjection.from_points([CENTER_LON], [CENTER_LAT])


def half_span_m(n: int) -> float:
    if n <= 1:
        return 0.0
    return SEGMENT_SPACING_M * (n - 1) / 2.0


def terminal_lonlat(n: int, index: int) -> tuple[float, float]:
    proj = _proj()
    span = half_span_m(n)
    if n == 1:
        x = 0.0
    else:
        x = -span + (2 * span) * index / (n - 1)
    sign = 1.0 if index % 2 == 0 else -1.0
    y = sign * ZIGZAG_AMPLITUDE_M
    return proj.to_wgs84(x, y)


def build_request(n_terminals: int) -> PlanRequest:
    terminals: list[TerminalInput] = []
    for i in range(n_terminals):
        if i == 0:
            role = "start"
        elif i == n_terminals - 1:
            role = "end"
        else:
            role = "intermediate"
        lon, lat = terminal_lonlat(n_terminals, i)
        terminals.append(
            TerminalInput(
                id=uuid4(),
                type="oil_pad",
                role=role,
                lon=lon,
                lat=lat,
            )
        )
    return PlanRequest(
        project_id=uuid4(),
        terminals=terminals,
        options=PlanOptions(max_points=100),
    )


def response_to_geojson(
    resp: PlanResponse, req: PlanRequest, n_terminals: int
) -> dict:
    features: list[dict] = []

    for t in req.terminals:
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [t.lon, t.lat]},
                "properties": {
                    "id": str(t.id),
                    "type": t.type,
                    "role": t.role,
                    "kind": "terminal",
                },
            }
        )

    for sp in resp.steiner_tree.steiner_points:
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [sp.lon, sp.lat],
                },
                "properties": {"id": sp.id, "kind": "steiner"},
            }
        )

    for edge in resp.steiner_tree.edges:
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": edge.coordinates,
                },
                "properties": {
                    "from": edge.from_id,
                    "to": edge.to_id,
                    "kind": "backbone",
                },
            }
        )

    return {
        "type": "FeatureCollection",
        "properties": {
            "layout": LAYOUT,
            "n_terminals": len(req.terminals),
            "segment_spacing_m": SEGMENT_SPACING_M,
            "half_span_m": half_span_m(n_terminals),
            "zigzag_amplitude_m": ZIGZAG_AMPLITUDE_M,
            "backbone_length_m": resp.steiner_tree.length_m,
            "total_length_m": resp.total_length_m,
            "warnings": resp.warnings,
        },
        "features": features,
    }


def run_plan(n_terminals: int) -> tuple[dict, PlanResponse, PlanRequest]:
    req = build_request(n_terminals)
    resp = plan_from_request(req)
    report = {
        "n_terminals": n_terminals,
        "layout": LAYOUT,
        "segment_spacing_m": SEGMENT_SPACING_M,
        "half_span_m": half_span_m(n_terminals),
        "zigzag_amplitude_m": ZIGZAG_AMPLITUDE_M,
        "backbone_length_m": resp.steiner_tree.length_m,
        "total_length_m": resp.total_length_m,
        "warnings": resp.warnings,
        "steiner_points": len(resp.steiner_tree.steiner_points),
        "backbone_edges": len(resp.steiner_tree.edges),
    }
    return report, resp, req


def main() -> None:
    out_dir = ROOT / "examples" / "by_terminal_count"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"Terminals zigzag, roles start/end, {SEGMENT_SPACING_M / 1000:.0f} km spacing, "
        f"+/-{ZIGZAG_AMPLITUDE_M / 1000:.0f} km lateral\n"
    )
    print(f"{'n':>3}  {'backbone':>10}  {'edges':>5}  {'St':>3}  warnings")
    print("-" * 55)

    reports = []
    for n in COUNTS:
        rep, resp, req = run_plan(n)
        reports.append(rep)
        w = ",".join(rep["warnings"]) if rep["warnings"] else "-"
        print(
            f"{n:>3}  {rep['backbone_length_m']:>10.1f}  "
            f"{rep['backbone_edges']:>5}  {rep['steiner_points']:>3}  {w}"
        )

        geo = response_to_geojson(resp, req, n)
        (out_dir / f"n{n:02d}.geojson").write_text(
            json.dumps(geo, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (out_dir / f"n{n:02d}.json").write_text(
            json.dumps(rep, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    (out_dir / "summary.json").write_text(
        json.dumps(reports, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nWritten: {out_dir}/n02.geojson ... n15.geojson")


if __name__ == "__main__":
    main()
