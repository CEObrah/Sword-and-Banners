"""Causal follow-ups for established institutional interactions.

Routing is authority:false. Only a settled event-registry record becomes
campaign occurrence truth.
"""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from typing import Any

from sword_runtime.api.interaction_surface import parse_interaction_attempt_summary
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.causal_event_store import get_causal_event, read_causal_event_owner, write_causal_event_owner
from sword_runtime.history_store import iter_history_events

ROUTING_PATH = "state/index/institutional-process-routing.json"
RUNTIME_PATH = "state/runtime.json"
EVENT_OWNER_REF = "events_messages_and_movement"
HISTORY_PATH = "state/history/events/index.json"


def _routes(planner: Any) -> list[dict[str, Any]]:
    doc = planner.read_optional(ROUTING_PATH)
    if doc is None:
        return []
    if not isinstance(doc, Mapping) or doc.get("authority") is not False:
        raise ValueError("institutional routing must be authority:false")
    rows = doc.get("processes")
    if not isinstance(rows, list):
        raise ValueError("institutional routing processes are invalid")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise ValueError("institutional route is invalid")
        response = raw.get("response")
        actions = raw.get("trigger_actions")
        if not isinstance(response, Mapping) or not isinstance(actions, list) or not actions:
            raise ValueError("institutional route contract is invalid")
        route = {
            "route_ref": str(raw.get("route_ref") or ""),
            "source_event_ref": str(raw.get("source_event_ref") or ""),
            "candidate_ref": str(raw.get("candidate_ref") or ""),
            "process_kind": str(raw.get("process_kind") or ""),
            "trigger_actions": tuple(str(value) for value in actions),
            "delay_hours": raw.get("delay_hours", 0),
            "priority": raw.get("priority", 55),
            "response_event_ref": str(response.get("event_ref") or ""),
            "response_kind": str(response.get("kind") or ""),
            "response_stage": str(response.get("stage") or ""),
            "response_summary": str(response.get("summary") or "").strip(),
            "wake": response.get("wake", True),
        }
        if (
            not all(route[key] for key in ("route_ref", "source_event_ref", "candidate_ref", "process_kind", "response_event_ref", "response_kind", "response_stage", "response_summary"))
            or route["route_ref"] in seen
            or isinstance(route["delay_hours"], bool)
            or not isinstance(route["delay_hours"], int)
            or not 0 <= route["delay_hours"] <= 8760
            or isinstance(route["priority"], bool)
            or not isinstance(route["priority"], int)
            or not 0 <= route["priority"] <= 1000
            or not isinstance(route["wake"], bool)
            or len(route["response_summary"]) > 4000
        ):
            raise ValueError("institutional route values are invalid")
        seen.add(route["route_ref"])
        result.append(route)
    return result


def _event_owner(planner: Any) -> tuple[str, dict[str, Any]]:
    return read_causal_event_owner(planner)


def _trigger_at(planner: Any, source: Mapping[str, Any], route: Mapping[str, Any]) -> str | None:
    source_at = CampaignTime.parse(str(source.get("triggered_at")))
    for event in iter_history_events(planner):
        if not isinstance(event, Mapping) or not isinstance(event.get("at"), str):
            continue
        at = CampaignTime.parse(event["at"])
        if at < source_at:
            continue
        attempt = parse_interaction_attempt_summary(event.get("summary"))
        if attempt is None or attempt.get("actor_id") != route["candidate_ref"]:
            continue
        if attempt.get("action") not in route["trigger_actions"]:
            continue
        if route["source_event_ref"] not in {attempt.get("target_ref"), attempt.get("process_ref")}:
            continue
        return event["at"]
    return None


def _ids(route_ref: str) -> tuple[str, str]:
    digest = hashlib.sha256(route_ref.encode("utf-8")).hexdigest()[:20]
    return f"host_institutional_{digest}", f"event_institutional_{digest}"


def sync_institutional_process_routes(planner: Any, runtime: dict[str, Any]) -> None:
    routes = _routes(planner)
    if not routes:
        return
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    current = CampaignTime.parse(str(runtime["world_time"]))
    _path, owner = _event_owner(planner)
    causal = owner["causal_events"]
    event_by_id = {str(row.get("event_id")): row for row in events if isinstance(row, dict)}
    for route in routes:
        source = get_causal_event(planner, route["source_event_ref"])
        if not isinstance(source, Mapping) or source.get("status") != "triggered":
            continue
        if get_causal_event(planner, route["response_event_ref"]) is not None:
            continue
        trigger_at = _trigger_at(planner, source, route)
        if trigger_at is None:
            continue
        original_due = CampaignTime.parse(trigger_at).add_seconds(route["delay_hours"] * 3600)
        due = original_due if original_due > current else current
        host_id, event_id = _ids(route["route_ref"])
        safe = due.add_seconds(-1)
        hosts[host_id] = {
            "host_id": host_id,
            "kind": "institutional_process",
            "owner_ref": EVENT_OWNER_REF,
            "route_ref": route["route_ref"],
            "recurrence_seconds": 0,
            "original_due_at": str(original_due),
            "resolved_through": str(current if current <= safe else safe),
            "safe_through": str(safe),
            "next_due": str(due),
        }
        scheduler = event_by_id.get(event_id)
        if not isinstance(scheduler, dict):
            scheduler = {"event_id": event_id}
            events.append(scheduler)
            event_by_id[event_id] = scheduler
        scheduler.update({
            "kind": "institutional_process",
            "priority": route["priority"],
            "target_host": host_id,
            "due_at": str(due),
        })
        scheduler.pop("suspended", None)


def settle_institutional_process_followup(planner: Any, host: Mapping[str, Any], at: str) -> dict[str, Any] | None:
    route_ref = host.get("route_ref")
    route = next((row for row in _routes(planner) if row["route_ref"] == route_ref), None)
    if route is None:
        raise ValueError("institutional process host lost its route")
    owner_path, owner = _event_owner(planner)
    causal = owner["causal_events"]
    source = get_causal_event(planner, route["source_event_ref"])
    if not isinstance(source, Mapping) or source.get("status") != "triggered":
        raise ValueError("institutional process host lost its source event")
    if get_causal_event(planner, route["response_event_ref"]) is not None:
        return None
    due_text = host.get("original_due_at")
    if not isinstance(due_text, str):
        raise ValueError("institutional process host lacks original due time")
    due = CampaignTime.parse(due_text)
    triggered = CampaignTime.parse(at)
    if triggered < due:
        raise ValueError("institutional follow-up fired before due time")
    causal[route["response_event_ref"]] = {
        "event_ref": route["response_event_ref"],
        "kind": route["response_kind"],
        "status": "triggered",
        "due_at": due_text,
        "triggered_at": at,
        "source_event_ref": route["source_event_ref"],
        "process_kind": route["process_kind"],
        "process_stage": route["response_stage"],
        "summary": route["response_summary"],
        "provenance": {
            "kind": "causal_runtime_settlement",
            "source_owner_ref": EVENT_OWNER_REF,
            "work_ref": route["response_event_ref"],
            "late_catch_up": triggered > due,
        },
    }
    owner["runtime"]["last_settled_at"] = at
    write_causal_event_owner(planner, owner)
    if not route["wake"]:
        return None
    digest = hashlib.sha256(f"{route['response_event_ref']}|{at}".encode("utf-8")).hexdigest()[:20]
    return {
        "wake_ref": f"wake.institutional.{digest}",
        "kind": "campaign_event",
        "at": at,
        "campaign_event_ref": route["response_event_ref"],
        "reason": route["response_summary"],
    }


__all__ = ["ROUTING_PATH", "settle_institutional_process_followup", "sync_institutional_process_routes"]
