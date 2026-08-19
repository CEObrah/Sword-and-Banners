from __future__ import annotations

from pathlib import Path

import pytest

from sword_runtime.api.warfare_operations import WarfareCampaignOperations
from sword_runtime.service_runtime import ProductionSwordRuntime


def _operations(campaign: Path, suffix: str) -> WarfareCampaignOperations:
    runtime = ProductionSwordRuntime(
        campaign,
        runtime_root=campaign.parent / suffix,
    )
    return WarfareCampaignOperations(runtime)


def test_controlled_formation_inspection_exposes_command_and_troop_capability(campaign: Path) -> None:
    operations = _operations(campaign, "runtime-command-staff-projection")
    context = operations.play_context()
    formations = context.get("controlled_formations", [])
    assert formations

    for row in formations:
        formation_ref = row["formation_ref"]
        inspected = operations.inspect_game_object(formation_ref)
        formation = inspected["object"]

        command_structure = formation.get("command_structure")
        assert isinstance(command_structure, dict)
        assert command_structure.get("projection_kind") == "formation_command_structure_v4"
        assert command_structure.get("fighting_establishment") == formation.get("personnel")

        troop_capability = formation.get("troop_capability")
        assert isinstance(troop_capability, dict)
        assert troop_capability.get("formation_personnel") == formation.get("personnel")
        assert int(troop_capability.get("cohort_personnel", 0)) >= 0
        assert int(troop_capability.get("unprojected_personnel", 0)) >= 0
        assert isinstance(troop_capability.get("cohorts", []), list)

    hint = context.get("read_hints", {}).get("controlled_formation_command_detail", {})
    assert "Inspect one exact controlled formation_ref" in hint.get("rule", "")


def test_controlled_named_officer_gets_bounded_command_service_sheet(campaign: Path) -> None:
    operations = _operations(campaign, "runtime-command-service-sheet")
    context = operations.play_context()
    player_id = context["campaign"]["player_id"]

    officer_ref = None
    for row in context.get("controlled_formations", []):
        for field in ("commander_ref", "deputy_ref"):
            value = row.get(field)
            if isinstance(value, str) and value.startswith("char_") and value != player_id:
                officer_ref = value
                break
        if officer_ref:
            break
    if officer_ref is None:
        pytest.skip("fixture has no exact non-player controlled-formation officer")

    assert officer_ref in context["permitted_person_ids"]
    sheet = operations.person_sheet(officer_ref)
    assert sheet["visibility"] == "player_visible_command_service_sheet"
    assert sheet["person"]["person_id"] == officer_ref
    assert sheet["person"].get("name")
    assert "relationships" not in sheet["person"]
    assert "behavior" not in sheet["person"]
    assert "private" not in sheet["person"]
