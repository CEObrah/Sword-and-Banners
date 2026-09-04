"""Physical command-message routing for campaign headquarters.

This module is deliberately small: it owns neither campaign decisions nor scene
presentation.  It gives every headquarters message the same geography-backed
travel law and manages one-shot delivery hosts for upward reports.
"""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from typing import Any

from sword_runtime.geography import shortest_path
from sword_runtime.sim.calendar import CampaignTime

_RUNTIME_PATH = "state/runtime.json"
_REPORT_PRIORITY = 44


def _digest(prefix: str, value: str) -> str:
    return hashlib.sha256(f"{prefix}|{value}".encode("utf-8")).hexdigest()[:20]


def command_message_route(
    read: Any, origin_ref: str, destination_ref: str, *, round_trip: bool = False,
) -> dict[str, Any]:
    """Return exact geography-backed courier timing between two command posts."""
    origin = str(origin_ref or "")
    destination = str(destination_ref or "")
    if not origin or not destination:
        raise ValueError("command message route requires exact endpoints")
    route = shortest_path(read, origin, destination, modes=("horse", "foot"))
    one_way = max(0, int(route.get("duration_hours", 0) or 0)) * 3600
    multiplier = 2 if round_trip else 1
    return {
        "origin_ref": origin,
        "destination_ref": destination,
        "route_refs": [str(x) for x in route.get("route_refs", []) if isinstance(x, str)],
        "path": [str(x) for x in route.get("path", []) if isinstance(x, str)],
        "one_way_seconds": one_way,
        "travel_seconds": one_way * multiplier,
        "round_trip": bool(round_trip),
        "modes": [str(x) for x in route.get("modes", []) if isinstance(x, str)],
    }


def command_person_location(planner: Any, person_ref: object) -> str | None:
    """Resolve one exact commander's physical command-post location."""
    if not isinstance(person_ref, str) or not person_ref:
        return None
    try:
        person = planner.read(planner.owner_path(person_ref))
    except (AttributeError, FileNotFoundError, KeyError, ValueError):
        return None
    if not isinstance(person, Mapping):
        return None
    for key in ("current_location", "location_ref", "location"):
        value = person.get(key)
        if isinstance(value, str) and value:
            return value
    return None




def command_endpoint_location(planner: Any, endpoint_ref: object) -> str | None:
    """Resolve a person/institution command endpoint to one physical location.

    Remote command traffic must route to a place, never merely to an owner ID.
    Exact people are resolved first. Static institution profiles are lawful
    geography for headquarters but do not imply current staffing or presence.
    """
    if not isinstance(endpoint_ref, str) or not endpoint_ref:
        return None
    person_location = command_person_location(planner, endpoint_ref)
    if person_location:
        return person_location
    try:
        profiles_owner = planner.read("game/data/politics/state-institution-profiles.json")
    except (AttributeError, FileNotFoundError, KeyError, ValueError):
        profiles_owner = None
    profiles = profiles_owner.get("profiles") if isinstance(profiles_owner, Mapping) else None
    profile = profiles.get(endpoint_ref) if isinstance(profiles, Mapping) else None
    if isinstance(profile, Mapping):
        for value in (
            profile.get("location_ref"),
            profile.get("geography", {}).get("headquarters_location_ref")
            if isinstance(profile.get("geography"), Mapping) else None,
        ):
            if isinstance(value, str) and value:
                return value
    return None


def player_command_location(planner: Any) -> str | None:
    """Return Tang Wei's exact current physical location for message delivery."""
    try:
        player = planner.read("state/player.json")
    except (AttributeError, FileNotFoundError, KeyError, ValueError):
        return None
    if not isinstance(player, Mapping):
        return None
    for key in ("location", "current_location", "location_ref"):
        value = player.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def ensure_player_message_delivery(
    planner: Any, host: Mapping[str, Any], at: str, *,
    target_key: str = "response_target_location_ref",
) -> bool:
    """Return True only when a scheduled reply has physically reached Wei.

    A reply aimed at Wei's dispatch location must not teleport to a later player
    location. If he moved, keep the same scheduler host alive and route the
    courier onward from the old target to his new position. Direct legacy calls
    without a response target remain compatible and settle immediately.
    """
    intended = host.get(target_key)
    if not isinstance(intended, str) or not intended:
        return True
    current = player_command_location(planner)
    if not current:
        raise ValueError("command reply delivery lost Tang Wei's exact location")
    runtime = copy.deepcopy(planner.read(_RUNTIME_PATH))
    active_host_id = getattr(planner, "_active_host_id", None)
    active = runtime.get("hosts", {}).get(active_host_id) if isinstance(runtime.get("hosts"), Mapping) else None
    if current == intended:
        if isinstance(active, dict):
            active["recurrence_seconds"] = 0
            active["retire_after_settlement"] = True
            planner.put(_RUNTIME_PATH, runtime)
        return True
    if not isinstance(active, dict):
        # Only scheduler-owned delivery can lawfully reroute. A direct test/legacy
        # call with a delivery target cannot pretend that the courier arrived.
        return False
    route = command_message_route(planner.read, intended, current, round_trip=False)
    travel_seconds = max(0, int(route.get("travel_seconds", 0) or 0))
    active["response_courier_origin_ref"] = intended
    active[target_key] = current
    active["response_reroute"] = copy.deepcopy(dict(route))
    active["recurrence_seconds"] = max(3600, travel_seconds) if travel_seconds > 0 else 3600
    active["retire_after_settlement"] = False
    planner.put(_RUNTIME_PATH, runtime)
    return False



def ensure_recipient_message_delivery(
    planner: Any, host: Mapping[str, Any], at: str, *, recipient_ref: str,
    target_key: str = "recipient_target_location_ref",
) -> bool:
    """Return True only when a scheduled message has reached its exact recipient.

    The host stores the location the courier was originally sent toward. If the
    exact recipient has moved by settlement time, the same causal host is
    rerouted from that old destination to the recipient's current location.
    This prevents fixed-delay or stale-coordinate delivery from becoming
    instantaneous knowledge or receipt.
    """
    intended = host.get(target_key)
    if not isinstance(intended, str) or not intended:
        return True
    current = command_endpoint_location(planner, recipient_ref)
    if not current:
        raise ValueError("message delivery lost the recipient's exact location")
    runtime = copy.deepcopy(planner.read(_RUNTIME_PATH))
    active_host_id = getattr(planner, "_active_host_id", None)
    active = runtime.get("hosts", {}).get(active_host_id) if isinstance(runtime.get("hosts"), Mapping) else None
    if current == intended:
        if isinstance(active, dict):
            active["recurrence_seconds"] = 0
            active["retire_after_settlement"] = True
            planner.put(_RUNTIME_PATH, runtime)
        return True
    if not isinstance(active, dict):
        return False
    route = command_message_route(planner.read, intended, current, round_trip=False)
    travel_seconds = max(0, int(route.get("travel_seconds", 0) or 0))
    active["recipient_courier_origin_ref"] = intended
    active[target_key] = current
    active["recipient_reroute"] = copy.deepcopy(dict(route))
    active["recurrence_seconds"] = max(3600, travel_seconds) if travel_seconds > 0 else 3600
    active["retire_after_settlement"] = False
    planner.put(_RUNTIME_PATH, runtime)
    return False

def _schedule_report_delivery(
    planner: Any, *, cycle_ref: str, operation_ref: str, report_ref: str,
    due_at: str, source_location_ref: str, target_location_ref: str,
) -> None:
    runtime = copy.deepcopy(planner.read(_RUNTIME_PATH))
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    token = _digest("report-delivery", f"{cycle_ref}|{report_ref}")
    host_id = f"host_campaign_command_report_delivery_{token}"
    event_id = f"event_campaign_command_report_delivery_{token}"
    due = CampaignTime.parse(due_at)
    hosts[host_id] = {
        "host_id": host_id,
        "kind": "campaign_command_report_delivery",
        "owner_ref": cycle_ref,
        "cycle_ref": cycle_ref,
        "operation_ref": operation_ref,
        "report_ref": report_ref,
        "source_location_ref": source_location_ref,
        "target_location_ref": target_location_ref,
        "recurrence_seconds": 0,
        "next_due": due_at,
        "resolved_through": str(due.add_seconds(-1)),
        "safe_through": str(due.add_seconds(-1)),
    }
    events[:] = [
        row for row in events
        if not (isinstance(row, Mapping) and row.get("event_id") == event_id)
    ]
    events.append({
        "event_id": event_id,
        "kind": "campaign_command_report_delivery",
        "priority": _REPORT_PRIORITY,
        "target_host": host_id,
        "due_at": due_at,
    })
    planner.put(_RUNTIME_PATH, runtime)


def queue_upward_report(
    planner: Any, cycle: dict[str, Any], *, at: str, phase: str,
    source_location_ref: str, payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Append one report and route it physically to the named superior.

    Co-located command posts deliver immediately. Remote named command posts use
    the same horse/foot geography law as explicit command contact. Missing or
    unroutable endpoints fail closed as ``route_unresolved`` rather than
    manufacturing instantaneous transmission.
    """
    cycle_ref = str(cycle.get("cycle_ref") or "")
    operation_ref = str(cycle.get("operation_ref") or "")
    target_ref = str(cycle.get("superior_command_ref") or cycle.get("supreme_commander_ref") or "")
    report_seed = str(payload.get("report_ref") or payload.get("event_ref") or f"{phase}|{at}")
    report_ref = str(payload.get("report_ref") or f"campaign_command_report.{_digest('report', cycle_ref + '|' + report_seed)}")
    rows = cycle.setdefault("upward_reports", [])
    if not isinstance(rows, list):
        rows = []
        cycle["upward_reports"] = rows
    for existing in rows:
        if isinstance(existing, Mapping) and existing.get("report_ref") == report_ref:
            return dict(existing)

    report = copy.deepcopy(dict(payload))
    report.update({
        "report_ref": report_ref,
        "prepared_at": at,
        # Retain reported_at as a compatibility field, but delivery_status and
        # delivered_at are the authority for whether superior command has it.
        "reported_at": at,
        "phase": phase,
        "from_ref": report.get("from_ref") or "char_tang_wei",
        "to_ref": target_ref or report.get("to_ref"),
        "source_location_ref": source_location_ref or None,
        "target_location_ref": None,
        "delivery_status": "route_unresolved",
        "delivered_at": None,
        "communication_travel_seconds": None,
        "communication_rule": "prepared_at is not receipt; superior command may use this report only after physical delivery is established",
    })

    target_location = command_person_location(planner, target_ref)
    report["target_location_ref"] = target_location

    if source_location_ref and target_location:
        try:
            route = command_message_route(planner.read, source_location_ref, target_location, round_trip=False)
        except (FileNotFoundError, KeyError, TypeError, ValueError):
            route = None
        if isinstance(route, Mapping):
            travel_seconds = max(0, int(route.get("travel_seconds", 0) or 0))
            report["communication_travel_seconds"] = travel_seconds
            report["courier_route"] = copy.deepcopy(dict(route))
            if travel_seconds <= 0:
                report["delivery_status"] = "delivered"
                report["delivered_at"] = at
            else:
                due = str(CampaignTime.parse(at).add_seconds(travel_seconds))
                report["delivery_status"] = "in_transit"
                report["delivery_due_at"] = due
                _schedule_report_delivery(
                    planner, cycle_ref=cycle_ref, operation_ref=operation_ref,
                    report_ref=report_ref, due_at=due,
                    source_location_ref=source_location_ref,
                    target_location_ref=target_location,
                )

    rows.append(report)
    cycle["upward_reports"] = rows[-48:]
    if report["delivery_status"] == "delivered":
        _apply_delivered_material_refs(cycle, report)
    return report


def _apply_delivered_material_refs(cycle: dict[str, Any], report: Mapping[str, Any]) -> None:
    info = [str(x) for x in report.get("information_refs", []) if isinstance(x, str)]
    requests = [str(x) for x in report.get("follow_on_request_refs", []) if isinstance(x, str)]
    if info:
        existing = [str(x) for x in cycle.get("reported_command_information_refs", []) if isinstance(x, str)]
        cycle["reported_command_information_refs"] = list(dict.fromkeys([*existing, *info]))[-128:]
    if requests:
        existing = [str(x) for x in cycle.get("reported_follow_on_request_refs", []) if isinstance(x, str)]
        cycle["reported_follow_on_request_refs"] = list(dict.fromkeys([*existing, *requests]))[-128:]


def settle_upward_report_delivery(planner: Any, host: Mapping[str, Any], at: str) -> dict[str, Any] | None:
    cycle_ref = str(host.get("cycle_ref") or host.get("owner_ref") or "")
    report_ref = str(host.get("report_ref") or "")
    if not cycle_ref or not report_ref:
        raise ValueError("campaign report delivery host lacks exact refs")
    try:
        cycle_path = planner.owner_path(cycle_ref)
        cycle = copy.deepcopy(planner.read(cycle_path))
    except (AttributeError, FileNotFoundError, KeyError, ValueError):
        return None
    rows = cycle.get("upward_reports") if isinstance(cycle.get("upward_reports"), list) else []
    settled = None
    for row in rows:
        if not isinstance(row, dict) or row.get("report_ref") != report_ref:
            continue
        if row.get("delivery_status") == "delivered":
            settled = row
            break
        recipient_ref = str(row.get("to_ref") or cycle.get("superior_command_ref") or cycle.get("supreme_commander_ref") or "")
        if not recipient_ref:
            raise ValueError("campaign report delivery lost its exact superior recipient")
        if not ensure_recipient_message_delivery(
            planner, host, at, recipient_ref=recipient_ref, target_key="target_location_ref"
        ):
            # The courier reached the old command post, but the named superior
            # has moved. Keep the report in transit and mirror the rerouted host
            # endpoint into the durable report record; no superior decision may
            # consume its information until a later physical delivery settles.
            try:
                runtime = planner.read(_RUNTIME_PATH)
            except (AttributeError, FileNotFoundError, KeyError, ValueError):
                runtime = None
            active_host_id = getattr(planner, "_active_host_id", None)
            active_host = (runtime.get("hosts", {}).get(active_host_id) if isinstance(runtime, Mapping) and isinstance(runtime.get("hosts"), Mapping) else None)
            if isinstance(active_host, Mapping):
                new_target = active_host.get("target_location_ref")
                if isinstance(new_target, str) and new_target:
                    row["target_location_ref"] = new_target
                reroute = active_host.get("recipient_reroute")
                if isinstance(reroute, Mapping):
                    history = row.setdefault("courier_reroutes", [])
                    if isinstance(history, list):
                        history.append({"at": at, **copy.deepcopy(dict(reroute))})
                        row["courier_reroutes"] = history[-8:]
            row["delivery_status"] = "in_transit"
            row["last_delivery_attempt_at"] = at
            cycle["updated_at"] = at
            planner.put(cycle_path, cycle)
            return None
        row["delivery_status"] = "delivered"
        row["delivered_at"] = at
        row.pop("delivery_due_at", None)
        _apply_delivered_material_refs(cycle, row)
        settled = row
        break
    if settled is None:
        return None
    cycle["updated_at"] = at
    planner.put(cycle_path, cycle)
    return copy.deepcopy(dict(settled))


__all__ = [
    "command_message_route", "command_person_location", "command_endpoint_location",
    "player_command_location", "ensure_player_message_delivery", "ensure_recipient_message_delivery", "queue_upward_report",
    "settle_upward_report_delivery",
]
