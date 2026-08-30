from __future__ import annotations

import copy
from pathlib import Path

import pytest

from sword_runtime.production_runtime_planner import ProductionCampaignPlanner


def _existing_exact_command(planner: ProductionCampaignPlanner) -> tuple[str, str, dict]:
    index = planner.read("state/index/commander-formation-index.json")
    for commander_ref, refs in index.get("assignments", {}).items():
        if not isinstance(refs, list):
            continue
        for formation_ref in refs:
            try:
                formation = planner.read(planner.owner_path(str(formation_ref)))
                person = planner.read(planner.owner_path(str(commander_ref)))
            except (KeyError, FileNotFoundError, ValueError):
                continue
            assignment = person.get("command_assignment", {}) if isinstance(person, dict) else {}
            if (
                formation.get("commander_ref") == commander_ref
                and isinstance(assignment, dict)
                and assignment.get("formation_ref") == formation_ref
            ):
                return str(commander_ref), str(formation_ref), formation
    raise AssertionError("campaign fixture has no exact indexed formation commander")


def _different_formation(planner: ProductionCampaignPlanner, commander_ref: str, current_ref: str) -> tuple[str, dict]:
    owners = planner.read("state/index/owner-index.json").get("owners", {})
    for ref, path in owners.items():
        if not isinstance(ref, str) or not ref.startswith("formation_") or ref == current_ref:
            continue
        if not isinstance(path, str) or "#/" in path:
            continue
        try:
            row = planner.read(path)
        except (KeyError, FileNotFoundError, ValueError):
            continue
        if isinstance(row, dict) and row.get("commander_ref") != commander_ref:
            return ref, row
    raise AssertionError("campaign fixture has no alternate formation")


def test_stale_extra_commander_index_entry_cannot_block_lawful_existing_command(campaign: Path) -> None:
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    commander_ref, formation_ref, _formation = _existing_exact_command(planner)
    stale_ref, _stale = _different_formation(planner, commander_ref, formation_ref)

    index = copy.deepcopy(planner.read("state/index/commander-formation-index.json"))
    index.setdefault("assignments", {})[commander_ref] = [formation_ref, stale_ref]
    planner.put("state/index/commander-formation-index.json", index)

    planner._assign_commander_index(commander_ref, formation_ref)

    after = planner.read("state/index/commander-formation-index.json")
    assert after["assignments"][commander_ref] == [formation_ref]


def test_missing_commander_index_entry_cannot_overwrite_an_exact_existing_billet(campaign: Path) -> None:
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    commander_ref, formation_ref, _formation = _existing_exact_command(planner)
    target_ref, target = _different_formation(planner, commander_ref, formation_ref)

    index = copy.deepcopy(planner.read("state/index/commander-formation-index.json"))
    index.setdefault("assignments", {}).pop(commander_ref, None)
    planner.put("state/index/commander-formation-index.json", index)

    with pytest.raises(ValueError, match=f"already assigned to {formation_ref}"):
        planner._bind_formation_commander_sheet(commander_ref, target_ref, target)

    person = planner.read(planner.owner_path(commander_ref))
    assert person["command_assignment"]["formation_ref"] == formation_ref


def test_commander_target_choice_ignores_stale_index_formation(campaign: Path) -> None:
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    commander_ref, formation_ref, formation = _existing_exact_command(planner)
    stale_ref, stale = _different_formation(planner, commander_ref, formation_ref)

    state_ref = planner._formation_political_state_ref(formation)
    if planner._formation_political_state_ref(stale) != state_ref:
        pytest.skip("fixture alternate formation is not in the same political state")

    index = copy.deepcopy(planner.read("state/index/commander-formation-index.json"))
    index.setdefault("assignments", {})[commander_ref] = [stale_ref, formation_ref]
    planner.put("state/index/commander-formation-index.json", index)

    assert planner._commander_target_formation(commander_ref, state_ref) == formation_ref
