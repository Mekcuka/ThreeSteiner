"""Terminal attachment to backbone: one edge per terminal (connector or via node)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from network_planner.geo.projection import LocalProjection
from network_planner.steiner.attach import nearest_attachment
from network_planner.steiner.types import SteinerTreeResult

NODE_SNAP_TOL_M = 2.0
MIN_CONNECTOR_M = 0.5


@dataclass
class ConnectorResult:
    terminal_id: UUID
    coordinates: list[list[float]]
    length_m: float
    attach_to: str
    attach_kind: Literal["steiner", "edge"]
    edge_endpoints: tuple[str, str] | None = None


@dataclass
class TerminalAttachment:
    terminal_id: UUID
    terminal_type: str
    lon: float
    lat: float
    attached_to: str
    via: Literal["connector", "node", "edge"]
    length_m: float
    attach_kind: Literal["steiner", "edge"] | None = None
    edge_endpoints: tuple[str, str] | None = None
    connector: ConnectorResult | None = None


def _nearest_node(
    loc: tuple[float, float],
    node_graph_ids: list[str],
    node_local: list[tuple[float, float]],
    *,
    tol_m: float,
) -> str | None:
    best_id: str | None = None
    best_d = tol_m
    for nid, npt in zip(node_graph_ids, node_local, strict=True):
        d = math.hypot(loc[0] - npt[0], loc[1] - npt[1])
        if d < best_d:
            best_d = d
            best_id = nid
    return best_id


def build_terminal_attachments(
    tree: SteinerTreeResult,
    terminal_ids: list[str],
    terminal_local: list[tuple[float, float]],
    terminal_uuid: list[UUID],
    terminal_types: list[str],
    terminal_lonlat: list[tuple[float, float]],
    node_graph_ids: list[str],
    node_local: list[tuple[float, float]],
    projection: LocalProjection,
    *,
    max_km: float,
) -> tuple[list[TerminalAttachment], list[str]]:
    """
    Each terminal gets exactly one logical connection.
    If within NODE_SNAP_TOL_M of a backbone node, attach via that node (no connector segment).
    """
    warnings: list[str] = []
    out: list[TerminalAttachment] = []
    max_m = max_km * 1000.0
    forbid = set(terminal_ids)

    for tid, loc, uid, ttype, ll in zip(
        terminal_ids,
        terminal_local,
        terminal_uuid,
        terminal_types,
        terminal_lonlat,
        strict=True,
    ):
        lon0, lat0 = ll
        snap_node = _nearest_node(
            loc, node_graph_ids, node_local, tol_m=NODE_SNAP_TOL_M
        )
        if snap_node is not None:
            out.append(
                TerminalAttachment(
                    terminal_id=uid,
                    terminal_type=ttype,
                    lon=lon0,
                    lat=lat0,
                    attached_to=snap_node,
                    via="node",
                    length_m=0.0,
                    connector=None,
                )
            )
            continue

        att = nearest_attachment(tree, loc, forbid_ids=forbid)
        if att.length_m < MIN_CONNECTOR_M:
            out.append(
                TerminalAttachment(
                    terminal_id=uid,
                    terminal_type=ttype,
                    lon=lon0,
                    lat=lat0,
                    attached_to=att.attach_to,
                    via="edge",
                    length_m=0.0,
                    attach_kind=att.attach_kind,
                    edge_endpoints=att.edge_endpoints,
                    connector=None,
                )
            )
            continue
        if att.length_m > max_m:
            warnings.append(f"connector_too_long:{uid}")
        lon1, lat1 = projection.to_wgs84(att.point[0], att.point[1])
        conn = ConnectorResult(
            terminal_id=uid,
            coordinates=[[lon0, lat0], [lon1, lat1]],
            length_m=att.length_m,
            attach_to=att.attach_to,
            attach_kind=att.attach_kind,
            edge_endpoints=att.edge_endpoints,
        )
        out.append(
            TerminalAttachment(
                terminal_id=uid,
                terminal_type=ttype,
                lon=lon0,
                lat=lat0,
                attached_to=att.attach_to,
                via="connector",
                length_m=att.length_m,
                attach_kind=att.attach_kind,
                edge_endpoints=att.edge_endpoints,
                connector=conn,
            )
        )

    return out, warnings
