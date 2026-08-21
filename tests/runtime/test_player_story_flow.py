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
from sword_runtime.sim.calendar import CampaignTime


QUALIFICATION_REF = "event_ouki_preliminary_review_disposition_001"
FORMATION_REF = "formation_qin_mobile_reserve"


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    meta = copy.deepcopy(planner.read("state/meta.json"))
    planner.PLAYER_ACTOR = str(meta["player_id"])
    planner._reset()
    return planner




def _prepare_offer_fixture(planner) -> None:
    """Open one real Qin vacancy in the disposable clone without rewriting live rules."""
    player = copy.deepcopy(planner.read("state/player.json"))
    career = player.setdefault("career_state", {})
    career["pending_qin_command_offer_refs"] = []
    career["pending_qin_command_offers"] = {}
    released_formations = []
    for row in career.get("appointments", []):
        if isinstance(row, dict) and row.get("kind") == "qin_field_command" and row.get("status") in {"active", "awaiting_assumption"}:
            row["status"] = "completed_service"
            if isinstance(row.get("formation_ref"), str):
                released_formations.append(str(row["formation_ref"]))
    declined = career.setdefault("declined_qin_command_formation_refs", [])
    career["declined_qin_command_formation_refs"] = list(dict.fromkeys([str(x) for x in declined if x] + released_formations))
    planner.put("state/player.json", player)
    commander_index = copy.deepcopy(planner.read("state/index/commander-formation-index.json"))
    commander_index.setdefault("assignments", {})["char_tang_wei"] = [
        ref for ref in commander_index.get("assignments", {}).get("char_tang_wei", []) if ref not in released_formations
    ]
    planner.put("state/index/commander-formation-index.json", commander_index)
    for formation_ref in released_formations:
        formation_path = planner.owner_path(formation_ref)
        formation = copy.deepcopy(planner.read(formation_path))
        if formation.get("commander_ref") == "char_tang_wei":
            formation["commander_ref"] = None
            formation["command_authority"] = str(formation.get("administrative_owner", "state_qin"))
            planner.put(formation_path, formation)
    qin = copy.deepcopy(planner.read("state/states/qin.json"))
    for row in qin.get("appointments", {}).values():
        if isinstance(row, dict) and row.get("status") in {"active", "awaiting_assumption"}:
            row["status"] = "completed_service"
    planner.put("state/states/qin.json", qin)

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
        "provenance": {
            "kind": "causal_runtime_settlement",
            "source_owner_ref": "events_messages_and_movement",
            "work_ref": QUALIFICATION_REF,
            "late_catch_up": False,
        },
    }
    write_causal_event_owner(planner, owner)


def _offer(planner, at: str) -> str:
    _prepare_offer_fixture(planner)
    _install_qualification(planner, at)
    wake = settle_player_story_review(planner, {"kind": "player_story_review"}, at)
    assert wake is not None
    offer_ref = str(wake["campaign_event_ref"])
    assert offer_ref.startswith("event_story_qin_command_offer_")
    return offer_ref


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


def _story_event_refs(planner) -> list[str]:
    _path, owner = read_causal_event_owner(planner)
    return sorted(
        str(ref) for ref in owner.get("causal_events", {})
        if str(ref).startswith("event_story_")
    )


def test_story_flow_schedules_a_near_term_player_relevant_host(campaign) -> None:
    planner = _planner(campaign)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    now = str(runtime["world_time"])
    sync_player_story_flow(planner, runtime)
    host = runtime["hosts"]["host_player_story_flow_tang_wei"]
    assert host["kind"] == "player_story_review"
    due = CampaignTime.parse(str(host["next_due"]))
    current = CampaignTime.parse(now)
    assert current <= due <= current.add_seconds(7 * 86400)
    assert any(row.get("target_host") == "host_player_story_flow_tang_wei" for row in runtime["events"])


def test_story_review_joins_real_qin_vacancy_to_qualified_candidate(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    _prepare_offer_fixture(planner)

    offer_ref = _offer(planner, at)
    offer = get_causal_event(planner, offer_ref)
    assert offer is not None
    assert offer["process_kind"] == "qin_field_command_offer"
    assert offer["process_stage"] == "offer_pending"
    assert "appointment_offer" not in offer
    assert offer["provenance"]["kind"] == "causal_runtime_settlement"
    assert "offer, not an automatic appointment" in offer["summary"]

    player = planner.read("state/player.json")
    details = player["career_state"]["pending_qin_command_offers"][offer_ref]
    formation_ref = str(details["formation_ref"])
    formation_path = planner.owner_path(formation_ref)
    formation = planner.read(formation_path)
    assert formation.get("commander_ref") in {None, ""}
    assert formation["administrative_owner"] == "state_qin"
    assert details["personnel"] == int(formation["personnel"])

    operation_path = planner.read("state/operations/index.json")["operations"][details["operation_ref"]]
    operation = planner.read(operation_path)
    assert formation_ref in operation["formation_refs"]
    assert operation["administrative_authority"] == "state_qin"
    assert operation["status"] in {"planned", "mobilizing", "active", "engaged", "occupied"}


def test_accepting_qin_offer_reserves_appointment_but_does_not_teleport_command(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    offer_ref = _offer(planner, at)
    pending = planner.read("state/player.json")["career_state"]["pending_qin_command_offers"][offer_ref]
    formation_ref = str(pending["formation_ref"])
    before_vacancies = int(planner.read("state/states/qin.json")["military_administration"]["commander_vacancy_count"])
    decision_ref = _accept(planner, offer_ref, at)

    decision = get_causal_event(planner, decision_ref)
    assert decision is not None
    assert decision["process_stage"] == "accepted_awaiting_assumption"
    formation = planner.read(planner.owner_path(formation_ref))
    assert formation.get("commander_ref") in {None, ""}
    assert formation["command_authority"] == "state_qin"
    assert formation["administrative_owner"] == "state_qin"

    player = planner.read("state/player.json")
    assert player["allegiance"] == "House Tang only"
    assert offer_ref not in player.get("career_state", {}).get("pending_qin_command_offers", {})
    assert any(
        row.get("formation_ref") == formation_ref and row.get("status") == "awaiting_assumption"
        for row in player.get("career_state", {}).get("appointments", [])
    )
    assert "awaiting assumption" in player["authority"]

    qin = planner.read("state/states/qin.json")
    appointment = qin["appointments"][f"field_command:{formation_ref}"]
    assert appointment["status"] == "awaiting_assumption"
    assert appointment["report_to_location_ref"] == formation["location_ref"]
    assert int(qin["military_administration"]["commander_vacancy_count"]) == before_vacancies


def test_arriving_at_appointed_formation_activates_command_without_transferring_ownership(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    offer_ref = _offer(planner, at)
    pending = planner.read("state/player.json")["career_state"]["pending_qin_command_offers"][offer_ref]
    formation_ref = str(pending["formation_ref"])
    _accept(planner, offer_ref, at)
    before_vacancies = int(planner.read("state/states/qin.json")["military_administration"]["commander_vacancy_count"])

    formation = planner.read(planner.owner_path(formation_ref))
    player = copy.deepcopy(planner.read("state/player.json"))
    player["location"] = formation["location_ref"]
    planner.put("state/player.json", player)

    wake = settle_player_story_review(planner, {"kind": "player_story_review"}, at)
    assert wake is not None
    assert str(wake["campaign_event_ref"]).startswith("event_story_qin_command_assumed_")

    formation = planner.read(planner.owner_path(formation_ref))
    assert formation["commander_ref"] == "char_tang_wei"
    assert formation["command_authority"] == "char_tang_wei"
    assert formation["administrative_owner"] == "state_qin"
    commander_index = planner.read("state/index/commander-formation-index.json")
    assert formation_ref in commander_index["assignments"]["char_tang_wei"]

    player = planner.read("state/player.json")
    assert player["allegiance"] == "House Tang only"
    assert any(
        row.get("formation_ref") == formation_ref and row.get("status") == "active"
        for row in player.get("career_state", {}).get("appointments", [])
    )
    assert "Qin field commander" in player["authority"]

    qin = planner.read("state/states/qin.json")
    assert qin["appointments"][f"field_command:{formation_ref}"]["status"] == "active"
    assert int(qin["military_administration"]["commander_vacancy_count"]) == max(0, before_vacancies - 1)


def test_lapsed_unassumed_appointment_restores_prior_authority(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    offer_ref = _offer(planner, at)
    pending = planner.read("state/player.json")["career_state"]["pending_qin_command_offers"][offer_ref]
    formation_ref = str(pending["formation_ref"])
    _accept(planner, offer_ref, at)
    player = planner.read("state/player.json")
    prior = next(
        row["prior_authority"] for row in player["career_state"]["appointments"]
        if row.get("formation_ref") == formation_ref and row.get("status") == "awaiting_assumption"
    )

    appointment = next(row for row in player["career_state"]["appointments"] if row.get("formation_ref") == formation_ref and row.get("status") == "awaiting_assumption")
    operation_path = planner.read("state/operations/index.json")["operations"][appointment["operation_ref"]]
    operation = copy.deepcopy(planner.read(operation_path))
    operation["status"] = "completed"
    planner.put(operation_path, operation)

    wake = settle_player_story_review(planner, {"kind": "player_story_review"}, at)
    assert wake is not None
    player = planner.read("state/player.json")
    assert player["authority"] == prior
    assert any(
        row.get("formation_ref") == formation_ref and row.get("status") == "lapsed_before_assumption"
        for row in player["career_state"]["appointments"]
    )
    formation = planner.read(planner.owner_path(formation_ref))
    assert formation.get("commander_ref") in {None, ""}


def test_story_review_surfaces_house_status_and_family_initiative(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    _install_qualification(planner, at)
    wake = settle_player_story_review(planner, {"kind": "player_story_review"}, at)
    assert wake is not None
    refs = _story_event_refs(planner)
    events = [get_causal_event(planner, ref) for ref in refs]
    summaries = [str(row.get("summary", "")) for row in events if row is not None]
    assert any("Sword Manor has completed" in summary for summary in summaries)
    assert any("Sword Manor" in summary for summary in summaries)
    assert any("family hall" in summary for summary in summaries)
    assert all(row.get("provenance", {}).get("kind") == "causal_runtime_settlement" for row in events if row is not None)
