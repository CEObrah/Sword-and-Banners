from __future__ import annotations

import copy

from sword_runtime.causal_event_store import get_causal_event, read_causal_event_owner, write_causal_event_owner
from sword_runtime.player_story_flow import (
    _decision_event_ref,
    settle_appointment_reply,
    settle_player_story_review,
    sync_player_story_flow,
)
from sword_runtime.production_planner import ProductionCampaignPlanner


QUALIFICATION_REF = "event_ouki_preliminary_review_disposition_001"
FORMATION_REF = "formation_qin_border_line"


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    meta = copy.deepcopy(planner.read("state/meta.json"))
    planner.PLAYER_ACTOR = str(meta["player_id"])
    planner._reset()
    return planner


def _install_qualification(planner, at: str) -> None:
    if get_causal_event(planner, QUALIFICATION_REF) is not None:
        return
    _path, owner = read_causal_event_owner(planner)
    owner["causal_events"][QUALIFICATION_REF] = {
        "event_ref": QUALIFICATION_REF,
        "kind": "institutional_response",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "target_ref": "char_tang_wei",
        "process_kind": "command_qualification_review",
        "process_stage": "preliminary_review_complete",
        "summary": "Tang Wei's preliminary command qualification review is complete.",
        "provenance": {"kind": "test_fixture"},
    }
    write_causal_event_owner(planner, owner)


def _offer(planner, at: str) -> str:
    _install_qualification(planner, at)
    wake = settle_player_story_review(planner, {"kind": "player_story_review"}, at)
    assert wake is not None
    return next(ref for ref in wake["story_event_refs"] if ref.startswith("event_story_qin_command_offer_"))


def _accept(planner, offer_ref: str, at: str) -> str:
    decision_ref = _decision_event_ref(offer_ref)
    wake = settle_appointment_reply(
        planner,
        {
            "offer_ref": offer_ref,
            "decision_event_ref": decision_ref,
            "player_action": "proceed",
            "request_id": "test-accept-qin-command-offer",
        },
        at,
    )
    assert wake is not None
    return decision_ref


def test_story_flow_schedules_a_near_term_player_relevant_host(campaign) -> None:
    planner = _planner(campaign)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    now = str(runtime["world_time"])
    sync_player_story_flow(planner, runtime)
    host = runtime["hosts"]["host_player_story_flow_tang_wei"]
    assert host["kind"] == "player_story_review"
    assert host["next_due"] == now
    assert any(
        row.get("target_host") == "host_player_story_flow_tang_wei"
        for row in runtime["events"]
    )


def test_story_review_joins_real_qin_vacancy_to_qualified_candidate(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    formation_path = planner.owner_path(FORMATION_REF)
    before = copy.deepcopy(planner.read(formation_path))
    assert before.get("commander_ref") in {None, ""}

    offer_ref = _offer(planner, at)
    offer = get_causal_event(planner, offer_ref)
    assert offer is not None
    assert offer["process_kind"] == "qin_field_command_offer"
    assert offer["process_stage"] == "offer_pending"
    assert offer["appointment_offer"]["formation_ref"] == FORMATION_REF
    assert offer["appointment_offer"]["personnel"] == 8000
    assert offer["appointment_offer"]["arc_ref"] == "arc_ryo_fui_northern_wei_campaign"
    assert "offer, not an automatic appointment" in offer["summary"]

    after = planner.read(formation_path)
    assert after.get("commander_ref") in {None, ""}
    assert after["administrative_owner"] == "state_qin"


def test_accepting_qin_offer_reserves_appointment_but_does_not_teleport_command(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    offer_ref = _offer(planner, at)
    decision_ref = _accept(planner, offer_ref, at)

    decision = get_causal_event(planner, decision_ref)
    assert decision is not None
    assert decision["process_stage"] == "accepted_awaiting_assumption"

    formation = planner.read(planner.owner_path(FORMATION_REF))
    assert formation.get("commander_ref") in {None, ""}
    assert formation["command_authority"] == "state_qin"
    assert formation["administrative_owner"] == "state_qin"

    player = planner.read("state/player.json")
    assert player["allegiance"] == "House Tang only"
    assert any(
        row.get("formation_ref") == FORMATION_REF and row.get("status") == "awaiting_assumption"
        for row in player.get("career_state", {}).get("appointments", [])
    )
    assert "awaiting assumption" in player["authority"]

    qin = planner.read("state/states/qin.json")
    appointment = qin["appointments"][f"field_command:{FORMATION_REF}"]
    assert appointment["person_ref"] == "char_tang_wei"
    assert appointment["status"] == "awaiting_assumption"
    assert appointment["report_to_location_ref"] == formation["location_ref"]


def test_arriving_at_appointed_formation_activates_command_without_transferring_ownership(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    offer_ref = _offer(planner, at)
    _accept(planner, offer_ref, at)

    formation = planner.read(planner.owner_path(FORMATION_REF))
    player = copy.deepcopy(planner.read("state/player.json"))
    player["location"] = formation["location_ref"]
    planner.put("state/player.json", player)

    wake = settle_player_story_review(planner, {"kind": "player_story_review"}, at)
    assert wake is not None
    assert any(ref.startswith("event_story_qin_command_assumed_") for ref in wake["story_event_refs"])

    formation = planner.read(planner.owner_path(FORMATION_REF))
    assert formation["commander_ref"] == "char_tang_wei"
    assert formation["command_authority"] == "char_tang_wei"
    assert formation["administrative_owner"] == "state_qin"

    commander_index = planner.read("state/index/commander-formation-index.json")
    assert FORMATION_REF in commander_index["assignments"]["char_tang_wei"]

    player = planner.read("state/player.json")
    assert player["allegiance"] == "House Tang only"
    assert any(
        row.get("formation_ref") == FORMATION_REF and row.get("status") == "active"
        for row in player.get("career_state", {}).get("appointments", [])
    )
    assert "Qin field commander" in player["authority"]

    qin = planner.read("state/states/qin.json")
    appointment = qin["appointments"][f"field_command:{FORMATION_REF}"]
    assert appointment["status"] == "active"


def test_story_review_surfaces_house_status_and_family_initiative(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    _install_qualification(planner, at)
    wake = settle_player_story_review(planner, {"kind": "player_story_review"}, at)
    assert wake is not None
    events = [get_causal_event(planner, ref) for ref in wake["story_event_refs"]]
    summaries = [str(row.get("summary", "")) for row in events if row is not None]
    assert any("Sword Manor has completed" in summary for summary in summaries)
    assert any("Great Bow Guard" in summary for summary in summaries)
    assert any("family hall" in summary for summary in summaries)
