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
    _disposition_response_ref,
    _match_disposition,
    _settle_audience_disposition,
)
from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    meta = copy.deepcopy(planner.read("state/meta.json"))
    planner.PLAYER_ACTOR = str(meta["player_id"])
    planner._reset()
    return planner


def _attempt(request_id: str, process_ref: str, action: str, statement: str) -> dict:
    return {
        "schema": "sword-interaction-attempt.v1",
        "surface_digest": "d" * 64,
        "request_id": request_id,
        "actor_id": "char_tang_wei",
        "target_ref": process_ref,
        "action": action,
        "process_ref": process_ref,
        "player_statement": statement,
        "formation_refs": [],
        "posture": None,
        "world_response_status": "not_established_by_attempt",
    }


def _append_attempt(planner, at: str, event_id: str, attempt: dict) -> None:
    history = copy.deepcopy(planner.read("state/history/events/index.json"))
    history["events"].append({
        "at": at,
        "event_id": event_id,
        "kind": "scene_consequence",
        "summary": INTERACTION_ATTEMPT_PREFIX + json.dumps(
            attempt, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
    })
    planner.put("state/history/events/index.json", history)


def _install_audience(planner, source_ref: str, audience_ref: str, at: str) -> None:
    _path, owner = read_causal_event_owner(planner)
    owner["causal_events"][source_ref] = {
        "event_ref": source_ref,
        "kind": "world_arc_report",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "arc_ref": "arc_ryo_fui_northern_wei_campaign",
        "summary": "A test report concerns the northern Wei operation.",
    }
    owner["causal_events"][audience_ref] = {
        "event_ref": audience_ref,
        "kind": "audience_response",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "actor_ref": "inst_qin_military_bureau",
        "target_ref": "char_tang_wei",
        "source_event_ref": source_ref,
        "summary": "A Qin Military Bureau duty officer is available to hear Tang Wei.",
    }
    write_causal_event_owner(planner, owner)


def _make_wei_recommendable(planner) -> None:
    player = copy.deepcopy(planner.read("state/player.json"))
    player.setdefault("attributes", {}).update({
        "Intelligence": 200,
        "Awareness": 200,
        "Composure": 200,
    })
    player.setdefault("skills", {}).update({
        "Strategy": 120,
        "Tactics": 110,
        "Leadership": 110,
        "Logistics": 110,
        "Formation Command": 105,
        "Governance": 110,
        "Intelligence Operations": 105,
    })
    planner.put("state/player.json", player)


def test_qualifying_request_schedules_audience_disposition(campaign) -> None:
    planner = _planner(campaign)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    at = str(runtime["world_time"])
    source_ref = "event_test_disposition_source"
    audience_ref = "event_contact_audience_test_disposition"
    request_id = "audience-disposition-schedule"
    _install_audience(planner, source_ref, audience_ref, at)
    ask = _attempt(
        request_id,
        audience_ref,
        "ask",
        "Based on this examination, are you willing to put my name forward for service in the northern operation?",
    )
    _append_attempt(planner, at, "scene_test_audience_disposition", ask)

    match = _match_disposition(planner, ask)
    assert match is not None
    route, spec, process = match
    assert route["institution_ref"] == "inst_qin_military_bureau"
    assert spec["disposition_ref"] == "qin_northern_wei_service_recommendation"
    assert process["event_ref"] == audience_ref

    planner._sync_contact_request_routes(runtime)
    hosts = [
        row for row in runtime["hosts"].values()
        if row.get("kind") == "audience_disposition" and row.get("request_id") == request_id
    ]
    assert len(hosts) == 1
    assert CampaignTime.parse(hosts[0]["next_due"]) == CampaignTime.parse(at).add_seconds(300)
    assert get_causal_event_from_reader(planner, _disposition_response_ref(request_id)) is None


def test_completed_examination_can_recommend_without_appointing(campaign) -> None:
    planner = _planner(campaign)
    _make_wei_recommendable(planner)
    at = str(planner.read("state/runtime.json")["world_time"])
    source_ref = "event_test_recommendation_source"
    audience_ref = "event_contact_audience_test_recommendation"
    request_id = "audience-recommendation-settlement"
    _install_audience(planner, source_ref, audience_ref, at)

    for index in range(6):
        _append_attempt(
            planner,
            at,
            f"scene_test_examination_{index}",
            _attempt(
                f"test-examination-{index}",
                audience_ref,
                "present",
                "A substantive examination answer.",
            ),
        )

    ask = _attempt(
        request_id,
        audience_ref,
        "ask",
        "Based on what you heard, are you willing to put my name forward for service in the northern operation?",
    )
    match = _match_disposition(planner, ask)
    assert match is not None
    route, spec, _process = match
    host = {
        "request_id": request_id,
        "institution_ref": route["institution_ref"],
        "route_ref": route["route_ref"],
        "disposition_ref": spec["disposition_ref"],
        "source_process_ref": audience_ref,
        "delivery_route": route["delivery_route"],
        "disposition_spec": copy.deepcopy(dict(spec)),
    }

    event_ref = _settle_audience_disposition(planner, host, at)
    event = get_causal_event_from_reader(planner, event_ref)
    assert event is not None
    assert event["kind"] == "petition_response"
    assert event["process_stage"] == "recommended"
    assert event["assessment"]["prior_present_attempts"] >= 6
    assert event["assessment"]["score"] >= 650
    assert "willing to put Tang Wei's name forward" in event["summary"]
    assert "no Qin rank, office, command" in event["summary"]


def test_unrelated_audience_question_does_not_route(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    source_ref = "event_test_non_disposition_source"
    audience_ref = "event_contact_audience_test_non_disposition"
    _install_audience(planner, source_ref, audience_ref, at)
    ask = _attempt(
        "ordinary-audience-question",
        audience_ref,
        "ask",
        "Which office keeps the marching returns?",
    )
    assert _match_disposition(planner, ask) is None
