from __future__ import annotations

import copy
import hashlib
import json

from sword_runtime.api.interaction_surface import INTERACTION_ATTEMPT_PREFIX, record_interaction_attempt
from sword_runtime.causal_event_store import (
    get_causal_event_from_reader,
    read_causal_event_owner,
    write_causal_event_owner,
)
from sword_runtime.contact_request_flow import _response_ref, _route_for_attempt, _settle_contact_request
from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    meta = copy.deepcopy(planner.read("state/meta.json"))
    planner.PLAYER_ACTOR = str(meta["player_id"])
    planner._reset()
    return planner


def _contact_attempt(label: str, process_ref: str) -> dict:
    return {
        "schema": "sword-interaction-attempt.v1",
        "surface_digest": hashlib.sha256(label.encode("utf-8")).hexdigest(),
        "actor_id": "char_tang_wei",
        "target_ref": "loc_kanyou",
        "action": "seek_contact",
        "process_ref": process_ref,
        "player_statement": None,
        "formation_refs": ["formation_tang_champions_first"],
        "posture": "Seek the proper Qin military receiving office before presenting substantive business.",
        "world_response_status": "not_established_by_attempt",
    }


def _install_process_event(planner, process_ref: str, at: str) -> None:
    _path, owner = read_causal_event_owner(planner)
    owner["causal_events"][process_ref] = {
        "event_ref": process_ref,
        "kind": "world_arc_report",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "summary": "A test report concerns Qin operations against northern Wei.",
        "arc_ref": "arc_ryo_fui_northern_wei_campaign",
        "provenance": {
            "kind": "world_arc_information_propagation",
            "exposure_roll": 1,
            "exposure_chance": 100,
        },
    }
    write_causal_event_owner(planner, owner)


def test_location_seek_contact_maps_to_exact_receiving_institution(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    process_ref = "event_test_contact_process"
    _install_process_event(planner, process_ref, at)
    route = _route_for_attempt(planner, _contact_attempt("contact-test", process_ref))
    assert route is not None
    assert route["institution_ref"] == "inst_qin_military_bureau"
    assert route["receiving_role"] == "Qin Military Bureau duty officer"
    assert route["delay_seconds"] == 3600


def test_seek_contact_schedules_access_before_any_petition(campaign) -> None:
    planner = _planner(campaign)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    at = str(runtime["world_time"])
    process_ref = "event_test_contact_schedule_process"
    label = "contact-test-schedule"
    _install_process_event(planner, process_ref, at)

    attempt = _contact_attempt(label, process_ref)
    attempt_ref = record_interaction_attempt(
        planner,
        INTERACTION_ATTEMPT_PREFIX + json.dumps(attempt, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        at=at,
    )
    assert isinstance(attempt_ref, str)

    planner._sync_contact_request_routes(runtime)
    contact_hosts = [
        row for row in runtime["hosts"].values()
        if row.get("kind") == "contact_request" and row.get("contact_ref") == attempt_ref
    ]
    assert len(contact_hosts) == 1
    host = contact_hosts[0]
    assert host["institution_ref"] == "inst_qin_military_bureau"
    assert CampaignTime.parse(host["next_due"]) == CampaignTime.parse(at).add_seconds(3600)
    assert get_causal_event_from_reader(planner, _response_ref(attempt_ref)) is None


def test_contact_settlement_establishes_hearing_only(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    process_ref = "event_test_contact_hearing_process"
    _install_process_event(planner, process_ref, at)
    route = _route_for_attempt(planner, _contact_attempt("contact-test-hearing", process_ref))
    assert route is not None
    host = {
        "contact_ref": "interaction_attempt_contact-test-hearing",
        "institution_ref": route["institution_ref"],
        "route_ref": route["route_ref"],
        "receiving_role": route["receiving_role"],
        "source_process_ref": process_ref,
        "audience_summary": route["audience_summary"],
        "delivery_route": route["delivery_route"],
    }
    event_ref = _settle_contact_request(planner, host, at)
    event = get_causal_event_from_reader(planner, event_ref)
    assert event is not None
    assert event["kind"] == "audience_response"
    assert event["actor_ref"] == "inst_qin_military_bureau"
    assert event["process_stage"] == "audience_ready"
    assert event["delivery"]["target_ref"] == "char_tang_wei"
    assert "has not yet made a substantive request" in event["summary"]
    assert "no appointment, command, deployment decision, or commitment" in event["summary"]
    assert event["provenance"]["late_catch_up"] is False
