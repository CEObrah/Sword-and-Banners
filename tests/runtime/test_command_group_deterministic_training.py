from __future__ import annotations

import copy
from types import SimpleNamespace

from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.training_programs import drill_record, program_record


def _allowed_program_skills(registry, program_ref: str) -> set[str]:
    return {
        str(skill)
        for module in program_record(registry, program_ref)["rotation"]
        for skill in drill_record(registry, str(module["drill_ref"])).get("skills", [])
    }


def test_command_group_training_theme_cannot_invent_gain_focus(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    runtime["pending_wake"] = None
    # Keep this integration fixture bounded to the requested one-hour local drill.
    for event in runtime.get("events", []):
        if isinstance(event, dict):
            event["suspended"] = True
    planner.put("state/runtime.json", runtime)

    before_wei = copy.deepcopy(planner.read("state/player.json"))
    lin_path = planner.owner_path("char_lin_zhen")
    before_lin = copy.deepcopy(planner.read(lin_path))
    command = SimpleNamespace(
        actor_id=planner.PLAYER_ACTOR,
        expected_revision=int(planner.read("state/meta.json")["revision"]),
        command_type="command_group_train",
        request_id="test-command-group-deterministic-training",
        digest="test-command-group-deterministic-training",
        semantic_digest="test-command-group-deterministic-training",
    )

    result = planner._dispatch_command_group_train(command, {
        "command_group_ref": "cmdgrp.tang_wei.field_army",
        "hours": 1,
        # Deliberately irrelevant to the saved senior-command program. It remains
        # a coordination/theme label and must not become gain authority.
        "focus": "Axe",
    })

    after_wei = planner.read("state/player.json")
    after_lin = planner.read(lin_path)
    registry = planner.read("game/data/mil/deterministic-training-programs.json")
    allowed = _allowed_program_skills(registry, "program.tang_field_senior_command")

    assert result["focus"] == "Axe"
    assert set(result["person_development"]) == {"char_tang_wei", "char_lin_zhen"}
    for ref, row in result["person_development"].items():
        assert row["gain_authority"] == "registered_deterministic_program"
        assert row["program_ref"] == "program.tang_field_senior_command"
        assert row["requested_theme"] == "Axe"
        assert 0 < row["verified_hours"] <= 1

    for before, after in ((before_wei, after_wei), (before_lin, after_lin)):
        before_skills = before["skills"]
        after_skills = after["skills"]
        changed = {skill for skill, value in after_skills.items() if value != before_skills.get(skill)}
        assert changed <= allowed
        assert "Axe" not in after_skills
        assert "Axe" not in before_skills
        ledger = after.get("development_state", {}).get("training_time_ledger", {}).get("active_entries", [])
        assert any(row.get("kind") == "personal_training" for row in ledger)
