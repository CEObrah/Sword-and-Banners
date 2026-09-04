"""Materialize a distinct follow-on march order after campaign entry authority opens.

The sovereign campaign order already owns the authority to enter the target state.
The campaign briefing lifecycle may refresh that old staging order into an actionable
mission packet when the previously hidden authority becomes visible. If headquarters
already delivered the historical staging form of that order, this module creates one
new exact follow-on order so the campaign command cycle has a distinct order to
transmit. It never moves formations, assigns a vanguard, chooses tactics, or changes
ownership or diplomacy.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any
from sword_runtime.operation_routing import exact_operation_record


_OPERATION_INDEX = "state/operations/index.json"
_RUNTIME_PATH = "state/runtime.json"


def _latest_order(operation: Mapping[str, Any]) -> dict[str, Any] | None:
    order_ref = str(operation.get("last_operational_order_ref", ""))
    rows = operation.get("operational_orders") if isinstance(operation.get("operational_orders"), list) else []
    for row in reversed(rows):
        if not isinstance(row, Mapping):
            continue
        if order_ref and str(row.get("order_ref", "")) != order_ref:
            continue
        return copy.deepcopy(dict(row))
    return None


def _cycle(planner: Any, operation: Mapping[str, Any]) -> Mapping[str, Any] | None:
    cycle_ref = operation.get("campaign_command_cycle_ref")
    if not isinstance(cycle_ref, str) or not cycle_ref:
        return None
    try:
        path = planner.owner_path(cycle_ref)
        row = planner.read(path)
    except (FileNotFoundError, KeyError, ValueError):
        return None
    return row if isinstance(row, Mapping) else None


def _packet_signature(base_order_ref: str, packet: Mapping[str, Any]) -> str:
    material = {
        "base_order_ref": base_order_ref,
        "issued_at": packet.get("issued_at"),
        "mission_phase": packet.get("mission_phase"),
        "phase_status": packet.get("phase_status"),
        "rendezvous_location_ref": packet.get("rendezvous_location_ref"),
        "destination_ref": packet.get("destination_ref"),
        "strategic_target_ref": packet.get("strategic_target_ref"),
        "hostile_entry_authorized": packet.get("hostile_entry_authorized"),
        "entry_status": packet.get("entry_status"),
    }
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:20]


def materialize_reconciled_campaign_follow_on_orders(
    planner: Any,
    operation_refs: Iterable[str],
) -> list[str]:
    """Create one newly deliverable march order for each just-reconciled operation.

    Reconciliation deliberately updates the old staging order in place. That is safe
    for saves created before campaign-entry authority was projected, but a campaign
    command cycle may already have recorded that old order ref as delivered. A new
    deterministic order ref makes the newly actionable march packet causally visible
    without rewriting the earlier delivery record.
    """
    runtime = planner.read(_RUNTIME_PATH)
    at = runtime.get("world_time") if isinstance(runtime, Mapping) else None
    if not isinstance(at, str):
        return []

    created: list[str] = []
    for operation_ref in dict.fromkeys(str(ref) for ref in operation_refs if isinstance(ref, str) and ref):
        resolved = exact_operation_record(planner, operation_ref)
        if resolved is None:
            continue
        path, raw = resolved
        operation = copy.deepcopy(dict(raw))
        base_order = _latest_order(operation)
        if not isinstance(base_order, Mapping):
            continue
        base_order_ref = str(base_order.get("order_ref", ""))
        packet = base_order.get("mission_packet") if isinstance(base_order.get("mission_packet"), Mapping) else None
        if not base_order_ref or not isinstance(packet, Mapping):
            continue
        if (
            str(operation.get("campaign_phase", "")) != "campaign_concentration"
            or str(base_order.get("status", "")) != "staff_briefed_awaiting_commander_execution"
            or str(base_order.get("actionability_status", "")) != "actionable"
            or str(packet.get("phase_status", "")) != "ready_for_commander_execution"
            or packet.get("hostile_entry_authorized") is not True
        ):
            continue

        cycle = _cycle(planner, operation)
        delivered_rows = cycle.get("delivered_superior_order_refs", []) if isinstance(cycle, Mapping) else []
        delivered = {
            str(ref)
            for ref in delivered_rows
            if isinstance(ref, str) and ref
        } if isinstance(delivered_rows, list) else set()
        if base_order_ref not in delivered:
            # The refreshed order has not yet been delivered in this campaign
            # command cycle, so the normal superior-order route can transmit it.
            continue

        signature = _packet_signature(base_order_ref, packet)
        follow_on_ref = f"operational_order_{signature}"
        orders = operation.get("operational_orders") if isinstance(operation.get("operational_orders"), list) else []
        if any(isinstance(row, Mapping) and str(row.get("order_ref", "")) == follow_on_ref for row in orders):
            operation["last_operational_order_ref"] = follow_on_ref
            planner.put(path, operation)
            created.append(follow_on_ref)
            continue

        destination_name = str(packet.get("destination_name") or packet.get("destination_ref") or "the authorized operational area")
        strategic_name = str(packet.get("strategic_target_name") or packet.get("strategic_target_ref") or destination_name)
        follow_on = copy.deepcopy(dict(base_order))
        follow_on.update({
            "order_ref": follow_on_ref,
            "order_kind": "campaign_entry_follow_on_march_order",
            "source_order_ref": base_order_ref,
            "issued_at": at,
            "status": "staff_briefed_awaiting_commander_execution",
            "actionability_status": "actionable",
            "objective": (
                f"Advance the Tang Wei Field Army on the authorized {strategic_name} campaign axis "
                f"toward {destination_name}, maintain campaign coordination, and report on arrival."
            ),
            "follow_on_requirement": (
                "Execute the authorized march packet. This order does not assign a vanguard, "
                "move the army automatically, choose Tang Wei's tactics, or transfer ownership of any formation."
            ),
            "mission_packet": copy.deepcopy(dict(packet)),
        })
        if isinstance(cycle, Mapping):
            superior = cycle.get("supreme_commander_ref") or cycle.get("superior_command_ref")
            if isinstance(superior, str) and superior:
                follow_on["superior_commander_ref"] = superior
            coordination = cycle.get("coordination_authority_ref")
            if isinstance(coordination, str) and coordination:
                follow_on["coordination_authority_ref"] = coordination

        orders.append(follow_on)
        operation["operational_orders"] = orders
        operation["last_operational_order_ref"] = follow_on_ref
        operation["order_status"] = "staff_briefed_awaiting_commander_execution"
        operation["campaign_phase"] = "campaign_concentration"
        planner.put(path, operation)
        created.append(follow_on_ref)
    return created


__all__ = ["materialize_reconciled_campaign_follow_on_orders"]
