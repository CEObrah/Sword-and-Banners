"""Causal access handoff for location-targeted institutional contact attempts.

A seek_contact interaction is only player-owned search/access intent.  It never
means that a petition was delivered or that an institution responded.  This
production layer maps a small registered set of player-visible contact contexts
to exact institutions, schedules the receiving process on the normal campaign
clock, and publishes only a hearing/access event when that process settles.
Substantive requests remain separate later interaction actions.
"""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from typing import Any

from sword_runtime.api.interaction_surface import parse_interaction_attempt_summary
from sword_runtime.causal_event_store import (
    get_causal_event_from_reader,
    read_causal_event_owner,
    write_causal_event_owner,
)
from sword_runtime.history_store import recent_history_events
from sword_runtime.sim.calendar import CampaignTime

_RUNTIME_PATH = "state/runtime.json"
_RULES_PATH = "game/data/politics/contact-routes.json"
_HISTORY_WINDOW = 256
_PRIORITY = 46


def _request_ids(request_id: str) -> tuple[str, str]:
    digest = hashlib.sha256(("institutional-contact|" + request_id).encode("utf-8")).hexdigest()[:20]
    return f"host_contact_request_{digest}", f"event_contact_request_{digest}"


def _response_ref(request_id: str) -> str:
    digest = hashlib.sha256(("institutional-contact-response|" + request_id).encode("utf-8")).hexdigest()[:20]
    return f"event_contact_audience_{digest}"


def _route_for_attempt(planner: Any, attempt: Mapping[str, Any]) -> Mapping[str, Any] | None:
    if attempt.get("actor_id") != "char_tang_wei" or attempt.get("action") != "seek_contact":
        return None
    location_ref = attempt.get("target_ref")
    process_ref = attempt.get("process_ref")
    if not isinstance(location_ref, str) or not location_ref.startswith("loc_"):
        return None
    if not isinstance(process_ref, str) or not process_ref:
        return None
    process = get_causal_event_from_reader(planner, process_ref)
    if not isinstance(process, Mapping):
        return None
    arc_ref = process.get("arc_ref")
    if not isinstance(arc_ref, str) or not arc_ref:
        return None

    rules = planner.read(_RULES_PATH)
    routes = rules.get("routes", []) if isinstance(rules, Mapping) else []
    if not isinstance(routes, list):
        raise ValueError("institutional contact route registry is invalid")
    for route in routes:
        if not isinstance(route, Mapping):
            raise ValueError("institutional contact route is invalid")
        if route.get("location_ref") != location_ref or route.get("arc_ref") != arc_ref:
            continue
        institution_ref = route.get("institution_ref")
        delay_seconds = route.get("delay_seconds")
        if not isinstance(institution_ref, str) or not institution_ref:
            raise ValueError("institutional contact route lost its institution owner")
        if isinstance(delay_seconds, bool) or not isinstance(delay_seconds, int) or delay_seconds <= 0:
            raise ValueError("institutional contact route delay is invalid")
        return route
    return None


def _settle_contact_request(planner: Any, host: Mapping[str, Any], at: str) -> str:
    request_id = host.get("request_id")
    institution_ref = host.get("institution_ref")
    route_ref = host.get("route_ref")
    receiving_role = host.get("receiving_role")
    source_process_ref = host.get("source_process_ref")
    summary = host.get("audience_summary")
    delivery_route = host.get("delivery_route")
    if not all(isinstance(value, str) and value for value in (
        request_id, institution_ref, route_ref, receiving_role, source_process_ref,
        summary, delivery_route,
    )):
        raise ValueError("institutional contact host is invalid")

    event_ref = _response_ref(str(request_id))
    if get_causal_event_from_reader(planner, event_ref) is not None:
        return event_ref

    player = planner.read("state/player.json")
    location_ref = player.get("location")
    if not isinstance(location_ref, str) or not location_ref:
        raise ValueError("institutional contact delivery lost player location")

    _path, owner = read_causal_event_owner(planner)
    owner["causal_events"][event_ref] = {
        "event_ref": event_ref,
        "kind": "audience_response",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "actor_ref": institution_ref,
        "target_ref": "char_tang_wei",
        "basis_goal": f"Receiving access for player contact request {request_id}"[:500],
        "process_kind": "institutional_contact",
        "process_stage": "audience_ready",
        "source_event_ref": source_process_ref,
        "summary": str(summary)[:4000],
        "delivery": {
            "target_ref": "char_tang_wei",
            "location_ref": location_ref,
            "route": str(delivery_route)[:1000],
        },
        "provenance": {
            "kind": "causal_runtime_settlement",
            "source_owner_ref": institution_ref,
            "work_ref": event_ref,
            "late_catch_up": False,
        },
    }
    owner.setdefault("runtime", {})["last_settled_at"] = at
    write_causal_event_owner(planner, owner)
    return event_ref


class ContactRequestFlowMixin:
    """Production-only scheduler adapter for institutional access requests."""

    def _sync_contact_request_routes(self, runtime: dict[str, Any]) -> None:
        hosts = runtime.get("hosts")
        events = runtime.get("events")
        current_text = runtime.get("world_time")
        if not isinstance(hosts, dict) or not isinstance(events, list) or not isinstance(current_text, str):
            raise ValueError("runtime causal queue is invalid")
        current = CampaignTime.parse(current_text)
        event_ids = {
            str(row.get("event_id"))
            for row in events
            if isinstance(row, Mapping) and isinstance(row.get("event_id"), str)
        }

        for event in recent_history_events(self, _HISTORY_WINDOW):
            if not isinstance(event, Mapping):
                continue
            attempt = parse_interaction_attempt_summary(event.get("summary"))
            if not isinstance(attempt, Mapping):
                continue
            route = _route_for_attempt(self, attempt)
            request_id = attempt.get("request_id")
            requested_at = event.get("at")
            if route is None or not isinstance(request_id, str) or not request_id or not isinstance(requested_at, str):
                continue
            if get_causal_event_from_reader(self, _response_ref(request_id)) is not None:
                continue

            host_id, event_id = _request_ids(request_id)
            if host_id in hosts:
                continue
            due = CampaignTime.parse(requested_at).add_seconds(int(route["delay_seconds"]))
            if due < current:
                due = current
            institution_ref = str(route["institution_ref"])
            hosts[host_id] = {
                "host_id": host_id,
                "kind": "contact_request",
                "owner_ref": institution_ref,
                "request_id": request_id,
                "source_event_id": event.get("event_id"),
                "source_process_ref": attempt.get("process_ref"),
                "route_ref": route.get("route_ref"),
                "institution_ref": institution_ref,
                "receiving_role": route.get("receiving_role"),
                "audience_summary": route.get("audience_summary"),
                "delivery_route": route.get("delivery_route"),
                "event_id": event_id,
                "recurrence_seconds": 0,
                "next_due": str(due),
                "resolved_through": str(current if current < due else due.add_seconds(-1)),
                "safe_through": str(due.add_seconds(-1)),
            }
            if event_id not in event_ids:
                events.append({
                    "event_id": event_id,
                    "kind": "contact_request",
                    "priority": _PRIORITY,
                    "target_host": host_id,
                    "due_at": str(due),
                })
                event_ids.add(event_id)

    def _advance_runtime(self, target_text: str) -> dict[str, Any]:
        runtime = copy.deepcopy(self.read(_RUNTIME_PATH))
        self._sync_contact_request_routes(runtime)
        self.put(_RUNTIME_PATH, runtime)
        return super()._advance_runtime(target_text)

    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        if host.get("kind") == "contact_request":
            _settle_contact_request(self, host, due_text)
            self._pending_wake_created = None
            return
        super()._run_due_host(host, due_text)


__all__ = ["ContactRequestFlowMixin", "_route_for_attempt", "_settle_contact_request"]
