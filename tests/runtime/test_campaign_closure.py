from __future__ import annotations

import copy
import json
import subprocess

from sword_runtime.campaign_closure import (
    record_operation_after_action,
    schedule_war_closure_ceremonies,
    settle_war_ceremony,
)
from sword_runtime.history_store import iter_history_events
from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime


def _planner(campaign):
    return ProductionCampaignPlanner(campaign)


def _flush_planner_fixture(campaign, planner, message: str) -> None:
    for rel, value in planner._writes.items():
        path = campaign / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    for rel in planner._deletes:
        path = campaign / rel
        if path.exists():
            path.unlink()
    subprocess.run(["git", "-C", str(campaign), "add", "-A"], check=True)
    staged = subprocess.run(["git", "-C", str(campaign), "diff", "--cached", "--quiet"]).returncode
    if staged != 0:
        subprocess.run(["git", "-C", str(campaign), "commit", "--quiet", "-m", message], check=True)


def _register_test_operation(planner, ref: str, formation_refs: list[str], *, status: str = "completed") -> str:
    path = f"state/operations/{ref}.json"
    planner.put(path, {
        "schema": "sword-operation",
        "operation_ref": ref,
        "status": status,
        "objective": "campaign closure regression",
        "formation_refs": list(formation_refs),
        "location_ref": "loc_qin_eastern_depot",
        "created_at": str(planner.read("state/runtime.json")["world_time"]),
    })
    planner._register_owner(ref, path)
    return path


def _history(planner, kind: str):
    return [row for row in iter_history_events(planner) if row.get("kind") == kind]


def test_operation_after_action_is_not_a_war_ceremony(campaign):
    p = _planner(campaign)
    now = str(p.read("state/runtime.json")["world_time"])
    ref = "operation_after_action_only"
    _register_test_operation(p, ref, ["formation_red_lance_a"], status="completed")

    review = record_operation_after_action(p, ref, at=now)

    assert review["operation_ref"] == ref
    assert review["participant_formation_refs"] == ["formation_red_lance_a"]
    assert "char_tang_wei" in review["participant_person_refs"]
    assert _history(p, "campaign_after_action_review")
    assert not _history(p, "war_campaign_closure")
    assert not _history(p, "war_closure_ceremony")
    assert p.read(p.owner_path(ref))["campaign_phase"] == "operation_closed_awaiting_campaign_direction"


def test_true_war_settlement_schedules_evidence_backed_state_ceremonies_without_rewards_or_teleport(campaign):
    p = _planner(campaign)
    now = str(p.read("state/runtime.json")["world_time"])
    op_ref = "operation_closure_participants"
    _register_test_operation(
        p,
        op_ref,
        ["formation_red_lance_a", "formation_zhao_border_line"],
        status="completed",
    )
    # Exact battle evidence links the two real formations to the closure.
    hist = copy.deepcopy(p.read("state/history/events/index.json"))
    hist.setdefault("events", []).append({
        "event_id": "battle_closure_evidence",
        "kind": "battle",
        "at": now,
        "operation_ref": op_ref,
        "attackers": ["formation_red_lance_a"],
        "defenders": ["formation_zhao_border_line"],
        "killed": {"attacker": 4, "defender": 9},
    })
    p.put("state/history/events/index.json", hist)
    before_player = copy.deepcopy(p.read("state/player.json"))
    before_qin = copy.deepcopy(p.read("state/states/qin.json"))

    closure = schedule_war_closure_ceremonies(
        p,
        war_scope_ref="war_test_qin_zhao",
        party_refs=["state_qin", "state_zhao"],
        at=now,
        result="negotiated_settlement",
        operation_refs=[op_ref],
    )

    assert closure["kind"] == "war_campaign_closure"
    assert closure["battle_event_refs"] == ["battle_closure_evidence"]
    assert closure["casualty_count"] == 13
    qin = next(row for row in closure["ceremonies"] if row["state_ref"] == "state_qin")
    assert qin["venue_ref"] == "loc_kanyou"
    assert "char_tang_wei" in qin["summoned_person_refs"]
    assert qin["status"] == "summoned"
    assert CampaignTime.parse(qin["scheduled_at"]) > CampaignTime.parse(now)
    # Summons are information and obligation, not teleport or reward authority.
    assert p.read("state/player.json")["location"] == before_player["location"]
    assert p.read("state/states/qin.json")["treasury_silver"] == before_qin["treasury_silver"]
    assert not _history(p, "war_closure_ceremony")
    info = p.read(p.owner_path(qin["player_summons_information_ref"]))
    assert info["epistemic_kind"] == "official_military_summons"
    assert "char_tang_wei" in info["knowers"]


def test_war_ceremony_attendance_uses_exact_location_and_is_idempotent(campaign):
    p = _planner(campaign)
    now = str(p.read("state/runtime.json")["world_time"])
    op_ref = "operation_closure_attendance"
    _register_test_operation(p, op_ref, ["formation_red_lance_a"], status="completed")
    closure = schedule_war_closure_ceremonies(
        p,
        war_scope_ref="war_test_attendance",
        party_refs=["state_qin", "state_zhao"],
        at=now,
        result="qin_victory",
        operation_refs=[op_ref],
    )
    qin = next(row for row in closure["ceremonies"] if row["state_ref"] == "state_qin")
    ceremony_ref = qin["ceremony_ref"]

    import pytest
    with pytest.raises(ValueError, match="before its scheduled time"):
        settle_war_ceremony(p, ceremony_ref, at=now)

    player = copy.deepcopy(p.read("state/player.json"))
    original_location = player["location"]
    player["location"] = "loc_kanyou"
    p.put("state/player.json", player)
    held = settle_war_ceremony(p, ceremony_ref, at=qin["scheduled_at"])
    assert "char_tang_wei" in held["present_person_refs"]
    assert held["formal_reward_status"] == "reviews_opened"
    assert held["reward_review_refs"]
    review = p.read(p.owner_path(held["reward_review_refs"][0]))
    assert review["status"] == "open"
    assert closure["event_id"] in review["evidence_refs"]
    # The ceremony did not move the player; the test explicitly moved him there.
    assert p.read("state/player.json")["location"] == "loc_kanyou"
    again = settle_war_ceremony(p, ceremony_ref, at=qin["scheduled_at"])
    assert again["event_id"] == held["event_id"]
    assert len([row for row in _history(p, "war_closure_ceremony") if row["ceremony_ref"] == ceremony_ref]) == 1

    # The ceremony did not move Wei; the fresh revision-1 baseline already begins at Kanyou.
    assert p.read("state/player.json")["location"] == original_location
    assert held["court_session"]["sovereign_ref"] == "char_ei_sei"
    assert "char_ei_sei" in held["present_person_refs"]
    assert "char_ryo_fui" in held["present_person_refs"]


def test_scheduled_player_ceremony_is_a_real_chronology_boundary(campaign):
    from conftest import execute_hosted_production

    p = _planner(campaign)
    now = str(p.read("state/runtime.json")["world_time"])
    op_ref = "operation_closure_scheduler"
    _register_test_operation(p, op_ref, ["formation_red_lance_a"], status="completed")
    closure = schedule_war_closure_ceremonies(
        p,
        war_scope_ref="war_test_scheduler",
        party_refs=["state_qin", "state_zhao"],
        at=now,
        result="qin_victory",
        operation_refs=[op_ref],
    )
    qin = next(row for row in closure["ceremonies"] if row["state_ref"] == "state_qin")
    scheduled = qin["scheduled_at"]
    runtime = p.read("state/runtime.json")
    assert any(row.get("kind") == "war_closure_ceremony" for row in runtime["hosts"].values())

    player = copy.deepcopy(p.read("state/player.json"))
    player["location"] = "loc_kanyou"
    p.put("state/player.json", player)
    # Direct planner setup is fixture construction. Persist the staged overlay
    # before entering SwordRuntime's transactional path.
    _flush_planner_fixture(campaign, p, "fixture: scheduled war ceremony")

    target = str(CampaignTime.parse(scheduled).add_days(2))
    result = execute_hosted_production(campaign, "advance_time", {"target_time": target}).receipt.result
    assert result["world_time"] == scheduled
    assert result["interrupted"] is True
    wake = _planner(campaign).read("state/runtime.json")["pending_wake"]
    assert wake["kind"] == "war_closure_ceremony"
    assert wake["ceremony_ref"] == qin["ceremony_ref"]
    assert _history(_planner(campaign), "war_closure_ceremony")

    # Explicit continuation acknowledges/skips the scene boundary and chronology resumes.
    result2 = execute_hosted_production(campaign, "advance_time", {"target_time": target, "scene_policy": "skip_to_conclusion"}).receipt.result
    assert result2["world_time"] == target
    runtime2 = _planner(campaign).read("state/runtime.json")
    assert "pending_wake" not in runtime2
    assert not any(row.get("kind") == "war_closure_ceremony" and row.get("ceremony_ref") == qin["ceremony_ref"] for row in runtime2["hosts"].values())


def test_war_closure_ends_obsolete_operation_routing_without_moving_or_transferring_formations(campaign):
    p = _planner(campaign)
    now = str(p.read("state/runtime.json")["world_time"])
    op_ref = "operation_postwar_disposition"
    path = _register_test_operation(
        p,
        op_ref,
        ["formation_high_guard_qin_a", "formation_red_lance_a"],
        status="active",
    )
    operation = copy.deepcopy(p.read(path))
    operation["battlefields"] = {
        "battlefield_postwar_disposition": {
            "status": "active",
            "assignments": {},
            "sectors": {},
            "reports": [],
        }
    }
    p.put(path, operation)
    index = copy.deepcopy(p.read("state/operations/index.json"))
    index.setdefault("active_battlefield_operation_refs", []).append(op_ref)
    p.put("state/operations/index.json", index)

    state_ref = "formation_high_guard_qin_a"
    house_ref = "formation_red_lance_a"
    before_state = copy.deepcopy(p.read(p.owner_path(state_ref)))
    before_house = copy.deepcopy(p.read(p.owner_path(house_ref)))

    closure = schedule_war_closure_ceremonies(
        p,
        war_scope_ref="war_postwar_disposition",
        party_refs=["state_qin", "state_zhao"],
        at=now,
        result="negotiated_settlement",
        operation_refs=[op_ref],
    )

    after_op = p.read(path)
    assert after_op["status"] == "completed"
    assert after_op["campaign_phase"] == "war_closed_available_for_owner_reassignment"
    assert after_op["battlefields"]["battlefield_postwar_disposition"]["status"] == "ended"
    assert op_ref not in p.read("state/operations/index.json")["active_battlefield_operation_refs"]
    dispositions = {row["formation_ref"]: row for row in closure["postwar_dispositions"]}
    assert dispositions[state_ref]["action"] == "available_for_state_reassignment"
    assert dispositions[house_ref]["action"] == "return_to_house_authority_pending_movement"
    assert dispositions[state_ref]["status"] == dispositions[house_ref]["status"] == "pending_owner_order"

    after_state = p.read(p.owner_path(state_ref))
    after_house = p.read(p.owner_path(house_ref))
    for before, after in ((before_state, after_state), (before_house, after_house)):
        assert after["personnel"] == before["personnel"]
        assert after.get("location_ref") == before.get("location_ref")
        assert after.get("administrative_owner") == before.get("administrative_owner")
        assert after.get("command_authority") == before.get("command_authority")
