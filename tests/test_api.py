"""HTTP API tests (этап 7, P1)."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from topo_network.api import create_app

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SYNTHETIC = FIXTURES / "plan_request_synthetic.json"


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app(default_base_dir=FIXTURES))


@pytest.fixture(scope="module")
def synthetic_request() -> dict:
    return json.loads(SYNTHETIC.read_text(encoding="utf-8"))


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_prototype_ui_index(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "topo_network" in response.text
    assert "Рассчитать" in response.text
    assert "map-toolbar" in response.text
    assert "exchangePanel" in response.text
    assert "requestSummary" in response.text
    assert "responseJsonCode" in response.text
    assert "buildPlanRequestFromEditor" in response.text
    assert "rebuildStoredDrawnZones" in response.text
    assert "optNormalizeLeaves" in response.text
    assert "edge_vertex_spacing_km" in response.text


def test_dev_fixtures_euclid_json(client: TestClient) -> None:
    response = client.get("/dev-fixtures/plan_request_euclid.json")
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "euclid"


def test_plan_422_terrain_required(client: TestClient, synthetic_request: dict) -> None:
    broken = deepcopy(synthetic_request)
    del broken["terrain"]
    response = client.post("/plan", json=broken)
    assert response.status_code == 422
    payload = response.json()
    assert payload["errors"][0]["code"] == "terrain_required"


def test_plan_422_invalid_roles(client: TestClient, synthetic_request: dict) -> None:
    broken = deepcopy(synthetic_request)
    broken["terminals"][1]["role"] = "start"
    response = client.post("/plan", json=broken)
    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == "invalid_roles"


def test_plan_422_bad_base_dir(client: TestClient, synthetic_request: dict) -> None:
    response = client.post(
        "/plan",
        json=synthetic_request,
        headers={"X-Plan-Base-Dir": str(FIXTURES / "missing_dir")},
    )
    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == "invalid_request"


@pytest.mark.slow
def test_plan_200(client: TestClient, synthetic_request: dict) -> None:
    response = client.post("/plan", json=synthetic_request)
    assert response.status_code == 200
    payload = response.json()
    assert payload["project_id"] == "fixture-synthetic-scene"
    assert payload["network_tree"]["edges"]
    assert payload["terminals"]


def test_plan_euclid_200(client: TestClient) -> None:
    request = json.loads((FIXTURES / "plan_request_euclid.json").read_text(encoding="utf-8"))
    response = client.post("/plan", json=request)
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "euclid"
    assert payload["network_tree"]["edges"]


def test_plan_euclid_optional_roles(client: TestClient) -> None:
    request = json.loads((FIXTURES / "plan_request_euclid.json").read_text(encoding="utf-8"))
    for terminal in request["terminals"]:
        terminal["role"] = "intermediate"
    response = client.post("/plan", json=request)
    assert response.status_code == 200
    payload = response.json()
    assert payload["network_tree"]["edges"]
    assert len(payload["terminals"]) == len(request["terminals"])
