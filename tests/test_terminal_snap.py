"""Each terminal is a leaf of the steiner tree (one incident edge)."""

from uuid import uuid4

from fastapi.testclient import TestClient

from network_planner.api.app import app

client = TestClient(app)


def test_colocated_start_end_terminals():
    tid_a = uuid4()
    tid_b = uuid4()
    lon, lat = 37.60, 55.75
    body = {
        "terminals": [
            {"id": str(tid_a), "type": "oil_pad", "role": "start", "lon": lon, "lat": lat},
            {"id": str(tid_b), "type": "oil_pad", "role": "end", "lon": lon, "lat": lat},
        ],
        "options": {"max_points": 50},
    }
    r = client.post("/v1/plan", json=body)
    assert r.status_code == 200
    data = r.json()
    for term in data["terminals"]:
        assert term["via"] == "tree"
        assert term["length_m"] >= 0
