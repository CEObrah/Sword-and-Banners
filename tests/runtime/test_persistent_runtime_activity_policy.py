from __future__ import annotations

from copy import deepcopy

from sword_runtime.production_runtime_planner import ProductionCampaignPlanner


def test_hosted_advance_time_inherits_saved_player_standing_training(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()

    player = deepcopy(planner.read("state/player.json"))
    player.setdefault("activity_contract", {})["auto_settle_standing_training"] = True
    planner.put("state/player.json", player)

    policy = planner._policy({"hours": 24})

    assert policy == {"player_standing_training": True}


def test_explicit_player_training_false_overrides_saved_automatic_setting(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()

    player = deepcopy(planner.read("state/player.json"))
    player.setdefault("activity_contract", {})["auto_settle_standing_training"] = True
    planner.put("state/player.json", player)

    policy = planner._policy(
        {"hours": 24, "activity_policy": {"player_standing_training": False}}
    )

    assert policy == {"player_standing_training": False}


def test_saved_player_routine_does_not_infer_formation_or_npc_training_targets(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()

    player = deepcopy(planner.read("state/player.json"))
    player.setdefault("activity_contract", {})["auto_settle_standing_training"] = True
    planner.put("state/player.json", player)

    policy = planner._policy({"hours": 24})

    assert "formation_refs" not in policy
    assert "household_standing_person_refs" not in policy
