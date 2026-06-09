"""Оркестратор PlanRequest → PlanResponse (этап 7)."""



from __future__ import annotations



from pathlib import Path

from typing import Any



from topo_network.adjusted_tree import build_adjusted_tree

from topo_network.cost_surface import build_cost_raster

from topo_network.export import build_plan_response

from topo_network.network_tree import build_network_tree

from topo_network.plan_request import PlanRequestError, load_local_scene, load_plan_request

from topo_network.routing_graph import build_euclid_routing_graph, build_routing_graph
from topo_network.terminal_outgoing import apply_fixed_terminal_outgoing

from topo_network.validation import (
    run_preflight,
    routing_skipped_warnings,
    validate_tree_ban_edges,
    validate_tree_edges_ban_zones,
)





def run_plan(

    source: str | Path | dict[str, Any],

    *,

    base_dir: Path | str | None = None,

) -> dict[str, Any]:

    """Загрузка → preflight → пайплайн 2–5 → PlanResponse dict."""

    request, _ = load_plan_request(source)

    scene, terminals, options = load_local_scene(source, base_dir=base_dir)

    mode = str(request["mode"])

    raster_checks = mode == "full"
    zone_checks = bool(scene.zones)

    preflight = run_preflight(
        scene,
        terminals,
        routing=None,
        max_points=options.max_points,
        raster_checks=raster_checks,
        zone_checks=zone_checks,
        allow_terminal_in_zone_buffer=options.allow_terminal_in_zone_buffer,
    )

    if not preflight.ok:

        first = preflight.errors[0]

        raise PlanRequestError(first.code, first.message)



    geosteiner_warnings: list[str] = []
    cost_raster = None

    if mode == "euclid":

        routing, geosteiner_warnings = build_euclid_routing_graph(
            terminals,
            zones=scene.zones or None,
            euclid_routing=options.euclid_routing,
            obstacle_buffer_m=options.obstacle_buffer_m,
            clip_buffer_m=options.clip_buffer_km * 1000.0,
            euclid_steiner_candidates=options.euclid_steiner_candidates,
            geosteiner_home=options.geosteiner_home,
            steiner_candidate_spacing_m=options.steiner_candidate_spacing_m,
        )

        metrics_extra: dict[str, float] | None = None

    else:

        cost_raster = build_cost_raster(

            scene,

            max_slope_deg=options.max_slope_deg,

            slope_cost_factor=options.slope_cost_factor,

        )

        routing = build_routing_graph(

            cost_raster,

            terminals,

            corridors=scene.corridors,

            candidate_stride_cells=options.candidate_stride_cells,

        )

        metrics_extra = {"max_slope_deg": cost_raster.summary()["max_slope_deg"]}

    outgoing_warnings = apply_fixed_terminal_outgoing(
        routing,
        terminals,
        zones=scene.zones or None,
        cost_raster=cost_raster,
        use_obstacle_ban=mode == "euclid" and options.euclid_routing == "obstacle",
    )



    preflight_routing = run_preflight(
        scene,
        terminals,
        routing=routing,
        max_points=options.max_points,
        raster_checks=raster_checks,
        zone_checks=zone_checks,
        allow_terminal_in_zone_buffer=options.allow_terminal_in_zone_buffer,
    )

    if not preflight_routing.ok:

        first = preflight_routing.errors[0]

        raise PlanRequestError(first.code, first.message)

    tree_result = build_network_tree(routing, terminals, solver=options.solver)

    tree_ban = validate_tree_ban_edges(routing, tree_result.tree)

    adjusted = build_adjusted_tree(
        tree_result,
        terminals,
        options=options.post_process,
    )

    edge_ban = validate_tree_edges_ban_zones(adjusted, scene)

    skipped_warnings = routing_skipped_warnings(routing)



    return build_plan_response(

        adjusted,

        project_id=str(request["project_id"]),

        mode=mode,

        solver=tree_result.solver,

        terminals=terminals,

        crs_work=scene.crs_work,

        metrics_extra={
            **(metrics_extra or {}),
            "ban_zones": float(len([z for z in scene.zones if z.mode == "ban"])),
            "routing_edges_skipped": float(len(routing.skipped_pairs)),
        },

        source_warnings=[
            *preflight.warnings,
            *preflight_routing.warnings,
            *geosteiner_warnings,
            *outgoing_warnings,
            *tree_result.warnings,
            *tree_ban.warnings,
            *edge_ban.warnings,
            *skipped_warnings,
        ],

    )

