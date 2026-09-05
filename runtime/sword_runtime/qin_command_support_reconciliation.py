"""Compatibility reconciliation for legacy Qin field-command support routing.

Older saves may carry a valid Qin field-command appointment whose command-group
link predates the appointment ``operation_ref`` field. A short-lived compatibility
repair also displaced newer pending directives by restoring older executable
missions as the operation's current order. This module normalizes those legacy
routing/pointer facts and catches overdue automatic briefing routes up to the
current causal frontier.

The reconciliation does not create orders, move formations, authorize battle, or
change ownership. Normal Qin staff support remains responsible for briefing the
exact pending directive.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from sword_runtime.operation_routing import exact_operation_record
from sword_runtime.sim.calendar import CampaignTime


_PLAYER_PATH = "state/player.json"
_RUNTIME_PATH = "state/runtime.json"
_LOGISTICS_RULES_PATH = "game/data/mechanics/logistics.json"
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


def reconcile_overdue_qin_command_support_routes(planner: Any) -> list[str]:
    """Catch recovered automatic briefings up to their original causal schedule.

    The normal support flow registers the physical review/courier route. This
    compatibility pass only shortens automatic briefing routes whose order was
    issued earlier than the registration frontier. Explicit player requests are
    intentionally untouched. An overdue route is placed one second beyond the
    current frontier because scheduler boundaries are strictly ``(current, target]``.
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
        now = CampaignTime.parse(now_text)
    except (TypeError, ValueError):
        return []

    review_seconds = review_hours * 3600
    changed_work_refs: list[str] = []
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
        operation_ref = str(raw_host.get("operation_ref") or "")
        order_ref = str(raw_host.get("order_ref") or "")
        order = _find_order(planner, operation_ref, order_ref)
        if not isinstance(order, Mapping):
            continue
        issued = _order_time(order)
        due_text = raw_host.get("next_due")
        travel_seconds = raw_host.get("communication_travel_seconds", 0)
        if (
            issued is None
            or not isinstance(due_text, str)
            or isinstance(travel_seconds, bool)
            or not isinstance(travel_seconds, int)
            or travel_seconds < 0
        ):
            continue
        try:
            existing_due = CampaignTime.parse(due_text)
        except (TypeError, ValueError):
            continue

        normal_due = issued.add_seconds(review_seconds + travel_seconds)
        earliest_future = now.add_seconds(1)
        desired_due = normal_due if normal_due > now else earliest_future
        if desired_due >= existing_due:
            continue

        host = copy.deepcopy(dict(raw_host))
        host["next_due"] = str(desired_due)
        host["resolved_through"] = str(desired_due.add_seconds(-1))
        host["safe_through"] = str(desired_due.add_seconds(-1))
        hosts[host_id] = host

        event_changed = False
        for index, raw_event in enumerate(events):
            if not isinstance(raw_event, Mapping) or raw_event.get("target_host") != host_id:
                continue
            event = copy.deepcopy(dict(raw_event))
            event["due_at"] = str(desired_due)
            events[index] = event
            event_changed = True
        if not event_changed:
            continue
        changed_work_refs.append(work_ref)

    if changed_work_refs:
        runtime["hosts"] = hosts
        runtime["events"] = events
        planner.put(_RUNTIME_PATH, runtime)
    return list(dict.fromkeys(changed_work_refs))


def reconcile_legacy_qin_command_support_state(planner: Any) -> list[str]:
    """Normalize legacy Qin appointment routing and repair regressed order pointers.

    The reconciliation is deterministic and idempotent. It considers active Qin
    field-command appointments held by Tang Wei, validates their exact active
    command-group operation, records that operation on legacy appointments, and
    restores a newer live order only when its ``issued_at`` proves the current
    pointer is older. It never replaces a newer pending directive merely because
    an older mission is actionable.
    """
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
