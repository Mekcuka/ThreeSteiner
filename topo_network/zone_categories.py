"""Категории penalty-зон и множители стоимости пересечения (за 1 м)."""

from __future__ import annotations

TERRAIN_PENALTY_CATEGORIES: dict[str, float] = {
    "dry_land": 1.0,
    "swamp": 2.0,
    "floodplain": 3.0,
}

LEGACY_PENALTY_MULTIPLIER = 5.0


def validate_penalty_category(category: str) -> None:
    if category not in TERRAIN_PENALTY_CATEGORIES:
        allowed = ", ".join(sorted(TERRAIN_PENALTY_CATEGORIES))
        raise ValueError(f"invalid penalty category: {category!r}; allowed: {allowed}")


def resolve_penalty_multiplier(
    category: str | None,
    *,
    explicit_multiplier: float | None,
) -> float:
    """Множитель penalty: явный multiplier > category > legacy 5.0."""
    if explicit_multiplier is not None:
        return float(explicit_multiplier)
    if category is not None:
        validate_penalty_category(category)
        return TERRAIN_PENALTY_CATEGORIES[category]
    return LEGACY_PENALTY_MULTIPLIER
