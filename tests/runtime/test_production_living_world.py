from __future__ import annotations

import copy
from pathlib import Path

from sword_runtime.production_living_world import ProductionLivingWorldSwordPlanner


_ACTIVE = {"planned", "mobilizing", "active", "engaged", "occupied"}


def _state_host(planner: ProductionLivingWorldSwordPlanner, state: str):
    runtime = planner.read("state/runtime.json")
    for host in runtime.get("hosts", {}).values():
        owner = str(host.get("owner_ref", "")).replace("state_", "")
        if host.get("kind") == "state" and owner == state:
            return host
    raise AssertionError(f"missing state host for {state}")


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


def test_legacy_state_operation_cannot_double_assign_manual_formation(campaign: Path) -> None:
    planner = ProductionLivingWorldSwordPlanner(campaign)
    planner.PLAYER_ACTOR = planner.read("state/meta.json")["player_id"]
    planner._reset()

    force = planner.read("state/forces/state-qin.json")
    allocated = force.get("allocated_to_formations", {})
    reserved_ref = next(iter(sorted(allocated)))
    formation = planner.read(planner._formation_path(reserved_ref))

    manual_ref = "operation_test_manual_reservation"
    manual_path = f"state/operations/{manual_ref}.json"
    planner.put(
        manual_path,
        {
            "schema": "sword-operation",
            "owner_id": manual_ref,
            "operation_ref": manual_ref,
            "objective": "existing manual commitment",
            "status": "active",
            "formation_refs": [reserved_ref],
            "location_ref": formation.get("location_ref"),
            "created_at": planner.read("state/meta.json")["time"],
            "autonomous": False,
        },
    )
    index = copy.deepcopy(planner.read("state/operations/index.json"))
    index.setdefault("operations", {})[manual_ref] = manual_path
    planner.put("state/operations/index.json", index)

    state_path = "state/states/qin.json"
    qin = copy.deepcopy(planner.read(state_path))
    qin["known_threats"] = {
        "forced_border_threat": {"severity": 95, "kind": "border"}
    }
    planner.put(state_path, qin)

    at = str(planner.read("state/runtime.json")["world_time"])
    planner._autonomy_state(_state_host(planner, "qin"), 1, at)

    final_index = planner.read("state/operations/index.json")
    for operation_ref, path in final_index.get("operations", {}).items():
        operation = planner.read(path)
        if operation_ref == manual_ref or str(operation.get("status", "")) not in _ACTIVE:
            continue
        if operation.get("autonomous") is True:
            assert reserved_ref not in operation.get("formation_refs", [])


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
