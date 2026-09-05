"""Causal delivery boundary for campaign-command decisions.

Campaign superior decision-making and player receipt are separate facts.  The
command-decision owner may persist a new order at superior headquarters, but an
undelivered remote order must not become Tang Wei's current mission merely
because it exists in the operation record.  This module keeps that boundary
explicit without creating a second chronology engine:

* reconcile legacy decision orders that were activated before courier receipt;
* register those exact orders on the existing campaign-command superior-order
  host kind and geography-backed message route;
* activate a decision order only after the existing superior-order settlement
  has recorded it in ``delivered_superior_order_refs``;
* retire the obsolete parallel follow-on-review hosts now that outbound requests
  travel inside the ordinary upward campaign report.

It owns no tactics, troop movement, battle outcome, or new strategic decision.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from sword_runtime.campaign_command_cycle import _load_operation, _read_cycle, _register_host
from sword_runtime.campaign_communications import command_message_route, command_person_location, player_command_location
from sword_runtime.sim.calendar import CampaignTime


_RUNTIME_PATH = "state/runtime.json"
_SUPERIOR_ORDER_PRIORITY = 39
_PENDING_STATUS = "issued_pending_delivery"
_PENDING_ACTIONABILITY = "pending_delivery"
_ACTIVE_STATUS = "staff_briefed_awaiting_commander_execution"
_ACTIVE_ACTIONABILITY = "actionable"
_ACTIVE_PHASE = "contact_development"
_COMPLETED_ORDER_STATES = {"completed", "phase_complete_awaiting_follow_on_direction"}


def _active_cycle(planner: Any) -> tuple[str, str, dict[str, Any], str, dict[str, Any]] | None:
    try:
        root = planner.read("state/cmd/command-groups/cmdgrp.tang_wei.field_army.json")
    except (FileNotFoundError, KeyError, ValueError):
        return None
    operation_ref = root.get("active_context_ref") if isinstance(root, Mapping) else None
    if not isinstance(operation_ref, str) or not operation_ref:
        return None
    existing = _read_cycle(planner, operation_ref)
    if existing is None:
        return None
    cycle_path, cycle = existing
    try:
        op_path, operation = _load_operation(planner, operation_ref)
    except ValueError:
        return None
    return operation_ref, cycle_path, cycle, op_path, operation


def _orders(operation: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = operation.get("operational_orders") if isinstance(operation.get("operational_orders"), list) else []
    return [row for row in rows if isinstance(row, dict)]


def _order_by_ref(operation: Mapping[str, Any], order_ref: object) -> dict[str, Any] | None:
    if not isinstance(order_ref, str) or not order_ref:
        return None
    for row in reversed(_orders(operation)):
        if str(row.get("order_ref", "")) == order_ref:
            return row
    return None


def _decision_rows(cycle: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = cycle.get("campaign_command_decisions") if isinstance(cycle.get("campaign_command_decisions"), list) else []
    return [row for row in rows if isinstance(row, dict)]


def _decision_order_refs(cycle: Mapping[str, Any]) -> set[str]:
    return {
        str(row.get("order_ref"))
        for row in _decision_rows(cycle)
        if isinstance(row.get("order_ref"), str) and row.get("order_ref")
    }


def _delivered_refs(cycle: Mapping[str, Any]) -> set[str]:
    return {
        str(ref) for ref in cycle.get("delivered_superior_order_refs", [])
        if isinstance(ref, str) and ref
    }


def _base_order_ref(order: Mapping[str, Any], decision: Mapping[str, Any] | None) -> str | None:
    for value in (
        order.get("source_order_ref"),
        (order.get("decision_basis") or {}).get("base_order_ref") if isinstance(order.get("decision_basis"), Mapping) else None,
        decision.get("base_order_ref") if isinstance(decision, Mapping) else None,
    ):
        if isinstance(value, str) and value:
            return value
    return None


def _fallback_pre_delivery_state(base_order: Mapping[str, Any]) -> tuple[str, str]:
    """Return the narrow legacy state for a completed concentration order.

    New decisions persist ``prior_operation_state`` and never need this fallback.
    The compatibility branch exists only for already-written follow-on decisions
    from the historical implementation that immediately advanced the operation.
    """
    packet = base_order.get("mission_packet") if isinstance(base_order.get("mission_packet"), Mapping) else {}
    if (
        str(base_order.get("status", "")) in _COMPLETED_ORDER_STATES
        or str(base_order.get("actionability_status", "")) == "completed"
    ) and str(packet.get("mission_phase", "")) == "campaign_concentration_and_advance":
        return "awaiting_follow_on_direction", "operational_area_arrival"
    return str(base_order.get("status") or "awaiting_follow_on_direction"), str(packet.get("mission_phase") or "operational_area_arrival")


def reconcile_undelivered_campaign_decisions(planner: Any) -> list[str]:
    """Demote decision orders that became current before physical delivery.

    The order record remains durable superior-headquarters truth.  Only the
    player's current-order pointer and operation phase are restored to the last
    delivered basis until the normal campaign-command delivery host settles.
    """
    resolved = _active_cycle(planner)
    if resolved is None:
        return []
    _operation_ref, cycle_path, cycle, op_path, operation = resolved
    delivered = _delivered_refs(cycle)
    decisions = _decision_rows(cycle)
    by_order = {
        str(row.get("order_ref")): row
        for row in decisions
        if isinstance(row.get("order_ref"), str) and row.get("order_ref")
    }
    changed_orders: list[str] = []
    op_changed = False
    cycle_changed = False

    for order_ref in sorted(_decision_order_refs(cycle)):
        if order_ref in delivered:
            continue
        order = _order_by_ref(operation, order_ref)
        if not isinstance(order, dict) or str(order.get("order_kind", "")) != "campaign_command_follow_on_mission":
            continue
        decision = by_order.get(order_ref)
        if order.get("status") != _PENDING_STATUS:
            order["status"] = _PENDING_STATUS
            order["actionability_status"] = _PENDING_ACTIONABILITY
            packet = order.get("mission_packet")
            if isinstance(packet, dict):
                packet["phase_status"] = _PENDING_STATUS
            changed_orders.append(order_ref)
            op_changed = True
        if isinstance(decision, dict):
            if decision.get("delivery_status") != "pending_delivery":
                decision["delivery_status"] = "pending_delivery"
                cycle_changed = True

        if str(operation.get("last_operational_order_ref", "")) != order_ref:
            continue
        base_ref = _base_order_ref(order, decision)
        base_order = _order_by_ref(operation, base_ref)
        if not isinstance(base_order, Mapping):
            continue
        prior = decision.get("prior_operation_state") if isinstance(decision, Mapping) and isinstance(decision.get("prior_operation_state"), Mapping) else None
        if isinstance(prior, Mapping):
            restored_status = str(prior.get("order_status") or "awaiting_follow_on_direction")
            restored_phase = str(prior.get("campaign_phase") or "operational_area_arrival")
            restored_ref = prior.get("last_operational_order_ref")
            if not isinstance(restored_ref, str) or not restored_ref:
                restored_ref = base_ref
        else:
            restored_status, restored_phase = _fallback_pre_delivery_state(base_order)
            restored_ref = base_ref
        operation["last_operational_order_ref"] = restored_ref
        operation["order_status"] = restored_status
        operation["campaign_phase"] = restored_phase
        op_changed = True
        if cycle.get("current_superior_order") and isinstance(cycle.get("current_superior_order"), Mapping):
            current_ref = cycle["current_superior_order"].get("order_ref")
            if current_ref == order_ref:
                cycle["current_superior_order"] = copy.deepcopy(dict(base_order))
                cycle_changed = True

    if op_changed:
        planner.put(op_path, operation)
    if cycle_changed:
        cycle["campaign_command_decisions"] = decisions[-32:]
        planner.put(cycle_path, cycle)
    return changed_orders


def _retire_legacy_follow_on_review_hosts(runtime: dict[str, Any]) -> int:
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    retired = {
        host_id for host_id, host in hosts.items()
        if isinstance(host_id, str)
        and isinstance(host, Mapping)
        and host.get("kind") == "institutional_followup"
        and host.get("route_domain") == "campaign_command_follow_on_review"
    }
    for host_id in retired:
        hosts.pop(host_id, None)
    if retired:
        events[:] = [
            row for row in events
            if not (
                isinstance(row, Mapping)
                and (
                    row.get("target_host") in retired
                    or row.get("event_id") in {
                        str(host.get("event_id")) for host_id, host in hosts.items()
                        if host_id in retired and isinstance(host, Mapping) and isinstance(host.get("event_id"), str)
                    }
                )
            )
        ]
    return len(retired)


def sync_campaign_decision_delivery_routes(planner: Any) -> dict[str, Any]:
    """Register one-way delivery for every undelivered superior decision order."""
    resolved = _active_cycle(planner)
    runtime = copy.deepcopy(planner.read(_RUNTIME_PATH))
    retired = _retire_legacy_follow_on_review_hosts(runtime)
    if resolved is None:
        if retired:
            planner.put(_RUNTIME_PATH, runtime)
        return {"registered": 0, "retired_legacy_review_hosts": retired}

    operation_ref, cycle_path, cycle, _op_path, operation = resolved
    current_text = runtime.get("world_time")
    if not isinstance(current_text, str) or not current_text:
        raise ValueError("runtime world time is missing")
    current = CampaignTime.parse(current_text)
    delivered = _delivered_refs(cycle)
    mechanics = planner.read("game/data/mechanics/campaign-command.json")
    section = mechanics.get("campaign_command_cycle") if isinstance(mechanics, Mapping) else {}
    delay_minutes = int(section.get("superior_order_delivery_delay_minutes", 15) or 0) if isinstance(section, Mapping) else 15
    delay_minutes = max(0, delay_minutes)
    target_location = player_command_location(planner)
    if not target_location:
        if retired:
            planner.put(_RUNTIME_PATH, runtime)
        return {"registered": 0, "retired_legacy_review_hosts": retired}

    registered = 0
    cycle_changed = False
    for decision in _decision_rows(cycle):
        order_ref = decision.get("order_ref")
        if not isinstance(order_ref, str) or not order_ref or order_ref in delivered:
            continue
        order = _order_by_ref(operation, order_ref)
        if not isinstance(order, Mapping) or str(order.get("order_kind", "")) != "campaign_command_follow_on_mission":
            continue
        commander_ref = order.get("superior_commander_ref") or cycle.get("supreme_commander_ref") or cycle.get("superior_command_ref")
        source_location = command_person_location(planner, commander_ref)
        if not source_location:
            continue
        try:
            route = command_message_route(planner.read, source_location, target_location, round_trip=False)
        except (FileNotFoundError, KeyError, TypeError, ValueError):
            continue
        travel_seconds = max(0, int(route.get("travel_seconds", 0) or 0))
        issued_at = order.get("issued_at")
        issued = CampaignTime.parse(issued_at) if isinstance(issued_at, str) and issued_at else current
        candidate = issued.add_seconds(travel_seconds + delay_minutes * 60)
        due = candidate if candidate > current else current.add_seconds(1)
        _register_host(
            runtime,
            cycle_ref=str(cycle.get("cycle_ref") or ""),
            operation_ref=operation_ref,
            phase="superior_order",
            due_at=str(due),
            priority=_SUPERIOR_ORDER_PRIORITY,
            instance_ref=order_ref,
            host_context={
                "source_commander_ref": commander_ref,
                "source_location_ref": source_location,
                "target_location_ref": target_location,
                "communication_travel_seconds": travel_seconds,
                "courier_route": copy.deepcopy(dict(route)),
                "communication_rule": (
                    "campaign decision issuance is not player receipt; this order becomes current only after one-way physical courier delivery plus staff handling"
                ),
                "campaign_decision_ref": decision.get("decision_ref"),
            },
        )
        if decision.get("delivery_status") != "in_transit" or decision.get("delivery_due_at") != str(due):
            decision["delivery_status"] = "in_transit"
            decision["delivery_due_at"] = str(due)
            cycle_changed = True
        registered += 1

    if cycle_changed:
        cycle["campaign_command_decisions"] = _decision_rows(cycle)[-32:]
        cycle["updated_at"] = current_text
        planner.put(cycle_path, cycle)
    planner.put(_RUNTIME_PATH, runtime)
    return {"registered": registered, "retired_legacy_review_hosts": retired}


def activate_delivered_campaign_decision(planner: Any, host: Mapping[str, Any], at: str) -> bool:
    """Promote one exact decision order only after the cycle records delivery."""
    if str(host.get("kind", "")) != "campaign_command_superior_order":
        return False
    operation_ref = host.get("operation_ref")
    order_ref = host.get("phase_instance_ref")
    if not isinstance(operation_ref, str) or not operation_ref or not isinstance(order_ref, str) or not order_ref:
        return False
    existing = _read_cycle(planner, operation_ref)
    if existing is None:
        return False
    cycle_path, cycle = existing
    if order_ref not in _delivered_refs(cycle):
        return False
    op_path, operation = _load_operation(planner, operation_ref)
    order = _order_by_ref(operation, order_ref)
    if not isinstance(order, dict) or str(order.get("order_kind", "")) != "campaign_command_follow_on_mission":
        return False
    if order.get("status") == _ACTIVE_STATUS and str(operation.get("last_operational_order_ref", "")) == order_ref:
        return False

    order["status"] = _ACTIVE_STATUS
    order["actionability_status"] = _ACTIVE_ACTIONABILITY
    order["delivered_at"] = at
    packet = order.get("mission_packet")
    if isinstance(packet, dict):
        packet["phase_status"] = "ready_for_commander_execution"
    operation["last_operational_order_ref"] = order_ref
    operation["order_status"] = _ACTIVE_STATUS
    operation["campaign_phase"] = _ACTIVE_PHASE
    planner.put(op_path, operation)

    for decision in _decision_rows(cycle):
        if decision.get("order_ref") == order_ref:
            decision["delivery_status"] = "delivered"
            decision["delivered_at"] = at
            decision.pop("delivery_due_at", None)
    cycle["campaign_command_decisions"] = _decision_rows(cycle)[-32:]
    cycle["current_superior_order"] = copy.deepcopy(order)
    cycle["updated_at"] = at
    planner.put(cycle_path, cycle)
    return True


class CampaignCommandDeliveryMixin:
    """Production hooks enforcing campaign decision receipt before activation."""

    def _sync_campaign_command_decisions(self) -> list[str]:
        refs = super()._sync_campaign_command_decisions()
        reconcile_undelivered_campaign_decisions(self)
        return refs

    def _sync_contact_request_routes(self, runtime: dict[str, Any]) -> None:
        super()._sync_contact_request_routes(runtime)
        _retire_legacy_follow_on_review_hosts(runtime)

    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        super()._run_due_host(host, due_text)
        if str(host.get("kind", "")) == "campaign_command_superior_order":
            activate_delivered_campaign_decision(self, host, due_text)


__all__ = [
    "CampaignCommandDeliveryMixin",
    "activate_delivered_campaign_decision",
    "reconcile_undelivered_campaign_decisions",
    "sync_campaign_decision_delivery_routes",
]
