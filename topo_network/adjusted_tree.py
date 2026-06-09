"""AdjustedTree: постобработка NetworkTree (этап 5 / фаза 5)."""

from __future__ import annotations

import copy
import math

import networkx as nx
from shapely.geometry import LineString, Point
from shapely.ops import substring

from topo_network.models import (
    AdjustedNode,
    AdjustedTreeEdge,
    AdjustedTreeResult,
    NetworkTreeResult,
    PostProcessOptions,
    TerminalAttachment,
    TerminalRecord,
)

_STUB_LENGTH_M = 0.1


def _terminal_graph_id(terminal_id: str) -> str:
    return f"terminal:{terminal_id}"


def _parse_terminal_id(node_id: str) -> str | None:
    if node_id.startswith("terminal:"):
        return node_id[len("terminal:") :]
    return None


def _hub_id(terminal_id: str) -> str:
    return f"steiner:hub:{terminal_id}"


def _attach_id(terminal_id: str) -> str:
    return f"steiner:attach:{terminal_id}"


def _waypoint_id(u: str, v: str, index: int) -> str:
    a, b = sorted((u, v))
    return f"steiner:waypoint:{a}-{b}-{index}"


def _edge_key(u: str, v: str) -> tuple[str, str]:
    return (u, v) if u <= v else (v, u)


def _orient_line(
    geom: LineString,
    from_xy: tuple[float, float],
    to_xy: tuple[float, float],
) -> LineString:
    if geom.is_empty or geom.length == 0:
        return LineString([from_xy, to_xy])
    coords = list(geom.coords)
    start = coords[0]
    end = coords[-1]
    d_start = (start[0] - from_xy[0]) ** 2 + (start[1] - from_xy[1]) ** 2
    d_end = (end[0] - from_xy[0]) ** 2 + (end[1] - from_xy[1]) ** 2
    if d_end < d_start:
        coords = list(reversed(coords))
    return LineString(coords)


def _split_weights(
    total_weight: float,
    total_length_m: float,
    part_length_m: float,
) -> tuple[float, float]:
    if total_length_m <= 0:
        half_w = total_weight / 2.0
        half_l = total_length_m / 2.0
        return half_w, half_l
    ratio = part_length_m / total_length_m
    w1 = total_weight * ratio
    return w1, total_weight - w1


def _subline(geom: LineString, start_m: float, end_m: float) -> LineString:
    length = geom.length
    start_m = max(0.0, min(start_m, length))
    end_m = max(start_m, min(end_m, length))
    if end_m - start_m < 1e-9:
        pt = geom.interpolate(start_m)
        return LineString([(pt.x, pt.y), (pt.x, pt.y)])
    return substring(geom, start_m, end_m, normalized=False)


def _build_positions(
    tree: nx.Graph,
    terminals: list[TerminalRecord],
) -> dict[str, tuple[float, float]]:
    positions: dict[str, tuple[float, float]] = {
        _terminal_graph_id(t.id): (t.x_m, t.y_m) for t in terminals
    }
    for u, v, data in tree.edges(data=True):
        geom = data.get("geometry")
        if geom is None or geom.is_empty:
            continue
        line = geom
        if not isinstance(line, LineString):
            line = LineString(line)
        coords = list(line.coords)
        if u not in positions:
            positions[u] = (coords[0][0], coords[0][1])
        if v not in positions:
            positions[v] = (coords[-1][0], coords[-1][1])
    for node in tree.nodes:
        if node not in positions:
            positions[node] = (0.0, 0.0)
    return positions


def _copy_tree(network: NetworkTreeResult) -> nx.Graph:
    return copy.deepcopy(network.tree)


def _remove_edge(tree: nx.Graph, u: str, v: str) -> dict:
    if tree.has_edge(u, v):
        data = dict(tree[u][v])
        tree.remove_edge(u, v)
        return data
    if tree.has_edge(v, u):
        data = dict(tree[v][u])
        tree.remove_edge(v, u)
        return data
    raise KeyError(f"edge not found: {u} — {v}")


def _add_edge(
    tree: nx.Graph,
    u: str,
    v: str,
    *,
    weight: float,
    length_m: float,
    geometry: LineString,
    edge_kind: str = "backbone",
) -> None:
    tree.add_edge(
        u,
        v,
        weight=weight,
        length_m=length_m,
        geometry=geometry,
        edge_kind=edge_kind,
    )


def _normalize_terminal_leaves(
    tree: nx.Graph,
    positions: dict[str, tuple[float, float]],
    terminal_ids: list[str],
) -> None:
    for node_id in terminal_ids:
        if tree.degree(node_id) <= 1:
            continue
        tid = _parse_terminal_id(node_id)
        if tid is None:
            continue
        hub = _hub_id(tid)
        tx, ty = positions[node_id]
        positions[hub] = (tx, ty)

        neighbors = list(tree.neighbors(node_id))
        for neighbor in neighbors:
            data = _remove_edge(tree, node_id, neighbor)
            geom = data.get("geometry")
            if geom is not None and not geom.is_empty:
                line = geom if isinstance(geom, LineString) else LineString(geom)
                nx_pos = positions.get(neighbor, (tx, ty))
                oriented = _orient_line(line, (tx, ty), nx_pos)
            else:
                nx_pos = positions.get(neighbor, (tx, ty))
                oriented = LineString([(tx, ty), nx_pos])

            _add_edge(
                tree,
                hub,
                neighbor,
                weight=float(data["weight"]),
                length_m=float(data["length_m"]),
                geometry=oriented,
                edge_kind=data.get("edge_kind", "backbone"),
            )

        stub = LineString([(tx, ty), (tx + _STUB_LENGTH_M, ty)])
        _add_edge(
            tree,
            node_id,
            hub,
            weight=0.0,
            length_m=_STUB_LENGTH_M,
            geometry=stub,
            edge_kind="connector",
        )


def _connector_limit_m(
    terminal_id: str,
    options: PostProcessOptions,
    overrides: dict[str, float] | None,
) -> float:
    if overrides and terminal_id in overrides:
        return overrides[terminal_id] * 1000.0
    return options.connector_max_km * 1000.0


def _enforce_connector_max(
    tree: nx.Graph,
    positions: dict[str, tuple[float, float]],
    terminals: list[TerminalRecord],
    options: PostProcessOptions,
    overrides: dict[str, float] | None,
    warnings: list[str],
) -> None:
    for terminal in terminals:
        node_id = _terminal_graph_id(terminal.id)
        if node_id not in tree:
            continue
        if tree.degree(node_id) != 1:
            warnings.append(f"attachment_skipped:degree:{terminal.id}")
            continue

        neighbor = next(iter(tree.neighbors(node_id)))
        data = _remove_edge(tree, node_id, neighbor)
        if data.get("fixed_outgoing") or neighbor.startswith("steiner:fixed_exit:"):
            _add_edge(
                tree,
                node_id,
                neighbor,
                weight=float(data["weight"]),
                length_m=float(data["length_m"]),
                geometry=data.get("geometry")
                if data.get("geometry") is not None
                else LineString(
                    [
                        positions[node_id],
                        positions.get(neighbor, positions[node_id]),
                    ]
                ),
                edge_kind="connector",
            )
            continue

        length_m = float(data["length_m"])
        limit_m = _connector_limit_m(terminal.id, options, overrides)

        if length_m <= limit_m + 1e-6:
            geom = data.get("geometry")
            if geom is None or geom.is_empty:
                tx, ty = positions[node_id]
                nx_pos = positions.get(neighbor, (tx, ty))
                geom = LineString([(tx, ty), nx_pos])
            _add_edge(
                tree,
                node_id,
                neighbor,
                weight=float(data["weight"]),
                length_m=length_m,
                geometry=geom if isinstance(geom, LineString) else LineString(geom),
                edge_kind=data.get("edge_kind", "backbone"),
            )
            continue

        tx, ty = positions[node_id]
        nx_pos = positions.get(neighbor, (tx, ty))
        geom = data.get("geometry")
        if geom is None or geom.is_empty:
            full_line = LineString([(tx, ty), nx_pos])
        else:
            full_line = geom if isinstance(geom, LineString) else LineString(geom)
            full_line = _orient_line(full_line, (tx, ty), nx_pos)

        split_dist = min(limit_m, full_line.length)
        if split_dist >= full_line.length - 1e-6:
            warnings.append(f"attachment_limit:{terminal.id}")
            _add_edge(
                tree,
                node_id,
                neighbor,
                weight=float(data["weight"]),
                length_m=length_m,
                geometry=full_line,
                edge_kind="connector",
            )
            continue

        conn_geom = _subline(full_line, 0.0, split_dist)
        rest_geom = _subline(full_line, split_dist, full_line.length)
        w1, w2 = _split_weights(float(data["weight"]), length_m, split_dist)
        l1, l2 = split_dist, length_m - split_dist

        attach = _attach_id(terminal.id)
        ax, ay = conn_geom.coords[-1]
        positions[attach] = (ax, ay)

        _add_edge(
            tree,
            node_id,
            attach,
            weight=w1,
            length_m=l1,
            geometry=conn_geom,
            edge_kind="connector",
        )
        _add_edge(
            tree,
            attach,
            neighbor,
            weight=w2,
            length_m=l2,
            geometry=rest_geom,
            edge_kind="backbone",
        )


def _repel_steiner_radius(
    tree: nx.Graph,
    positions: dict[str, tuple[float, float]],
    terminal_ids: list[str],
    radius_m: float,
    warnings: list[str],
) -> None:
    if radius_m <= 0:
        return

    terminal_xy = {
        tid: positions[tid]
        for tid in terminal_ids
        if tid in positions
    }

    for node in list(tree.nodes):
        if node in terminal_ids or node.startswith("steiner:hub:"):
            continue
        if node not in positions:
            continue
        nx_pos = positions[node]
        px, py = nx_pos

        closest_tid: str | None = None
        closest_dist = math.inf
        for tid, (tx, ty) in terminal_xy.items():
            dist = math.hypot(px - tx, py - ty)
            if dist < closest_dist:
                closest_dist = dist
                closest_tid = tid

        if closest_tid is None or closest_dist >= radius_m:
            continue

        tx, ty = terminal_xy[closest_tid]
        moved = False
        for neighbor in tree.neighbors(node):
            nxy = positions.get(neighbor)
            if nxy is None:
                continue
            nx_x, nx_y = nxy
            edge_dx = nx_x - px
            edge_dy = nx_y - py
            to_term_dx = tx - px
            to_term_dy = ty - py
            dot = edge_dx * to_term_dx + edge_dy * to_term_dy
            if dot >= 0:
                continue
            dist = math.hypot(edge_dx, edge_dy)
            if dist < 1e-9:
                continue
            step = min(radius_m - closest_dist + 1.0, dist * 0.5)
            positions[node] = (px + edge_dx / dist * step, py + edge_dy / dist * step)
            moved = True
            break

        if not moved:
            warnings.append(f"steiner_repel_failed:{node}")


def _densify_waypoints_simple(
    tree: nx.Graph,
    positions: dict[str, tuple[float, float]],
    spacing_m: float,
) -> None:
    """Insert waypoint nodes at fixed spacing along long edges."""
    if spacing_m <= 0:
        return

    for u, v, data in list(tree.edges(data=True)):
        if not tree.has_edge(u, v):
            continue
        length_m = float(data["length_m"])
        if length_m <= spacing_m + 1e-6:
            continue

        ux, uy = positions.get(u, (0.0, 0.0))
        vx, vy = positions.get(v, (0.0, 0.0))
        geom = data.get("geometry")
        if geom is None or geom.is_empty:
            line = LineString([(ux, uy), (vx, vy)])
        else:
            line = geom if isinstance(geom, LineString) else LineString(geom)
            line = _orient_line(line, (ux, uy), (vx, vy))

        _remove_edge(tree, u, v)
        total_weight = float(data["weight"])
        edge_kind = data.get("edge_kind", "backbone")

        dist = spacing_m
        prev = u
        prev_dist = 0.0
        used_weight = 0.0
        wp_index = 1

        while dist < length_m - 1e-6:
            wp = _waypoint_id(u, v, wp_index)
            wp_index += 1
            pt = line.interpolate(min(dist, line.length))
            positions[wp] = (pt.x, pt.y)
            seg_len = dist - prev_dist
            w_part, _ = _split_weights(total_weight, length_m, seg_len)
            seg_geom = _subline(line, prev_dist, min(dist, line.length))
            _add_edge(
                tree,
                prev,
                wp,
                weight=w_part,
                length_m=seg_len,
                geometry=seg_geom,
                edge_kind=edge_kind,
            )
            used_weight += w_part
            prev = wp
            prev_dist = dist
            dist += spacing_m

        rest_len = length_m - prev_dist
        rest_geom = _subline(line, prev_dist, line.length)
        _add_edge(
            tree,
            prev,
            v,
            weight=max(0.0, total_weight - used_weight),
            length_m=rest_len,
            geometry=rest_geom,
            edge_kind=edge_kind,
        )


def _collect_nodes(
    tree: nx.Graph,
    positions: dict[str, tuple[float, float]],
    terminals: list[TerminalRecord],
) -> dict[str, AdjustedNode]:
    terminal_set = {_terminal_graph_id(t.id) for t in terminals}
    nodes: dict[str, AdjustedNode] = {}

    for terminal in terminals:
        nid = _terminal_graph_id(terminal.id)
        x, y = positions.get(nid, (terminal.x_m, terminal.y_m))
        nodes[nid] = AdjustedNode(nid, x, y, "terminal")

    for node_id in tree.nodes:
        if node_id in nodes:
            continue
        x, y = positions.get(node_id, (0.0, 0.0))
        if node_id.startswith("steiner:hub:"):
            kind = "hub"
        elif node_id.startswith("steiner:attach:"):
            kind = "attach"
        elif node_id.startswith("steiner:waypoint:"):
            kind = "waypoint"
        elif node_id.startswith("steiner:candidate:"):
            kind = "steiner_candidate"
        elif node_id.startswith("steiner:fixed_exit:"):
            kind = "fixed_exit"
        elif node_id in terminal_set:
            kind = "terminal"
        else:
            kind = "steiner"
        nodes[node_id] = AdjustedNode(node_id, x, y, kind)

    return nodes


def _build_attachments(
    tree: nx.Graph,
    terminals: list[TerminalRecord],
) -> list[TerminalAttachment]:
    attachments: list[TerminalAttachment] = []
    for terminal in terminals:
        node_id = _terminal_graph_id(terminal.id)
        if node_id not in tree:
            continue
        if tree.degree(node_id) == 0:
            attachments.append(
                TerminalAttachment(terminal.id, terminal.role, "", "tree")
            )
            continue

        neighbor = next(iter(tree.neighbors(node_id)))
        via = "tree"
        attached_to = neighbor

        if neighbor.startswith("steiner:hub:"):
            via = "hub"
            attached_to = neighbor
            hub_neighbors = [n for n in tree.neighbors(neighbor) if n != node_id]
            if hub_neighbors:
                attached_to = hub_neighbors[0]
        elif neighbor.startswith("steiner:attach:"):
            via = "attach"
            attached_to = neighbor
        elif neighbor.startswith("steiner:fixed_exit:"):
            via = "fixed_exit"
            attached_to = neighbor

        attachments.append(
            TerminalAttachment(
                terminal_id=terminal.id,
                role=terminal.role,
                attached_to=attached_to,
                via=via,
            )
        )
    return attachments


def _assemble_result(
    tree: nx.Graph,
    nodes: dict[str, AdjustedNode],
    attachments: list[TerminalAttachment],
    warnings: list[str],
) -> AdjustedTreeResult:
    edges: list[AdjustedTreeEdge] = []
    total_weight = 0.0
    total_length_m = 0.0
    seen: set[tuple[str, str]] = set()

    for u, v, data in tree.edges(data=True):
        key = _edge_key(u, v)
        if key in seen:
            continue
        seen.add(key)
        weight = float(data["weight"])
        length_m = float(data["length_m"])
        geometry = data.get("geometry")
        edges.append(
            AdjustedTreeEdge(
                u=u,
                v=v,
                weight=weight,
                length_m=length_m,
                geometry=geometry,
                edge_kind=str(data.get("edge_kind", "backbone")),
            )
        )
        total_weight += weight
        total_length_m += length_m

    return AdjustedTreeResult(
        tree=tree,
        nodes=nodes,
        edges=edges,
        attachments=attachments,
        warnings=warnings,
        total_weight=total_weight,
        total_length_m=total_length_m,
    )


def build_adjusted_tree(
    network: NetworkTreeResult,
    terminals: list[TerminalRecord],
    *,
    options: PostProcessOptions | None = None,
    attachment_overrides_km: dict[str, float] | None = None,
) -> AdjustedTreeResult:
    """
    Постобработка NetworkTree: hub, attach, repel, waypoint, warnings.
    """
    opts = options or PostProcessOptions()
    warnings: list[str] = list(network.warnings)

    if network.tree.number_of_nodes() == 0:
        raise ValueError("network tree is empty")

    tree = _copy_tree(network)
    terminal_ids = list(network.terminal_ids)
    positions = _build_positions(tree, terminals)

    if opts.normalize_terminal_leaves:
        _normalize_terminal_leaves(tree, positions, terminal_ids)

    if opts.enforce_attachment_radius:
        _enforce_connector_max(
            tree,
            positions,
            terminals,
            opts,
            attachment_overrides_km,
            warnings,
        )

    radius_m = opts.steiner_radius_km * 1000.0
    _repel_steiner_radius(tree, positions, terminal_ids, radius_m, warnings)

    spacing_m = opts.edge_vertex_spacing_km * 1000.0
    _densify_waypoints_simple(tree, positions, spacing_m)

    start_id = next(
        (_terminal_graph_id(t.id) for t in terminals if t.role == "start"),
        None,
    )
    end_id = next(
        (_terminal_graph_id(t.id) for t in terminals if t.role == "end"),
        None,
    )
    if start_id and end_id and not nx.has_path(tree, start_id, end_id):
        warnings.append("start_end_not_connected")

    nodes = _collect_nodes(tree, positions, terminals)
    attachments = _build_attachments(tree, terminals)
    return _assemble_result(tree, nodes, attachments, warnings)
