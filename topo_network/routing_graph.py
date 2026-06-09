"""Sparse RoutingGraph: узлы-кандидаты + LCP-рёбра (этап 3 / фаза 3)."""

from __future__ import annotations

import itertools

import networkx as nx
import numpy as np
from shapely.geometry import LineString

from topo_network.lcp import (
    cell_to_world,
    least_cost_path,
    snap_to_finite_cell,
    world_to_cell,
)
from topo_network.models import (
    CostRaster,
    GraphNode,
    RoutingGraphResult,
    TerminalRecord,
    ZoneRecord,
)
from topo_network.euclid_zones import (
    EUCLID_BAN_FORBIDDEN_WEIGHT,
    euclid_edge_weights,
)
from topo_network.euclid_visibility import build_euclid_visibility_routing_graph


def _euclidean_m(x0: float, y0: float, x1: float, y1: float) -> float:
    return float(np.hypot(x1 - x0, y1 - y0))


def _sample_corridor_points(
    corridors: list,
    *,
    sample_m: float,
) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for geom in corridors:
        if geom is None:
            continue
        if geom.geom_type == "LineString":
            lines = [geom]
        elif geom.geom_type == "MultiLineString":
            lines = list(geom.geoms)
        else:
            continue
        for line in lines:
            length = line.length
            if length <= 0:
                continue
            step = max(sample_m, 1.0)
            dist = 0.0
            while dist <= length:
                pt = line.interpolate(dist)
                points.append((float(pt.x), float(pt.y)))
                dist += step
    return points


def _grid_candidate_cells(
    cost: np.ndarray,
    *,
    stride: int,
) -> list[tuple[int, int]]:
    rows, cols = cost.shape
    cells: list[tuple[int, int]] = []
    for row in range(0, rows, stride):
        for col in range(0, cols, stride):
            value = cost[row, col]
            if np.isfinite(value) and not np.isinf(value):
                cells.append((row, col))
    return cells


def _add_node(
    nodes: dict[str, GraphNode],
    node: GraphNode,
    *,
    min_spacing_m: float,
) -> bool:
    """Добавить узел; terminal вытесняет близкий non-terminal."""
    to_remove: list[str] = []
    for existing in nodes.values():
        dist = _euclidean_m(existing.x_m, existing.y_m, node.x_m, node.y_m)
        if dist >= min_spacing_m:
            continue
        if node.kind == "terminal" and existing.kind != "terminal":
            to_remove.append(existing.id)
            continue
        return False
    for nid in to_remove:
        del nodes[nid]
    nodes[node.id] = node
    return True


def _collect_nodes(
    cost_raster: CostRaster,
    terminals: list[TerminalRecord],
    *,
    corridors: list | None,
    candidate_stride_cells: int,
    corridor_sample_m: float,
    min_node_spacing_m: float,
) -> tuple[dict[str, GraphNode], list[tuple[str, str, str]]]:
    cost = cost_raster.cost
    transform = cost_raster.transform
    shape = cost.shape
    nodes: dict[str, GraphNode] = {}
    skipped: list[tuple[str, str, str]] = []

    for terminal in terminals:
        rc = world_to_cell(terminal.x_m, terminal.y_m, transform, shape=shape)
        if rc is None:
            skipped.append((terminal.id, terminal.id, "out_of_bounds"))
            continue
        snapped = snap_to_finite_cell(rc[0], rc[1], cost)
        if snapped is None:
            skipped.append((terminal.id, terminal.id, "no_finite_cell"))
            continue
        row, col = snapped
        x_m, y_m = cell_to_world(row, col, transform)
        _add_node(
            nodes,
            GraphNode(
                id=f"terminal:{terminal.id}",
                x_m=x_m,
                y_m=y_m,
                kind="terminal",
                row=row,
                col=col,
            ),
            min_spacing_m=min_node_spacing_m,
        )

    for row, col in _grid_candidate_cells(
        cost, stride=max(1, candidate_stride_cells)
    ):
        x_m, y_m = cell_to_world(row, col, transform)
        _add_node(
            nodes,
            GraphNode(
                id=f"grid:{row}_{col}",
                x_m=x_m,
                y_m=y_m,
                kind="grid",
                row=row,
                col=col,
            ),
            min_spacing_m=min_node_spacing_m,
        )

    if corridors:
        for i, (x_m, y_m) in enumerate(
            _sample_corridor_points(corridors, sample_m=corridor_sample_m)
        ):
            rc = world_to_cell(x_m, y_m, transform, shape=shape)
            if rc is None:
                continue
            snapped = snap_to_finite_cell(rc[0], rc[1], cost)
            if snapped is None:
                continue
            row, col = snapped
            sx, sy = cell_to_world(row, col, transform)
            _add_node(
                nodes,
                GraphNode(
                    id=f"corridor:{i}",
                    x_m=sx,
                    y_m=sy,
                    kind="corridor",
                    row=row,
                    col=col,
                ),
                min_spacing_m=min_node_spacing_m,
            )

    return nodes, skipped


def _should_connect_pair(
    a: GraphNode,
    b: GraphNode,
    *,
    n_nodes: int,
    max_nodes_for_full_lcp: int,
    max_pair_distance_m: float,
) -> bool:
    if a.id == b.id:
        return False
    if n_nodes <= max_nodes_for_full_lcp:
        return True
    return _euclidean_m(a.x_m, a.y_m, b.x_m, b.y_m) <= max_pair_distance_m


def build_routing_graph(
    cost_raster: CostRaster,
    terminals: list[TerminalRecord],
    *,
    corridors: list | None = None,
    candidate_stride_cells: int = 5,
    corridor_sample_m: float = 50.0,
    max_pair_distance_m: float = 2000.0,
    min_node_spacing_m: float = 5.0,
    max_nodes_for_full_lcp: int = 80,
) -> RoutingGraphResult:
    """CostRaster + terminals → sparse RoutingGraph (NetworkX)."""
    nodes, pre_skipped = _collect_nodes(
        cost_raster,
        terminals,
        corridors=corridors,
        candidate_stride_cells=candidate_stride_cells,
        corridor_sample_m=corridor_sample_m,
        min_node_spacing_m=min_node_spacing_m,
    )

    graph = nx.Graph()
    skipped_pairs: list[tuple[str, str, str]] = list(pre_skipped)
    cost = cost_raster.cost
    cell_x, cell_y = cost_raster.cell_size_m
    transform = cost_raster.transform

    for node in nodes.values():
        graph.add_node(
            node.id,
            x_m=node.x_m,
            y_m=node.y_m,
            kind=node.kind,
            row=node.row,
            col=node.col,
        )

    node_list = list(nodes.values())
    n_nodes = len(node_list)

    for a, b in itertools.combinations(node_list, 2):
        if not _should_connect_pair(
            a,
            b,
            n_nodes=n_nodes,
            max_nodes_for_full_lcp=max_nodes_for_full_lcp,
            max_pair_distance_m=max_pair_distance_m,
        ):
            continue

        if a.row is None or a.col is None or b.row is None or b.col is None:
            skipped_pairs.append((a.id, b.id, "missing_cell"))
            continue

        if a.row == b.row and a.col == b.col:
            skipped_pairs.append((a.id, b.id, "same_cell"))
            continue

        result = least_cost_path(
            cost,
            (a.row, a.col),
            (b.row, b.col),
            cell_size_x=cell_x,
            cell_size_y=cell_y,
        )
        if result is None:
            skipped_pairs.append((a.id, b.id, "no_route"))
            continue

        coords = [cell_to_world(r, c, transform) for r, c in result.path_rc]
        geometry = LineString(coords)

        graph.add_edge(
            a.id,
            b.id,
            weight=result.weight,
            length_m=result.length_m,
            geometry=geometry,
        )

    return RoutingGraphResult(
        graph=graph,
        nodes=nodes,
        skipped_pairs=skipped_pairs,
    )


def build_euclid_routing_graph(
    terminals: list[TerminalRecord],
    zones: list[ZoneRecord] | None = None,
    *,
    euclid_routing: str = "direct",
    obstacle_buffer_m: float = 5.0,
    clip_buffer_m: float = 500.0,
    euclid_steiner_candidates: bool = True,
    geosteiner_home: str | None = None,
    steiner_candidate_spacing_m: float = 1.0,
) -> tuple[RoutingGraphResult, list[str]]:
    """Терминалы → euclid-граф; direct = прямые рёбра, obstacle = visibility + ban."""
    return build_euclid_visibility_routing_graph(
        terminals,
        zones,
        euclid_routing=euclid_routing,
        obstacle_buffer_m=obstacle_buffer_m,
        clip_buffer_m=clip_buffer_m,
        euclid_steiner_candidates=euclid_steiner_candidates,
        geosteiner_home=geosteiner_home,
        steiner_candidate_spacing_m=steiner_candidate_spacing_m,
    )
