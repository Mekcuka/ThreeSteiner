"""HTTP routes."""

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from network_planner.plan.pipeline import plan_from_request
from network_planner.schemas.io import PlanRequest, PlanResponse

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/v1/plan", response_model=PlanResponse)
def plan(req: PlanRequest) -> PlanResponse:
    try:
        return plan_from_request(req)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
