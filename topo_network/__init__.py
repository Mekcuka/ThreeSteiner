"""Прототип пайплайна топографической сети."""

from topo_network.adjusted_tree import build_adjusted_tree
from topo_network.benchmark import (
    BenchmarkSnapshot,
    compare_to_golden,
    load_golden,
    run_demo_scene_benchmark,
    save_golden,
)
from topo_network.cost_surface import build_cost_raster
from topo_network.export import build_plan_response, meters_to_wgs84, write_plan_response
from topo_network.models import (
    AdjustedNode,
    AdjustedTreeEdge,
    AdjustedTreeResult,
    CostRaster,
    LocalScene,
    NetworkTreeEdge,
    NetworkTreeResult,
    PostProcessOptions,
    RoutingGraphResult,
    TerminalAttachment,
    TerminalRecord,
    ZoneRecord,
)
from topo_network.network_tree import build_network_tree
from topo_network.api import app, create_app
from topo_network.plan_request import (
    PlanOptions,
    PlanRequestError,
    load_local_scene,
    load_plan_request,
)
from topo_network.pipeline import run_plan
from topo_network.routing_graph import build_euclid_routing_graph, build_routing_graph
from topo_network.geosteiner_candidates import compute_steiner_candidates
from topo_network.euclid_visibility import build_euclid_visibility_routing_graph

from topo_network.validation import (
    ValidationIssue,
    ValidationResult,
    merge_results,
    run_preflight,
    terminal_graph_id,
    validate_raster_extent,
    validate_routing_connectivity,
    validate_terminal_ban_zones,
    validate_terminal_count,
    validate_terminal_roles,
)

__all__ = [
    "BenchmarkSnapshot",
    "ValidationIssue",
    "ValidationResult",
    "AdjustedNode",
    "AdjustedTreeEdge",
    "AdjustedTreeResult",
    "CostRaster",
    "LocalScene",
    "NetworkTreeEdge",
    "NetworkTreeResult",
    "PostProcessOptions",
    "PlanOptions",
    "PlanRequestError",
    "RoutingGraphResult",
    "TerminalAttachment",
    "TerminalRecord",
    "ZoneRecord",
    "app",
    "build_adjusted_tree",
    "build_cost_raster",
    "build_network_tree",
    "build_plan_response",
    "build_euclid_routing_graph",
    "build_euclid_visibility_routing_graph",
    "build_routing_graph",
    "compute_steiner_candidates",
    "compare_to_golden",
    "create_app",
    "load_golden",
    "load_local_scene",
    "load_plan_request",
    "merge_results",
    "meters_to_wgs84",
    "run_demo_scene_benchmark",
    "run_plan",
    "run_preflight",
    "save_golden",
    "terminal_graph_id",
    "validate_raster_extent",
    "validate_routing_connectivity",
    "validate_terminal_ban_zones",
    "validate_terminal_count",
    "validate_terminal_roles",
    "write_plan_response",
]
