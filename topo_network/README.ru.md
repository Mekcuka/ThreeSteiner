# topo_network

Python-пакет пайплайна **топографической сети**: от `PlanRequest` (JSON) до `PlanResponse` (дерево рёбер, метрики, warnings).

Связанные документы: [TOPOGRAPHIC_NETWORK_PLAN.ru.md](../TOPOGRAPHIC_NETWORK_PLAN.ru.md), [GLOSSARY.ru.md](../GLOSSARY.ru.md).

---

## Назначение

Построить **связное Steiner-дерево** через все терминалы с учётом:

- **`mode: full`** — DEM, уклон, ban/penalty на растре, LCP-маршруты;
- **`mode: euclid`** — без DEM; ban/penalty по геометрии; обход ban через **граф видимости**; обход penalty (×2/×3) — углы `penalty:*` на контуре зоны.

Точка входа для расчёта: **`run_plan()`** в [`pipeline.py`](pipeline.py).

---

## Поток данных

```text
PlanRequest (JSON)
    │
    ▼
load_plan_request / load_local_scene     ← plan_request.py
    │
    ▼
run_preflight                            ← validation.py
    │
    ├─ mode: full ──► build_cost_raster  ← cost_surface.py
    │                      │
    │                      ▼
    │                 build_routing_graph ← routing_graph.py + lcp.py
    │
    └─ mode: euclid ─► build_euclid_routing_graph
                           ├─ geosteiner_candidates.py (опц. efst|bb)
                           ├─ euclid_zones.py (ban / penalty веса)
                           ├─ direct: прямые рёбра между узлами
                           └─ obstacle + penalty: visibility (ban) + penalty_contour (углы penalty)
    │
    ▼
apply_fixed_terminal_outgoing            ← terminal_outgoing.py (опц. outgoing у терминала)
    │
    ▼
build_network_tree                       ← network_tree.py (SteinerPy)
    │
    ▼
build_adjusted_tree                      ← adjusted_tree.py (hub, attach, …)
    │
    ▼
build_plan_response                      ← export.py (WGS84 JSON)
```

HTTP-обёртка: [`api.py`](api.py) → `POST /plan`.

---

## Модули

| Файл | Этап | Назначение |
|------|------|------------|
| [`models.py`](models.py) | 1–5 | Dataclass: `LocalScene`, `CostRaster`, `TerminalRecord`, `RoutingGraphResult`, `NetworkTreeResult`, `AdjustedTreeResult`, … |
| [`plan_request.py`](plan_request.py) | 7 | Загрузка PlanRequest L0–L9 → `LocalScene` + терминалы + `PlanOptions`; `PlanRequestError` (422) |
| [`cost_surface.py`](cost_surface.py) | 2 | DEM + зоны + коридоры → `CostRaster` (slope, ban, penalty) |
| [`lcp.py`](lcp.py) | 3 | Least cost path по растру (scikit-image); snap терминалов к ячейкам |
| [`routing_graph.py`](routing_graph.py) | 3 | Sparse LCP-граф (`full`) или euclid-граф (`direct` / `obstacle`) |
| [`zone_categories.py`](zone_categories.py) | L6 | Категории penalty: `dry_land`×1, `swamp`×2, `floodplain`×3; `resolve_penalty_multiplier` |
| [`euclid_zones.py`](euclid_zones.py) | euclid | Ban/penalty по Shapely; `zone_terminal_ban_geometry` для preflight |
| [`euclid_visibility.py`](euclid_visibility.py) | euclid | Visibility graph: `obstacle:*` (ban), `penalty:*` (контур penalty), GeoSteiner-кандидаты |
| [`geosteiner_candidates.py`](geosteiner_candidates.py) | euclid | GeoSteiner `efst|bb` → координаты `steiner:candidate:*` |
| [`terminal_outgoing.py`](terminal_outgoing.py) | 3+ | Фиксированный выход `steiner:fixed_exit:{id}` по `outgoing` |
| [`network_tree.py`](network_tree.py) | 4 | Steiner на routing graph (SteinerPy / nx fallback); пары терминалов → shortest path в subgraph |
| [`adjusted_tree.py`](adjusted_tree.py) | 5 | Hub, attach, repel, waypoint |
| [`validation.py`](validation.py) | 6 | Preflight, связность, ban warnings |
| [`export.py`](export.py) | 6 | PlanResponse JSON; `export_plan_response_gpkg` |
| [`pipeline.py`](pipeline.py) | 7 | Оркестратор `run_plan()` |
| [`api.py`](api.py) | 7 | FastAPI `POST /plan`, статика прототипа |
| [`benchmark.py`](benchmark.py) | 6 | Golden-сравнение demo-сцены |

---

## Режимы расчёта

### `mode: full`

1. GeoTIFF → clip по bbox терминалов
2. `build_cost_raster()` — уклон, `max_slope_deg`, rasterize ban/penalty/corridors
3. `build_routing_graph()` — узлы: терминалы + grid + коридоры; рёбра: попарный LCP
4. SteinerPy по **`weight`** (интеграл cost, не длина)

### `mode: euclid`

Без растра DEM. Опционально `terrain.zones`.

| `options.euclid_routing` | Поведение |
|--------------------------|-----------|
| **`obstacle`** (default) | Узлы: терминалы + углы ban (+ GeoSteiner-кандидаты). Рёбра visibility → **полный граф** для SteinerPy |
| **`direct`** | Терминалы + кандидаты; прямые рёбра; ban → `weight = 1e12` |

**Penalty-зоны** (при любом `euclid_routing`): углы effective-полигона → `penalty:{zone_id}:{index}`; Steiner обходит контур, если дешевле прямой (×multiplier вдоль хорды). Суходол (`category: dry_land`, ×1) не удорожает пересечение; обход обычно не выгоден.

**Категории** (`mode: penalty` + `category`): `dry_land` ×1, `swamp` ×2, `floodplain` ×3. Явный `multiplier` в JSON **переопределяет** category. Без category — legacy default **5.0**.

Дополнительно: `euclid_steiner_candidates` (default **true**), `geosteiner_home`, `steiner_candidate_spacing_m`, `obstacle_buffer_m`, `terrain.clip_buffer_km`, `allow_terminal_in_zone_buffer` (терминал в кольце `zones[].buffer_m`, только **ban**).

Зоны: `buffer_m` расширяет **эффективную** геометрию для трасс (`zone.geometry`); ядро без буфера — `geometry_core`. Preflight терминала: по `geometry` (default) или только по core при `allow_terminal_in_zone_buffer: true`.

Без установленного GeoSteiner расчёт продолжается; в ответе — warning `geosteiner_unavailable:...`.

---

## Ключевые типы (`models.py`)

| Тип | Описание |
|-----|----------|
| `LocalScene` | CRS, elevation, transform, zones, corridors |
| `CostRaster` | 2D `cost[]`, `slope_deg`, cell size |
| `ZoneRecord` | id, geometry (effective), geometry_core, buffer_m, mode, multiplier, category (`dry_land` \| `swamp` \| `floodplain`) |
| `TerminalRecord` | id, x_m, y_m, role; опц. `outgoing_bearing_deg`, `outgoing_length_m` |
| `RoutingGraphResult` | NetworkX graph, nodes, skipped_pairs |
| `NetworkTreeResult` | Steiner-дерево до post-process |
| `AdjustedTreeResult` | Дерево после hub/attach + attachments |

---

## Публичный API (`__init__.py`)

Экспортируется для внешнего использования:

```python
from topo_network import run_plan, load_local_scene, load_plan_request
from topo_network import build_cost_raster, build_routing_graph, build_network_tree
from topo_network import build_euclid_routing_graph, compute_steiner_candidates
from topo_network import build_adjusted_tree, build_plan_response
from topo_network import run_preflight, PlanRequestError
```

**Не в `__init__.py`**, но используются пайплайном:

- `build_euclid_obstacle_routing_graph`, `build_euclid_visibility_routing_graph`
- `build_euclid_scene`
- `export_plan_response_gpkg`

---

## Быстрый старт

```python
from topo_network import run_plan

# full + DEM
response = run_plan("tests/fixtures/plan_request_synthetic.json", base_dir="tests/fixtures")

# euclid + ban + обход
response = run_plan("tests/fixtures/plan_request_euclid_zones.json", base_dir="tests/fixtures")
```

CLI / HTTP:

```bash
python examples/demo_plan_request.py tests/fixtures/plan_request_euclid_zones.json
python examples/serve_plan.py --base-dir tests/fixtures
# POST http://127.0.0.1:8000/plan
```

---

## Зависимости

| Режим | Библиотеки |
|-------|------------|
| **full** | numpy, rasterio, scikit-image, shapely, networkx, steinerpy, pyproj, geopandas |
| **euclid** | shapely, networkx, steinerpy, pyproj (+ geopandas для loader/API). **GeoSteiner** — опционально, вне `requirements.txt` |

См. [`requirements.txt`](../requirements.txt).

---

## Ошибки и warnings

| Код | Когда |
|-----|--------|
| `PlanRequestError` | HTTP 422: invalid_request, terrain_required, terminal_in_ban_zone, … |
| `route_may_be_blocked` | warning: нет ban-free пути (direct) или нет visibility-пути |
| `edge_crosses_ban_zone` | warning: геометрия ребра пересекает ban |
| `fixed_outgoing_*` | warning: фиксированный выход (`outgoing`) — applied / crosses_ban / exit_in_ban / snap_failed |
| `geosteiner_unavailable:…` | GeoSteiner не найден или subprocess упал; кандидаты не добавлены |
| `geosteiner_candidates_added:{n}` | Добавлено n узлов `steiner:candidate:*` |
| `geosteiner_candidates_filtered:{n}` | n кандидатов отброшено (ban / dedupe / близко к terminal) |

---

## Тесты

```bash
pytest tests/ -q -k "not slow"
pytest tests/ -m geosteiner   # опционально, нужны бинарники efst/bb
```

Основные: `test_plan_request_load.py`, `test_euclid_zones.py`, `test_zone_categories.py`, `test_zone_buffer_terminal.py`, `test_terminal_outgoing.py`, `test_geosteiner_candidates.py`, `test_api.py`, `test_export_gpkg.py`.

---

## Ограничения

- LCP MVP: scikit-image (production-кандидат: WhiteboxTools).
- Steiner: SteinerPy на дискретном графе, не непрерывная оптимизация.
- Euclid obstacle: обход по **углам** ban-полигонов + опциональные GeoSteiner-кандидаты; не гладкая дуга.
- Euclid penalty: обход по **углам** penalty-полигонов (`penalty:*`); ломаная, не дуга; суходол ×1 почти не влияет на выбор трассы.
- GeoSteiner ESMT **не учитывает ban** при генерации координат; фильтр ban + visibility обеспечивают обход.
- Post-processing не строит новый маршрут — только hub/attach на уже выбранном дереве.

Полный список параметров: [PARAMETERS.ru.md](PARAMETERS.ru.md).
