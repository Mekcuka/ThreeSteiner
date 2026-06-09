"""HTTP API: POST /plan (этап 7, P1)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from topo_network.pipeline import run_plan
from topo_network.plan_request import PlanRequestError

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_PROTOTYPE_DIR = _REPO_ROOT / "examples" / "plan_prototype"
_DEFAULT_FIXTURES_DIR = _REPO_ROOT / "tests" / "fixtures"
_DEFAULT_BASE_DIR = os.environ.get("TOPO_PLAN_BASE_DIR")


def _resolve_base_dir(
    header_base_dir: str | None,
    *,
    default: str | Path | None = None,
) -> Path | None:
    raw = header_base_dir or default or _DEFAULT_BASE_DIR
    if raw is None:
        return None
    path = Path(str(raw)).expanduser().resolve()
    if not path.is_dir():
        raise PlanRequestError(
            "invalid_request",
            f"base_dir is not a directory: {path}",
        )
    return path


def create_app(
    *,
    default_base_dir: str | Path | None = None,
    prototype_dir: str | Path | None = _DEFAULT_PROTOTYPE_DIR,
    fixtures_dir: str | Path | None = _DEFAULT_FIXTURES_DIR,
) -> FastAPI:
    """FastAPI-приложение с endpoint POST /plan и dev UI."""
    app = FastAPI(
        title="topo_network plan API",
        version="0.1.0",
        description=(
            "Расчёт технологической сети по PlanRequest JSON. "
            "Относительные пути к GeoTIFF/файлам зон резолвятся от "
            "`X-Plan-Base-Dir` или env `TOPO_PLAN_BASE_DIR`. "
            "UI-прототип: GET / (если examples/plan_prototype существует)."
        ),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/plan")
    def plan(
        body: dict[str, Any],
        x_plan_base_dir: str | None = Header(default=None, alias="X-Plan-Base-Dir"),
    ) -> dict[str, Any]:
        try:
            base_dir = _resolve_base_dir(
                x_plan_base_dir,
                default=default_base_dir,
            )
            return run_plan(body, base_dir=base_dir)
        except PlanRequestError as exc:
            return JSONResponse(
                status_code=exc.http_status,
                content=exc.to_dict(),
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    fixtures_path = Path(fixtures_dir) if fixtures_dir else None
    if fixtures_path and fixtures_path.is_dir():
        app.mount(
            "/dev-fixtures",
            StaticFiles(directory=str(fixtures_path)),
            name="dev-fixtures",
        )

    prototype_path = Path(prototype_dir) if prototype_dir else None
    if prototype_path and prototype_path.is_dir():
        app.mount(
            "/",
            StaticFiles(directory=str(prototype_path), html=True),
            name="prototype-ui",
        )

    return app


app = create_app()
