"""Request/response schemas for POST /v1/plan."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class TerminalInput(BaseModel):
    id: UUID
    type: str = "terminal"
    role: Literal["start", "end", "intermediate"] = "intermediate"
    lon: float
    lat: float


class PlanOptions(BaseModel):
    connector_max_km: float = Field(default=0.2, gt=0)
    max_points: int = Field(default=50, ge=2, le=200)


class PlanRequest(BaseModel):
    project_id: UUID | None = None
    terminals: list[TerminalInput] = Field(..., min_length=2)
    options: PlanOptions = Field(default_factory=PlanOptions)

    @model_validator(mode="after")
    def _validate_roles_and_limits(self) -> PlanRequest:
        starts = [t for t in self.terminals if t.role == "start"]
        ends = [t for t in self.terminals if t.role == "end"]
        if len(starts) != 1:
            raise ValueError("exactly one terminal with role 'start' is required")
        if len(ends) != 1:
            raise ValueError("exactly one terminal with role 'end' is required")
        if len(self.terminals) > self.options.max_points:
            raise ValueError(f"total points exceed max_points ({self.options.max_points})")
        return self


class SteinerPointOut(BaseModel):
    id: str
    lon: float
    lat: float


class SteinerEdgeOut(BaseModel):
    from_id: str
    to_id: str
    coordinates: list[list[float]]


class SteinerTreeOut(BaseModel):
    edges: list[SteinerEdgeOut] = Field(default_factory=list)
    steiner_points: list[SteinerPointOut] = Field(default_factory=list)
    length_m: float = 0.0


class TerminalResultOut(BaseModel):
    id: UUID
    type: str = ""
    role: str
    lon: float
    lat: float
    attached_to: str
    via: Literal["tree"] = "tree"
    length_m: float = 0.0


class PlanResponse(BaseModel):
    steiner_tree: SteinerTreeOut
    terminals: list[TerminalResultOut] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    total_length_m: float = 0.0
