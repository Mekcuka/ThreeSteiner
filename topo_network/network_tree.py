"""NetworkTree: Steiner-оптимизация на RoutingGraph (этап 4 / фаза 4)."""

from __future__ import annotations

import itertools
import logging

import networkx as nx
from networkx.algorithms.approximation import steiner_tree

from topo_network.models import (
    NetworkTreeEdge,
    NetworkTreeResult,
    RoutingGraphResult,
    TerminalRecord,
)

logger = logging.getLogger(__name__)

_SOLVER_STEINERPY = "steinerpy"
_SOLVER_NX_APPROX = "nx_approx"


def _terminal_graph_id(terminal_id: str) -> str:
    return f"terminal:{terminal_id}"


def _validate_terminals(
    routing: RoutingGraphResult,
    terminals: list[TerminalRecord],
) -> list[str]:
    terminal_ids: list[str] = []
    for terminal in terminals:
        node_id = _terminal_graph_id(terminal.id)
        if node_id not in routing.nodes:
            raise ValueError(f"terminal not in routing graph: {terminal.id}")
        terminal_ids.append(node_id)

    if routing.graph.number_of_nodes() == 0:
        raise ValueError("routing graph is empty")
    if nx.number_connected_components(routing.graph) != 1:
        raise ValueError("routing graph must be connected")

    return terminal_ids


def _terminal_relevant_subgraph(
    graph: nx.Graph,
    terminal_ids: list[str],
) -> nx.Graph:
    """Узлы на кратчайших путях между терминалами → индуцированный подграф."""
    nodes: set[str] = set(terminal_ids)
    for a, b in itertools.combinations(terminal_ids, 2):
        path = nx.shortest_path(graph, a, b, weight="weight")
        nodes.update(path)
    return graph.subgraph(nodes).copy()

def _materialize_selected_edges(
    routing: RoutingGraphResult,
    work_graph: nx.Graph,
    selected: list[tuple[str, str]],
) -> nx.Graph:
    """Map solver edge pairs onto routing edges via shortest paths in work_graph."""
    tree = nx.Graph()
    for u, v in selected:
        path = nx.shortest_path(work_graph, u, v, weight="weight")
        for a, b in zip(path, path[1:]):
            if tree.has_edge(a, b):
                continue
            if not routing.graph.has_edge(a, b):
                raise ValueError(f"selected edge not in routing graph: {a} — {b}")
            tree.add_edge(a, b, **routing.graph[a][b])
    return tree


def _tree_from_edge_pairs(
    routing: RoutingGraphResult,
    selected: list[tuple[str, str]],
) -> nx.Graph:
    tree = nx.Graph()
    for u, v in selected:
        if not routing.graph.has_edge(u, v):
            raise ValueError(f"selected edge not in routing graph: {u} — {v}")
        tree.add_edge(u, v, **routing.graph[u][v])
    return tree


def _solve_steinerpy(
    graph: nx.Graph,
    terminal_groups: list[list[str]],
) -> tuple[list[tuple[str, str]], float]:
    from steinerpy import SteinerProblem

    problem = SteinerProblem(graph, terminal_groups)
    solution = problem.get_solution()
    edges: list[tuple[str, str]] = []
    for edge in solution.selected_edges:
        if isinstance(edge, (list, tuple)) and len(edge) == 2:
            u, v = edge
        else:
            raise ValueError(f"unexpected edge format from SteinerPy: {edge!r}")
        edges.append((str(u), str(v)))
    return edges, float(solution.objective)


def _solve_nx_approx(
    graph: nx.Graph,
    terminal_ids: list[str],
) -> tuple[list[tuple[str, str]], float]:
    tree = steiner_tree(graph, terminal_ids, weight="weight", method="mehlhorn")
    edges = [(str(u), str(v)) for u, v in tree.edges()]
    total = float(sum(data["weight"] for _, _, data in tree.edges(data=True)))
    return edges, total


def _build_result(
    routing: RoutingGraphResult,
    terminal_ids: list[str],
    tree: nx.Graph,
    *,
    solver: str,
    warnings: list[str],
) -> NetworkTreeResult:
    edges: list[NetworkTreeEdge] = []
    total_weight = 0.0
    total_length_m = 0.0
    for u, v, data in tree.edges(data=True):
        weight = float(data["weight"])
        length_m = float(data["length_m"])
        geometry = data.get("geometry")
        edges.append(
            NetworkTreeEdge(
                u=u,
                v=v,
                weight=weight,
                length_m=length_m,
                geometry=geometry,
            )
        )
        total_weight += weight
        total_length_m += length_m

    steiner_node_ids = sorted(
        node
        for node in tree.nodes
        if routing.nodes.get(node) is not None
        and routing.nodes[node].kind != "terminal"
    )

    return NetworkTreeResult(
        tree=tree,
        edges=edges,
        terminal_ids=list(terminal_ids),
        steiner_node_ids=steiner_node_ids,
        total_weight=total_weight,
        total_length_m=total_length_m,
        solver=solver,
        warnings=warnings,
    )


def build_network_tree(
    routing: RoutingGraphResult,
    terminals: list[TerminalRecord],
    *,
    solver: str = _SOLVER_STEINERPY,
) -> NetworkTreeResult:
    """
    Построить NetworkTree — минимальное Steiner-дерево на LCP-графе.

    solver: ``steinerpy`` (HiGHS) или ``nx_approx`` (NetworkX Mehlhorn).
    """
    if solver not in (_SOLVER_STEINERPY, _SOLVER_NX_APPROX):
        raise ValueError(f"unknown solver: {solver!r}")

    terminal_ids = _validate_terminals(routing, terminals)
    terminal_groups = [terminal_ids]
    warnings: list[str] = []

    work_graph = _terminal_relevant_subgraph(routing.graph, terminal_ids)
    if work_graph.number_of_nodes() < routing.graph.number_of_nodes():
        warnings.append(
            f"subgraph:{work_graph.number_of_nodes()}/{routing.graph.number_of_nodes()}_nodes"
        )

    used_solver = solver
    selected_edges: list[tuple[str, str]]
    if solver == _SOLVER_STEINERPY:
        try:
            selected_edges, _objective = _solve_steinerpy(work_graph, terminal_groups)
        except Exception as exc:
            logger.warning("SteinerPy failed (%s), falling back to nx_approx", exc)
            warnings.append(f"solver_fallback:{exc}")
            used_solver = _SOLVER_NX_APPROX
            selected_edges, _objective = _solve_nx_approx(work_graph, terminal_ids)
    else:
        selected_edges, _objective = _solve_nx_approx(work_graph, terminal_ids)

    tree = _materialize_selected_edges(routing, work_graph, selected_edges)

    if tree.number_of_nodes() != tree.number_of_edges() + 1:
        raise ValueError(
            f"result is not a tree: {tree.number_of_nodes()} nodes, "
            f"{tree.number_of_edges()} edges"
        )
    if not all(tid in tree for tid in terminal_ids):
        raise ValueError("tree does not contain all terminals")

    return _build_result(
        routing,
        terminal_ids,
        tree,
        solver=used_solver,
        warnings=warnings,
    )
