"""Compatibility reconciliation for legacy Qin field-command support routing.

Older saves may carry a valid Qin field-command appointment whose command-group
link predates the appointment ``operation_ref`` field. A short-lived compatibility
repair also displaced newer pending directives by restoring older executable
missions as the operation's current order. Older one-shot Qin briefing routes may
also survive in the scheduler registry after exhaustion with no next due time, or
may never have been registered when legacy order history was stored out of
issuance order.

This module normalizes those legacy routing/pointer facts and catches recovered
automatic briefing routes up to the current causal frontier. It does not create
orders, move formations, authorize battle, or change ownership. Normal Qin staff
support remains responsible for briefing the exact pending directive.
"""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from typing import Any

from sword_runtime.campaign_communications import (
    command_endpoint_location,
    command_message_route,
    player_command_location,
)
from sword_runtime.causal_event_store import get_causal_event
from sword_runtime.operation_routing import exact_operation_record
from sword_runtime.sim.calendar import CampaignTime


_PLAYER_PATH = "state/player.json"
_RUNTIME_PATH = "state/runtime.json"
_LOGISTICS_RULES_PATH = "game/data/mechanics/logistics.json"
_QIN_BUREAU_REF = "inst_qin_military_bureau"
_ACTIVE_OPERATION_STATUSES = {"active", "mobilizing", "advancing", "engaged", "occupied"}
_TERMINAL_ORDER_STATUSES = {
    "completed",
    "superseded",
    "cancelled",
    "canceled",
    "phase_complete_awaiting_follow_on_direction",
    "staged_awaiting_entry_authority",
}
_PENDING = "pending_operational_briefing"
_ACTIONABLE = "actionable"
_PENDING_OPERATION_STATUS = "awaiting_operational_briefing"
_AUTO_BRIEFING_PREFIX = "auto_qin_campaign_briefing_"
_REVIEW_PRIORITY = 43


def _digest(prefix: str, value: str) -> str:
    return hashlib.sha256(f"{prefix}|{value}".encode("utf-8")).hexdigest()[:20]


def _response_ref(work_ref: str) -> str:
    return f"event_qin_command_support_{_digest('response', work_ref)}"


def _review_ids(work_ref: str) -> tuple[str, str]:
    digest = _digest("review", work_ref)
    return f"host_qin_command_support_{digest}", f"event_qin_command_support_due_{digest}"


def _auto_briefing_work_ref(operation_ref: str, order_ref: str) -> str:
    return f"auto_qin_campaign_briefing_{_digest('auto-briefing', operation_ref + '|' + order_ref)}"


def _formation_refs(appointment: Mapping[str, Any]) -> list[str]:
    refs: list[str] = []
    raw = appointment.get("formation_refs")
    if isinstance(raw, list):
        refs.extend(str(ref) for ref in raw if isinstance(ref, str) and ref)
    single = appointment.get("formation_ref")
    if isinstance(single, str) and single:
        refs.append(single)
    return list(dict.fromkeys(refs))


def _active_operation(planner: Any, operation_ref: str) -> tuple[str, dict[str, Any]] | None:
    if not operation_ref:
        return None
    resolved = exact_operation_record(planner, operation_ref)
    if resolved is None:
        return None
    path, raw = resolved
    if not isinstance(raw, Mapping) or str(raw.get("status", "")) not in _ACTIVE_OPERATION_STATUSES:
        return None
    return path, copy.deepcopy(dict(raw))


def _scope_matches_operation(
    operation: Mapping[str, Any], *, command_group_ref: str, formation_refs: list[str]
) -> bool:
    operation_group_ref = operation.get("command_group_ref")
    if (
        isinstance(operation_group_ref, str)
        and operation_group_ref
        and operation_group_ref != command_group_ref
    ):
        return False
    participants = {
        str(ref)
        for ref in operation.get("formation_refs", [])
        if isinstance(ref, str) and ref
    }
    return not formation_refs or bool(participants.intersection(formation_refs))


def _command_group_active_operation_ref(planner: Any, command_group_ref: str) -> str:
    if (
        not command_group_ref.startswith("cmdgrp.")
        or "/" in command_group_ref
        or "\\" in command_group_ref
        or ".." in command_group_ref
    ):
        return ""
    path = f"state/cmd/command-groups/{command_group_ref}.json"
    try:
        group = planner.read(path)
    except (KeyError, FileNotFoundError, ValueError):
        return ""
    if not isinstance(group, Mapping):
        return ""
    recorded_ref = group.get("command_group_ref")
    if isinstance(recorded_ref, str) and recorded_ref and recorded_ref != command_group_ref:
        return ""
    candidate = group.get("active_context_ref")
    return str(candidate) if isinstance(candidate, str) and candidate else ""


def _resolve_appointment_operation(
    planner: Any, appointment: Mapping[str, Any]
) -> tuple[str, str, dict[str, Any]] | None:
    refs = _formation_refs(appointment)
    command_group_ref = str(appointment.get("command_group_ref") or "")

    direct = appointment.get("operation_ref")
    if isinstance(direct, str) and direct:
        resolved = _active_operation(planner, direct)
        if resolved is not None:
            path, operation = resolved
            if not command_group_ref or _scope_matches_operation(
                operation, command_group_ref=command_group_ref, formation_refs=refs
            ):
                return direct, path, operation

    if not command_group_ref:
        return None
    candidate = _command_group_active_operation_ref(planner, command_group_ref)
    resolved = _active_operation(planner, candidate)
    if resolved is None:
        return None
    path, operation = resolved
    if not _scope_matches_operation(
        operation, command_group_ref=command_group_ref, formation_refs=refs
    ):
        return None
    return candidate, path, operation


def _order_time(order: Mapping[str, Any]) -> CampaignTime | None:
    issued_at = order.get("issued_at")
    if not isinstance(issued_at, str) or not issued_at:
        return None
    try:
        return CampaignTime.parse(issued_at)
    except (TypeError, ValueError):
        return None


def _newest_relevant_order(operation: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Select current briefing pressure by issuance chronology, not list position."""
    orders = operation.get("operational_orders")
    if not isinstance(orders, list):
        return None
    timestamped: list[tuple[CampaignTime, int, Mapping[str, Any]]] = []
    fallback: list[Mapping[str, Any]] = []
    for index, row in enumerate(orders):
        if not isinstance(row, Mapping):
            continue
        actionability = str(row.get("actionability_status") or "")
        if actionability not in {_PENDING, _ACTIONABLE, "completed"}:
            continue
        fallback.append(row)
        issued = _order_time(row)
        if issued is not None:
            timestamped.append((issued, index, row))
    if timestamped:
        return max(timestamped, key=lambda item: (item[0], item[1]))[2]
    return fallback[-1] if fallback else None


def _latest_pending_order_ref(planner: Any, operation_ref: str) -> str:
    resolved = _active_operation(planner, operation_ref)
    if resolved is None:
        return ""
    _path, operation = resolved
    newest = _newest_relevant_order(operation)
    if not isinstance(newest, Mapping):
        return ""
    if str(newest.get("actionability_status") or "") != _PENDING:
        return ""
    return str(newest.get("order_ref") or "")


def _reconcile_newest_live_order_pointer(
    planner: Any, *, operation_path: str, operation: Mapping[str, Any]
) -> bool:
    """Repair only a provably older current pointer; never roll a newer order back."""
    orders = operation.get("operational_orders")
    if not isinstance(orders, list) or len(orders) < 2:
        return False
    current_ref = str(operation.get("last_operational_order_ref") or "")
    if not current_ref:
        return False

    current = None
    candidates: list[tuple[CampaignTime, int, Mapping[str, Any]]] = []
    for index, row in enumerate(orders):
        if not isinstance(row, Mapping):
            continue
        if str(row.get("order_ref") or "") == current_ref:
            current = row
        actionability = str(row.get("actionability_status") or "")
        if actionability not in {_PENDING, _ACTIONABLE}:
            continue
        if str(row.get("status") or "") in _TERMINAL_ORDER_STATUSES:
            continue
        issued = _order_time(row)
        if issued is not None:
            candidates.append((issued, index, row))

    if not isinstance(current, Mapping):
        return False
    current_time = _order_time(current)
    if current_time is None or not candidates:
        return False

    newest_time, _index, newest = max(candidates, key=lambda item: (item[0], item[1]))
    if newest_time <= current_time:
        return False
    newest_ref = str(newest.get("order_ref") or "")
    if not newest_ref:
        return False

    repaired = copy.deepcopy(dict(operation))
    repaired["last_operational_order_ref"] = newest_ref
    actionability = str(newest.get("actionability_status") or "")
    newest_status = str(newest.get("status") or "")
    if actionability == _PENDING:
        repaired["order_status"] = _PENDING_OPERATION_STATUS
    elif newest_status:
        repaired["order_status"] = newest_status
    planner.put(operation_path, repaired)
    return True


def _find_order(planner: Any, operation_ref: str, order_ref: str) -> Mapping[str, Any] | None:
    resolved = exact_operation_record(planner, operation_ref)
    if resolved is None:
        return None
    _path, operation = resolved
    if not isinstance(operation, Mapping):
        return None
    orders = operation.get("operational_orders")
    if not isinstance(orders, list):
        return None
    for row in reversed(orders):
        if isinstance(row, Mapping) and str(row.get("order_ref") or "") == order_ref:
            return row
    return None


def _active_qin_scopes(planner: Any) -> list[dict[str, Any]]:
    try:
        player = planner.read(_PLAYER_PATH)
    except (KeyError, FileNotFoundError, ValueError):
        return []
    career = player.get("career_state") if isinstance(player, Mapping) else None
    appointments = career.get("appointments") if isinstance(career, Mapping) else None
    if not isinstance(appointments, list):
        return []
    scopes: list[dict[str, Any]] = []
    for raw in appointments:
        if not isinstance(raw, Mapping):
            continue
        if not (
            raw.get("kind") == "qin_field_command"
            and raw.get("state_ref") == "state_qin"
            and raw.get("status") == "active"
        ):
            continue
        resolved = _resolve_appointment_operation(planner, raw)
        if resolved is None:
            continue
        operation_ref, _path, _operation = resolved
        scopes.append({
            "office": str(raw.get("office") or ""),
            "operation_ref": operation_ref,
            "formation_refs": _formation_refs(raw),
        })
    return scopes


def _canonicalize_review_event(
    events: list[Any], *, event_id: str, host_id: str, due_at: str
) -> None:
    """Keep one active scheduler event for an exact recovered support host."""
    retained: list[Any] = []
    for raw in events:
        if isinstance(raw, Mapping) and (
            str(raw.get("event_id") or "") == event_id
            or str(raw.get("target_host") or "") == host_id
        ):
            continue
        retained.append(raw)
    retained.append({
        "event_id": event_id,
        "kind": "qin_command_support_review",
        "priority": _REVIEW_PRIORITY,
        "target_host": host_id,
        "due_at": due_at,
    })
    events[:] = retained


def _ensure_missing_automatic_routes(
    planner: Any,
    runtime: dict[str, Any],
    *,
    current: CampaignTime,
    review_seconds: int,
) -> list[str]:
    """Register an exact automatic briefing route absent from the legacy scheduler."""
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        return []
    changed: list[str] = []
    for scope in _active_qin_scopes(planner):
        operation_ref = str(scope.get("operation_ref") or "")
        order_ref = _latest_pending_order_ref(planner, operation_ref)
        if not operation_ref or not order_ref:
            continue
        work_ref = _auto_briefing_work_ref(operation_ref, order_ref)
        if isinstance(get_causal_event(planner, _response_ref(work_ref)), Mapping):
            continue
        host_id, event_id = _review_ids(work_ref)
        if host_id in hosts:
            continue
        order = _find_order(planner, operation_ref, order_ref)
        if not isinstance(order, Mapping):
            continue
        bureau_location = command_endpoint_location(planner, _QIN_BUREAU_REF)
        response_target = player_command_location(planner)
        if not bureau_location or not response_target:
            continue
        route = command_message_route(planner.read, bureau_location, response_target, round_trip=False)
        travel_seconds = max(0, int(route.get("travel_seconds", 0) or 0))
        issued = _order_time(order)
        normal_due = (
            issued.add_seconds(review_seconds + travel_seconds)
            if issued is not None
            else current.add_seconds(review_seconds + travel_seconds)
        )
        due = normal_due if normal_due > current else current.add_seconds(1)
        hosts[host_id] = {
            "host_id": host_id,
            "kind": "qin_command_support_review",
            "owner_ref": _QIN_BUREAU_REF,
            "work_ref": work_ref,
            "source_event_id": None,
            "support_kind": "operational_briefing",
            "appointment_office": scope.get("office"),
            "operation_ref": operation_ref,
            "order_ref": order_ref,
            "formation_refs": list(scope.get("formation_refs", [])),
            "bureau_location_ref": bureau_location,
            "response_target_location_ref": response_target,
            "communication_travel_seconds": travel_seconds,
            "institution_processing_seconds": review_seconds,
            "courier_route": copy.deepcopy(dict(route)),
            "communication_rule": "automatic staff briefing is not delivered until review and physical courier travel complete",
            "recurrence_seconds": 0,
            "next_due": str(due),
            "resolved_through": str(due.add_seconds(-1)),
            "safe_through": str(due.add_seconds(-1)),
        }
        _canonicalize_review_event(events, event_id=event_id, host_id=host_id, due_at=str(due))
        changed.append(work_ref)
    return changed


def reconcile_overdue_qin_command_support_routes(planner: Any) -> list[str]:
    """Repair missing, exhausted, or late automatic Qin briefing routes.

    Exact pending pressure is selected by ``issued_at`` chronology rather than
    durable list position. Explicit player support requests are untouched. An
    overdue recovered route is placed one second beyond the current frontier
    because scheduler boundaries are strictly ``(current, target]``.
    """
    try:
        runtime_raw = planner.read(_RUNTIME_PATH)
        rules = planner.read(_LOGISTICS_RULES_PATH)
    except (KeyError, FileNotFoundError, ValueError):
        return []
    if not isinstance(runtime_raw, Mapping) or not isinstance(rules, Mapping):
        return []
    policy = rules.get("military_supply_policy")
    if not isinstance(policy, Mapping):
        return []
    review_hours = policy.get("qin_support_review_delay_hours", 4)
    if isinstance(review_hours, bool) or not isinstance(review_hours, int) or review_hours <= 0:
        return []

    runtime = copy.deepcopy(dict(runtime_raw))
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    now_text = runtime.get("world_time")
    if not isinstance(hosts, dict) or not isinstance(events, list) or not isinstance(now_text, str):
        return []
    try:
        current = CampaignTime.parse(now_text)
    except (TypeError, ValueError):
        return []

    review_seconds = review_hours * 3600
    changed_work_refs = _ensure_missing_automatic_routes(
        planner,
        runtime,
        current=current,
        review_seconds=review_seconds,
    )

    for host_id, raw_host in list(hosts.items()):
        if not isinstance(raw_host, Mapping):
            continue
        work_ref = str(raw_host.get("work_ref") or "")
        if (
            raw_host.get("kind") != "qin_command_support_review"
            or raw_host.get("support_kind") != "operational_briefing"
            or not work_ref.startswith(_AUTO_BRIEFING_PREFIX)
        ):
            continue
        if isinstance(get_causal_event(planner, _response_ref(work_ref)), Mapping):
            continue
        operation_ref = str(raw_host.get("operation_ref") or "")
        order_ref = str(raw_host.get("order_ref") or "")
        if not operation_ref or not order_ref:
            continue
        if _latest_pending_order_ref(planner, operation_ref) != order_ref:
            continue
        order = _find_order(planner, operation_ref, order_ref)
        if not isinstance(order, Mapping):
            continue
        issued = _order_time(order)
        due_text = raw_host.get("next_due")
        travel_seconds = raw_host.get("communication_travel_seconds", 0)
        if (
            issued is None
            or isinstance(travel_seconds, bool)
            or not isinstance(travel_seconds, int)
            or travel_seconds < 0
        ):
            continue
        existing_due = None
        if isinstance(due_text, str):
            try:
                existing_due = CampaignTime.parse(due_text)
            except (TypeError, ValueError):
                existing_due = None

        normal_due = issued.add_seconds(review_seconds + travel_seconds)
        earliest_future = current.add_seconds(1)
        desired_due = normal_due if normal_due > current else earliest_future
        scheduled_due = desired_due if existing_due is None or desired_due < existing_due else existing_due
        scheduled_text = str(scheduled_due)
        _host_id, event_id = _review_ids(work_ref)
        active_event = any(
            isinstance(raw_event, Mapping)
            and str(raw_event.get("event_id") or "") == event_id
            and str(raw_event.get("target_host") or "") == str(host_id)
            and raw_event.get("suspended") is not True
            and str(raw_event.get("due_at") or "") == scheduled_text
            for raw_event in events
        )
        if existing_due is not None and scheduled_due == existing_due and active_event:
            continue

        host = copy.deepcopy(dict(raw_host))
        host["next_due"] = scheduled_text
        host["resolved_through"] = str(scheduled_due.add_seconds(-1))
        host["safe_through"] = str(scheduled_due.add_seconds(-1))
        hosts[host_id] = host
        _canonicalize_review_event(
            events,
            event_id=event_id,
            host_id=str(host_id),
            due_at=scheduled_text,
        )
        changed_work_refs.append(work_ref)

    if changed_work_refs:
        runtime["hosts"] = hosts
        runtime["events"] = events
        planner.put(_RUNTIME_PATH, runtime)
    return list(dict.fromkeys(changed_work_refs))


def reconcile_legacy_qin_command_support_state(planner: Any) -> list[str]:
    """Normalize legacy Qin appointment routing and repair regressed order pointers."""
    player_raw = planner.read(_PLAYER_PATH)
    if not isinstance(player_raw, Mapping):
        return []
    player = copy.deepcopy(dict(player_raw))
    career = player.get("career_state")
    if not isinstance(career, Mapping):
        return []
    career_copy = copy.deepcopy(dict(career))
    appointments = career_copy.get("appointments")
    if not isinstance(appointments, list):
        return []

    changed_player = False
    repaired_operations: list[str] = []
    normalized_appointments: list[Any] = []
    for raw in appointments:
        if not isinstance(raw, Mapping):
            normalized_appointments.append(copy.deepcopy(raw))
            continue
        appointment = copy.deepcopy(dict(raw))
        if not (
            appointment.get("kind") == "qin_field_command"
            and appointment.get("state_ref") == "state_qin"
            and appointment.get("status") == "active"
        ):
            normalized_appointments.append(appointment)
            continue

        resolved = _resolve_appointment_operation(planner, appointment)
        if resolved is None:
            normalized_appointments.append(appointment)
            continue
        operation_ref, operation_path, operation = resolved
        if str(appointment.get("operation_ref") or "") != operation_ref:
            appointment["operation_ref"] = operation_ref
            changed_player = True
        if _reconcile_newest_live_order_pointer(
            planner, operation_path=operation_path, operation=operation
        ):
            repaired_operations.append(operation_ref)
        normalized_appointments.append(appointment)

    if changed_player:
        career_copy["appointments"] = normalized_appointments
        player["career_state"] = career_copy
        planner.put(_PLAYER_PATH, player)
    return list(dict.fromkeys(repaired_operations))


__all__ = [
    "reconcile_legacy_qin_command_support_state",
    "reconcile_overdue_qin_command_support_routes",
]
