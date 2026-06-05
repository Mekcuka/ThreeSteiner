#!/usr/bin/env python3
"""Compare n09 scenarios (terminals with start/end roles) and write SVG/HTML."""

from __future__ import annotations

import html
import json
import math
import sys
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "examples" / "by_terminal_count" / "compare_n09"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from demo_terminal_counts import (  # noqa: E402
    SEGMENT_SPACING_M,
    ZIGZAG_AMPLITUDE_M,
    build_request,
    half_span_m,
    run_plan,
    terminal_lonlat,
)
from network_planner.geo.projection import LocalProjection  # noqa: E402
from network_planner.plan.pipeline import plan_from_request  # noqa: E402
from network_planner.schemas.io import (  # noqa: E402
    PlanOptions,
    PlanRequest,
    PlanResponse,
    SteinerEdgeOut,
    SteinerPointOut,
    SteinerTreeOut,
    TerminalInput,
    TerminalResultOut,
)
from network_planner.steiner.point4 import steiner_tree_4  # noqa: E402

N = 9


def _metrics(resp: PlanResponse) -> dict:
    return {
        "tree_m": round(resp.steiner_tree.length_m, 1),
        "total_m": round(resp.total_length_m, 1),
        "steiner_points": len(resp.steiner_tree.steiner_points),
        "tree_edges": len(resp.steiner_tree.edges),
        "warnings": resp.warnings,
    }


def _plan(req: PlanRequest) -> PlanResponse:
    return plan_from_request(req)


def scenario_a() -> tuple[str, str, PlanRequest, PlanResponse]:
    _, resp, req = run_plan(N)
    return "A", "baseline n09 (9 terminals, start/end roles)", req, resp


def scenario_b() -> tuple[str, str, PlanRequest, PlanResponse]:
    _, resp, req = run_plan(6)
    return "B", "fewer terminals (n=6)", req, resp


def scenario_c() -> tuple[str, str, PlanRequest, PlanResponse]:
    _, resp, req = run_plan(12)
    return "C", "more terminals (n=12)", req, resp


def scenario_d() -> tuple[str, str, PlanRequest, PlanResponse]:
    """Shift middle terminal off zigzag — more Steiner geometry."""
    req = build_request(N)
    proj = LocalProjection.from_points(
        [t.lon for t in req.terminals], [t.lat for t in req.terminals]
    )
    mid = len(req.terminals) // 2
    lon, lat = req.terminals[mid].lon, req.terminals[mid].lat
    x, y = proj.to_local(lon, lat)
    lon2, lat2 = proj.to_wgs84(x, y + 8000.0)
    t = req.terminals[mid]
    req.terminals[mid] = TerminalInput(
        id=t.id, type=t.type, role=t.role, lon=lon2, lat=lat2
    )
    return "D", "middle terminal +8 km off route", req, _plan(req)


def scenario_e() -> tuple[str, str, PlanRequest, PlanResponse]:
    req = build_request(N)
    start = next(t for t in req.terminals if t.role == "start")
    req.terminals[1] = TerminalInput(
        id=uuid4(),
        type="oil_pad",
        role="intermediate",
        lon=start.lon,
        lat=start.lat,
    )
    return "E", "intermediate colocated with start", req, _plan(req)


def scenario_f() -> tuple[str, str, PlanRequest, PlanResponse]:
    _, resp, req = run_plan(15)
    return "F", "n=15 (heuristic SMT warning)", req, resp


def scenario_g() -> tuple[str, str, PlanRequest, PlanResponse]:
    req = build_request(N)
    proj = LocalProjection.from_points(
        [t.lon for t in req.terminals], [t.lat for t in req.terminals]
    )
    amp = ZIGZAG_AMPLITUDE_M * 3

    def bump(lon: float, lat: float, idx: int) -> tuple[float, float]:
        x, _y = proj.to_local(lon, lat)
        sign = 1.0 if idx % 2 == 0 else -1.0
        return proj.to_wgs84(x, sign * amp)

    for i, t in enumerate(req.terminals):
        t.lon, t.lat = bump(t.lon, t.lat, i)
    return "G", "zigzag amplitude x3 (3 km)", req, _plan(req)


def scenario_h() -> tuple[str, str, PlanRequest, PlanResponse]:
    n = N
    proj = LocalProjection.from_points([37.62], [55.75])
    span = half_span_m(n) * (2000.0 / SEGMENT_SPACING_M)

    def pt(index: int) -> tuple[float, float]:
        x = -span + (2 * span) * index / (n - 1)
        sign = 1.0 if index % 2 == 0 else -1.0
        return proj.to_wgs84(x, sign * ZIGZAG_AMPLITUDE_M)

    terminals: list[TerminalInput] = []
    for i in range(n):
        if i == 0:
            role = "start"
        elif i == n - 1:
            role = "end"
        else:
            role = "intermediate"
        lon, lat = pt(i)
        terminals.append(
            TerminalInput(id=uuid4(), type="oil_pad", role=role, lon=lon, lat=lat)
        )
    req = PlanRequest(terminals=terminals, options=PlanOptions(max_points=100))
    return "H", "segment spacing 2 km", req, _plan(req)


def _response_from_local(
    terminals: list[TerminalInput],
    edges_local: list[tuple[str, str, tuple[float, float], tuple[float, float]]],
    steiner_local: dict[str, tuple[float, float]],
) -> PlanResponse:
    lons = [t.lon for t in terminals]
    lats = [t.lat for t in terminals]
    proj = LocalProjection.from_points(lons, lats)

    length = 0.0
    edges_out: list[SteinerEdgeOut] = []
    for a, b, pa, pb in edges_local:
        length += math.hypot(pb[0] - pa[0], pb[1] - pa[1])
        lon_a, lat_a = proj.to_wgs84(pa[0], pa[1])
        lon_b, lat_b = proj.to_wgs84(pb[0], pb[1])
        edges_out.append(
            SteinerEdgeOut(
                from_id=a,
                to_id=b,
                coordinates=[[lon_a, lat_a], [lon_b, lat_b]],
            )
        )

    sp_out = [
        SteinerPointOut(id=sid, lon=lon, lat=lat)
        for sid, (lon, lat) in (
            (s, proj.to_wgs84(steiner_local[s][0], steiner_local[s][1]))
            for s in steiner_local
        )
    ]

    terminals_out: list[TerminalResultOut] = []
    for t in terminals:
        gid = f"terminal:{t.id}"
        attached, edge_len = gid, 0.0
        for a, b, pta, ptb in edges_local:
            if a == gid:
                attached = b
                loc = proj.to_local(t.lon, t.lat)
                edge_len = math.hypot(loc[0] - pta[0], loc[1] - pta[1])
                break
            if b == gid:
                attached = a
                loc = proj.to_local(t.lon, t.lat)
                edge_len = math.hypot(loc[0] - ptb[0], loc[1] - ptb[1])
                break
        terminals_out.append(
            TerminalResultOut(
                id=t.id,
                type=t.type,
                role=t.role,
                lon=t.lon,
                lat=t.lat,
                attached_to=attached,
                via="tree",
                length_m=round(edge_len, 3),
            )
        )

    return PlanResponse(
        steiner_tree=SteinerTreeOut(
            edges=edges_out,
            steiner_points=sp_out,
            length_m=round(length, 3),
        ),
        terminals=terminals_out,
        warnings=[],
        total_length_m=round(length, 3),
    )


def steiner_sweep_real(k: int) -> tuple[PlanRequest, PlanResponse] | None:
    """Real planner: St=0 (n=2), St=1 (n>=3 zigzag), St=2 (n=4..5)."""
    if k == 0:
        _, resp, req = run_plan(2)
        return req, resp
    if k == 1:
        _, resp, req = run_plan(3)
        return req, resp
    if k == 2:
        _, resp, req = run_plan(4)
        return req, resp
    return None


def steiner_sweep_clusters(k: int) -> tuple[PlanRequest, PlanResponse]:
    """k Steiner points via m=k/2 disjoint 4-terminal full SMT clusters (k even, 4..20)."""
    if k < 4 or k % 2 != 0:
        raise ValueError("cluster sweep requires even k >= 4")
    m = k // 2
    cluster_gap = 12000.0
    square = 900.0
    amp = 700.0
    proj = LocalProjection.from_points([37.62], [55.75])

    terminals: list[TerminalInput] = []
    edges_local: list[tuple[str, str, tuple[float, float], tuple[float, float]]] = []
    steiner_local: dict[str, tuple[float, float]] = {}
    bridge_ids: list[str] = []

    for c in range(m):
        cx = c * cluster_gap
        y_sign = 1.0 if c % 2 == 0 else -1.0
        local_pts = [
            (cx, y_sign * amp),
            (cx + square, y_sign * amp),
            (cx + square, -y_sign * amp),
            (cx, -y_sign * amp),
        ]
        t_ids: list[UUID] = []
        for pt in local_pts:
            lon, lat = proj.to_wgs84(pt[0], pt[1])
            role = "intermediate"
            t_ids.append(uuid4())
            terminals.append(
                TerminalInput(
                    id=t_ids[-1],
                    type="oil_pad",
                    role=role,
                    lon=lon,
                    lat=lat,
                )
            )

        gids = [f"terminal:{uid}" for uid in t_ids]
        tree4 = steiner_tree_4(gids, local_pts)
        rename: dict[str, str] = {}
        for i, (old, pt) in enumerate(tree4.steiner_points.items()):
            new = f"steiner:{c}:{i}"
            rename[old] = new
            steiner_local[new] = pt
        for a, b, pa, pb in tree4.edges:
            edges_local.append((rename.get(a, a), rename.get(b, b), pa, pb))
        bridge_ids.append(rename["steiner:0"])

    terminals[0] = TerminalInput(
        id=terminals[0].id,
        type=terminals[0].type,
        role="start",
        lon=terminals[0].lon,
        lat=terminals[0].lat,
    )
    terminals[-1] = TerminalInput(
        id=terminals[-1].id,
        type=terminals[-1].type,
        role="end",
        lon=terminals[-1].lon,
        lat=terminals[-1].lat,
    )

    for i in range(len(bridge_ids) - 1):
        a, b = bridge_ids[i], bridge_ids[i + 1]
        pa, pb = steiner_local[a], steiner_local[b]
        edges_local.append((a, b, pa, pb))

    req = PlanRequest(terminals=terminals, options=PlanOptions(max_points=200))
    return req, _response_from_local(terminals, edges_local, steiner_local)


def steiner_sweep_chain(k: int) -> tuple[PlanRequest, PlanResponse]:
    """Chain of k Steiner points with k+2 terminals (odd k >= 3)."""
    spacing = 5000.0
    amp = 1000.0
    proj = LocalProjection.from_points([37.62], [55.75])
    steiner_local = {f"steiner:{i}": (spacing * (i + 1), 0.0) for i in range(k)}
    terminals: list[TerminalInput] = []
    n_term = k + 2
    for i in range(n_term):
        role = "start" if i == 0 else ("end" if i == n_term - 1 else "intermediate")
        x = i * spacing
        y = amp if i % 2 == 0 else -amp
        lon, lat = proj.to_wgs84(x, y)
        terminals.append(
            TerminalInput(id=uuid4(), type="oil_pad", role=role, lon=lon, lat=lat)
        )

    edges_local: list[tuple[str, str, tuple[float, float], tuple[float, float]]] = []
    for i in range(k - 1):
        a, b = f"steiner:{i}", f"steiner:{i + 1}"
        edges_local.append((a, b, steiner_local[a], steiner_local[b]))

    for i, t in enumerate(terminals):
        gid = f"terminal:{t.id}"
        si = min(max(i - 1, 0), k - 1)
        sid = f"steiner:{si}"
        tloc = proj.to_local(t.lon, t.lat)
        edges_local.append((gid, sid, tloc, steiner_local[sid]))

    req = PlanRequest(terminals=terminals, options=PlanOptions(max_points=100))
    return req, _response_from_local(terminals, edges_local, steiner_local)


def steiner_sweep_scenario(k: int) -> tuple[str, str, PlanRequest, PlanResponse, str]:
    """Build scenario with exactly k Steiner points."""
    if k == 1:
        req, resp = steiner_sweep_real(1)  # type: ignore[misc]
        return f"S{k:02d}", f"St={k} real zigzag n=3", req, resp, "plan_from_request"
    if k == 2:
        req, resp = steiner_sweep_real(2)  # type: ignore[misc]
        return f"S{k:02d}", f"St={k} real zigzag n=4", req, resp, "plan_from_request"
    if k % 2 == 0:
        req, resp = steiner_sweep_clusters(k)
        return (
            f"S{k:02d}",
            f"St={k} ({k // 2} clusters x2 Steiner)",
            req,
            resp,
            f"{k // 2} x steiner_tree_4",
        )
    req, resp = steiner_sweep_chain(k)
    return f"S{k:02d}", f"St={k} chain ({k + 2} terminals)", req, resp, "Steiner chain"


def steiner_sweep_all() -> list[tuple[str, str, PlanRequest, PlanResponse, str]]:
    rows: list[tuple[str, str, PlanRequest, PlanResponse, str]] = []
    for k in range(1, 21):
        rows.append(steiner_sweep_scenario(k))
    return rows


def _wide_bar_chart(
    title: str,
    x_labels: list[str],
    values: list[float],
    unit: str,
    color: str,
    *,
    width: int = 720,
) -> str:
    max_v = max(values) or 1
    n = len(values)
    bw = max(8, (width - 60) // max(n, 1) - 2)
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="200">',
        f'<text x="10" y="16" font-size="12" font-weight="bold">{html.escape(title)}</text>',
    ]
    for i, (lab, v) in enumerate(zip(x_labels, values)):
        x = 40 + i * (bw + 2)
        bh = (v / max_v) * 120
        lines.append(
            f'<rect x="{x}" y="{150-bh:.0f}" width="{bw}" height="{bh:.0f}" fill="{color}"/>'
        )
        if i % 2 == 0 or n <= 10:
            lines.append(
                f'<text x="{x+bw/2}" y="165" text-anchor="middle" font-size="8">{lab}</text>'
            )
    lines.append(
        f'<text x="{width-10}" y="190" text-anchor="end" font-size="9" fill="#64748b">'
        f"max={max(values):.0f}{unit}</text>"
    )
    lines.append("</svg>")
    return "\n".join(lines)


def _local_points(
    req: PlanRequest, resp: PlanResponse
) -> dict[str, tuple[float, float]]:
    lons = [t.lon for t in req.terminals]
    lats = [t.lat for t in req.terminals]
    for sp in resp.steiner_tree.steiner_points:
        lons.append(sp.lon)
        lats.append(sp.lat)
    proj = LocalProjection.from_points(lons, lats)
    pts: dict[str, tuple[float, float]] = {}
    for t in req.terminals:
        pts[f"terminal:{t.id}"] = proj.to_local(t.lon, t.lat)
    for sp in resp.steiner_tree.steiner_points:
        pts[sp.id] = proj.to_local(sp.lon, sp.lat)
    return pts


def _to_svg(
    code: str,
    title: str,
    req: PlanRequest,
    resp: PlanResponse,
    metrics: dict,
) -> str:
    pts = _local_points(req, resp)
    xs = [p[0] for p in pts.values()]
    ys = [p[1] for p in pts.values()]
    pad = 800.0
    min_x, max_x = min(xs) - pad, max(xs) + pad
    min_y, max_y = min(ys) - pad, max(ys) + pad
    w, h = 520, 220
    sx = (w - 40) / max(max_x - min_x, 1.0)
    sy = (h - 55) / max(max_y - min_y, 1.0)
    s = min(sx, sy)

    def xy(p: tuple[float, float]) -> tuple[float, float]:
        return (40 + (p[0] - min_x) * s, h - 30 - (p[1] - min_y) * s)

    role_color = {"start": "#dc2626", "end": "#b91c1c", "intermediate": "#2563eb"}

    lines: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
        '<rect width="100%" height="100%" fill="#f8fafc"/>',
        f'<text x="10" y="18" font-size="12" font-family="sans-serif" font-weight="bold">'
        f"{html.escape(code)} — {html.escape(title)}</text>",
    ]

    for edge in resp.steiner_tree.edges:
        if edge.from_id not in pts or edge.to_id not in pts:
            continue
        x1, y1 = xy(pts[edge.from_id])
        x2, y2 = xy(pts[edge.to_id])
        lines.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="#1e293b" stroke-width="2"/>'
        )

    for sid, p in pts.items():
        if sid.startswith("steiner:"):
            x, y = xy(p)
            lines.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="#22c55e"/>')

    for t in req.terminals:
        key = f"terminal:{t.id}"
        if key not in pts:
            continue
        x, y = xy(pts[key])
        col = role_color.get(t.role, "#2563eb")
        r = 6 if t.role in ("start", "end") else 4
        lines.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{col}"/>')

    warn = ", ".join(metrics["warnings"][:2]) if metrics["warnings"] else "ok"
    if len(metrics["warnings"]) > 2:
        warn += "..."
    cap = (
        f"St={metrics['steiner_points']}  edges={metrics['tree_edges']}  "
        f"tree={metrics['tree_m']/1000:.1f}km  total={metrics['total_m']/1000:.1f}km  {warn}"
    )
    lines.append(
        f'<text x="10" y="{h-8}" font-size="10" font-family="monospace" fill="#334155">'
        f"{html.escape(cap)}</text>"
    )
    lines.append(
        '<text x="280" y="32" font-size="9" fill="#64748b">'
        "● start/end  ● intermediate  ● steiner  ─ tree</text>"
    )
    lines.append("</svg>")
    return "\n".join(lines)


def _bar_chart(title: str, labels: list[str], values: list[float], unit: str, color: str) -> str:
    max_v = max(values) or 1
    bw = 48
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="520" height="180">',
        f'<text x="10" y="16" font-size="12" font-weight="bold">{html.escape(title)}</text>',
    ]
    for i, (lab, v) in enumerate(zip(labels, values)):
        x = 30 + i * (bw + 8)
        bh = (v / max_v) * 120
        lines.append(
            f'<rect x="{x}" y="{150-bh:.0f}" width="{bw}" height="{bh:.0f}" fill="{color}"/>'
        )
        lines.append(
            f'<text x="{x+bw/2}" y="165" text-anchor="middle" font-size="9">{lab}</text>'
        )
        lines.append(
            f'<text x="{x+bw/2}" y="{145-bh:.0f}" text-anchor="middle" font-size="8">'
            f"{v:.0f}{unit}</text>"
        )
    lines.append("</svg>")
    return "\n".join(lines)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    scenarios = [
        scenario_a(),
        scenario_b(),
        scenario_c(),
        scenario_d(),
        scenario_e(),
        scenario_f(),
        scenario_g(),
        scenario_h(),
    ]

    rows_html: list[str] = []
    print(f"{'code':<4} {'scenario':<38}  St  edges   tree_km  total_km  warnings")
    print("-" * 88)
    for code, title, req, resp in scenarios:
        m = _metrics(resp)
        wtxt = "—" if not m["warnings"] else f"{len(m['warnings'])}"
        print(
            f"{code:<4} {title:<38} {m['steiner_points']:>3} {m['tree_edges']:>5} "
            f"{m['tree_m']/1000:>8.1f} {m['total_m']/1000:>9.1f}  {wtxt}"
        )
        svg = _to_svg(code, title, req, resp, m)
        (OUT / f"{code.lower()}.svg").write_text(svg, encoding="utf-8")
        rows_html.append(f"<section><h3>{code}. {html.escape(title)}</h3>{svg}</section>")

    base = _metrics(scenarios[0][3])
    labels = [s[0] for s in scenarios]
    vals_st = [_metrics(s[3])["steiner_points"] for s in scenarios]
    vals_total = [_metrics(s[3])["total_m"] / 1000 for s in scenarios]
    charts = _bar_chart("steiner points", labels, vals_st, "", "#22c55e") + _bar_chart(
        "total tree length (km)", labels, vals_total, "km", "#2563eb"
    )
    (OUT / "charts.svg").write_text(charts, encoding="utf-8")

    page = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"/><title>n09 comparison (terminals model)</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 24px; background: #fff; max-width: 960px; }}
section {{ margin-bottom: 28px; border: 1px solid #e2e8f0; padding: 12px; border-radius: 8px; }}
table {{ border-collapse: collapse; margin: 16px 0; width: 100%; }}
th, td {{ border: 1px solid #cbd5e1; padding: 6px 10px; font-size: 13px; }}
th {{ background: #f1f5f9; }}
.note {{ color: #475569; font-size: 14px; line-height: 1.5; }}
</style></head><body>
<h1>Сравнение сценариев n09 (модель: терминалы с role start/end)</h1>
<p class="note">SMT строится по <strong>всем терминалам</strong>. Отдельных nodes и connectors нет.
Первый терминал — <code>start</code>, последний — <code>end</code>.</p>
<p>База A: steiner_points={base['steiner_points']}, tree_edges={base['tree_edges']},
total={base['total_m']/1000:.1f} km</p>
<table>
<tr><th></th><th>St</th><th>edges</th><th>tree km</th><th>total km</th><th>warnings</th></tr>
"""
    for code, title, _, resp in scenarios:
        m = _metrics(resp)
        w = html.escape(", ".join(m["warnings"]) or "—")
        page += (
            f"<tr><td>{code}</td><td>{m['steiner_points']}</td><td>{m['tree_edges']}</td>"
            f"<td>{m['tree_m']/1000:.1f}</td><td>{m['total_m']/1000:.1f}</td><td>{w}</td></tr>"
        )
    page += (
        "</table>"
        + charts
        + "".join(rows_html)
    )

    # --- Steiner points sweep 1..20 ---
    sweep = steiner_sweep_all()
    sweep_rows: list[dict] = []
    sweep_html: list[str] = [
        '<h2>Sweep: steiner_points 1 → 20</h2>',
        '<p class="note">St=1,2 — реальный <code>plan_from_request</code> (зигзаг). '
        "Чётные St≥4 — склейка кластеров <code>steiner_tree_4</code> (2 Steiner на кластер). "
        "Нечётные St≥3 — цепочка Steiner-точек. Длина дерева растёт с числом St.</p>",
        "<table><tr><th>St</th><th>terminals</th><th>edges</th><th>tree km</th>"
        "<th>источник</th></tr>",
    ]
    st_vals: list[float] = []
    len_vals: list[float] = []
    st_labels: list[str] = []

    print("\nSteiner sweep 1..20:")
    print(f"{'St':>3}  {'term':>5}  {'edges':>5}  {'tree_km':>8}  source")
    print("-" * 60)
    for code, title, req, resp, src in sweep:
        m = _metrics(resp)
        assert m["steiner_points"] == int(code[1:]), (
            f"{code} expected St={code[1:]}, got {m['steiner_points']}"
        )
        sweep_rows.append(
            {
                "steiner_points": m["steiner_points"],
                "terminals": len(req.terminals),
                "tree_edges": m["tree_edges"],
                "tree_km": m["tree_m"] / 1000,
                "source": src,
            }
        )
        print(
            f"{m['steiner_points']:>3}  {len(req.terminals):>5}  {m['tree_edges']:>5}  "
            f"{m['tree_m']/1000:>8.1f}  {src}"
        )
        st_vals.append(float(m["steiner_points"]))
        len_vals.append(m["tree_m"] / 1000)
        st_labels.append(str(m["steiner_points"]))
        sweep_html.append(
            f"<tr><td>{m['steiner_points']}</td><td>{len(req.terminals)}</td>"
            f"<td>{m['tree_edges']}</td><td>{m['tree_m']/1000:.1f}</td>"
            f"<td>{html.escape(src)}</td></tr>"
        )
        svg = _to_svg(code, title, req, resp, m)
        (OUT / f"{code.lower()}.svg").write_text(svg, encoding="utf-8")
        if m["steiner_points"] in (1, 2, 4, 10, 20) or m["steiner_points"] % 5 == 0:
            sweep_html.append(
                f"<section><h3>{code}. {html.escape(title)}</h3>{svg}</section>"
            )

    sweep_html.append("</table>")
    sweep_chart = _wide_bar_chart(
        "total tree length vs steiner_points (1..20)",
        st_labels,
        len_vals,
        "km",
        "#2563eb",
    )
    (OUT / "steiner_sweep_chart.svg").write_text(sweep_chart, encoding="utf-8")
    (OUT / "steiner_sweep.json").write_text(
        json.dumps(sweep_rows, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    page += "".join(sweep_html) + sweep_chart + "</body></html>"
    (OUT / "index.html").write_text(page, encoding="utf-8")
    print(f"\nDiagrams: {OUT / 'index.html'}")


if __name__ == "__main__":
    main()
