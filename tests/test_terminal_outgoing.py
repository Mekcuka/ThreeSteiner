"""Tests for fixed terminal outgoing (bearing + length)."""

from __future__ import annotations

import math
from copy import deepcopy
from pathlib import Path

import pytest

from topo_network.models import TerminalRecord
from topo_network.plan_request import PlanRequestError, load_plan_request
from topo_network.pipeline import run_plan
from topo_network.terminal_outgoing import compute_fixed_exit_xy, fixed_exit_node_id

FIXTURES = Path(__file__).resolve().parent / "fixtures"
EUCLID = FIXTURES / "plan_request_euclid.json"


def test_compute_fixed_exit_xy_bearings() -> None:
    base = TerminalRecord("a", 1000.0, 2000.0, "intermediate", 0.0, 100.0)
    north = TerminalRecord("n", 1000.0, 2000.0, "intermediate", 0.0, 100.0)
    east = TerminalRecord("e", 1000.0, 2000.0, "intermediate", 90.0, 100.0)
    south = TerminalRecord("s", 1000.0, 2000.0, "intermediate", 180.0, 100.0)

    assert compute_fixed_exit_xy(north) == pytest.approx((1000.0, 2100.0))
    assert compute_fixed_exit_xy(east) == pytest.approx((1100.0, 2000.0))
    assert compute_fixed_exit_xy(south) == pytest.approx((1000.0, 1900.0))

    base.outgoing_bearing_deg = 45.0
    ex, ey = compute_fixed_exit_xy(base)
    assert ex == pytest.approx(1000.0 + 100.0 * math.sin(math.radians(45.0)))
    assert ey == pytest.approx(2000.0 + 100.0 * math.cos(math.radians(45.0)))


def test_outgoing_requires_both_fields() -> None:
    request, _ = load_plan_request(EUCLID)
    broken = deepcopy(request)
    broken["terminals"][0]["outgoing"] = {"bearing_deg": 90}
    with pytest.raises(PlanRequestError) as exc:
        load_plan_request(broken)
    assert exc.value.code == "invalid_request"
    assert "bearing_deg and length_m" in exc.value.message


def test_run_plan_euclid_with_fixed_outgoing() -> None:
    request, _ = load_plan_request(EUCLID)
    request = deepcopy(request)
    request["options"]["euclid_steiner_candidates"] = False
    request["options"]["connector_max_km"] = 0.04
    request["terminals"][1]["outgoing"] = {"bearing_deg": 90, "length_m": 80}

    response = run_plan(request, base_dir=FIXTURES)
    warnings = response.get("warnings") or []
    assert any(w == "fixed_outgoing_applied:t-mid" for w in warnings)

    exit_id = fixed_exit_node_id("t-mid")
    edges = response["network_tree"]["edges"]
    connector = next(
        (
            e
            for e in edges
            if {e["from"], e["to"]} == {f"terminal:t-mid", exit_id}
        ),
        None,
    )
    assert connector is not None
    assert connector["length_m"] == pytest.approx(80.0, abs=1.0)

    attachments = response["terminals"]
    mid_attach = next(a for a in attachments if a["id"] == "t-mid")
    assert mid_attach["via"] == "fixed_exit"
    assert mid_attach["attached_to"] == exit_id


def test_fixed_outgoing_not_split_by_connector_max() -> None:
    request, _ = load_plan_request(EUCLID)
    request = deepcopy(request)
    request["options"]["euclid_steiner_candidates"] = False
    request["options"]["connector_max_km"] = 0.01
    request["terminals"][1]["outgoing"] = {"bearing_deg": 0, "length_m": 120}

    response = run_plan(request, base_dir=FIXTURES)
    exit_id = fixed_exit_node_id("t-mid")
    edges = response["network_tree"]["edges"]
    connector = next(
        e for e in edges if {e["from"], e["to"]} == {f"terminal:t-mid", exit_id}
    )
    assert connector["length_m"] == pytest.approx(120.0, abs=1.0)
    assert not any(e["from"].startswith("steiner:attach:t-mid") for e in edges)


def test_fixed_outgoing_crosses_ban_warning() -> None:
    request = {
        "project_id": "outgoing-ban",
        "mode": "euclid",
        "terminals": [
            {"id": "t-a", "role": "start", "lon": 39.0016, "lat": 55.9445},
            {"id": "t-b", "role": "end", "lon": 39.0077, "lat": 55.9429},
            {
                "id": "t-out",
                "role": "intermediate",
                "lon": 39.0025,
                "lat": 55.9539,
                "outgoing": {"bearing_deg": 90, "length_m": 200},
            },
        ],
        "options": {
            "euclid_steiner_candidates": False,
            "euclid_routing": "direct",
        },
        "terrain": {
            "zones": [
                {
                    "id": "ban-1",
                    "mode": "ban",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [39.003, 55.9545],
                                [39.0045, 55.9545],
                                [39.0045, 55.953],
                                [39.003, 55.953],
                                [39.003, 55.9545],
                            ]
                        ],
                    },
                }
            ]
        },
    }
    response = run_plan(request)
    warnings = response.get("warnings") or []
    assert any(w.startswith("fixed_outgoing_crosses_ban:") for w in warnings)
    assert response["network_tree"]["edges"]
