"""Internal types for Steiner tree construction."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SteinerTreeResult:
    """Tree in local coordinates: edges as (id_a, id_b, (x,y) endpoints)."""

    edges: list[tuple[str, str, tuple[float, float], tuple[float, float]]] = field(
        default_factory=list
    )
    steiner_points: dict[str, tuple[float, float]] = field(default_factory=dict)
    length_m: float = 0.0
    heuristic: bool = False
