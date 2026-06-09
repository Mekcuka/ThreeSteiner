"""Единая учебная сцена для notebook.ipynb, examples/ и lib-ноутбуков."""

from __future__ import annotations

import numpy as np
from rasterio.transform import Affine, from_origin
from shapely.geometry import LineString, box

from topo_network.models import LocalScene, TerminalRecord, ZoneRecord

ORIGIN_X = 500_000.0
ORIGIN_Y = 6_200_000.0
CELL_M = 10.0
ROWS, COLS = 40, 50

BAN_BOX = (500_170.0, 6_199_770.0, 500_320.0, 6_199_880.0)
PENALTY_BOX = (500_400.0, 6_199_700.0, 500_480.0, 6_199_780.0)
CORRIDOR_WAYPOINTS: list[tuple[float, float]] = [
    (500_100.0, 6_199_900.0),
    (500_180.0, 6_199_965.0),
    (500_360.0, 6_199_965.0),
    (500_450.0, 6_199_750.0),
]

# Зона исключения вокруг уже проложенной трассы (notebook.ipynb, § две трассы)
TRACE_EXCLUSION_BUFFER_M = 20.0
HUB_CLEARANCE_M = 30.0

# t-north — на северном обходе ban (вне ban по Y, на коридоре)
TERMINAL_SPECS: list[tuple[str, float, float, str]] = [
    ("t-start", 500_100.0, 6_199_900.0, "start"),
    ("t-mid", 500_450.0, 6_199_800.0, "intermediate"),
    ("t-end", 500_480.0, 6_199_720.0, "end"),
    ("t-north", 500_250.0, 6_199_970.0, "branch"),
]


def make_transform() -> Affine:
    return from_origin(ORIGIN_X, ORIGIN_Y, CELL_M, CELL_M)


def make_elevation(rows: int = ROWS, cols: int = COLS) -> np.ndarray:
    y, x = np.mgrid[0:rows, 0:cols]
    return 100.0 + 0.5 * x + 0.2 * y


def make_terminals() -> list[TerminalRecord]:
    return [TerminalRecord(tid, x, y, role) for tid, x, y, role in TERMINAL_SPECS]


def terminal_node_id(terminal_id: str) -> str:
    return f"terminal:{terminal_id}"


def make_synthetic_scene() -> tuple[LocalScene, list[TerminalRecord]]:
    """Учебная сцена 40×50 ячеек, шаг 10 м."""
    transform = make_transform()
    elevation = make_elevation()
    ban_zone = box(*BAN_BOX)
    penalty_zone = box(*PENALTY_BOX)
    corridor = LineString(CORRIDOR_WAYPOINTS)

    scene = LocalScene(
        crs_work="EPSG:32637",
        transform=transform,
        elevation=elevation,
        nodata=-9999.0,
        zones=[
            ZoneRecord("ban-1", ban_zone, "ban"),
            ZoneRecord("swamp", penalty_zone, "penalty", multiplier=5.0),
        ],
        corridors=[corridor],
        corridor_cost_multiplier=0.5,
        corridor_buffer_m=20.0,
    )
    return scene, make_terminals()
