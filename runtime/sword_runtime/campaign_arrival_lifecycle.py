"""Pre-chronology reconciliation for already-satisfied player campaign arrivals.

Campaign briefing and march completion own the actual arrival transition. This
module only makes that existing authority reachable for historical or recovered
operations whose actionable arrival packet is still open even though the exact
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


def reconcile_satisfied_player_campaign_arrivals(
    planner: Any,
    *,
    at: str | None = None,
) -> list[str]:
    """Complete open arrival packets only when the existing authority proves arrival.

    ``reconcile_campaign_arrival`` remains the sole consequence owner. It checks
    every required non-opposing formation's exact location and returns ``None``
    when movement is still outstanding, so calling this before chronology is
    idempotent and cannot turn a remote order into a zero-distance arrival.
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
        packet = order.get("mission_packet") if isinstance(order, Mapping) else None
        if not isinstance(packet, Mapping):
            continue
        if str(packet.get("mission_phase", "")) not in _ARRIVAL_MISSION_PHASES:
            continue
        if str(packet.get("phase_status", "")) == "completed":
            continue
        destination_ref = packet.get("destination_ref")
        if not isinstance(destination_ref, str) or not destination_ref:
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
