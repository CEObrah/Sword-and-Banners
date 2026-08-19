from __future__ import annotations

import copy
import json

from sword_runtime.api.interaction_surface import INTERACTION_ATTEMPT_PREFIX
from sword_runtime.causal_event_store import read_causal_event_owner, write_causal_event_owner
from sword_runtime.contact_request_flow import _disposition_ids
from sword_runtime.production_planner import ProductionCampaignPlanner


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    meta = copy.deepcopy(planner.read("state/meta.json"))
    planner.PLAYER_ACTOR = str(meta["player_id"])
    planner._reset()
    return planner


def _install_hearing(planner, at: str, audience_ref: str) -> None:
    source_ref = "event_test_precommit_source"
    _path, owner = read_causal_event_owner(planner)
    owner["causal_events"][source_ref] = {
        "event_ref": source_ref,
        "kind": "world_arc_report",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "arc_ref": "arc_ryo_fui_northern_wei_campaign",
        "summary": "Test northern Wei report.",
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
        "summary": "A Qin duty officer is available to hear Tang Wei.",
    }
    write_causal_event_owner(planner, owner)


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


def _attempt(request_id: str, audience_ref: str, action: str, statement: str) -> dict:
    return {
        "schema": "sword-interaction-attempt.v1",
        "surface_digest": "e" * 64,
        "request_id": request_id,
        "actor_id": "char_tang_wei",
        "target_ref": audience_ref,
        "action": action,
        "process_ref": audience_ref,
        "player_statement": statement,
        "formation_refs": [],
        "posture": None,
        "world_response_status": "not_established_by_attempt",
    }


def test_existing_disposition_host_is_enriched_before_due_settlement(campaign) -> None:
    planner = _planner(campaign)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    at = str(runtime["world_time"])
    audience_ref = "event_contact_audience_precommit_test"
    request_id = "audience-precommit-test"
    _install_hearing(planner, at, audience_ref)

    for index in range(6):
        _append_attempt(
            planner,
            at,
            f"scene_precommit_answer_{index}",
            _attempt(f"precommit-answer-{index}", audience_ref, "present", "A substantive examination answer."),
        )
    ask = _attempt(
        request_id,
        audience_ref,
        "ask",
        "Based on the examination, are you willing to put my name forward for service in the northern operation?",
    )
    _append_attempt(planner, at, "scene_precommit_request", ask)

    host_id, event_id = _disposition_ids(request_id)
    runtime["hosts"][host_id] = {
        "host_id": host_id,
        "kind": "audience_disposition",
        "owner_ref": "inst_qin_military_bureau",
        "request_id": request_id,
        "source_process_ref": audience_ref,
        "route_ref": "contact_qin_military_bureau_kanyou_northern_wei",
        "institution_ref": "inst_qin_military_bureau",
        "delivery_route": "Qin Military Bureau receiving office in Kanyou",
        "event_id": event_id,
        "recurrence_seconds": 0,
        "next_due": at,
        "resolved_through": at,
        "safe_through": at,
    }
    runtime["events"].append({
        "event_id": event_id,
        "kind": "audience_disposition",
        "priority": 47,
        "target_host": host_id,
        "due_at": at,
    })

    planner._sync_contact_request_routes(runtime)
    host = runtime["hosts"][host_id]
    assert host["disposition_outcome"] == "recommended"
    assert "willing to put Tang Wei's name forward" in host["response_summary"]
