from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from sword_runtime.campaign_event_planner import CampaignEventPlayerGroupActionPlanner
from sword_runtime.production_living_world import ProductionLivingWorldSwordPlanner
from sword_runtime.sim.calendar import CampaignTime


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


def test_commanderless_formation_is_not_autonomous_deployment_ready(campaign: Path) -> None:
    planner = ProductionLivingWorldSwordPlanner(campaign)
    score = planner._formation_score(
        "formation_vacant",
        {
            "personnel": 10000,
            "status": "commander_vacant",
            "commander_ref": None,
            "readiness": 100,
            "morale": 100,
            "cohesion": 100,
            "training_progress": 100,
            "fatigue": 0,
            "composition": {"line_infantry": 10000},
            "logistics": {"food_kg": 1_000_000},
        },
        "defend a threatened border",
        {"state_memory": {}, "formation_memory": {}},
        set(),
    )
    assert score <= -(10**8)


def test_baseline_state_operation_cannot_double_assign_manual_formation(campaign: Path) -> None:
    planner = ProductionLivingWorldSwordPlanner(campaign)
    planner.PLAYER_ACTOR = planner.read("state/meta.json")["player_id"]
    planner._reset()
    host = _state_host(planner, "qin")
    at = str(planner.read("state/runtime.json")["world_time"])

    # Current campaign state begins with conserved pools and may have no exact
    # state formations yet. One lawful autonomous state review materializes the
    # registered baseline formations before this reservation regression.
    planner._autonomy_state(host, 1, at)
    force = planner.read("state/forces/state-qin.json")
    allocated = force.get("allocated_to_formations", {})
    assert allocated
    reserved_ref = next(iter(sorted(allocated)))
    formation_path = planner._formation_path(reserved_ref)
    formation = copy.deepcopy(planner.read(formation_path))
    formation["mobilized"] = True
    formation["status"] = "mobilized"
    planner.put(formation_path, formation)

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

    planner._autonomy_state(host, 1, at)

    final_index = planner.read("state/operations/index.json")
    for operation_ref, path in final_index.get("operations", {}).items():
        operation = planner.read(path)
        status = str(operation.get("status", ""))
        if operation_ref == manual_ref or status not in _ACTIVE:
            continue
        if operation.get("autonomous") is not True:
            continue
        refs = [str(ref) for ref in operation.get("formation_refs", [])]
        assert reserved_ref not in refs
        if status == "active":
            assert refs
            formations = [planner._load_formation(ref)[1] for ref in refs]
            assert all(bool(item.get("mobilized", False)) for item in formations)
            assert {str(item.get("location_ref")) for item in formations} == {
                str(operation.get("location_ref"))
            }


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


def test_campaign_causal_work_catches_up_without_rewind_and_wakes_once(campaign: Path) -> None:
    planner = CampaignEventPlayerGroupActionPlanner(campaign)
    planner.PLAYER_ACTOR = planner.read("state/meta.json")["player_id"]
    planner._reset()
    now = CampaignTime.parse(str(planner.read("state/runtime.json")["world_time"]))
    owner_ref = "events_messages_and_movement"
    work_path = campaign / "state/index/campaign-causal-work.json"
    work_path.write_text(
        json.dumps(
            {
                "authority": False,
                "purpose": "test bounded campaign causal routing",
                "targets": [
                    {
                        "work_ref": "event_test_overdue_boundary",
                        "source_owner_ref": owner_ref,
                        "kind": "calendar_boundary",
                        "due_at": str(now.add_seconds(-3600)),
                        "priority": 40,
                        "status": "pending",
                        "effect": {"summary": "The known test calendar boundary has been reached."},
                        "wake": False,
                    },
                    {
                        "work_ref": "event_test_staff_response",
                        "source_owner_ref": owner_ref,
                        "kind": "institutional_response",
                        "due_at": str(now),
                        "priority": 50,
                        "status": "pending",
                        "effect": {"summary": "The test staff channel returns a procedural response."},
                        "wake": True,
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    planner._active_command_type = "advance_time"
    first = planner._advance_runtime(str(now.add_seconds(3600)))
    runtime = planner.read("state/runtime.json")
    assert first["interrupted"] is True
    assert first["wake_required"] is True
    assert first["events_processed"] == 2
    assert runtime["world_time"] == str(now)
    assert runtime["pending_wake"]["kind"] == "campaign_event"
    assert runtime["pending_wake"]["campaign_event_ref"] == "event_test_staff_response"

    owners = planner.read("state/index/owner-index.json")["owners"]
    event_owner = planner.read(owners[owner_ref])
    causal_events = event_owner["causal_events"]
    assert causal_events["event_test_overdue_boundary"]["status"] == "triggered"
    assert causal_events["event_test_overdue_boundary"]["triggered_at"] == str(now)
    assert causal_events["event_test_overdue_boundary"]["provenance"]["late_catch_up"] is True
    assert causal_events["event_test_staff_response"]["status"] == "triggered"
    assert causal_events["event_test_staff_response"]["provenance"]["late_catch_up"] is False
    work = planner.read("state/index/campaign-causal-work.json")
    assert {target["status"] for target in work["targets"]} == {"pending"}

    # Continuing after the one-shot wake acknowledges it without rearming the
    # already-triggered campaign events or moving the clock backward. The
    # authority:false routing remains unchanged; exact triggered records suppress
    # duplicate scheduling.
    second = planner._advance_runtime(str(now.add_seconds(3600)))
    runtime2 = planner.read("state/runtime.json")
    assert second.get("wake_required") is not True
    assert runtime2.get("pending_wake") is None
    assert runtime2["world_time"] == str(now.add_seconds(3600))
    event_owner2 = planner.read(owners[owner_ref])
    assert set(event_owner2["causal_events"]) >= {
        "event_test_overdue_boundary",
        "event_test_staff_response",
    }
    work2 = planner.read("state/index/campaign-causal-work.json")
    assert work2 == work


def test_campaign_causal_work_fails_closed_on_non_event_owner(campaign: Path) -> None:
    planner = CampaignEventPlayerGroupActionPlanner(campaign)
    planner.PLAYER_ACTOR = planner.read("state/meta.json")["player_id"]
    planner._reset()
    now = CampaignTime.parse(str(planner.read("state/runtime.json")["world_time"]))
    path = campaign / "state/index/campaign-causal-work.json"
    path.write_text(
        json.dumps(
            {
                "authority": False,
                "targets": [
                    {
                        "work_ref": "event_test_bad_owner",
                        "source_owner_ref": "char_tang_wei",
                        "kind": "institutional_response",
                        "due_at": str(now),
                        "priority": 50,
                        "status": "pending",
                        "effect": {"summary": "This must never become campaign truth."},
                        "wake": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    planner._active_command_type = "advance_time"
    with pytest.raises(ValueError, match="exact event owner"):
        planner._advance_runtime(str(now.add_seconds(3600)))
