# Steiner Network Planner

Python microservice that builds a **Euclidean Steiner tree** over map **terminals**. **Start** and **end** of the network are terminals with roles `start` and `end`; other objects use `intermediate`.

## Model

| Layer | Points | Connection |
|-------|--------|------------|
| `steiner_tree` | all `terminals` + optional `steiner:*` | SMT; each terminal is a leaf (one incident edge) |
| `terminals` | result rows | `role`, `via: tree`, `attached_to` = neighbor on the tree |

Terminal IDs appear in `steiner_tree.edges` as `terminal:{uuid}`.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -e ".[dev]"
uvicorn network_planner.api:app --reload --port 8080
```

Health: `GET http://localhost:8080/health`  
Plan: `POST http://localhost:8080/v1/plan`

## Request example

```json
{
  "project_id": "550e8400-e29b-41d4-a716-446655440000",
  "terminals": [
    { "id": "11111111-1111-1111-1111-111111111101", "type": "oil_pad", "role": "start", "lon": 37.60, "lat": 55.75 },
    { "id": "22222222-2222-2222-2222-222222222201", "type": "oil_pad", "role": "intermediate", "lon": 37.62, "lat": 55.76 },
    { "id": "11111111-1111-1111-1111-111111111102", "type": "gas_processing", "role": "end", "lon": 37.64, "lat": 55.74 }
  ],
  "options": {
    "connector_max_km": 0.2,
    "max_points": 50
  }
}
```

Exactly one terminal with `role: "start"` and one with `role: "end"` is required.

## Response (outline)

- `steiner_tree` — tree over terminals (`steiner_points`, `edges`)
- `terminals` — every object with `role`, `via`, `attached_to`, `length_m`
- `warnings` — e.g. `smt_heuristic_mst`, `terminal_degree_violation`, `start_end_not_connected`
- `total_length_m` — tree length

## Algorithms

| Terminals n | Method |
|-------------|--------|
| collinear | Star on line median (each leaf degree 1) |
| 2 | Single edge (or collinear star) |
| 3 | Torricelli–Simpson / collinear star |
| 4 | Full SMT, 3 topologies |
| 5 | Split 4+1 |
| 6+ | Steiner star (centroid / line median) |

## Demo by terminal count

```bash
python scripts/demo_terminal_counts.py
```

Writes `examples/by_terminal_count/summary.json` (zigzag: first=start, last=end).

## Tests

```bash
pytest
```

## Docker

```bash
docker build -t network-planner .
docker run -p 8080:8080 network-planner
```

## API docs

OpenAPI UI: `http://localhost:8080/docs`
