from __future__ import annotations

import copy
from pathlib import Path

from sword_runtime.production_living_world import ProductionLivingWorldSwordPlanner


def test_production_training_consolidates_server_discovered_breakthrough(campaign: Path) -> None:
    planner = ProductionLivingWorldSwordPlanner(campaign)
    planner.PLAYER_ACTOR = planner.read("state/meta.json")["player_id"]
    planner._reset()

    player = copy.deepcopy(planner.read("state/player.json"))
    player_id = str(player.get("owner_id") or player.get("id") or planner.PLAYER_ACTOR)
    player.setdefault("skills", {})["Sword"] = 200
    development_state = player.setdefault("development_state", {})
    development_state.setdefault("skill_edu_banks", {})["Sword"] = 10000.0
    development_state["breakthrough_event_refs"] = []
    development_state["breakthrough_dossiers"] = {}
    planner.put("state/player.json", player)

    history = copy.deepcopy(planner.read("state/history/events/index.json"))
    history["events"] = [
        {"event_id": "event.breakthrough.one", "kind": "personal_combat", "actor_refs": [player_id], "battle_ref": "battle.one"},
        {"event_id": "event.breakthrough.two", "kind": "interstate_battle", "actor_refs": [player_id], "battle_ref": "battle.two"},
        {"event_id": "event.breakthrough.three", "kind": "siege_assault", "actor_refs": [player_id], "siege_ref": "siege.three"},
    ]
    planner.put("state/history/events/index.json", history)

    updated, breakthrough = planner._resolve_training_breakthrough_if_ready(
        focus="Sword",
        training_result={
            "skill": "Sword",
            "skill_score": 200,
            "routine_training_ceiling": 180,
            "edu_bank_milli": 10_000_000,
        },
    )

    assert breakthrough is not None
    assert updated["skill_score"] == 201
    assert updated["exceptional_breakthrough_point"] == 1
    staged = planner.read("state/player.json")
    assert staged["skills"]["Sword"] == 201
    assert len(staged["development_state"]["breakthrough_event_refs"]) == 3


def test_production_breakthrough_rejects_irrelevant_life_events() -> None:
    assert ProductionLivingWorldSwordPlanner._breakthrough_event_relevant(
        "Sword", {"kind": "marriage"}
    ) is False
    assert ProductionLivingWorldSwordPlanner._breakthrough_event_relevant(
        "Sword", {"kind": "personal_combat"}
    ) is True
    assert ProductionLivingWorldSwordPlanner._breakthrough_event_relevant(
        "Diplomacy", {"kind": "negotiation_settlement"}
    ) is True
