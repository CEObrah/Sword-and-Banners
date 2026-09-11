from __future__ import annotations

import json
from pathlib import Path

from sword_runtime.api.warfare_operations import WarfareCampaignOperations
from sword_runtime.service_runtime import ProductionSwordRuntime


def _ops(campaign: Path, suffix: str) -> WarfareCampaignOperations:
    return WarfareCampaignOperations(
        ProductionSwordRuntime(campaign, runtime_root=campaign.parent / suffix)
    )


def _field_army(context: dict) -> dict:
    return next(
        row for row in context.get("controlled_command_groups", [])
        if row.get("command_group_ref") == "cmdgrp.tang_wei.field_army"
    )


def test_tang_wei_field_army_projects_lin_as_strategist_and_first_successor(campaign: Path) -> None:
    operations = _ops(campaign, "runtime-command-group-lin")
    context = operations.play_context()
    group = _field_army(context)

    assert context["controlled_command_groups_count"] >= 1
    assert group["commander_ref"] == "char_tang_wei"
    assert group["role_assignments"]["char_lin_zhen"] == "strategist"
    assert group["successor_refs"][0] == "char_lin_zhen"
    assert group["standing_doctrine_ref"] == "doc.tang_wei.field_army"
    assert group["integrity_status"] == "ok"
    assert group["integrity_diagnostics"] == []
    assert "char_lin_zhen" in context["permitted_person_ids"]

    sheet = operations.person_sheet("char_lin_zhen")
    assert sheet["person"]["person_id"] == "char_lin_zhen"


def test_command_group_projection_keeps_lin_visible_and_surfaces_desync(campaign: Path) -> None:
    lin_path = campaign / "state/char/lin-zhen.json"
    lin = json.loads(lin_path.read_text(encoding="utf-8"))
    lin["current_location"] = "loc_tang_manor"
    lin_path.write_text(json.dumps(lin, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    index_path = campaign / "state/cmd/command-groups/index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index.setdefault("staff_person_groups", {})["char_lin_zhen"] = ["cmdgrp.somewhere_else"]
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    operations = _ops(campaign, "runtime-command-group-lin-desync")
    context = operations.play_context()
    group = _field_army(context)

    assert group["role_assignments"]["char_lin_zhen"] == "strategist"
    assert "char_lin_zhen" in context["permitted_person_ids"]
    assert group["integrity_status"] == "needs_attention"
    issues = {row["issue"] for row in group["integrity_diagnostics"]}
    assert "command_group_location_mismatch" in issues
    assert "command_group_assignment_mismatch" in issues
