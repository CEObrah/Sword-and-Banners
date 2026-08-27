from pathlib import Path

import pytest

from sword_runtime.commands import CommandEnvelope
from sword_runtime.production_planner import ProductionCampaignPlanner


def test_current_command_group_index_carries_additive_staff_routes(campaign: Path) -> None:
    planner = ProductionCampaignPlanner(campaign)
    idx = planner.read("state/cmd/command-groups/index.json")
    assert isinstance(idx.get("staff_person_groups"), dict)
    assert "cmdgrp.tang_wei.field_army" in idx["staff_person_groups"].get("char_lin_zhen", [])
    # Primary command and additive staff authority are deliberately separate:
    # Lin commands High Guard (4,500) while serving as strategist on Wei's
    # 9,500-man Tang Wei Army root command.
    assert idx["primary_person_group"].get("char_lin_zhen") == "cmdgrp.tang_wei.high_guard"


def test_add_person_rejects_unregistered_staff_role(campaign: Path) -> None:
    planner = ProductionCampaignPlanner(campaign)
    meta = planner.read("state/meta.json")
    command = CommandEnvelope(
        meta["campaign_id"],
        "test-unregistered-staff-role",
        "char_tang_wei",
        "command_group_action",
        meta["revision"],
        meta["time"],
        {
            "action": "add_person",
            "command_group_ref": "cmdgrp.tang_wei.field_army",
            "person_ref": "char_lin_zhen",
            "role": "magic_wizard_staff",
        },
        mode="gameplay",
    )
    with pytest.raises(ValueError, match="unknown registered command-staff role"):
        planner._validate_command_semantics(command, command.payload)
