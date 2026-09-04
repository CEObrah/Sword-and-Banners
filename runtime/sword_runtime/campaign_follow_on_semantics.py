"""Canonical semantics for campaign-command follow-on mission packets.

Campaign arrival orders and contact-development orders are distinct lifecycle
objects. A follow-on mission may inherit useful campaign authority and
intelligence from its source order, but it must not inherit completed-arrival
markers or arrival-specific completion text. This module normalizes only the
latest executable follow-on mission owned by the player's exact active field
command and creates no movement, contact, battle authority, or chronology.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from sword_runtime.operation_routing import exact_operation_record


_PLAYER_FIELD_COMMAND_PATH = "state/cmd/command-groups/cmdgrp.tang_wei.field_army.json"
_ACTIVE_OPERATION_STATUSES = {"active", "mobilizing", "advancing", "engaged", "occupied"}
_EXECUTABLE_ACTIONABILITY_STATUSES = {"actionable", "executing"}
_ORDER_KIND = "campaign_command_follow_on_mission"
_CONTACT_PHASE = "contact_development"
_ARRIVAL_ONLY_PACKET_KEYS = {
    "actual_arrival_ref",
    "completed_at",
    "destination_name",
    "destination_ref",
    "rendezvous_location_ref",
    "rendezvous_name",
}


def _latest_order_slot(operation: Mapping[str, Any]) -> tuple[list[Any], int] | None:
    order_ref = str(operation.get("last_operational_order_ref", ""))
    rows = operation.get("operational_orders") if isinstance(operation.get("operational_orders"), list) else None
    if not isinstance(rows, list):
        return None
    for index in range(len(rows) - 1, -1, -1):
        row = rows[index]
        if not isinstance(row, Mapping):
            continue
        if order_ref and str(row.get("order_ref", "")) != order_ref:
            continue
        return rows, index
    return None


def canonical_contact_development_packet(
    operation: Mapping[str, Any],
    order: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Return canonical packet semantics for this module's contact follow-on order."""
    if str(order.get("order_kind", "")) != _ORDER_KIND:
        return None
    if str(order.get("actionability_status", "")) not in _EXECUTABLE_ACTIONABILITY_STATUSES:
        return None
    packet = order.get("mission_packet") if isinstance(order.get("mission_packet"), Mapping) else None
    if not isinstance(packet, Mapping) or str(packet.get("mission_phase", "")) != _CONTACT_PHASE:
        return None

    normalized = copy.deepcopy(dict(packet))
    strategic_ref = operation.get("strategic_target_ref") or normalized.get("strategic_target_ref") or operation.get("operational_area_ref")
    strategic_name = normalized.get("strategic_target_name") or strategic_ref or "the current campaign"
    anchor_ref = normalized.get("field_command_anchor_ref") or operation.get("location_ref") or operation.get("operational_area_ref")
    anchor_name = normalized.get("field_command_anchor_name") or normalized.get("destination_name") or normalized.get("rendezvous_name") or anchor_ref or strategic_name

    for key in _ARRIVAL_ONLY_PACKET_KEYS:
        normalized.pop(key, None)

    order_issued_at = order.get("issued_at")
    if isinstance(order_issued_at, str) and order_issued_at:
        normalized["issued_at"] = order_issued_at
    if isinstance(anchor_ref, str) and anchor_ref:
        normalized["field_command_anchor_ref"] = anchor_ref
    if isinstance(anchor_name, str) and anchor_name:
        normalized["field_command_anchor_name"] = anchor_name
    normalized.update({
        "mission_phase": _CONTACT_PHASE,
        "operational_intent": "develop_contact",
        "next_phase_trigger": (
            "Confirmed enemy contact or another material operational change is reported to field command. "
            "Contact itself does not authorize or automatically start a general battle."
        ),
        "success_condition": (
            f"Locate, confirm, observe, and report enemy dispositions affecting the {strategic_name} axis while maintaining "
            f"{anchor_name} as the field-command anchor and preserving campaign support continuity."
        ),
    })
    return normalized


def normalize_current_contact_development_order(planner: Any) -> bool:
    """Repair stale arrival metadata on the current executable campaign follow-on.

    This is bounded to the player's exact active field-command context and to the
    order kind created by the campaign-command decision owner. It never edits a
    terminal order, another mission kind, or an arbitrary historical packet.
    """
    try:
        root = planner.read(_PLAYER_FIELD_COMMAND_PATH)
    except (FileNotFoundError, KeyError, ValueError):
        return False
    operation_ref = root.get("active_context_ref") if isinstance(root, Mapping) else None
    if not isinstance(operation_ref, str) or not operation_ref:
        return False
    resolved = exact_operation_record(planner, operation_ref)
    if resolved is None:
        return False
    path, raw = resolved
    operation = copy.deepcopy(dict(raw))
    if str(operation.get("status", "")) not in _ACTIVE_OPERATION_STATUSES:
        return False
    slot = _latest_order_slot(operation)
    if slot is None:
        return False
    orders, index = slot
    order = copy.deepcopy(dict(orders[index]))
    normalized = canonical_contact_development_packet(operation, order)
    if normalized is None:
        return False
    current = order.get("mission_packet") if isinstance(order.get("mission_packet"), Mapping) else None
    if isinstance(current, Mapping) and dict(current) == normalized:
        return False
    order["mission_packet"] = normalized
    orders[index] = order
    operation["operational_orders"] = orders
    planner.put(path, operation)
    return True


__all__ = ["canonical_contact_development_packet", "normalize_current_contact_development_order"]
