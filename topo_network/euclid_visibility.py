"""Euclid routing with ban avoidance via visibility graph (no DEM)."""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import networkx as nx
import numpy as np
from shapely.geometry import LineString

from topo_network.euclid_zones import (
    EUCLID_PENALTY_SAMPLE_M,
    edge_blocked_by_ban,
    euclid_edge_weights,
    penalized_edge_weight,
)
from topo_network.geosteiner_candidates import compute_steiner_candidates
from topo_network.models import GraphNode, RoutingGraphResult, TerminalRecord, ZoneRecord

EUCLID_CONTOUR_MAX_VERTS = 36
EUCLID_VISIBILITY_PENALTY_SAMPLES_MAX = 80


def _subsample_contour_coords(coords: list[tuple[float, ...]]) -> list[tuple[float, ...]]:
    """Равномерная децимация контура для routing graph (не для растра)."""
    if len(coords) <= EUCLID_CONTOUR_MAX_VERTS:
        return coords
    n = len(coords)
    step = n / EUCLID_CONTOUR_MAX_VERTS
    return [coords[int(i * step) % n] for i in range(EUCLID_CONTOUR_MAX_VERTS)]


def _visibility_penalty_sample_m(length_m: float) -> float:
    """Шаг сэмплирования penalty при построении visibility/direct графа."""
    if length_m <= 0.0:
        return EUCLID_PENALTY_SAMPLE_M
    return max(EUCLID_PENALTY_SAMPLE_M, length_m / EUCLID_VISIBILITY_PENALTY_SAMPLES_MAX)


@dataclass(frozen=True)
class _VisNode:
    id: str
    x_m: float
    y_m: float
    kind: str  # terminal | obstacle | penalty_contour | steiner_candidate


def _terminal_bbox_m(
    terminals: list[TerminalRecord],
    *,
    buffer_m: float,
) -> tuple[float, float, float, float]:
    xs = [t.x_m for t in terminals]
    ys = [t.y_m for t in terminals]
    return (
        min(xs) - buffer_m,
        min(ys) - buffer_m,
        max(xs) + buffer_m,
        max(ys) + buffer_m,
    )


def _in_bbox(x: float, y: float, bbox: tuple[float, float, float, float]) -> bool:
    xmin, ymin, xmax, ymax = bbox
    return xmin <= x <= xmax and ymin <= y <= ymax


def _dedupe_nodes(nodes: list[_VisNode], *, min_spacing_m: float = 1.0) -> list[_VisNode]:
    kept: list[_VisNode] = []
    for node in nodes:
        if node.kind == "terminal":
            kept.append(node)
            continue
        if any(
            np.hypot(node.x_m - other.x_m, node.y_m - other.y_m) < min_spacing_m
            for other in kept
        ):
            continue
        kept.append(node)
    return kept


def _obstacle_vertices(
    ban_zones: list[ZoneRecord],
    *,
    obstacle_buffer_m: float,
    bbox: tuple[float, float, float, float],
) -> list[_VisNode]:
    nodes: list[_VisNode] = []
    for zone in ban_zones:
        geom = zone.geometry
        if obstacle_buffer_m > 0:
            geom = geom.buffer(obstacle_buffer_m, quad_segs=4)
        if geom.is_empty:
            continue
        polys = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
        for poly in polys:
            coords = _subsample_contour_coords(list(poly.exterior.coords)[:-1])
            for index, (x, y) in enumerate(coords):
                if not _in_bbox(float(x), float(y), bbox):
                    continue
                nodes.append(
                    _VisNode(
                        id=f"obstacle:{zone.id}:{index}",
                        x_m=float(x),
                        y_m=float(y),
                        kind="obstacle",
                    )
                )
    return nodes


def _penalty_vertices(
    penalty_zones: list[ZoneRecord],
    *,
    bbox: tuple[float, float, float, float],
) -> list[_VisNode]:
    """Углы effective-полигона penalty-зоны для обхода по контуру."""
    nodes: list[_VisNode] = []
    for zone in penalty_zones:
        geom = zone.geometry
        if geom.is_empty:
            continue
        polys = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
        for poly in polys:
            coords = _subsample_contour_coords(list(poly.exterior.coords)[:-1])
            for index, (x, y) in enumerate(coords):
                if not _in_bbox(float(x), float(y), bbox):
                    continue
                nodes.append(
                    _VisNode(
                        id=f"penalty:{zone.id}:{index}",
                        x_m=float(x),
                        y_m=float(y),
                        kind="penalty_contour",
                    )
                )
    return nodes


def _steiner_candidate_nodes(
    points: list[tuple[float, float]],
    *,
    bbox: tuple[float, float, float, float],
) -> list[_VisNode]:
    nodes: list[_VisNode] = []
    for index, (x, y) in enumerate(points):
        if not _in_bbox(x, y, bbox):
            continue
        nodes.append(
            _VisNode(
                id=f"steiner:candidate:{index}",
                x_m=x,
                y_m=y,
                kind="steiner_candidate",
            ),
        )
    return nodes


def _collect_vis_nodes(
    terminals: list[TerminalRecord],
    ban_zones: list[ZoneRecord],
    penalty_zones: list[ZoneRecord],
    candidate_points: list[tuple[float, float]],
    *,
    obstacle_buffer_m: float,
    clip_buffer_m: float,
    include_obstacles: bool,
) -> list[_VisNode]:
    bbox = _terminal_bbox_m(terminals, buffer_m=clip_buffer_m)
    nodes: list[_VisNode] = [
        _VisNode(
            id=f"terminal:{t.id}",
            x_m=t.x_m,
            y_m=t.y_m,
            kind="terminal",
        )
        for t in terminals
    ]
    if include_obstacles:
        nodes.extend(
            _obstacle_vertices(
                ban_zones,
                obstacle_buffer_m=obstacle_buffer_m,
                bbox=bbox,
            ),
        )
    if penalty_zones:
        nodes.extend(_penalty_vertices(penalty_zones, bbox=bbox))
    nodes.extend(_steiner_candidate_nodes(candidate_points, bbox=bbox))
    return _dedupe_nodes(nodes)


def build_visibility_graph(
    nodes: list[_VisNode],
    ban_zones: list[ZoneRecord],
    penalty_zones: list[ZoneRecord],
) -> nx.Graph:
    """Полный граф видимости: ребро есть, если отрезок не пересекает ban."""
    graph = nx.Graph()
    for node in nodes:
        graph.add_node(node.id, x_m=node.x_m, y_m=node.y_m, kind=node.kind)

    for a, b in itertools.combinations(nodes, 2):
        line = LineString([(a.x_m, a.y_m), (b.x_m, b.y_m)])
        if ban_zones and edge_blocked_by_ban(line, ban_zones):
            continue
        length_m = float(line.length)
        if penalty_zones:
            weight = penalized_edge_weight(
                line,
                penalty_zones,
                sample_m=_visibility_penalty_sample_m(length_m),
            )
        else:
            weight = length_m
        graph.add_edge(
            a.id,
            b.id,
            weight=weight,
            length_m=length_m,
            geometry=line,
            crosses_ban=False,
        )
    return graph


def _build_direct_graph(
    nodes: list[_VisNode],
    ban_zones: list[ZoneRecord],
    penalty_zones: list[ZoneRecord],
) -> tuple[nx.Graph, list[tuple[str, str, str]]]:
    """Straight-line edges between all nodes (ban → high weight, still present)."""
    graph = nx.Graph()
    skipped_pairs: list[tuple[str, str, str]] = []
    for node in nodes:
        graph.add_node(node.id, x_m=node.x_m, y_m=node.y_m, kind=node.kind)

    for a, b in itertools.combinations(nodes, 2):
        line = LineString([(a.x_m, a.y_m), (b.x_m, b.y_m)])
        length_m = float(line.length)
        weight, length_m, crosses_ban = euclid_edge_weights(
            line,
            ban_zones,
            penalty_zones,
            penalty_sample_m=_visibility_penalty_sample_m(length_m),
        )
        if crosses_ban:
            skipped_pairs.append((a.id, b.id, "ban_forbidden_weight"))
        graph.add_edge(
            a.id,
            b.id,
            weight=weight,
            length_m=length_m,
            geometry=line,
            crosses_ban=crosses_ban,
        )
    return graph, skipped_pairs


def _prune_to_terminal_component(
    graph: nx.Graph,
    nodes: list[_VisNode],
    terminals: list[TerminalRecord],
) -> tuple[nx.Graph, list[_VisNode]]:
    """Drop isolated visibility nodes; keep the component that contains all terminals."""
    if graph.number_of_nodes() == 0:
        return graph, nodes

    terminal_ids = {f"terminal:{t.id}" for t in terminals}
    components = list(nx.connected_components(graph))
    if len(components) == 1:
        return graph, nodes

    viable = [comp for comp in components if terminal_ids.issubset(comp)]
    if not viable:
        return graph, nodes

    keep = max(viable, key=len)
    pruned = graph.subgraph(keep).copy()
    kept_ids = set(pruned.nodes)
    pruned_nodes = [node for node in nodes if node.id in kept_ids]
    return pruned, pruned_nodes


def _vis_nodes_to_catalog(nodes: list[_VisNode]) -> dict[str, GraphNode]:
    return {
        node.id: GraphNode(
            id=node.id,
            x_m=node.x_m,
            y_m=node.y_m,
            kind=node.kind,
        )
        for node in nodes
    }


def build_euclid_visibility_routing_graph(
    terminals: list[TerminalRecord],
    zones: list[ZoneRecord] | None = None,
    *,
    euclid_routing: str = "obstacle",
    obstacle_buffer_m: float = 5.0,
    clip_buffer_m: float = 500.0,
    euclid_steiner_candidates: bool = True,
    geosteiner_home: str | None = None,
    steiner_candidate_spacing_m: float = 1.0,
) -> tuple[RoutingGraphResult, list[str]]:
    """
    Euclid routing graph with optional obstacle vertices and GeoSteiner candidates.

    Returns routing graph suitable for SteinerPy (all junction nodes explicit).
    """
    zone_list = list(zones or [])
    ban_zones = [z for z in zone_list if z.mode == "ban"]
    penalty_zones = [z for z in zone_list if z.mode == "penalty"]

    candidate_result = compute_steiner_candidates(
        terminals,
        ban_zones,
        enabled=euclid_steiner_candidates,
        geosteiner_home=geosteiner_home,
        min_spacing_m=steiner_candidate_spacing_m,
    )
    warnings = list(candidate_result.warnings)

    use_obstacle_vis = euclid_routing == "obstacle" and bool(ban_zones)
    vis_nodes = _collect_vis_nodes(
        terminals,
        ban_zones,
        penalty_zones,
        candidate_result.points,
        obstacle_buffer_m=obstacle_buffer_m,
        clip_buffer_m=clip_buffer_m,
        include_obstacles=use_obstacle_vis,
    )
    vis_nodes = _dedupe_nodes(vis_nodes, min_spacing_m=steiner_candidate_spacing_m)

    if use_obstacle_vis:
        graph = build_visibility_graph(vis_nodes, ban_zones, penalty_zones)
        skipped_pairs: list[tuple[str, str, str]] = []
    else:
        graph, skipped_pairs = _build_direct_graph(vis_nodes, ban_zones, penalty_zones)

    graph, vis_nodes = _prune_to_terminal_component(graph, vis_nodes, terminals)

    return (
        RoutingGraphResult(
            graph=graph,
            nodes=_vis_nodes_to_catalog(vis_nodes),
            skipped_pairs=skipped_pairs,
        ),
        warnings,
    )


def build_euclid_obstacle_routing_graph(
    terminals: list[TerminalRecord],
    zones: list[ZoneRecord] | None = None,
    *,
    obstacle_buffer_m: float = 5.0,
    clip_buffer_m: float = 500.0,
    euclid_steiner_candidates: bool = True,
    geosteiner_home: str | None = None,
    steiner_candidate_spacing_m: float = 1.0,
) -> RoutingGraphResult:
    """Backward-compatible wrapper; warnings discarded (use visibility builder)."""
    result, _ = build_euclid_visibility_routing_graph(
        terminals,
        zones,
        euclid_routing="obstacle",
        obstacle_buffer_m=obstacle_buffer_m,
        clip_buffer_m=clip_buffer_m,
        euclid_steiner_candidates=euclid_steiner_candidates,
        geosteiner_home=geosteiner_home,
        steiner_candidate_spacing_m=steiner_candidate_spacing_m,
    )
    return result
