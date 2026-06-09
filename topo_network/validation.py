"""Preflight-валидация LocalScene и терминалов (этап 6)."""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx
from shapely.geometry import Point

from topo_network.lcp import world_to_cell
from topo_network.euclid_zones import edge_blocked_by_ban
from topo_network.models import AdjustedTreeResult, LocalScene, RoutingGraphResult, TerminalRecord


@dataclass
class ValidationIssue:
    code: str
    message: str
    severity: str = "error"  # error | warning


@dataclass
class ValidationResult:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[str]:
        return [i.message for i in self.issues if i.severity == "warning"]

    @property
    def error_codes(self) -> list[str]:
        return [i.code for i in self.errors]

    def add(self, code: str, message: str, *, severity: str = "error") -> None:
        self.issues.append(ValidationIssue(code, message, severity))


def validate_terminal_roles(terminals: list[TerminalRecord]) -> ValidationResult:
    """Не более одного start и одного end (оба опциональны)."""
    result = ValidationResult()
    starts = [t for t in terminals if t.role == "start"]
    ends = [t for t in terminals if t.role == "end"]
    if len(starts) > 1:
        result.add(
            "invalid_roles",
            f"expected at most one start, got {len(starts)}",
        )
    if len(ends) > 1:
        result.add(
            "invalid_roles",
            f"expected at most one end, got {len(ends)}",
        )
    return result


def validate_terminal_count(
    terminals: list[TerminalRecord],
    *,
    max_points: int = 50,
) -> ValidationResult:
    result = ValidationResult()
    if len(terminals) > max_points:
        result.add(
            "too_many_terminals",
            f"{len(terminals)} terminals exceed max_points={max_points}",
        )
    if len(terminals) < 2:
        result.add(
            "too_few_terminals",
            f"need at least 2 terminals, got {len(terminals)}",
        )
    return result


def validate_raster_extent(
    scene: LocalScene,
    terminals: list[TerminalRecord],
    *,
    clip_buffer_m: float = 0.0,
) -> ValidationResult:
    """Терминалы внутри растра elevation (+ опциональный buffer)."""
    result = ValidationResult()
    rows, cols = scene.elevation.shape
    for terminal in terminals:
        cell = world_to_cell(
            terminal.x_m,
            terminal.y_m,
            scene.transform,
            shape=(rows, cols),
        )
        if cell is None:
            result.add(
                "raster_extent",
                f"terminal {terminal.id} outside raster bounds",
            )
            continue
        if clip_buffer_m > 0:
            row, col = cell
            margin = int(clip_buffer_m / max(scene.transform.a, 1.0)) + 1
            if (
                row < margin
                or col < margin
                or row >= rows - margin
                or col >= cols - margin
            ):
                result.add(
                    "raster_extent",
                    f"terminal {terminal.id} within {clip_buffer_m} m of raster edge",
                )
    return result


def validate_terminal_ban_zones(
    scene: LocalScene,
    terminals: list[TerminalRecord],
    *,
    allow_terminal_in_zone_buffer: bool = False,
) -> ValidationResult:
    """Точка терминала не должна попадать в ban-полигон (core или effective — по флагу)."""
    from topo_network.euclid_zones import zone_terminal_ban_geometry

    result = ValidationResult()
    ban_zones = [z for z in scene.zones if z.mode == "ban"]
    if not ban_zones:
        return result
    for terminal in terminals:
        point = Point(terminal.x_m, terminal.y_m)
        for zone in ban_zones:
            ban_geom = zone_terminal_ban_geometry(
                zone,
                allow_in_buffer=allow_terminal_in_zone_buffer,
            )
            if ban_geom.contains(point):
                where = "ban zone core" if allow_terminal_in_zone_buffer else "ban zone"
                result.add(
                    "terminal_in_ban_zone",
                    f"terminal {terminal.id} inside {where} {zone.id}",
                )
                break
    return result


def validate_routing_connectivity(
    routing: RoutingGraphResult,
    start_id: str,
    end_id: str,
    *,
    terminal_ids: list[str] | None = None,
) -> ValidationResult:
    """Связность RoutingGraph; warning если маршрут start→end возможен только через ban-рёбра."""
    result = ValidationResult()
    graph = routing.graph
    if graph.number_of_nodes() == 0:
        result.add(
            "route_may_be_blocked",
            "routing graph is empty",
        )
        return result

    if start_id not in graph or end_id not in graph:
        result.add(
            "route_may_be_blocked",
            "missing terminal node(s) in routing graph",
        )
        return result
    if not nx.has_path(graph, start_id, end_id):
        result.add(
            "route_may_be_blocked",
            f"no path {start_id} → {end_id} in routing graph",
        )
        return result

    allowed = nx.Graph()
    for u, v, data in graph.edges(data=True):
        if not data.get("crosses_ban"):
            allowed.add_edge(u, v)
    if allowed.number_of_edges() == 0 or not nx.has_path(allowed, start_id, end_id):
        result.add(
            "route_may_be_blocked",
            f"no path {start_id} → {end_id} avoiding ban zones; "
            "Steiner may select edges with forbidden weight",
            severity="warning",
        )

    if terminal_ids:
        for issue in _terminal_ban_component_warnings(graph, terminal_ids):
            result.issues.append(issue)

    return result


def _terminal_ban_component_warnings(
    graph: nx.Graph,
    terminal_ids: list[str],
) -> list[ValidationIssue]:
    """Warning, если терминалы не связаны ban-free подграфом."""
    issues: list[ValidationIssue] = []
    allowed = nx.Graph()
    for u, v, data in graph.edges(data=True):
        if not data.get("crosses_ban"):
            allowed.add_edge(u, v)
    term_set = set(terminal_ids)
    groups: list[list[str]] = []
    for component in nx.connected_components(allowed):
        terms = sorted(n for n in component if n in term_set)
        if terms:
            groups.append(terms)
    if len(groups) > 1:
        group_msg = "; ".join("{" + ", ".join(g) + "}" for g in groups)
        issues.append(
            ValidationIssue(
                "route_may_be_blocked",
                "terminals have no ban-free routes between groups: "
                f"{len(groups)} component(s): {group_msg}",
                severity="warning",
            ),
        )
    return issues


def validate_terminals_routing_connectivity(
    routing: RoutingGraphResult,
    terminal_ids: list[str],
) -> ValidationResult:
    """Связность всех терминалов в RoutingGraph."""
    result = ValidationResult()
    graph = routing.graph
    if graph.number_of_nodes() == 0:
        result.add(
            "route_may_be_blocked",
            "routing graph is empty",
        )
        return result

    missing = [tid for tid in terminal_ids if tid not in graph]
    if missing:
        result.add(
            "route_may_be_blocked",
            f"missing terminal node(s) in routing graph: {', '.join(missing)}",
        )
        return result

    if len(terminal_ids) < 2:
        return result

    term_set = set(terminal_ids)
    components = [
        component
        for component in nx.connected_components(graph)
        if term_set & component
    ]
    if len(components) != 1:
        result.add(
            "route_may_be_blocked",
            "terminals are not in one connected component of routing graph",
        )
        return result

    for issue in _terminal_ban_component_warnings(graph, terminal_ids):
        result.issues.append(issue)
    return result


def validate_tree_ban_edges(
    routing: RoutingGraphResult,
    tree: nx.Graph,
) -> ValidationResult:
    """Warning, если Steiner-дерево включает рёбра через ban."""
    result = ValidationResult()
    for u, v in tree.edges:
        if not routing.graph.has_edge(u, v):
            continue
        if routing.graph[u][v].get("crosses_ban"):
            result.add(
                "edge_crosses_ban_zone",
                f"tree edge {u} → {v} crosses ban zone (high forbidden weight)",
                severity="warning",
            )
    return result


def validate_tree_edges_ban_zones(
    adjusted: AdjustedTreeResult,
    scene: LocalScene,
) -> ValidationResult:
    """Предупреждение, если геометрия ребра пересекает ban-полигон."""
    result = ValidationResult()
    ban_zones = [z for z in scene.zones if z.mode == "ban"]
    if not ban_zones:
        return result
    for edge in adjusted.edges:
        if edge_blocked_by_ban(edge.geometry, ban_zones):
            result.add(
                "edge_crosses_ban_zone",
                f"edge {edge.u} → {edge.v} crosses ban zone",
                severity="warning",
            )
    return result


def routing_skipped_warnings(routing: RoutingGraphResult) -> list[str]:
    warnings: list[str] = []
    for a_id, b_id, reason in routing.skipped_pairs:
        warnings.append(f"routing_skipped:{a_id}:{b_id}:{reason}")
    return warnings


def merge_results(*parts: ValidationResult) -> ValidationResult:
    merged = ValidationResult()
    for part in parts:
        merged.issues.extend(part.issues)
    return merged


def terminal_graph_id(terminal_id: str) -> str:
    return f"terminal:{terminal_id}"


def run_preflight(
    scene: LocalScene,
    terminals: list[TerminalRecord],
    routing: RoutingGraphResult | None = None,
    *,
    start_id: str | None = None,
    end_id: str | None = None,
    max_points: int = 50,
    clip_buffer_m: float = 0.0,
    raster_checks: bool = True,
    zone_checks: bool = False,
    terrain_checks: bool | None = None,
    allow_terminal_in_zone_buffer: bool = False,
) -> ValidationResult:
    """Сводная preflight-проверка перед расчётом."""
    if terrain_checks is not None:
        raster_checks = terrain_checks
        zone_checks = terrain_checks

    parts: list[ValidationResult] = [
        validate_terminal_count(terminals, max_points=max_points),
        validate_terminal_roles(terminals),
    ]
    if raster_checks:
        parts.append(
            validate_raster_extent(scene, terminals, clip_buffer_m=clip_buffer_m),
        )
    if zone_checks:
        parts.append(
            validate_terminal_ban_zones(
                scene,
                terminals,
                allow_terminal_in_zone_buffer=allow_terminal_in_zone_buffer,
            )
        )
    result = merge_results(*parts)
    if routing is not None:
        terminal_ids = [terminal_graph_id(t.id) for t in terminals]
        if start_id is None:
            starts = [t for t in terminals if t.role == "start"]
            start_id = terminal_graph_id(starts[0].id) if starts else None
        if end_id is None:
            ends = [t for t in terminals if t.role == "end"]
            end_id = terminal_graph_id(ends[0].id) if ends else None
        if start_id and end_id:
            result = merge_results(
                result,
                validate_routing_connectivity(
                    routing,
                    start_id,
                    end_id,
                    terminal_ids=terminal_ids,
                ),
            )
        else:
            result = merge_results(
                result,
                validate_terminals_routing_connectivity(routing, terminal_ids),
            )
    return result
