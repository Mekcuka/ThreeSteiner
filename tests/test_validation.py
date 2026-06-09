"""Tests for preflight validation (stage 6)."""

from __future__ import annotations

from demo_scene import make_synthetic_scene
from topo_network.models import TerminalRecord
from topo_network.validation import (
    run_preflight,
    validate_raster_extent,
    validate_terminal_ban_zones,
    validate_terminal_count,
    validate_terminal_roles,
)


def test_demo_scene_preflight_ok():
    scene, terminals = make_synthetic_scene()
    result = run_preflight(scene, terminals)
    assert result.ok
    assert not result.errors


def test_invalid_roles_two_starts():
    scene, terminals = make_synthetic_scene()
    bad = [
        TerminalRecord("a", 0, 0, "start"),
        TerminalRecord("b", 1, 1, "start"),
        TerminalRecord("c", 2, 2, "end"),
    ]
    result = validate_terminal_roles(bad)
    assert not result.ok
    assert "invalid_roles" in result.error_codes


def test_optional_roles_no_start_end():
    terminals = [
        TerminalRecord("a", 0, 0, "intermediate"),
        TerminalRecord("b", 1, 1, "branch"),
    ]
    result = validate_terminal_roles(terminals)
    assert result.ok


def test_terminal_in_ban_zone():
    scene, terminals = make_synthetic_scene()
    ban = scene.zones[0].geometry
    xmin, ymin, xmax, ymax = ban.bounds
    inside = TerminalRecord(
        "inside-ban",
        (xmin + xmax) / 2,
        (ymin + ymax) / 2,
        "intermediate",
    )
    result = validate_terminal_ban_zones(scene, [inside])
    assert not result.ok
    assert "terminal_in_ban_zone" in result.error_codes


def test_raster_extent_outside():
    scene, _ = make_synthetic_scene()
    far = TerminalRecord("far", 600_000.0, 6_300_000.0, "intermediate")
    result = validate_raster_extent(scene, [far])
    assert not result.ok
    assert "raster_extent" in result.error_codes


def test_too_many_terminals():
    terminals = [
        TerminalRecord(f"t{i}", float(i), float(i), "intermediate")
        for i in range(51)
    ]
    terminals[0] = TerminalRecord("s", 0, 0, "start")
    terminals[1] = TerminalRecord("e", 1, 1, "end")
    result = validate_terminal_count(terminals, max_points=50)
    assert not result.ok
    assert "too_many_terminals" in result.error_codes
