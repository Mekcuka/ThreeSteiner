"""Запуск HTTP API: POST /plan (этап 7, P1).

Поднимает FastAPI с расчётом и HTML-прототипом для ручного тестирования:
  http://127.0.0.1:8000/  — UI (Leaflet + JSON)
  POST /plan              — PlanRequest → PlanResponse
  GET /health             — проверка сервера
  GET /dev-fixtures/...   — тестовые JSON и Shapefile (dev)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="topo_network plan HTTP API + HTML UI at http://host:port/"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--base-dir",
        default=os.environ.get("TOPO_PLAN_BASE_DIR"),
        help="Корень для относительных path в PlanRequest (GeoTIFF, GPKG)",
    )
    args = parser.parse_args()

    if args.base_dir:
        os.environ["TOPO_PLAN_BASE_DIR"] = str(Path(args.base_dir).resolve())

    print(f"UI:  http://{args.host}:{args.port}/")
    print(f"API: POST http://{args.host}:{args.port}/plan")

    import uvicorn

    uvicorn.run(
        "topo_network.api:app",
        host=args.host,
        port=args.port,
        reload=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
