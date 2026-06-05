"""Planning pipeline: SMT over terminals; start/end are terminal roles."""

from __future__ import annotations

import math
from uuid import UUID

from network_planner.geo.projection import LocalProjection
from network_planner.schemas.io import (
    PlanRequest,
    PlanResponse,
    SteinerEdgeOut,
    SteinerPointOut,
    SteinerTreeOut,
    TerminalResultOut,
)
from network_planner.steiner.solver import solve_steiner_tree
from network_planner.steiner.union_find import UnionFind
from network_planner.steiner.validate import leaf_degree_violations


def _id_terminal(uid: UUID) -> str:
    return f"terminal:{uid}"


def _terminal_attachment(
    tree,
    terminal_graph_id: str,
    local_pt: tuple[float, float],
) -> tuple[str, float]:
    for a, b, pta, ptb in tree.edges:
        if a == terminal_graph_id:
            return b, math.hypot(local_pt[0] - pta[0], local_pt[1] - pta[1])
        if b == terminal_graph_id:
            return a, math.hypot(local_pt[0] - ptb[0], local_pt[1] - ptb[1])
    return terminal_graph_id, 0.0


def plan_from_request(req: PlanRequest) -> PlanResponse:
    warnings: list[str] = []

    lons = [t.lon for t in req.terminals]
    lats = [t.lat for t in req.terminals]
    proj = LocalProjection.from_points(lons, lats)

    graph_ids: list[str] = []
    local_pts: list[tuple[float, float]] = []
    meta: dict[str, tuple[UUID, str, str, float, float]] = {}

    for t in req.terminals:
        gid = _id_terminal(t.id)
        x, y = proj.to_local(t.lon, t.lat)
        graph_ids.append(gid)
        local_pts.append((x, y))
        meta[gid] = (t.id, t.type, t.role, t.lon, t.lat)

    tree_local = solve_steiner_tree(graph_ids, local_pts)
    if tree_local.heuristic:
        warnings.append("smt_heuristic_mst")

    violations = leaf_degree_violations(tree_local.edges, set(graph_ids))
    if violations:
        warnings.append(f"terminal_degree_violation:{len(violations)}")

    steiner_points_out: list[SteinerPointOut] = []
    for sid, (x, y) in tree_local.steiner_points.items():
        lon, lat = proj.to_wgs84(x, y)
        steiner_points_out.append(SteinerPointOut(id=sid, lon=lon, lat=lat))

    edges_out: list[SteinerEdgeOut] = []
    for a, b, pta, ptb in tree_local.edges:
        lon_a, lat_a = proj.to_wgs84(pta[0], pta[1])
        lon_b, lat_b = proj.to_wgs84(ptb[0], ptb[1])
        edges_out.append(
            SteinerEdgeOut(
                from_id=a,
                to_id=b,
                coordinates=[[lon_a, lat_a], [lon_b, lat_b]],
            )
        )

    terminals_out: list[TerminalResultOut] = []
    for gid, (uid, ttype, role, lon, lat) in meta.items():
        loc = proj.to_local(lon, lat)
        attached, edge_len = _terminal_attachment(tree_local, gid, loc)
        terminals_out.append(
            TerminalResultOut(
                id=uid,
                type=ttype,
                role=role,
                lon=lon,
                lat=lat,
                attached_to=attached,
                via="tree",
                length_m=round(edge_len, 3),
            )
        )

    start_id = _id_terminal(next(t.id for t in req.terminals if t.role == "start"))
    end_id = _id_terminal(next(t.id for t in req.terminals if t.role == "end"))
    if not _connected(start_id, end_id, tree_local):
        warnings.append("start_end_not_connected")

    return PlanResponse(
        steiner_tree=SteinerTreeOut(
            edges=edges_out,
            steiner_points=steiner_points_out,
            length_m=round(tree_local.length_m, 3),
        ),
        terminals=terminals_out,
        warnings=warnings,
        total_length_m=round(tree_local.length_m, 3),
    )


def _connected(start: str, end: str, tree) -> bool:
    vertices: list[str] = []
    v_index: dict[str, int] = {}

    def add_vertex(v: str) -> None:
        if v not in v_index:
            v_index[v] = len(vertices)
            vertices.append(v)

    for a, b, _, _ in tree.edges:
        add_vertex(a)
        add_vertex(b)
    for sid in tree.steiner_points:
        add_vertex(sid)

    uf = UnionFind(len(vertices))

    def union_ids(a: str, b: str) -> None:
        if a in v_index and b in v_index:
            uf.union(v_index[a], v_index[b])

    for a, b, _, _ in tree.edges:
        union_ids(a, b)

    if start not in v_index or end not in v_index:
        return False
    return uf.find(v_index[start]) == uf.find(v_index[end])
