"""Fixed outgoing vector (bearing + length) from terminal to routing graph."""

from __future__ import annotations

import math

import networkx as nx
from shapely.geometry import LineString, Point

from topo_network.euclid_zones import (
    edge_blocked_by_ban,
    euclid_edge_weights,
    penalized_edge_weight,
)
from topo_network.lcp import cell_to_world, least_cost_path, snap_to_finite_cell, world_to_cell
from topo_network.models import (
    CostRaster,
    GraphNode,
    RoutingGraphResult,
    TerminalRecord,
    ZoneRecord,
)


def fixed_exit_node_id(terminal_id: str) -> str:
    return f"steiner:fixed_exit:{terminal_id}"


def _terminal_graph_id(terminal_id: str) -> str:
    return f"terminal:{terminal_id}"


def has_fixed_outgoing(terminal: TerminalRecord) -> bool:
    return (
        terminal.outgoing_bearing_deg is not None
        and terminal.outgoing_length_m is not None
    )


def compute_fixed_exit_xy(terminal: TerminalRecord) -> tuple[float, float]:
    """Geographic bearing: 0°=north (+Y), 90°=east (+X), clockwise."""
    if not has_fixed_outgoing(terminal):
        raise ValueError(f"terminal {terminal.id} has no outgoing spec")
    bearing_deg = float(terminal.outgoing_bearing_deg) % 360.0
    length_m = float(terminal.outgoing_length_m)
    rad = math.radians(bearing_deg)
    exit_x = terminal.x_m + length_m * math.sin(rad)
    exit_y = terminal.y_m + length_m * math.cos(rad)
    return exit_x, exit_y


def _remove_incident_edges(graph: nx.Graph, node_id: str) -> None:
    for neighbor in list(graph.neighbors(node_id)):
        graph.remove_edge(node_id, neighbor)


def _add_euclid_edges_from_exit(
    graph: nx.Graph,
    exit_id: str,
    exit_x: float,
    exit_y: float,
    ban_zones: list[ZoneRecord],
    penalty_zones: list[ZoneRecord],
    *,
    use_obstacle_ban: bool,
) -> None:
    for other_id, data in list(graph.nodes(data=True)):
        if other_id == exit_id:
            continue
        ox = float(data.get("x_m", 0.0))
        oy = float(data.get("y_m", 0.0))
        line = LineString([(exit_x, exit_y), (ox, oy)])
        if use_obstacle_ban and ban_zones and edge_blocked_by_ban(line, ban_zones):
            continue
        if ban_zones and not use_obstacle_ban:
            weight, length_m, crosses_ban = euclid_edge_weights(
                line,
                ban_zones,
                penalty_zones,
            )
        elif penalty_zones:
            length_m = float(line.length)
            weight = penalized_edge_weight(line, penalty_zones)
            crosses_ban = False
        else:
            length_m = float(line.length)
            weight = length_m
            crosses_ban = False
        graph.add_edge(
            exit_id,
            other_id,
            weight=weight,
            length_m=length_m,
            geometry=line,
            crosses_ban=crosses_ban,
        )


def _add_lcp_edges_from_exit(
    graph: nx.Graph,
    routing: RoutingGraphResult,
    exit_node: GraphNode,
    cost_raster: CostRaster,
) -> None:
    cost = cost_raster.cost
    transform = cost_raster.transform
    cell_x, cell_y = cost_raster.cell_size_m
    if exit_node.row is None or exit_node.col is None:
        return

    for other_id, other in routing.nodes.items():
        if other_id == exit_node.id:
            continue
        if other.row is None or other.col is None:
            continue
        if exit_node.row == other.row and exit_node.col == other.col:
            continue
        result = least_cost_path(
            cost,
            (exit_node.row, exit_node.col),
            (other.row, other.col),
            cell_size_x=cell_x,
            cell_size_y=cell_y,
        )
        if result is None:
            routing.skipped_pairs.append((exit_node.id, other_id, "no_route"))
            continue
        coords = [cell_to_world(r, c, transform) for r, c in result.path_rc]
        geometry = LineString(coords)
        graph.add_edge(
            exit_node.id,
            other_id,
            weight=result.weight,
            length_m=result.length_m,
            geometry=geometry,
        )


def apply_fixed_terminal_outgoing(
    routing: RoutingGraphResult,
    terminals: list[TerminalRecord],
    *,
    zones: list[ZoneRecord] | None = None,
    cost_raster: CostRaster | None = None,
    use_obstacle_ban: bool = True,
) -> list[str]:
    """
    For terminals with outgoing bearing/length: strip other edges from terminal,
    add steiner:fixed_exit node and mandatory connector edge.
    """
    warnings: list[str] = []
    zone_list = list(zones or [])
    ban_zones = [z for z in zone_list if z.mode == "ban"]
    penalty_zones = [z for z in zone_list if z.mode == "penalty"]
    graph = routing.graph

    for terminal in terminals:
        if not has_fixed_outgoing(terminal):
            continue

        terminal_id = _terminal_graph_id(terminal.id)
        if terminal_id not in graph:
            warnings.append(f"fixed_outgoing_missing_terminal:{terminal.id}")
            continue

        exit_x, exit_y = compute_fixed_exit_xy(terminal)
        exit_id = fixed_exit_node_id(terminal.id)
        connector = LineString([(terminal.x_m, terminal.y_m), (exit_x, exit_y)])

        for zone in ban_zones:
            if zone.geometry.contains(Point(exit_x, exit_y)):
                warnings.append(f"fixed_outgoing_exit_in_ban:{terminal.id}:{zone.id}")
        if ban_zones and edge_blocked_by_ban(connector, ban_zones):
            warnings.append(f"fixed_outgoing_crosses_ban:{terminal.id}")

        exit_node: GraphNode
        if cost_raster is not None:
            rc = world_to_cell(
                exit_x,
                exit_y,
                cost_raster.transform,
                shape=cost_raster.cost.shape,
            )
            if rc is None:
                warnings.append(f"fixed_outgoing_snap_failed:{terminal.id}")
                continue
            snapped = snap_to_finite_cell(rc[0], rc[1], cost_raster.cost)
            if snapped is None:
                warnings.append(f"fixed_outgoing_snap_failed:{terminal.id}")
                continue
            row, col = snapped
            sx, sy = cell_to_world(row, col, cost_raster.transform)
            exit_node = GraphNode(
                id=exit_id,
                x_m=sx,
                y_m=sy,
                kind="fixed_exit",
                row=row,
                col=col,
            )
        else:
            exit_node = GraphNode(
                id=exit_id,
                x_m=exit_x,
                y_m=exit_y,
                kind="fixed_exit",
            )

        _remove_incident_edges(graph, terminal_id)
        if exit_id in graph:
            _remove_incident_edges(graph, exit_id)
        else:
            graph.add_node(
                exit_id,
                x_m=exit_node.x_m,
                y_m=exit_node.y_m,
                kind="fixed_exit",
            )
        routing.nodes[exit_id] = exit_node
        graph.nodes[exit_id]["x_m"] = exit_node.x_m
        graph.nodes[exit_id]["y_m"] = exit_node.y_m
        graph.nodes[exit_id]["kind"] = "fixed_exit"

        length_m = float(connector.length)
        graph.add_edge(
            terminal_id,
            exit_id,
            weight=length_m,
            length_m=length_m,
            geometry=connector,
            edge_kind="connector",
            fixed_outgoing=True,
            crosses_ban=False,
        )

        if cost_raster is not None:
            _add_lcp_edges_from_exit(graph, routing, exit_node, cost_raster)
        else:
            _add_euclid_edges_from_exit(
                graph,
                exit_id,
                exit_node.x_m,
                exit_node.y_m,
                ban_zones,
                penalty_zones,
                use_obstacle_ban=use_obstacle_ban and bool(ban_zones),
            )

        warnings.append(f"fixed_outgoing_applied:{terminal.id}")

    return warnings
