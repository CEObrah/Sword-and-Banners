from __future__ import annotations

import copy

from sword_runtime.causal_event_store import get_causal_event, read_causal_event_owner, write_causal_event_owner
from sword_runtime.household_request_flow import _classify_request, _settle_household_request
from sword_runtime.production_planner import ProductionCampaignPlanner


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    meta = copy.deepcopy(planner.read("state/meta.json"))
    planner.PLAYER_ACTOR = str(meta["player_id"])
    planner._reset()
    return planner


def _install_northern_report(planner, event_ref: str, at: str) -> None:
    _path, owner = read_causal_event_owner(planner)
    owner["causal_events"][event_ref] = {
        "event_ref": event_ref,
        "kind": "world_arc_report",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "arc_ref": "arc_ryo_fui_northern_wei_campaign",
        "source_event_ref": "event_test_northern_source",
        "summary": "Reports reaching Tang Wei concern preparations for a Qin operation against northern Wei; material military particulars remain limited.",
        "delivery": {
            "target_ref": "char_tang_wei",
            "location_ref": planner.read("state/player.json")["location"],
            "route": "House Tang report",
        },
        "provenance": {
            "kind": "world_arc_information_propagation",
            "exposure_roll": 1,
            "exposure_chance": 100,
        },
    }
    write_causal_event_owner(planner, owner)


def test_tang_ling_investigation_request_is_bound_to_delivered_northern_report(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    process_ref = "event_test_northern_report"
    _install_northern_report(planner, process_ref, at)
    attempt = {
        "actor_id": "char_tang_wei",
        "action": "request",
        "target_ref": "char_tang_ling",
        "process_ref": process_ref,
        "player_statement": (
            "Have House Tang verify these latest reports about the northern Wei operation before I approach Qin again. "
            "I want to know what material action actually settled, what can be established about the forces, movement, supply, authority and result, which parts are confirmed and which remain rumor, and whether anything in it bears on the recommendation the Qin Military Bureau made for me. "
            "At the same time, give me a detailed accounting of the Great Bow Guard recruitment so far: how many applicants we actually have, how many have been screened, accepted or rejected if any, what has been spent or committed on recruiting, screening, training and equipment, what future costs are already implied, and what that leaves against the House's treasury-safe ceiling."
        ),
    }
    assert _classify_request(planner, attempt) == "northern_wei_recruitment_review"

    unrelated = dict(attempt, process_ref="event_missing_report")
    assert _classify_request(planner, unrelated) is None


def test_tang_ling_review_settles_bounded_house_planning_information(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    process_ref = "event_test_northern_review_source"
    request_id = "test-house-northern-review"
    _install_northern_report(planner, process_ref, at)

    house = copy.deepcopy(planner.read("state/houses/house_tang.json"))
    house.setdefault("administrative_requests", {})[request_id] = {
        "request_id": request_id,
        "kind": "northern_wei_recruitment_review",
        "status": "queued",
        "requested_at": at,
        "target_ref": "char_tang_ling",
        "process_ref": process_ref,
        "action": "request",
        "player_statement": "Verify northern Wei and give me the Great Bow Guard recruitment costs.",
    }
    planner.put("state/houses/house_tang.json", house)

    _settle_household_request(planner, {"request_id": request_id}, at)

    settled = planner.read("state/houses/house_tang.json")["administrative_requests"][request_id]
    assert settled["status"] == "settled"
    assert settled["result"]["source_process_ref"] == process_ref
    assert settled["result"]["treasury"]["treasury_safe_ceiling_silver"] >= 0
    assert "No enemy disposition is established beyond" in settled["result"]["knowledge_boundary"]
    accounting = settled["result"]["great_bow_guard_accounting"]
    assert accounting["accepted_fighters"] >= 0
    assert accounting["spending_committed_by_opening_silver"] >= 0
    assert accounting["applicant_total"] is None
    assert accounting["screened_total"] is None
    assert accounting["rejected_total"] is None
    assert accounting["missing_totals_status"] == "not_registered_by_current_program_owner"
    event = get_causal_event(planner, settled["response_event_ref"])
    assert event["kind"] == "institutional_response"
    assert "military information available to this House review remains the report already received" in event["summary"]
    assert "does not yet register separate applicant, screened, or rejected totals" in event["summary"]
    assert "planning information only" in event["summary"]
    assert "creates no Qin appointment or deployment order" in event["summary"]
