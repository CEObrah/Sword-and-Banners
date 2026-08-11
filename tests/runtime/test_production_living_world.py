from __future__ import annotations

from pathlib import Path

from sword_runtime.production_living_world import ProductionLivingWorldSwordPlanner


def test_reserved_formation_is_absolutely_ineligible(campaign: Path) -> None:
    planner = ProductionLivingWorldSwordPlanner(campaign)
    score = planner._formation_score(
        "formation_reserved",
        {
            "personnel": 10000,
            "status": "ready",
            "readiness": 100,
            "morale": 100,
            "cohesion": 100,
            "training_progress": 100,
            "fatigue": 0,
            "composition": {"siege_engineering": 10000},
            "logistics": {"food_kg": 1_000_000},
        },
        "siege and breach a fortified position",
        {"state_memory": {}, "formation_memory": {}},
        {"formation_reserved"},
    )
    assert score <= -(10**8)


def test_interstate_provenance_uses_exact_location_ref(campaign: Path) -> None:
    planner = ProductionLivingWorldSwordPlanner(campaign)
    planner.PLAYER_ACTOR = planner.read("state/meta.json")["player_id"]
    planner._reset()
    at = str(planner.read("state/runtime.json")["world_time"])
    event = {
        "event_id": "event.test.location-provenance",
        "kind": "interstate_battle",
        "at": at,
        "theater_ref": "theater_test",
        "location_ref": "loc_test_field",
        "attacker_state": "qin",
        "defender_state": "zhao",
        "attacker_formation_ref": "formation_qin_test",
        "defender_formation_ref": "formation_zhao_test",
        "winner_state": "qin",
        "losses": {},
    }
    planner._record_interstate_battle_memory(event, at)
    assert event["place_refs"] == ["loc_test_field"]
    assert event["causal_refs"] == ["theater_test"]
    assert "battlefield_ref" not in event
    assert event["provenance"]["kind"] == "autonomous_runtime_resolution"
