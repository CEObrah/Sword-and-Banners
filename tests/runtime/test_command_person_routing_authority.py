from __future__ import annotations

import json
from pathlib import Path

from sword_runtime.api.warfare_operations import WarfareCampaignOperations
from sword_runtime.battle_command import _command_group_for_person
from sword_runtime.commander_cognition import _primary_command_group
from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.service_runtime import ProductionSwordRuntime


def _corrupt_player_person_routes(campaign: Path) -> None:
    path = campaign / "state/cmd/command-groups/index.json"
    index = json.loads(path.read_text(encoding="utf-8"))
    index.setdefault("primary_person_group", {})["char_tang_wei"] = "cmdgrp.kanki.field_army"
    index.setdefault("command_person_groups", {})["char_tang_wei"] = ["cmdgrp.kanki.field_army"]
    path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_stale_player_person_route_cannot_expose_enemy_group_as_controlled(campaign: Path) -> None:
    _corrupt_player_person_routes(campaign)
    operations = WarfareCampaignOperations(
        ProductionSwordRuntime(campaign, runtime_root=campaign.parent / "runtime-stale-player-person-route")
    )
    context = operations.play_context()
    refs = {row["command_group_ref"] for row in context.get("controlled_command_groups", [])}
    assert "cmdgrp.tang_wei.field_army" in refs
    assert "cmdgrp.kanki.field_army" not in refs


def test_stale_or_missing_person_routes_cannot_replace_or_suppress_exact_commander_assignment(campaign: Path) -> None:
    _corrupt_player_person_routes(campaign)
    planner = ProductionCampaignPlanner(campaign)

    battle_group = _command_group_for_person(planner, "char_tang_wei")
    cognition_group = _primary_command_group(planner, "char_tang_wei")

    assert battle_group is not None
    assert cognition_group is not None
    assert battle_group.get("commander_ref") == "char_tang_wei"
    assert cognition_group.get("commander_ref") == "char_tang_wei"
    assert battle_group.get("context") == "field_army"
    assert cognition_group.get("context") == "field_army"
