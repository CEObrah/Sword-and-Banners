"""Compatibility reconciliation for legacy Qin field-command support routing.

Older saves may carry a valid Qin field-command appointment whose command-group
link predates the appointment ``operation_ref`` field. They may also preserve a
pending strategic directive as the current order after it displaced an already
executable field mission under older guard behavior.

This module repairs only those routing/pointer facts. It does not create orders,
move formations, authorize battle, or change ownership. The pending directive
remains durable in order history and normal Qin staff support remains responsible
for making that exact directive executable.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from sword_runtime.operation_routing import exact_operation_record


_PLAYER_PATH = "state/player.json"
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


def _restore_displaced_actionable_order(
    planner: Any, *, operation_path: str, operation: Mapping[str, Any]
) -> bool:
    orders = operation.get("operational_orders")
    if not isinstance(orders, list) or len(orders) < 2:
        return False
    current_ref = str(operation.get("last_operational_order_ref") or "")
    if not current_ref:
        return False

    current_index = None
    for index in range(len(orders) - 1, -1, -1):
        row = orders[index]
        if isinstance(row, Mapping) and str(row.get("order_ref") or "") == current_ref:
            current_index = index
            break
    if current_index is None or current_index <= 0:
        return False

    current = orders[current_index]
    if not isinstance(current, Mapping) or str(current.get("actionability_status") or "") != _PENDING:
        return False
    prior = orders[current_index - 1]
    if not isinstance(prior, Mapping):
        return False
    if str(prior.get("actionability_status") or "") != _ACTIONABLE:
        return False
    if str(prior.get("status") or "") in _TERMINAL_ORDER_STATUSES:
        return False
    prior_ref = str(prior.get("order_ref") or "")
    if not prior_ref:
        return False

    repaired = copy.deepcopy(dict(operation))
    repaired["last_operational_order_ref"] = prior_ref
    prior_status = str(prior.get("status") or "")
    if prior_status:
        repaired["order_status"] = prior_status
    planner.put(operation_path, repaired)
    return True


def reconcile_legacy_qin_command_support_state(planner: Any) -> list[str]:
    """Normalize legacy Qin appointment routing and repair displaced current orders.

    The reconciliation is deterministic and idempotent. It only considers active
    Qin field-command appointments held by Tang Wei, validates their exact active
    command-group operation, records that operation on legacy appointments, and
    restores an immediately preceding actionable order when the current pointer
    is a pending strategic directive. The pending directive itself is never
    removed or marked executable here.
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
        if _restore_displaced_actionable_order(
            planner, operation_path=operation_path, operation=operation
        ):
            repaired_operations.append(operation_ref)
        normalized_appointments.append(appointment)

    if changed_player:
        career_copy["appointments"] = normalized_appointments
        player["career_state"] = career_copy
        planner.put(_PLAYER_PATH, player)
    return list(dict.fromkeys(repaired_operations))


__all__ = ["reconcile_legacy_qin_command_support_state"]
