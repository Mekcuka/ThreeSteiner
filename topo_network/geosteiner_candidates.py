"""GeoSteiner euclid Steiner candidate generation (P3)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from shapely.geometry import Point

from topo_network.models import TerminalRecord, ZoneRecord

_TERMINAL_CANDIDATE_MIN_M = 5.0
_STEINER_COORD_RE = re.compile(
    r"^\s*%\s*@C\s+([-+\d.eE]+)\s+([-+\d.eE]+)\s*$",
    re.MULTILINE,
)


@dataclass
class GeosteinerCandidateResult:
    points: list[tuple[float, float]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def resolve_geosteiner_home(home: str | Path | None = None) -> Path | None:
    """Resolve GeoSteiner install directory from argument or GEOSTEINER_HOME."""
    if home is not None:
        path = Path(home)
        return path if path.is_dir() else None
    env = os.environ.get("GEOSTEINER_HOME", "").strip()
    if env:
        path = Path(env)
        return path if path.is_dir() else None
    return None


def _find_executable(name: str, home: Path | None) -> Path | None:
    candidates: list[Path] = []
    if home is not None:
        candidates.extend(
            [
                home / name,
                home / f"{name}.exe",
                home / "bin" / name,
                home / "bin" / f"{name}.exe",
            ],
        )
    found = shutil.which(name)
    if found:
        candidates.append(Path(found))
    for path in candidates:
        if path.is_file():
            return path
    return None


def format_efst_point_input(terminals: list[TerminalRecord]) -> str:
    """Plain coordinate list for GeoSteiner ``efst`` (stdin).

    ``efst`` reads all numbers as x/y pairs via ``gst_get_points(stdin, 0, …)``;
    a leading terminal count line would leave an odd number of values.
    """
    lines = [f"{terminal.x_m:.6f} {terminal.y_m:.6f}" for terminal in terminals]
    return "\n".join(lines) + "\n"


def _subprocess_env(home: Path | None) -> dict[str, str]:
    """Ensure MSYS2/UCRT64 DLL directories are on PATH when spawning on Windows."""
    env = os.environ.copy()
    if os.name != "nt" or home is None:
        return env

    parts = home.resolve().parts
    if "home" not in parts:
        return env
    idx = parts.index("home")
    if idx == 0:
        return env

    msys_root = Path(*parts[:idx])
    extra_bins = [
        msys_root / "ucrt64" / "bin",
        msys_root / "mingw64" / "bin",
        msys_root / "usr" / "bin",
    ]
    prefix = os.pathsep.join(str(path) for path in extra_bins if path.is_dir())
    if prefix:
        env["PATH"] = prefix + os.pathsep + env.get("PATH", "")
    return env


def parse_bb_steiner_coordinates(bb_output: str) -> list[tuple[float, float]]:
    """Parse Steiner point coordinates from ``bb`` postscript comments ``% @C x y``."""
    points: list[tuple[float, float]] = []
    for match in _STEINER_COORD_RE.finditer(bb_output):
        points.append((float(match.group(1)), float(match.group(2))))
    return points


def run_geosteiner_efst_bb(
    terminals: list[TerminalRecord],
    *,
    geosteiner_home: str | Path | None = None,
) -> tuple[str | None, str | None]:
    """
    Run ``efst | bb`` on terminal coordinates.

    Returns ``(bb_stdout, error_message)``; stdout is None on failure.
    """
    if len(terminals) < 2:
        return None, "need at least 2 terminals for GeoSteiner"

    home = resolve_geosteiner_home(geosteiner_home)
    efst = _find_executable("efst", home)
    bb = _find_executable("bb", home)
    if efst is None or bb is None:
        return None, "GeoSteiner binaries efst/bb not found (set GEOSTEINER_HOME or PATH)"

    point_data = format_efst_point_input(terminals)
    run_env = _subprocess_env(home)
    run_cwd = str(home) if home is not None else None
    try:
        efst_proc = subprocess.run(
            [str(efst)],
            input=point_data,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
            env=run_env,
            cwd=run_cwd,
        )
        if efst_proc.returncode != 0:
            err = (efst_proc.stderr or efst_proc.stdout or "").strip()
            return None, f"efst failed: {err or efst_proc.returncode}"

        bb_proc = subprocess.run(
            [str(bb)],
            input=efst_proc.stdout,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
            env=run_env,
            cwd=run_cwd,
        )
        if bb_proc.returncode != 0:
            err = (bb_proc.stderr or bb_proc.stdout or "").strip()
            return None, f"bb failed: {err or bb_proc.returncode}"
        return bb_proc.stdout, None
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)


def _near_existing(
    x: float,
    y: float,
    existing: list[tuple[float, float]],
    *,
    min_spacing_m: float,
) -> bool:
    return any(np.hypot(x - ex, y - ey) < min_spacing_m for ex, ey in existing)


def filter_steiner_candidates(
    raw_points: list[tuple[float, float]],
    terminals: list[TerminalRecord],
    ban_zones: list[ZoneRecord],
    *,
    min_spacing_m: float = 1.0,
    terminal_min_m: float = _TERMINAL_CANDIDATE_MIN_M,
) -> tuple[list[tuple[float, float]], int]:
    """
    Drop candidates inside ban, near terminals, and duplicates.

    Returns ``(kept, filtered_count)``.
    """
    terminal_xy = [(t.x_m, t.y_m) for t in terminals]
    kept: list[tuple[float, float]] = []
    filtered = 0

    for x, y in raw_points:
        if _near_existing(x, y, terminal_xy, min_spacing_m=terminal_min_m):
            filtered += 1
            continue
        point = Point(x, y)
        if any(zone.geometry.contains(point) for zone in ban_zones):
            filtered += 1
            continue
        if _near_existing(x, y, kept, min_spacing_m=min_spacing_m):
            filtered += 1
            continue
        kept.append((x, y))

    return kept, filtered


def compute_steiner_candidates(
    terminals: list[TerminalRecord],
    ban_zones: list[ZoneRecord] | None = None,
    *,
    enabled: bool = True,
    geosteiner_home: str | Path | None = None,
    min_spacing_m: float = 1.0,
) -> GeosteinerCandidateResult:
    """Generate filtered Steiner candidate coordinates via GeoSteiner."""
    result = GeosteinerCandidateResult()
    if not enabled or len(terminals) < 2:
        return result

    bb_output, err = run_geosteiner_efst_bb(
        terminals,
        geosteiner_home=geosteiner_home,
    )
    if bb_output is None:
        result.warnings.append(f"geosteiner_unavailable:{err or 'unknown'}")
        return result

    raw = parse_bb_steiner_coordinates(bb_output)
    if not raw:
        result.warnings.append("geosteiner_unavailable:no_steiner_coordinates_in_bb_output")
        return result

    kept, filtered = filter_steiner_candidates(
        raw,
        terminals,
        list(ban_zones or []),
        min_spacing_m=min_spacing_m,
    )
    if filtered:
        result.warnings.append(f"geosteiner_candidates_filtered:{filtered}")
    if kept:
        result.warnings.append(f"geosteiner_candidates_added:{len(kept)}")
    result.points = kept
    return result
