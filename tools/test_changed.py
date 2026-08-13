#!/usr/bin/env python3
"""Run the smallest maintained regression slice for changed repository paths."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

API_TESTS = {
    "tests/runtime/test_architecture_service.py",
    "tests/runtime/test_stable_operations.py",
    "tests/runtime/test_interaction_surface.py",
}
COMMAND_TESTS = {
    "tests/runtime/test_hostile_command_matrix.py",
    "tests/runtime/test_interaction_surface.py",
}
LIVING_WORLD_TESTS = {
    "tests/runtime/test_living_world_intelligence.py",
    "tests/runtime/test_production_living_world.py",
    "tests/runtime/test_world_arcs.py",
}
GROUP_ACTION_TESTS = {"tests/runtime/test_player_group_actions.py"}
DEFAULT_TESTS = {"tests/runtime/test_architecture_service.py"}


def normalize(value: str) -> str:
    path = Path(value)
    try:
        path = path.resolve().relative_to(ROOT.resolve())
    except (ValueError, OSError):
        pass
    return path.as_posix().lstrip("./")


def select(paths: list[str]) -> list[str]:
    selected: set[str] = set()
    for raw in paths:
        path = normalize(raw)
        if path.startswith("runtime/sword_runtime/api/"):
            selected.update(API_TESTS)
        if path in {"runtime/sword_runtime/command_contracts.py", "game/data/mechanics/command-catalog.json", "game/data/mechanics/command-hostile-contracts.json"}:
            selected.update(COMMAND_TESTS)
        if (
            path.startswith("runtime/sword_runtime/living_world.py")
            or path.startswith("runtime/sword_runtime/causal_living_world.py")
            or path.startswith("runtime/sword_runtime/production_living_world.py")
            or path.startswith("runtime/sword_runtime/systems/campaign_events.py")
            or path.startswith("runtime/sword_runtime/campaign_event_planner.py")
            or path.startswith("runtime/sword_runtime/world_arcs.py")
        ):
            selected.update(LIVING_WORLD_TESTS)
        if path.startswith("runtime/sword_runtime/player_group_actions.py"):
            selected.update(GROUP_ACTION_TESTS)
        if path in {"railway.toml", "pyproject.toml", "requirements.txt"} or path.startswith("runtime/contracts/"):
            selected.update(DEFAULT_TESTS)
        if path.startswith("plugins/sword-and-banners/skills/"):
            selected.update(DEFAULT_TESTS)
        if path.startswith("tests/runtime/") and path.endswith(".py"):
            selected.add(path)
    if not selected:
        selected.update(DEFAULT_TESTS)
    return sorted(path for path in selected if (ROOT / path).is_file())


def main(argv: list[str]) -> int:
    if not argv:
        raise SystemExit("usage: python tools/test_changed.py <changed paths...>")
    tests = select(argv)
    print("test_changed: " + " ".join(tests))
    subprocess.run(
        [sys.executable, "tools/run_pytest_module.py", "-q", *tests],
        cwd=ROOT,
        check=True,
    )
    print("test_changed: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
