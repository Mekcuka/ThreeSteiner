from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from network_planner.api.app import app
from network_planner.schemas.io import PlanRequest

client = TestClient(app)


def _sample_request(**kwargs) -> dict:
    start = uuid4()
    end = uuid4()
    base = {
        "project_id": str(uuid4()),
        "terminals": [
            {
                "id": str(start),
                "type": "oil_pad",
                "role": "start",
                "lon": 37.60,
                "lat": 55.75,
            },
            {
                "id": str(uuid4()),
                "type": "oil_pad",
                "role": "intermediate",
                "lon": 37.62,
                "lat": 55.76,
            },
            {
                "id": str(end),
                "type": "gas_processing",
                "role": "end",
                "lon": 37.64,
                "lat": 55.74,
            },
        ],
        "options": {"connector_max_km": 5.0, "max_points": 50},
    }
    base.update(kwargs)
    return base


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_plan_success():
    r = client.post("/v1/plan", json=_sample_request())
    assert r.status_code == 200
    data = r.json()
    assert data["steiner_tree"]["length_m"] > 0
    assert len(data["steiner_tree"]["edges"]) >= 1
    assert "start_end_not_connected" not in data["warnings"]


def test_terminals_in_steiner_tree():
    body = _sample_request()
    r = client.post("/v1/plan", json=body)
    assert r.status_code == 200
    data = r.json()
    assert len(data["terminals"]) == 3
    terminal_ids = {t["id"] for t in body["terminals"]}
    assert {t["id"] for t in data["terminals"]} == terminal_ids
    assert all(t["via"] == "tree" for t in data["terminals"])
    roles = {t["role"] for t in data["terminals"]}
    assert roles == {"start", "end", "intermediate"}
    edge_ids = set()
    for edge in data["steiner_tree"]["edges"]:
        edge_ids.add(edge["from_id"])
        edge_ids.add(edge["to_id"])
    for tid in terminal_ids:
        assert f"terminal:{tid}" in edge_ids


def test_plan_requires_start_and_end_roles():
    body = _sample_request()
    body["terminals"] = [
        {"id": str(uuid4()), "role": "start", "lon": 37.6, "lat": 55.75},
        {"id": str(uuid4()), "role": "intermediate", "lon": 37.61, "lat": 55.75},
    ]
    r = client.post("/v1/plan", json=body)
    assert r.status_code == 422


def test_plan_schema_validation():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PlanRequest.model_validate(
            {
                "terminals": [
                    {
                        "id": str(uuid4()),
                        "role": "start",
                        "lon": 37.6,
                        "lat": 55.75,
                    }
                ],
            }
        )
