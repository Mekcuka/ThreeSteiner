# Параметры и константы topo_network

Справочник **всех настраиваемых величин**: что задаёт пользователь в JSON, что зашито в коде, на что влияет.

Простое правило:

- **JSON / options** — меняете в запросе `POST /plan`, не трогая код.
- **Константы в `.py`** — меняются только правкой кода (или позже — через конфиг).
- **Demo / notebook** — для учебных примеров, в `run_plan()` по умолчанию **не** участвуют.

---

## 1. Корень запроса

| Поле | Где читается | Default | На что влияет |
|------|--------------|---------|---------------|
| `mode` | [`plan_request.py`](plan_request.py) | обязательно | `"full"` — DEM + LCP; `"euclid"` — без растра |
| `project_id` | [`pipeline.py`](pipeline.py) | обязательно | Имя в ответе, не на расчёт |
| `terminals[]` | [`plan_request.py`](plan_request.py) | ≥ 2 точек | Узлы сети; роли `start` / `end` / `intermediate` / `branch` |

### Поля терминала

| Поле | Default | На что влияет |
|------|---------|---------------|
| `id` | — | Идентификатор в графе (`terminal:{id}`) |
| `role` | — | Не более одного `start` и одного `end` (оба опциональны); метка в ответе; при наличии пары — preflight start→end |
| `lon`, `lat` | — | Координаты → метры в `crs_work` |
| `outgoing.bearing_deg` | нет | Географический азимут первого отрезка от терминала: 0° = север (+Y), 90° = восток (+X), по часовой |
| `outgoing.length_m` | нет | Длина фиксированного отрезка (м); вместе с `bearing_deg` задаёт узел `steiner:fixed_exit:{id}` |
| `attachment_max_km` | нет | **Задокументировано** для override длины примыкания; в `run_plan()` **пока не передаётся** в `build_adjusted_tree` (см. [`adjusted_tree.py`](adjusted_tree.py)) |

**`outgoing` (опционально):** если объект присутствует, **оба** поля обязательны; `length_m > 0`. После построения routing graph ([`terminal_outgoing.py`](terminal_outgoing.py)) все рёбра с `terminal:{id}` удаляются, добавляется прямой connector `terminal:{id}` → `steiner:fixed_exit:{id}` (`fixed_outgoing=True`). Steiner и LCP/visibility идут от exit, не от произвольного соседа. Post-process **не** режет такое ребро по `connector_max_km`. Warnings: `fixed_outgoing_applied:{id}`, `fixed_outgoing_crosses_ban:{id}`, `fixed_outgoing_exit_in_ban:{id}`, `fixed_outgoing_snap_failed:{id}` (full).

---

## 2. Блок `terrain`

### Общие

| Поле | `full` | `euclid` | Default | На что влияет |
|------|--------|----------|---------|---------------|
| `elevation_raster.path` | да | запрещён | — | GeoTIFF высот; размер и clip участка |
| `elevation_raster.crs` | опц. | — | из файла | Рабочая CRS; иначе UTM по centroid терминалов |
| `elevation_raster.nodata` | опц. | — | из файла | Ячейки без данных → cost = ∞ |
| `clip_buffer_km` | да | да | **0.5** | **`full`:** буфер bbox вокруг терминалов при clip DEM. **`euclid`:** рамка для узлов visibility (× 1000 → м) |
| `zones[]` | да | да | `[]` | Ban / penalty полигоны |
| `corridors` | да | запрещён | — | Дешёвые линейные коридоры на растре |

### Зона (`terrain.zones[]`)

| Поле | Default | На что влияет |
|------|---------|---------------|
| `id` | обяз. | Имя зоны, id узлов obstacle |
| `mode` | обяз. | `"ban"` — запрет; `"penalty"` — удорожание |
| `category` | — | Только для `penalty`: `dry_land` (суходол ×1), `swamp` (болото ×2), `floodplain` (пойма ×3). Задаёт `multiplier`, если он не указан явно ([`zone_categories.py`](zone_categories.py)) |
| `multiplier` | **5.0** (penalty без category), **1.0** (ban) | **`full`:** × cost на растре. **`euclid`:** множитель вдоль отрезка (penalty). **Явное значение в JSON переопределяет `category`** — не задавайте `multiplier` вместе с `category`, если нужны стандартные ×1/×2/×3 |
| `buffer_m` | **0** | Расширение **эффективной** зоны для трасс (`zone.geometry`); ядро без буфера — `geometry_core`. Буфер строится с `resolution=4` (не сотни дуг на углах). В **`euclid` + obstacle** дополнительно — `options.obstacle_buffer_m` |
| `geometry` / `source.path` | один из | GeoJSON или Shapefile |

### Коридоры (`terrain.corridors`)

| Поле | Default | На что влияет |
|------|---------|---------------|
| `cost_multiplier` | **0.5** | Cost в полосе коридора = ×0.5 (дешевле) |
| `source` / `geometry` | — | LineString; буфер задаётся отдельно |

---

## 3. Блок `options` → [`PlanOptions`](plan_request.py)

Читается в [`load_options()`](plan_request.py). Передаётся в pipeline, cost surface, routing, Steiner, post-process.

### Режим и солвер

| Поле | Default | Файл / этап | На что влияет |
|------|---------|-------------|---------------|
| `solver` | **`steinerpy`** | [`network_tree.py`](network_tree.py) | `"steinerpy"` — MIP SteinerPy; `"nx_approx"` — приближение NetworkX |
| `max_points` | **50** | [`validation.py`](validation.py) | Макс. число терминалов; иначе 422 |

### Cost surface (`mode: full` only)

| Поле | Default | Файл | На что влияет |
|------|---------|------|---------------|
| `max_slope_deg` | **30** | [`cost_surface.py`](cost_surface.py) | Уклон выше → **cost = ∞** (непроходимо) |
| `slope_cost_factor` | **1.0** | [`cost_surface.py`](cost_surface.py) | Плавное удорожание до `max_slope_deg`; **0** = только жёсткий ban по уклону |

### Routing graph (`mode: full`)

| Поле | Default в JSON | Default в `build_routing_graph()` | На что влияет |
|------|----------------|-----------------------------------|---------------|
| `candidate_stride_cells` | **8** | 5 (если вызвать без pipeline) | Шаг subsample сетки: каждая N-я ячейка → узел-кандидат. **Меньше** = плотнее граф, медленнее |

Параметры **только в коде** [`build_routing_graph()`](routing_graph.py) (pipeline их не пробрасывает из JSON):

| Параметр | Default | На что влияет |
|----------|---------|---------------|
| `corridor_sample_m` | **50** | Шаг точек вдоль линии коридора |
| `max_pair_distance_m` | **2000** | Если узлов > 80 — LCP только для пар ближе этого расстояния |
| `min_node_spacing_m` | **5** | Мин. расстояние между кандидатами (дедуп) |
| `max_nodes_for_full_lcp` | **80** | Порог: выше — фильтр по `max_pair_distance_m` |

### Euclid + ban

| Поле | Default | Файл | На что влияет |
|------|---------|------|---------------|
| `euclid_routing` | **`obstacle`** | [`routing_graph.py`](routing_graph.py) | **`obstacle`** — visibility graph (если есть ban). **`direct`** — все пары узлов, ban → `weight=1e12` |
| `obstacle_buffer_m` | **5** | [`euclid_visibility.py`](euclid_visibility.py) | Ban-полигон расширяется перед извлечением углов `obstacle:*` |
| `clip_buffer_km` | см. **`terrain`** | [`euclid_visibility.py`](euclid_visibility.py) | Bbox терминалов + буфер (× 1000 → м): какие углы ban и кандидаты попадают в граф |
| `euclid_steiner_candidates` | **`true`** | [`geosteiner_candidates.py`](geosteiner_candidates.py) | GeoSteiner `efst\|bb` → узлы `steiner:candidate:*`. **`false`** — terminal + `obstacle:*` / `penalty:*` (без GeoSteiner) |
| `geosteiner_home` | `null` | [`geosteiner_candidates.py`](geosteiner_candidates.py) | Override пути к GeoSteiner; иначе env **`GEOSTEINER_HOME`** или `PATH` |
| `steiner_candidate_spacing_m` | **1.0** | [`geosteiner_candidates.py`](geosteiner_candidates.py) | Dedupe кандидатов и повторный dedupe узлов visibility |
| `allow_terminal_in_zone_buffer` | **`false`** | [`validation.py`](validation.py) | **`true`** — preflight ban по **ядру** (`geometry_core`); терминал допустим в кольце `buffer_m`; трассы по-прежнему по `zone.geometry` |

**Поведение `euclid_routing` (важно):**

| Условие | Фактический граф |
|---------|------------------|
| `obstacle` + есть `mode: ban` | Полный visibility graph: `terminal:*` + `obstacle:*` + опц. `steiner:candidate:*`; ребро только если отрезок **не** пересекает ban |
| `obstacle` + **нет** ban | Прямые рёбра между узлами (углы ban не добавляются); при penalty — см. строку ниже |
| `direct` | Прямые рёбра; ban → `skipped_pairs` + `weight=1e12`, `crosses_ban=True` |
| Есть `mode: penalty` (любой `euclid_routing`) | Углы effective-полигона → `penalty:{zone_id}:{index}`; обход по контуру, если дешевле прямой (×multiplier вдоль хорды) |
| Любой режим | **Routing graph для SteinerPy** = этот граф целиком. Subgraph = union кратчайших путей между терминалами; SteinerPy материализует пары через **shortest path** в subgraph ([`network_tree.py`](network_tree.py)) |

**Программный вызов:** [`build_euclid_routing_graph()`](routing_graph.py) по умолчанию `euclid_routing="direct"`; [`run_plan()`](pipeline.py) берёт default **`obstacle`** из [`PlanOptions`](plan_request.py).

#### GeoSteiner: установка и отладка

GeoSteiner — **опциональный** внешний инструмент. В `requirements.txt` **не входит**. Роль в пайплайне: только **генерация координат** внутренних Steiner-точек для `mode: euclid`; финальное дерево по-прежнему строит **SteinerPy** на visibility-графе. GeoSteiner **не учитывает ban** при расчёте ESMT — ban применяются на этапах фильтра и visibility.

**Когда вызывается**

| Условие | Поведение |
|---------|-----------|
| `mode: euclid` и `euclid_steiner_candidates: true` (default) | Попытка `efst \| bb` |
| `euclid_steiner_candidates: false` | Subprocess не вызывается |
| `< 2` терминалов | GeoSteiner не вызывается |
| Бинарники не найдены / subprocess упал | `[]`, warning `geosteiner_unavailable:…`, **расчёт продолжается** |

**Установка (Linux / WSL)**

1. Скачать и собрать [GeoSteiner](https://www3.cs.stonybrook.edu/~algorith/implement/geosteiner/distrib/README.htm) (типично каталог вроде `geosteiner-5.3/` с исполняемыми `efst`, `bb`).
2. Указать каталог одним из способов (приоритет сверху вниз):

| Способ | Пример |
|--------|--------|
| `options.geosteiner_home` в PlanRequest | `"geosteiner_home": "/opt/geosteiner-5.3"` |
| env **`GEOSTEINER_HOME`** | `export GEOSTEINER_HOME=/opt/geosteiner-5.3` |
| **`PATH`** | `efst` и `bb` доступны как команды в shell |

**Где ищутся бинарники** ([`_find_executable`](geosteiner_candidates.py)):  
`$GEOSTEINER_HOME/efst`, `$GEOSTEINER_HOME/bin/efst` (и то же для `bb`), затем `shutil.which("efst")` / `which("bb")`.

**Windows (MSYS2 UCRT64):** собрать `efst.exe` / `bb.exe`, указать `GEOSTEINER_HOME` (часто `C:\Program Files\msys2\home\user\geosteiner-5.3`, **не** `C:\msys64\…`). При `./configure` на GCC 15: `CFLAGS="-std=gnu99"` (буква **O** в `-O3`, не ноль/маленькая o). Полный `make` может упасть на `demo2`; достаточно `make efst bb`. Код сам добавляет `ucrt64\bin` в `PATH` subprocess, если каталог лежит под `…/home/…` MSYS2.

**Что делает subprocess**

```text
terminals (x_m, y_m в crs_work)
    → stdin efst: N пар "x y" (без строки-счётчика; иначе odd count → "X coord without Y coord")
    → stdout efst → stdin bb
    → stdout bb: парсинг строк "% @C x y"
    → filter (ban, 5 m к terminal, dedupe)
    → узлы steiner:candidate:{index} в visibility-графе
```

Таймаут каждого процесса: **120 с**. Ошибки `efst` / `bb` попадают в `geosteiner_unavailable:efst failed:…` и т.п.

**Пример options в PlanRequest**

```json
{
  "mode": "euclid",
  "options": {
    "euclid_steiner_candidates": true,
    "geosteiner_home": "/opt/geosteiner-5.3",
    "steiner_candidate_spacing_m": 1.0,
    "euclid_routing": "obstacle"
  }
}
```

**Проверка**

```bash
# unit-тесты без бинарников (mock + парсер fixture)
pytest tests/test_geosteiner_candidates.py -q -k "not geosteiner"

# e2e с реальными efst/bb (не в CI по умолчанию)
export GEOSTEINER_HOME=/opt/geosteiner-5.3
pytest tests/ -m geosteiner
```

Fixture парсера: [`tests/fixtures/geosteiner_bb_sample.txt`](../tests/fixtures/geosteiner_bb_sample.txt).  
В HTML-прототипе: чекбокс **«GeoSteiner кандидаты»** → `options.euclid_steiner_candidates`.

**Ограничения**

- GeoSteiner ESMT **игнорирует ban** и cost surface; это приближение в рамках дискретного графа, не глобальный минимум с ban.
- `solver: "geosteiner"` как **primary** solver в PlanRequest **не реализован** (v2); используйте `solver: "steinerpy"`.
- Кандидаты внутри ban или ближе 5 m к terminal отбрасываются — смотрите `geosteiner_candidates_filtered:{n}`.

### Коридоры на растре

| Поле | Default | На что влияет |
|------|---------|---------------|
| `corridor_buffer_m` | **15** | Ширина буфера линии коридора при rasterize (м) |

### Постобработка → [`PostProcessOptions`](models.py)

| Поле | Default | Файл | На что влияет |
|------|---------|------|---------------|
| `connector_max_km` | **0.2** | [`adjusted_tree.py`](adjusted_tree.py) | Макс. длина «подводки» от терминала к магистрали; длиннее → узел `attach` |
| `steiner_radius_km` | **0** | [`adjusted_tree.py`](adjusted_tree.py) | Круг вокруг терминала, куда **нельзя** ставить Steiner-точки (repel) |
| `normalize_terminal_leaves` | **true** | [`adjusted_tree.py`](adjusted_tree.py) | На терминале с несколькими рёбрами — hub + короткий stub 0.1 м |
| `edge_vertex_spacing_km` | **0** | [`adjusted_tree.py`](adjusted_tree.py) | **> 0** — разбить длинные рёбра на waypoint-узлы |
| `enforce_attachment_radius` | **true** | [`adjusted_tree.py`](adjusted_tree.py) | **false** — не резать длинные примыкания (чистое Steiner-дерево) |

### Задокументированы, но не в MVP post-process

| Поле | Default в плане | Статус |
|------|-----------------|--------|
| `attachment_angle_deg` | 90 | **Не используется** в коде post-process |
| `attachment_angle_penalty` | 0 | **Не используется** в коде post-process |

---

## 4. Константы в коде (жёстко в `.py`)

### [`lcp.py`](lcp.py)

| Константа | Значение | На что влияет |
|-----------|----------|---------------|
| `LCP_FORBIDDEN_COST` | **1e12** | Ячейки с cost = ∞ в LCP; также «forbidden weight» для ban в euclid `direct` |
| `snap_to_finite_cell` → `max_radius` | **5** | Сколько ячеек вокруг терминала искать проходимую ячейку на растре |

### [`euclid_zones.py`](euclid_zones.py)

| Константа | Значение | На что влияет |
|-----------|----------|---------------|
| `EUCLID_PENALTY_SAMPLE_M` | **2.0** | Шаг сэмплирования penalty вдоль отрезка (euclid) |
| `EUCLID_BAN_FORBIDDEN_WEIGHT` | **1e12** (= LCP) | Weight ребра через ban в режиме `direct` |
| `edge_blocked_by_ban` → `eps_m` | **1e-3** | Мин. длина пересечения, чтобы считать «пересекает ban» |

### [`euclid_visibility.py`](euclid_visibility.py)

| Параметр | Default | На что влияет |
|----------|---------|---------------|
| `_dedupe_nodes` → `min_spacing_m` | **1.0** | Слияние близких узлов visibility |
| `EUCLID_CONTOUR_MAX_VERTS` | **36** | Децимация контура ban/penalty для узлов `obstacle:*` / `penalty:*` |
| `EUCLID_VISIBILITY_PENALTY_SAMPLES_MAX` | **80** | Макс. сэмплов penalty на ребро при построении графа (длинные хорды) |
| `build_euclid_obstacle_routing_graph` → `clip_buffer_m` | **500** | Если не передан из pipeline — fallback bbox (pipeline передаёт `clip_buffer_km × 1000`) |
| `_prune_to_terminal_component` | — | Удаляет изолированные углы ban вне компоненты терминалов |

### [`geosteiner_candidates.py`](geosteiner_candidates.py)

| Константа / параметр | Default | На что влияет |
|----------------------|---------|---------------|
| `_TERMINAL_CANDIDATE_MIN_M` | **5.0** | Не добавлять кандидат ближе 5 м к terminal |
| `min_spacing_m` / `steiner_candidate_spacing_m` | **1.0** | Dedupe кандидатов и узлов visibility |
| `GEOSTEINER_HOME` | env | Каталог с `efst`, `bb`; иначе `PATH` |
| Парсер `% @C x y` | regex | Координаты Steiner-точек из stdout `bb` |

**Warnings:** `geosteiner_unavailable:…`, `geosteiner_candidates_added:{n}`, `geosteiner_candidates_filtered:{n}`.

**Фильтр кандидатов** (`filter_steiner_candidates`): отбрасываются точки внутри ban (`contains`), ближе **5 m** к terminal, ближе `steiner_candidate_spacing_m` к уже принятому кандидату; вне `clip_buffer_km` bbox — не попадают в граф (`_steiner_candidate_nodes`).

### [`network_tree.py`](network_tree.py)

| Параметр | Default | На что влияет |
|----------|---------|---------------|
| `solver` | **`steinerpy`** | `"steinerpy"` — MIP HiGHS; `"nx_approx"` — NetworkX Mehlhorn |
| `_terminal_relevant_subgraph` | — | Узлы на SP между всеми парами терминалов → индуцированный подграф (ускорение SteinerPy) |
| `_materialize_selected_edges` | — | Если SteinerPy вернул пару без прямого ребра — раскрытие shortest path по subgraph |

**Warnings:** `subgraph:{n}/{m}_nodes`, `solver_fallback:{exc}`.

### [`adjusted_tree.py`](adjusted_tree.py)

| Константа | Значение | На что влияет |
|-----------|----------|---------------|
| `_STUB_LENGTH_M` | **0.1** | Длина stub-ребра terminal → hub (м) |

### [`cost_surface.py`](cost_surface.py)

| Параметр | Default | На что влияет |
|----------|---------|---------------|
| `LocalScene.corridor_cost_multiplier` | **0.5** | Из JSON `corridors.cost_multiplier` |
| `LocalScene.corridor_buffer_m` | **15.0** | Из `options.corridor_buffer_m` |
| `trace_exclusion_mask` → `hub_clearance_m` | **25.0** | «Окно» вокруг hub при exclusion второй трассы (notebook/API cost, не `run_plan`) |

### [`models.py`](models.py)

| Поле | Default | На что влияет |
|------|---------|---------------|
| `ZoneRecord.multiplier` | category / **5.0** | Из `category` (1/2/3), явного `multiplier` или legacy 5.0 |
| `ZoneRecord.category` | — | `dry_land` \| `swamp` \| `floodplain` (только penalty) |

### [`validation.py`](validation.py)

| Параметр | Default | На что влияет |
|----------|---------|---------------|
| `run_preflight` → `clip_buffer_m` | **0** | Запас при проверке «терминал внутри растра» |
| `validate_terminal_count` → `max_points` | **50** | Лимит терминалов |

### [`benchmark.py`](benchmark.py)

| Параметр | Default | На что влияет |
|----------|---------|---------------|
| `compare_to_golden` → `rel_tol` | **1e-3** | Допуск сравнения с golden-файлом |
| `compare_to_golden` → `abs_tol` | **0.5** | Абсолютный допуск (м) |
| `run_demo_scene_benchmark` → `connector_max_km` | **0.05** | Только demo benchmark |

### [`api.py`](api.py) / HTTP

| Переменная | Default | На что влияет |
|------------|---------|---------------|
| `TOPO_PLAN_BASE_DIR` | нет | Корень для относительных `path` в JSON |
| Заголовок `X-Plan-Base-Dir` | — | То же, приоритет над env |
| CORS / static paths | repo paths | UI прототип и `/dev-fixtures` |

### [`examples/serve_plan.py`](../examples/serve_plan.py)

| CLI | Default | На что влияет |
|-----|---------|---------------|
| `--host` | **127.0.0.1** | Адрес сервера |
| `--port` | **8000** | Порт |
| `--base-dir` | env `TOPO_PLAN_BASE_DIR` | Base dir для API |

---

## 5. Demo / notebook (не PlanRequest)

Константы [`notebooks/demo_scene.py`](../notebooks/demo_scene.py) — **учебная сцена**, не подставляются в `run_plan()` автоматически:

| Константа | Значение | На что влияет |
|-----------|----------|---------------|
| `CELL_M` | **10** | Размер ячейки synthetic DEM |
| `ROWS`, `COLS` | **40**, **50** | Размер synthetic растра |
| `TRACE_EXCLUSION_BUFFER_M` | **20** | Буфер «вторая трасса не здесь» в notebook |
| `HUB_CLEARANCE_M` | **30** | Дырка в exclusion вокруг start (notebook) |
| `BAN_BOX`, `PENALTY_BOX`, `TERMINAL_SPECS` | координаты | Демо-участок |

---

## 6. Как параметры тянутся по pipeline

```text
PlanRequest
  terrain.clip_buffer_km ──────► clip DEM (full)
                              └► clip_buffer_m для euclid visibility
  terrain.zones[].buffer_m ────► ZoneRecord.geometry (трассы); geometry_core (preflight)
  terrain.zones[].category ────► zone_categories → ZoneRecord.multiplier (1/2/3)
  terrain.zones[] penalty ─────► euclid_visibility: penalty:{id}:{index} (контур)
  terminals[].outgoing ────────► apply_fixed_terminal_outgoing → steiner:fixed_exit:*
  options.allow_terminal_in_zone_buffer ► validate_terminal_ban_zones (core vs effective)

  options.max_slope_deg ───────► build_cost_raster (full)
  options.slope_cost_factor ───► build_cost_raster (full)
  options.candidate_stride_cells ► build_routing_graph (full)
  options.corridor_buffer_m ───► LocalScene + rasterize corridors

  options.euclid_routing ──────► build_euclid_routing_graph
  options.obstacle_buffer_m ───► euclid_visibility
  options.euclid_steiner_candidates ► geosteiner_candidates → steiner:candidate:*
  options.geosteiner_home ─────► geosteiner_candidates (override GEOSTEINER_HOME)
  options.steiner_candidate_spacing_m ► dedupe кандидатов + visibility nodes

  options.solver ──────────────► build_network_tree
  options.post_process.* ──────► build_adjusted_tree
       (connector_max_km, steiner_radius_km, normalize_terminal_leaves,
        edge_vertex_spacing_km, enforce_attachment_radius)
```

---

## 7. Шпаргалка «что крутить для типичных задач»

| Задача | Параметры |
|--------|-----------|
| Сеть не обходит ban в euclid | `euclid_routing: "obstacle"`, при необходимости ↑ `obstacle_buffer_m` |
| Пойма/болото: обход по контуру в euclid | Автоматически при `mode: penalty` (узлы `penalty:*`); выгодно при ×2/×3; суходол ×1 обычно пересекают напрямую |
| Суходол обходится, хотя ×1 | Проверьте JSON: нет ли `"multiplier": 5` (перебивает category); прямая может идти через соседние ×2/×3 зоны — обход суходола побочный |
| Штрафные зоны на карте | `mode: penalty` + `category`: `dry_land` \| `swamp` \| `floodplain`; в прототипе — кнопки «+ суходол / болото / пойма» |
| Пойма/болото: трасса через зону в euclid | Penalty не запрещает проход; обход — только если дешевле прямой; иначе трасса может идти через зону |
| Внутренние Steiner-точки в euclid | `euclid_steiner_candidates: true` + `GEOSTEINER_HOME`; без бинарников — warning, расчёт OK |
| Слишком медленный `full` | ↑ `candidate_stride_cells`, уменьшить участок `clip_buffer_km` |
| Крутые склоны непроходимы | ↓ `max_slope_deg` или ↑ `slope_cost_factor` |
| Длинные «хвосты» к терминалам | ↓ `connector_max_km`, `enforce_attachment_radius: true` |
| Чистое Steiner без hub/attach | `normalize_terminal_leaves: false`, `enforce_attachment_radius: false` |
| Отключить GeoSteiner (быстрее, без subprocess) | `euclid_steiner_candidates: false` |
| Дешевле вдоль дороги | `terrain.corridors` + `cost_multiplier` < 1 |
| Запретная зона на карте | `zones[].mode: "ban"` |
| Отступ трассы от ban | `zones[].buffer_m` (м); на карте в прототипе — оранжевый контур |
| Терминал у ban, но не внутри core | `buffer_m` + `options.allow_terminal_in_zone_buffer: true` |
| Фиксированное направление от терминала | `terminals[].outgoing: { bearing_deg, length_m }` |

---

## 8. Идентификаторы узлов routing graph

| Префикс | `GraphNode.kind` | Источник |
|---------|------------------|----------|
| `terminal:{id}` | `terminal` | `terminals[]` |
| `obstacle:{zone_id}:{index}` | `obstacle` | Вершины ban-полигона (+ `obstacle_buffer_m`) |
| `penalty:{zone_id}:{index}` | `penalty_contour` | Углы penalty-полигона (`zone.geometry`, с `buffer_m`); обход в euclid |
| `steiner:candidate:{index}` | `steiner_candidate` | GeoSteiner после фильтра |
| `steiner:fixed_exit:{terminal_id}` | `fixed_exit` | Фиксированный выход по `outgoing` ([`terminal_outgoing.py`](terminal_outgoing.py)) |
| `grid:…`, `corridor:…` | `grid`, `corridor` | Только `mode: full`, [`routing_graph.py`](routing_graph.py) |

После post-process в `AdjustedNode.kind`: `hub`, `attach`, `waypoint`, `steiner`, `steiner_candidate`, `fixed_exit` (см. [`adjusted_tree.py`](adjusted_tree.py)).

---

## 9. Warnings в `PlanResponse`

| Код / префикс | Источник | Когда |
|---------------|----------|-------|
| `geosteiner_unavailable:…` | GeoSteiner | Бинарники не найдены, subprocess упал, нет `% @C` в выводе |
| `geosteiner_candidates_added:{n}` | GeoSteiner | n кандидатов добавлено в граф |
| `geosteiner_candidates_filtered:{n}` | GeoSteiner | n кандидатов отброшено (ban / dedupe / terminal) |
| `routing_skipped:{a}:{b}:{reason}` | [`validation.py`](validation.py) | Пара без маршрута в euclid `direct` (`ban_forbidden_weight`, …) |
| `route_may_be_blocked` | preflight | Нет ban-free / visibility пути между терминалами |
| `edge_crosses_ban_zone` | post-validate | Геометрия ребра пересекает ban |
| `subgraph:{n}/{m}_nodes` | [`network_tree.py`](network_tree.py) | SteinerPy работал на subgraph, не на полном графе |
| `solver_fallback:{exc}` | [`network_tree.py`](network_tree.py) | SteinerPy упал → `nx_approx` |
| `attachment_skipped:degree:…` | [`adjusted_tree.py`](adjusted_tree.py) | Терминал с degree>1, hub не вставлен |
| `attachment_limit:…` | [`adjusted_tree.py`](adjusted_tree.py) | Примыкание длиннее `connector_max_km` |
| `steiner_repel_failed:…` | [`adjusted_tree.py`](adjusted_tree.py) | Repel не смог сдвинуть Steiner из `steiner_radius_km` |
| `start_end_not_connected` | [`adjusted_tree.py`](adjusted_tree.py) | start и end не на одном дереве после post-process |
| `fixed_outgoing_applied:{id}` | [`terminal_outgoing.py`](terminal_outgoing.py) | Фиксированный выход применён для терминала |
| `fixed_outgoing_crosses_ban:{id}` | [`terminal_outgoing.py`](terminal_outgoing.py) | Отрезок terminal→exit пересекает ban (расчёт продолжается) |
| `fixed_outgoing_exit_in_ban:{id}:{zone}` | [`terminal_outgoing.py`](terminal_outgoing.py) | Точка exit внутри ban |
| `fixed_outgoing_snap_failed:{id}` | [`terminal_outgoing.py`](terminal_outgoing.py) | full: exit не привязан к finite cell растра |

---

## 10. HTML-прототип ([`examples/plan_prototype/index.html`](../examples/plan_prototype/index.html))

| Элемент UI | Поле в PlanRequest |
|------------|-------------------|
| **+ ban** | `mode: "ban"` |
| **+ суходол / болото / пойма** | `mode: "penalty"` + `category`: `dry_land` \| `swamp` \| `floodplain` |
| **buffer_m (м)** | `terrain.zones[].buffer_m` для всех зон на карте; оранжевый контур = effective-полигон (core + buffer) |
| **allow_terminal_in_zone_buffer** | `options.allow_terminal_in_zone_buffer` (только **ban**) |
| **Обход ban (visibility graph)** | `options.euclid_routing: "obstacle"` |
| **Рассчитать** | `buildPlanRequestFromEditor()` → merge зон с карты в JSON → `POST /plan` |

**Синхронизация penalty-зон:** при «карта → JSON» для зон с `category` в запрос попадает **только** `category` (без `multiplier`). Legacy `multiplier: 5` подставляется **только** для penalty без `category` и без явного множителя (старые зоны без категории).

**Перед расчётом:** проверьте вкладку «Запрос» — у penalty с категорией не должно быть лишнего `"multiplier": 5` (иначе API игнорирует ×1/×2/×3).

**Визуализация:** заливка ban — красная; penalty — зелёный (суходол), коричневый (болото), голубой (пойма); `buffer_m` — оранжевый пунктир для всех типов зон.

---

## 11. Связанные документы

- [README.ru.md](README.ru.md) — обзор пакета
- [TOPOGRAPHIC_NETWORK_PLAN.ru.md §4.3](../TOPOGRAPHIC_NETWORK_PLAN.ru.md) — полная схема PlanRequest
- [GLOSSARY.ru.md](../GLOSSARY.ru.md) — термины
