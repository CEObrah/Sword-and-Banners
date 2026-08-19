from __future__ import annotations

import copy
import json

from sword_runtime.api.interaction_surface import INTERACTION_ATTEMPT_PREFIX
from sword_runtime.causal_event_store import (
    get_causal_event_from_reader,
    read_causal_event_owner,
    write_causal_event_owner,
)
from sword_runtime.contact_request_flow import (
    _followup_response_ref,
    _settle_institutional_followup,
)
from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    meta = copy.deepcopy(planner.read("state/meta.json"))
    planner.PLAYER_ACTOR = str(meta["player_id"])
    planner._reset()
    return planner


def _install_response(planner, event_ref: str, at: str, *, process_kind: str, process_stage: str, actor_ref: str | None = None) -> None:
    _path, owner = read_causal_event_owner(planner)
    row = {
        "event_ref": event_ref,
        "kind": "institutional_response",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "target_ref": "char_tang_wei",
        "process_kind": process_kind,
        "process_stage": process_stage,
        "summary": "Test institutional disposition.",
        "provenance": {
            "kind": "causal_runtime_settlement",
            "source_owner_ref": actor_ref or "events_messages_and_movement",
            "work_ref": event_ref,
            "late_catch_up": False,
        },
    }
    if actor_ref is not None:
        row["actor_ref"] = actor_ref
    owner["causal_events"][event_ref] = row
    write_causal_event_owner(planner, owner)


def _append_attempt(planner, *, request_id: str, process_ref: str, at: str, statement: str) -> None:
    attempt = {
        "schema": "sword-interaction-attempt.v1",
        "surface_digest": "b" * 64,
        "request_id": request_id,
        "actor_id": "char_tang_wei",
        "target_ref": process_ref,
        "action": "request",
        "process_ref": process_ref,
        "player_statement": statement,
        "formation_refs": [],
        "posture": None,
        "world_response_status": "not_established_by_attempt",
    }
    history = copy.deepcopy(planner.read("state/history/events/index.json"))
    history["events"].append({
        "at": at,
        "event_id": f"scene_{request_id}",
        "kind": "scene_consequence",
        "summary": INTERACTION_ATTEMPT_PREFIX + json.dumps(
            attempt, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
    })
    planner.put("state/history/events/index.json", history)


def _followup_host(runtime: dict, request_id: str) -> dict:
    rows = [
        row for row in runtime["hosts"].values()
        if row.get("kind") == "institutional_followup" and row.get("request_id") == request_id
    ]
    assert len(rows) == 1
    return rows[0]


def test_old_qin_appointment_request_catches_up_without_granting_office(campaign) -> None:
    planner = _planner(campaign)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    current = CampaignTime.parse(str(runtime["world_time"]))
    requested_at = str(current.add_seconds(-86400))
    process_ref = "event_test_qin_recommended"
    request_id = "test-qin-appointment-followup"
    _install_response(
        planner,
        process_ref,
        requested_at,
        process_kind="institutional_disposition",
        process_stage="recommended",
        actor_ref="inst_qin_military_bureau",
    )
    _append_attempt(
        planner,
        request_id=request_id,
        process_ref=process_ref,
        at=requested_at,
        statement="I request an appointment and command connected to the northern operation.",
    )

    planner._sync_contact_request_routes(runtime)
    host = _followup_host(runtime, request_id)
    assert CampaignTime.parse(host["next_due"]) == current
    assert host["late_catch_up"] is True

    event_ref = _settle_institutional_followup(planner, host, str(current))
    event = get_causal_event_from_reader(planner, event_ref)
    assert event_ref == _followup_response_ref(request_id)
    assert event["kind"] == "institutional_response"
    assert event["process_kind"] == "institutional_followup"
    assert event["actor_ref"] == "inst_qin_military_bureau"
    assert "no current appointment" in event["summary"]
    assert "rank, command, troop custody, or deployment authority" in event["summary"]


def test_old_ouki_appointment_request_catches_up_on_exact_review_event(campaign) -> None:
    planner = _planner(campaign)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    current = CampaignTime.parse(str(runtime["world_time"]))
    requested_at = str(current.add_seconds(-86400))
    process_ref = "event_ouki_preliminary_review_disposition_001"
    request_id = "test-ouki-appointment-followup"
    _install_response(
        planner,
        process_ref,
        requested_at,
        process_kind="command_qualification_review",
        process_stage="preliminary_review_complete",
    )
    _append_attempt(
        planner,
        request_id=request_id,
        process_ref=process_ref,
        at=requested_at,
        statement="I request an appointment or command under Ouki if a post is available.",
    )

    planner._sync_contact_request_routes(runtime)
    host = _followup_host(runtime, request_id)
    assert CampaignTime.parse(host["next_due"]) == current
    assert host.get("actor_ref") is None

    event_ref = _settle_institutional_followup(planner, host, str(current))
    event = get_causal_event_from_reader(planner, event_ref)
    assert event["kind"] == "institutional_response"
    assert "Ouki's staff acknowledges" in event["summary"]
    assert "no current field-command vacancy or Qin appointment" in event["summary"]
    assert "actor_ref" not in event


def test_unrelated_institutional_response_does_not_route_as_appointment_followup(campaign) -> None:
    planner = _planner(campaign)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    at = str(runtime["world_time"])
    process_ref = "event_unrelated_institutional_response"
    _install_response(
        planner,
        process_ref,
        at,
        process_kind="unrelated_process",
        process_stage="complete",
    )
    _append_attempt(
        planner,
        request_id="test-unrelated-followup",
        process_ref=process_ref,
        at=at,
        statement="Please appoint me to this unrelated matter.",
    )
    planner._sync_contact_request_routes(runtime)
    assert not any(
        row.get("kind") == "institutional_followup" and row.get("request_id") == "test-unrelated-followup"
        for row in runtime["hosts"].values()
    )
