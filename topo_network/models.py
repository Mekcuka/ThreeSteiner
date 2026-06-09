"""Внутренние структуры данных пайплайна (этапы 1–5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import networkx as nx
import numpy as np
from rasterio.transform import Affine


@dataclass
class ZoneRecord:
    id: str
    geometry: Any  # shapely geometry в crs_work (effective: core + buffer_m для маршрутов)
    mode: str  # "ban" | "penalty"
    multiplier: float = 1.0
    geometry_core: Any | None = None  # без buffer_m; для preflight при allow_terminal_in_zone_buffer
    buffer_m: float = 0.0
    category: str | None = None  # dry_land | swamp | floodplain (только penalty)


@dataclass
class LocalScene:
    """Выход фазы «Подготовка» (этап 1 / фаза 1)."""

    crs_work: str
    transform: Affine
    elevation: np.ndarray
    nodata: float | None
    zones: list[ZoneRecord] = field(default_factory=list)
    corridors: list[Any] | None = None  # shapely LineString / MultiLineString
    corridor_cost_multiplier: float = 0.5
    corridor_buffer_m: float = 15.0


@dataclass
class CostRaster:
    """Выход фазы «Cost surface» (этап 2 / фаза 2)."""

    cost: np.ndarray
    transform: Affine
    crs: str
    cell_size_m: tuple[float, float]
    slope_deg: np.ndarray
    nodata_mask: np.ndarray

    @property
    def shape(self) -> tuple[int, ...]:
        return self.cost.shape

    def summary(self) -> dict[str, float | int]:
        finite = self.cost[np.isfinite(self.cost)]
        banned = np.isinf(self.cost) & ~self.nodata_mask
        return {
            "rows": int(self.cost.shape[0]),
            "cols": int(self.cost.shape[1]),
            "finite_cells": int(finite.size),
            "banned_cells": int(banned.sum()),
            "min_cost": float(finite.min()) if finite.size else 0.0,
            "max_cost": float(finite.max()) if finite.size else 0.0,
            "max_slope_deg": float(np.nanmax(self.slope_deg)),
        }


@dataclass
class TerminalRecord:
    id: str
    x_m: float
    y_m: float
    role: str  # start | end | intermediate | branch (start/end optional)
    outgoing_bearing_deg: float | None = None
    outgoing_length_m: float | None = None


@dataclass
class GraphNode:
    id: str
    x_m: float
    y_m: float
    kind: str  # terminal | grid | corridor | obstacle | penalty_contour | steiner_candidate | fixed_exit
    row: int | None = None
    col: int | None = None


@dataclass
class RoutingGraphResult:
    """Выход фазы «Граф» (этап 3 / фаза 3)."""

    graph: nx.Graph
    nodes: dict[str, GraphNode]
    skipped_pairs: list[tuple[str, str, str]]

    def summary(self) -> dict[str, float | int]:
        n_nodes = self.graph.number_of_nodes()
        n_edges = self.graph.number_of_edges()
        n_components = nx.number_connected_components(self.graph) if n_nodes else 0
        attempted = n_nodes * (n_nodes - 1) // 2 if n_nodes > 1 else 0
        skipped = len(self.skipped_pairs)
        return {
            "nodes": n_nodes,
            "edges": n_edges,
            "components": n_components,
            "skipped_pairs": skipped,
            "pair_attempts": attempted,
            "successful_lcp_ratio": (
                float(n_edges) / float(attempted - skipped)
                if attempted > skipped
                else 0.0
            ),
        }


@dataclass
class NetworkTreeEdge:
    """Ребро результата фазы «Сеть» (этап 4)."""

    u: str
    v: str
    weight: float
    length_m: float
    geometry: Any


@dataclass
class NetworkTreeResult:
    """Выход фазы «Сеть» (этап 4 / фаза 4): Steiner-дерево на LCP-графе."""

    tree: nx.Graph
    edges: list[NetworkTreeEdge]
    terminal_ids: list[str]
    steiner_node_ids: list[str]
    total_weight: float
    total_length_m: float
    solver: str
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, float | int | str]:
        return {
            "nodes": self.tree.number_of_nodes(),
            "edges": self.tree.number_of_edges(),
            "terminals": len(self.terminal_ids),
            "steiner_nodes": len(self.steiner_node_ids),
            "total_weight": self.total_weight,
            "total_length_m": self.total_length_m,
            "solver": self.solver,
            "warnings": len(self.warnings),
        }


@dataclass
class PostProcessOptions:
    """Параметры постобработки (фаза 5)."""

    connector_max_km: float = 0.2
    steiner_radius_km: float = 0.0
    normalize_terminal_leaves: bool = True
    edge_vertex_spacing_km: float = 0.0
    enforce_attachment_radius: bool = True


@dataclass
class AdjustedNode:
    id: str
    x_m: float
    y_m: float
    kind: str  # terminal | hub | attach | waypoint | steiner | steiner_candidate | fixed_exit


@dataclass
class AdjustedTreeEdge:
    u: str
    v: str
    weight: float
    length_m: float
    geometry: Any
    edge_kind: str = "backbone"  # connector | backbone


@dataclass
class TerminalAttachment:
    terminal_id: str
    role: str
    attached_to: str
    via: str  # hub | attach | tree


@dataclass
class AdjustedTreeResult:
    """Выход фазы «Постобработка» (этап 5): инженерно нормализованное дерево."""

    tree: nx.Graph
    nodes: dict[str, AdjustedNode]
    edges: list[AdjustedTreeEdge]
    attachments: list[TerminalAttachment]
    warnings: list[str]
    total_weight: float
    total_length_m: float

    def summary(self) -> dict[str, float | int]:
        kinds: dict[str, int] = {}
        for node in self.nodes.values():
            kinds[node.kind] = kinds.get(node.kind, 0) + 1
        return {
            "nodes": self.tree.number_of_nodes(),
            "edges": self.tree.number_of_edges(),
            "attachments": len(self.attachments),
            "total_weight": self.total_weight,
            "total_length_m": self.total_length_m,
            "warnings": len(self.warnings),
            **{f"kind_{k}": v for k, v in sorted(kinds.items())},
        }
