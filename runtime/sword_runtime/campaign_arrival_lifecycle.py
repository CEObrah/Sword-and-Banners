"""Pre-chronology reconciliation for already-satisfied player campaign arrivals.

Campaign briefing and march completion own the actual arrival transition. This
module only makes that existing authority reachable for historical or recovered
operations whose executable arrival packet is still open even though the exact
participating formations have already reached its destination. It creates no
movement, contact, tactics, manpower, or authority of its own.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sword_runtime.campaign_briefing import reconcile_campaign_arrival
from sword_runtime.operation_routing import exact_operation_record


_PLAYER_PATH = "state/player.json"
_PLAYER_FIELD_COMMAND_PATH = "state/cmd/command-groups/cmdgrp.tang_wei.field_army.json"
_RUNTIME_PATH = "state/runtime.json"
_ACTIVE_OPERATION_STATUSES = {"active", "mobilizing", "advancing", "engaged", "occupied"}
_ARRIVAL_MISSION_PHASES = {"campaign_concentration_and_advance", "campaign_muster_and_staging"}
_FIELD_APPOINTMENT_KINDS = {"qin_field_command", "state_field_command"}
_EXECUTABLE_ACTIONABILITY_STATUSES = {"actionable", "executing"}
_OPEN_PACKET_PHASE_STATUSES = {"ready_for_commander_execution", "executing"}
_TERMINAL_ORDER_STATUSES = {"completed", "cancelled", "canceled", "withdrawn", "terminated", "superseded"}


def _player_operation_refs(planner: Any) -> list[str]:
    """Resolve the player's exact active campaign operations without global scans."""
    player = planner.read(_PLAYER_PATH)
    career = player.get("career_state", {}) if isinstance(player, Mapping) else {}
    appointments = career.get("appointments", []) if isinstance(career, Mapping) else []
    refs: list[str] = []
    for row in appointments if isinstance(appointments, list) else []:
        if not isinstance(row, Mapping) or str(row.get("status", "")) != "active":
            continue
        if str(row.get("kind", "")) not in _FIELD_APPOINTMENT_KINDS:
            continue
        operation_ref = row.get("operation_ref")
        if isinstance(operation_ref, str) and operation_ref:
            refs.append(operation_ref)
    if refs:
        return list(dict.fromkeys(refs))

    # Compatibility fallback for older appointments that predate operation_ref.
    # The root field command's active context is an exact bounded route, not a
    # repository-wide operation search.
    try:
        group = planner.read(_PLAYER_FIELD_COMMAND_PATH)
    except (FileNotFoundError, KeyError, ValueError):
        return []
    operation_ref = group.get("active_context_ref") if isinstance(group, Mapping) else None
    return [operation_ref] if isinstance(operation_ref, str) and operation_ref else []


def _latest_order(operation: Mapping[str, Any]) -> Mapping[str, Any] | None:
    order_ref = str(operation.get("last_operational_order_ref", ""))
    rows = operation.get("operational_orders") if isinstance(operation.get("operational_orders"), list) else []
    for row in reversed(rows):
        if not isinstance(row, Mapping):
            continue
        if order_ref and str(row.get("order_ref", "")) != order_ref:
            continue
        return row
    return None


def _arrival_scope(operation: Mapping[str, Any], order: Mapping[str, Any]) -> list[str]:
    """Return a non-empty friendly formation scope before invoking arrival authority."""
    opposing = {
        str(ref)
        for ref in operation.get("opposing_formation_refs", [])
        if isinstance(ref, str) and ref
    }
    operation_refs = [
        str(ref)
        for ref in operation.get("formation_refs", [])
        if isinstance(ref, str) and ref
    ]
    friendly = [ref for ref in operation_refs if ref not in opposing]
    if friendly:
        return list(dict.fromkeys(friendly))

    applies = [
        str(ref)
        for ref in order.get("applies_to_formation_refs", [])
        if isinstance(ref, str) and ref and ref not in opposing
    ]
    if operation_refs:
        operation_ref_set = set(operation_refs)
        applies = [ref for ref in applies if ref in operation_ref_set]
    return list(dict.fromkeys(applies))


def reconcile_satisfied_player_campaign_arrivals(
    planner: Any,
    *,
    at: str | None = None,
) -> list[str]:
    """Complete open arrivals only when an executable packet and exact bodies prove it.

    ``reconcile_campaign_arrival`` remains the sole consequence owner. It checks
    every required non-opposing formation's exact location and returns ``None``
    when movement is still outstanding. This pre-chronology bridge additionally
    fails closed for terminal/non-executable orders, unsupported packet states,
    and empty formation scopes so unrelated or stale campaign records cannot be
    promoted merely because they contain old arrival-shaped metadata.
    """
    if at is None:
        runtime = planner.read(_RUNTIME_PATH)
        at = runtime.get("world_time") if isinstance(runtime, Mapping) else None
    if not isinstance(at, str) or not at:
        raise ValueError("campaign arrival reconciliation requires current world time")

    reconciled: list[str] = []
    for operation_ref in _player_operation_refs(planner):
        resolved = exact_operation_record(planner, operation_ref)
        if resolved is None:
            continue
        _path, operation = resolved
        if str(operation.get("status", "")) not in _ACTIVE_OPERATION_STATUSES:
            continue
        order = _latest_order(operation)
        if not isinstance(order, Mapping):
            continue
        if str(order.get("status", "")) in _TERMINAL_ORDER_STATUSES:
            continue
        if str(order.get("actionability_status", "")) not in _EXECUTABLE_ACTIONABILITY_STATUSES:
            continue
        packet = order.get("mission_packet") if isinstance(order.get("mission_packet"), Mapping) else None
        if not isinstance(packet, Mapping):
            continue
        if str(packet.get("mission_phase", "")) not in _ARRIVAL_MISSION_PHASES:
            continue
        if str(packet.get("phase_status", "")) not in _OPEN_PACKET_PHASE_STATUSES:
            continue
        destination_ref = packet.get("destination_ref")
        if not isinstance(destination_ref, str) or not destination_ref:
            continue
        if not _arrival_scope(operation, order):
            continue

        result = reconcile_campaign_arrival(
            planner,
            operation_ref,
            destination_ref=destination_ref,
            at=at,
        )
        if result is not None:
            reconciled.append(operation_ref)
    return reconciled


__all__ = ["reconcile_satisfied_player_campaign_arrivals"]
