# topo_network — HTTP API планирования сети

Микросервис расчёта технологической сети по JSON **PlanRequest** → **PlanResponse**.

Поддерживаются режимы `full` (DEM + LCP), `euclid` (геометрия), зоны ban/penalty с категориями, обход препятствий (visibility graph), опционально GeoSteiner.

## Быстрый старт (локально)

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS
pip install -e ".[dev]"
python tests/fixtures/generate_fixtures.py   # GeoTIFF + Shapefile для тестов
pytest tests/ -q -m "not geosteiner and not slow"
```

### HTTP API + UI

```bash
python examples/serve_plan.py --host 0.0.0.0 --port 8080 --base-dir tests/fixtures
```

| Endpoint | Описание |
|----------|----------|
| `GET /` | Leaflet-прототип (карта + JSON) |
| `GET /health` | Проверка сервера |
| `POST /plan` | PlanRequest → PlanResponse |
| `GET /dev-fixtures/...` | Тестовые JSON (только dev) |

Относительные пути к GeoTIFF/файлам зон резолвятся от `X-Plan-Base-Dir` или env `TOPO_PLAN_BASE_DIR`.

## Docker

```bash
docker build -t topo-network .
docker run -p 8080:8080 -e TOPO_PLAN_BASE_DIR=/data -v /path/to/data:/data topo-network
```

Образ содержит API и UI; данные (DEM, shapefile) монтируйте в `/data` или передавайте inline GeoJSON в запросе (режим `euclid`).

## Пример запроса (euclid)

```json
{
  "project_id": "demo",
  "mode": "euclid",
  "crs": { "work": "EPSG:32637" },
  "terminals": [
    { "id": "t1", "role": "start", "lon": 37.60, "lat": 55.75 },
    { "id": "t2", "role": "end", "lon": 37.64, "lat": 55.74 }
  ],
  "options": { "euclid_routing": "obstacle" }
}
```

Полные примеры: [`schemas/plan_request.example.json`](./schemas/plan_request.example.json).

## OpenAPI

После запуска: `http://localhost:8080/docs`

## GeoSteiner (опционально)

Для `options.euclid_steiner_candidates: true` нужны бинарники GeoSteiner (`efst`, `bb`):

```bash
export GEOSTEINER_HOME=/path/to/geosteiner-5.3
```

Без GeoSteiner расчёт не падает — в `warnings` будет `geosteiner_unavailable`.

## Структура

| Путь | Назначение |
|------|------------|
| `topo_network/` | Пакет: pipeline, API, euclid, export |
| `examples/plan_prototype/` | Веб-UI |
| `examples/serve_plan.py` | Запуск uvicorn (dev) |
| `schemas/` | Примеры JSON |
| `tests/` | pytest (фикстуры генерируются скриптом) |
