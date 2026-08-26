from __future__ import annotations

import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from sword_runtime.campaign_event_planner import CampaignEventPlayerGroupActionPlanner
from sword_runtime.api.interaction_surface import INTERACTION_ATTEMPT_PREFIX, record_interaction_attempt
from sword_runtime.causal_event_store import read_causal_event_owner, write_causal_event_owner
from sword_runtime.institutional_processes import settle_institutional_process_followup, sync_institutional_process_routes
from sword_runtime.sim.calendar import CampaignTime


def test_active_institutional_route_arms_and_settles_valid_followup(campaign: Path) -> None:
    planner = CampaignEventPlayerGroupActionPlanner(campaign)
    planner._reset()
    at = str(planner._world_time())
    source_ref = "event_test_institutional_source"
    response_ref = "event_test_institutional_response"
    route_ref = "process_test_institutional_followup"

    routing = copy.deepcopy(planner.read("state/index/institutional-process-routing.json"))
    routing["processes"] = [{
        "candidate_ref": "char_tang_wei",
        "delay_hours": 48,
        "priority": 55,
        "process_kind": "command_qualification_review",
        "response": {
            "event_ref": response_ref,
            "kind": "institutional_response",
            "stage": "evaluation_ready",
            "summary": "The registered institutional review finishes and sends its procedural disposition through the same channel.",
            "wake": True,
        },
        "route_ref": route_ref,
        "source_event_ref": source_ref,
        "trigger_actions": ["withdraw"],
    }]
    planner.put("state/index/institutional-process-routing.json", routing)

    _owner_path, owner = read_causal_event_owner(planner)
    owner["causal_events"][source_ref] = {
        "event_ref": source_ref,
        "kind": "institutional_response",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "summary": "A bounded institutional review channel is open.",
        "provenance": {
            "kind": "causal_runtime_settlement",
            "source_owner_ref": "events_messages_and_movement",
            "work_ref": source_ref,
            "late_catch_up": False,
        },
    }
    write_causal_event_owner(planner, owner)

    attempt = {
        "schema": "sword-interaction-attempt.v1",
        "surface_digest": "c" * 64,
        "actor_id": "char_tang_wei",
        "target_ref": source_ref,
        "process_ref": source_ref,
        "action": "withdraw",
        "formation_refs": [],
        "player_statement": None,
        "posture": None,
        "world_response_status": "not_established_by_attempt",
    }
    summary = INTERACTION_ATTEMPT_PREFIX + json.dumps(attempt, sort_keys=True, separators=(",", ":"))
    assert record_interaction_attempt(planner, summary, at=at) is not None

    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    sync_institutional_process_routes(planner, runtime)
    hosts = [
        host for host in runtime["hosts"].values()
        if isinstance(host, dict) and host.get("kind") == "institutional_process"
    ]
    assert len(hosts) == 1
    host = hosts[0]
    expected_due = str(CampaignTime.parse(at).add_seconds(48 * 3600))
    assert host["original_due_at"] == expected_due

    wake = settle_institutional_process_followup(planner, host, host["original_due_at"])
    assert wake["campaign_event_ref"] == response_ref
    _path, settled_owner = read_causal_event_owner(planner)
    assert settled_owner["causal_events"][response_ref]["status"] == "triggered"

    event_owner = planner.read("state/event/events-messages-and-movement.json")
    schema = json.loads((campaign / "game/schemas/event-registry.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(event_owner)
