#!/usr/bin/env python3
"""Run the smallest maintained regression slice for changed repository paths."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

API_TESTS = {"tests/runtime/test_architecture_service.py", "tests/runtime/test_stable_operations.py", "tests/runtime/test_interaction_surface.py", "tests/runtime/test_household_social_surface.py"}
COMMAND_TESTS = {"tests/runtime/test_hostile_command_matrix.py", "tests/runtime/test_interaction_surface.py"}
V6_STRATEGIC_TESTS = {"tests/runtime/test_v6_strategic_depth.py"}
CIVIL_WORLD_TESTS = {"tests/runtime/test_civil_world.py", "tests/runtime/test_causal_connections.py", "tests/runtime/test_production_living_world.py", "tests/runtime/test_world_arcs.py"}
LIVING_WORLD_TESTS = {"tests/runtime/test_campaign_event_liveness.py", "tests/runtime/test_living_world_intelligence.py", "tests/runtime/test_production_living_world.py", "tests/runtime/test_world_arcs.py"}
ENVIRONMENT_TESTS = {"tests/runtime/test_environment.py"}
GROUP_ACTION_TESTS = {"tests/runtime/test_player_group_actions.py"}
COHORT_TESTS = {"tests/runtime/test_exact_aggregate_conservation.py", "tests/runtime/test_production_exceptional_progression.py", "tests/runtime/test_release_hardening.py", "tests/runtime/test_combat_cohort_integration.py", "tests/runtime/test_release_military_logistics.py"}
PERSON_TESTS = {"tests/runtime/test_exact_aggregate_conservation.py", "tests/runtime/test_character_progression_schema.py", "tests/runtime/test_release_hardening.py"}
TRANSACTION_TESTS = {"tests/runtime/test_transactions.py"}
REFERENCE_TESTS = {"tests/runtime/test_world_reference_search.py"}
LONG_HORIZON_TESTS = {"tests/runtime/test_long_horizon.py"}
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
        if path in {"runtime/sword_runtime/environment.py", "game/data/world/environment-climates.json", "runtime/contracts/environment.json", "tests/runtime/test_environment.py"}:
            selected.update(ENVIRONMENT_TESTS | API_TESTS | CIVIL_WORLD_TESTS | COHORT_TESTS)
        if path == "runtime/sword_runtime/production_planner.py":
            selected.update(ENVIRONMENT_TESTS | GROUP_ACTION_TESTS | CIVIL_WORLD_TESTS | COHORT_TESTS)
        if path in {"runtime/sword_runtime/command_contracts.py", "game/data/mechanics/command-catalog.json", "game/data/mechanics/command-hostile-contracts.json"}:
            selected.update(COMMAND_TESTS | V6_STRATEGIC_TESTS)
        if (path.startswith("runtime/sword_runtime/living_world.py") or path.startswith("runtime/sword_runtime/causal_living_world.py") or path.startswith("runtime/sword_runtime/production_living_world.py") or path.startswith("runtime/sword_runtime/systems/campaign_events.py") or path.startswith("runtime/sword_runtime/campaign_event_planner.py") or path.startswith("runtime/sword_runtime/world_arcs.py") or path.startswith("runtime/sword_runtime/causal_event_store.py")):
            selected.update(LIVING_WORLD_TESTS)
            if path.startswith("runtime/sword_runtime/causal_event_store.py"):
                selected.add("tests/runtime/test_causal_connections.py")
        if (path.startswith("runtime/sword_runtime/civil_world.py") or path.startswith("game/data/mechanics/civil-economy.json") or path.startswith("game/data/politics/faction-profiles.json") or path.startswith("state/markets/") or path.startswith("state/economy/private/") or path.startswith("state/economy/merchant-houses.json") or path.startswith("state/contract/tang-supply-contracts.json") or path.startswith("state/contract/tang-contracted-defense.json") or path.startswith("game/schemas/sword-merchant-house-registry.schema.json") or path.startswith("game/schemas/sword-polity.schema.json") or path.startswith("game/schemas/sword-diplomatic-proposal.schema.json") or path.startswith("state/politics/polities/") or path.startswith("state/politics/diplomatic-proposals/") or path.startswith("state/population/") or path.startswith("state/territory/") or path.startswith("state/factions/")):
            selected.update(CIVIL_WORLD_TESTS | V6_STRATEGIC_TESTS)
        if path.startswith("runtime/sword_runtime/history_store.py") or path.startswith("game/schemas/sword-history-segment.schema.json") or path.startswith("state/history/"):
            selected.add("tests/runtime/test_history_store.py"); selected.update(LIVING_WORLD_TESTS)
        if path == "runtime/sword_runtime/engine.py":
            selected.update(CIVIL_WORLD_TESTS | V6_STRATEGIC_TESTS | LIVING_WORLD_TESTS | COMMAND_TESTS)
        if path == "game/data/mechanics/rules-runtime-parity.json":
            selected.update(CIVIL_WORLD_TESTS | LIVING_WORLD_TESTS)
        if path.startswith("runtime/sword_runtime/activity_living_world.py"):
            selected.update(LONG_HORIZON_TESTS)
        if path.startswith("runtime/sword_runtime/tx/"):
            selected.update(TRANSACTION_TESTS)
        if path.startswith("runtime/sword_runtime/api/world_reference.py") or path.startswith("game/data/world/noble-houses.json"):
            selected.update(REFERENCE_TESTS)
        if path.startswith("state/politics/treaties.json") or path.startswith("game/schemas/sword-treaty-registry.schema.json") or path.startswith("game/schemas/sword-diplomatic-proposal.schema.json") or path.startswith("state/politics/diplomatic-proposals/") or path.startswith("state/institutions/"):
            selected.update(CIVIL_WORLD_TESTS)
        if path.startswith("game/schemas/sword-court-case.schema.json"):
            selected.update(V6_STRATEGIC_TESTS)
        if path.startswith("state/arc/") or path.startswith("game/schemas/event-registry.schema.json"):
            selected.add("tests/runtime/test_world_arcs.py")
        if path.startswith("game/schemas/sword-causal-event-") or path.startswith("state/event/archive/") or path.startswith("state/event/index/route_"):
            selected.update({"tests/runtime/test_causal_connections.py", "tests/runtime/test_world_arcs.py"})
        if path.startswith("runtime/sword_runtime/player_group_actions.py"):
            selected.update(GROUP_ACTION_TESTS)
        if (path.startswith("runtime/sword_runtime/cohort_personnel.py") or path.startswith("runtime/sword_runtime/cohort_tx_support.py") or path.startswith("runtime/sword_runtime/combat_capability.py") or path.startswith("runtime/sword_runtime/force_cohort_living_world.py") or path.startswith("runtime/sword_runtime/house_tang_development.py") or path.startswith("game/data/mil/combat-role-profiles.json") or path.startswith("game/data/mil/standing-force-capability-baselines.json") or path.startswith("game/data/mechanics/formation.json") or path.startswith("game/data/mechanics/economy.json")):
            selected.update(COHORT_TESTS)
        if path.startswith("runtime/sword_runtime/recruitment_campaigns.py") or path.startswith("runtime/sword_runtime/cohort_personnel.py") or path.startswith("game/data/mil/recruitment-cohort-profiles.json"):
            selected.update(PERSON_TESTS | V6_STRATEGIC_TESTS)
        if path in {"railway.toml", "pyproject.toml", "requirements.txt"} or path.startswith("runtime/contracts/"):
            selected.update(DEFAULT_TESTS)
        if path.startswith("plugins/sword-and-banners/skills/"):
            selected.update(DEFAULT_TESTS); selected.add("tests/runtime/test_skill_repository_contract.py")
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
    for test_path in tests:
        print(f"test_changed: running {test_path}", flush=True)
        subprocess.run([sys.executable, "tools/run_pytest_module.py", "-q", test_path], cwd=ROOT, check=True)
    print("test_changed: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
