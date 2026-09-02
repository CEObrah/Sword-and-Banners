"""Causal routing for exact autonomous campaign-participant march orders.

This module is deliberately downstream of campaign command.  It never turns a
staff projection into an order.  A route exists only for an exact autonomous
participant operation whose saved operational order is executable and names an
exact destination plus exact formation scope.

Physical movement remains owned by the existing autonomous formation movement
resolver.  The scheduler records the planned next leg, waits for that leg's real
elapsed time, then invokes the canonical resolver using the saved departure instant.
Tang Wei-commanded formations are never eligible for this autonomous route.
"""
from __future__ import annotations

import copy
import hashlib
import math
from collections.abc import Mapping
from typing import Any

from sword_runtime.military_supply import evaluate_military_supply
from sword_runtime.operation_routing import exact_operation_record, iter_exact_operation_records
from sword_runtime.sim.calendar import CampaignTime


CAMPAIGN_MARCH_HOST_KIND = "campaign_march"
_ACTIVE_OPERATION_STATUSES = frozenset({"planned", "mobilizing", "active", "advancing"})
_TERMINAL_OPERATION_STATUSES = frozenset({"completed", "cancelled", "canceled", "failed", "closed", "resolved", "terminated", "withdrawn", "abandoned"})
_TERMINAL_ORDER_STATUSES = frozenset({"completed", "cancelled", "canceled", "withdrawn", "terminated", "superseded"})
_PLAYER_REF = "char_tang_wei"
_RUNTIME_PATH = "state/runtime.json"
_MARCH_PRIORITY = 44


def _digest(*parts: object) -> str:
    material = "|".join(str(part) for part in parts)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]


def _latest_order(operation: Mapping[str, Any]) -> Mapping[str, Any] | None:
    ref = str(operation.get("last_operational_order_ref", ""))
    rows = operation.get("operational_orders") if isinstance(operation.get("operational_orders"), list) else []
    for row in reversed(rows):
        if not isinstance(row, Mapping):
            continue
        if ref and str(row.get("order_ref", "")) != ref:
            continue
        return row
    current = operation.get("current_operational_order")
    return current if isinstance(current, Mapping) else None


def _executable_order(operation: Mapping[str, Any]) -> tuple[Mapping[str, Any], str, list[str]] | None:
    if operation.get("autonomous") is not True:
        return None
    if str(operation.get("status", "")) not in _ACTIVE_OPERATION_STATUSES:
        return None
    owner = str(operation.get("institutional_owner_ref") or operation.get("administrative_authority") or "")
    if not owner.startswith("state_"):
        return None
    order = _latest_order(operation)
    if not isinstance(order, Mapping):
        return None
    if str(order.get("status", "")) in _TERMINAL_ORDER_STATUSES:
        return None
    if str(order.get("actionability_status", "")) not in {"actionable", "executing"}:
        return None
    if str(order.get("issuer_ref", "")) != owner:
        return None
    campaign_commander = str(operation.get("campaign_commander_ref") or "")
    superior = str(order.get("superior_commander_ref") or order.get("superior_command_ref") or "")
    if campaign_commander and superior != campaign_commander:
        return None
    packet = order.get("mission_packet") if isinstance(order.get("mission_packet"), Mapping) else {}
    destination = packet.get("destination_ref")
    if not isinstance(destination, str) or not destination:
        return None
    if packet.get("hostile_entry_authorized") is not True or str(packet.get("entry_status", "")) != "authorized":
        return None
    op_refs = {str(ref) for ref in operation.get("formation_refs", []) if isinstance(ref, str) and ref}
    applies = [str(ref) for ref in order.get("applies_to_formation_refs", []) if isinstance(ref, str) and ref]
    if not applies or not set(applies).issubset(op_refs):
        return None
    return order, destination, applies


def _event_for_host(events: list[Any], host_id: str) -> dict[str, Any] | None:
    for row in events:
        if isinstance(row, dict) and row.get("target_host") == host_id:
            return row
    return None


def _remove_host(runtime: dict[str, Any], host_id: str) -> None:
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    hosts.pop(host_id, None)
    runtime["events"] = [
        row for row in events
        if not (isinstance(row, Mapping) and row.get("target_host") == host_id)
    ]


def _active_host_for_formation(runtime: Mapping[str, Any], formation_ref: str) -> tuple[str, Mapping[str, Any]] | None:
    hosts = runtime.get("hosts") if isinstance(runtime.get("hosts"), Mapping) else {}
    for host_id, host in hosts.items():
        if (
            isinstance(host_id, str)
            and isinstance(host, Mapping)
            and host.get("kind") == CAMPAIGN_MARCH_HOST_KIND
            and str(host.get("formation_ref", "")) == formation_ref
            and host.get("next_due") is not None
        ):
            return host_id, host
    return None


def _formation_eligible(planner: Any, formation_ref: str, owner_ref: str) -> Mapping[str, Any] | None:
    try:
        _path, formation = planner._load_formation(formation_ref)
    except (FileNotFoundError, KeyError, ValueError):
        return None
    if str(formation.get("command_authority", "")) == _PLAYER_REF:
        return None
    if str(formation.get("administrative_owner", "")) != owner_ref:
        return None
    if int(formation.get("personnel", 0) or 0) <= 0:
        return None
    if not bool(formation.get("mobilized", False)):
        return None
    return formation


def _next_leg_plan(planner: Any, formation: Mapping[str, Any], destination_ref: str, departure_at: str) -> dict[str, Any] | None:
    origin_ref = str(formation.get("location_ref") or "")
    if not origin_ref:
        raise ValueError("campaign march formation lacks location_ref")
    if origin_ref == destination_ref:
        return None
    next_ref, base_hours = planner._formation_route_next(
        origin_ref,
        destination_ref,
        formation=formation,
        at=departure_at,
    )
    supply = evaluate_military_supply(planner, formation, at=departure_at)
    supply_factor = max(0.40, min(1.0, float(supply.get("movement_factor", 1.0) or 1.0)))
    hours = max(1, int(math.ceil(int(base_hours) / supply_factor)))
    return {
        "origin_ref": origin_ref,
        "next_ref": str(next_ref),
        "hours": hours,
        "departure_at": departure_at,
        "supply_condition": str(supply.get("condition", "adequate")),
        "supply_score_milli": int(supply.get("score_milli", 1000)),
    }


def _host_ids(operation_ref: str, order_ref: str, formation_ref: str, destination_ref: str) -> tuple[str, str]:
    token = _digest(operation_ref, order_ref, formation_ref, destination_ref)
    return f"host_campaign_march_{token}", f"event_campaign_march_{token}"


def _register_host(
    planner: Any,
    runtime: dict[str, Any],
    *,
    operation_ref: str,
    owner_ref: str,
    order: Mapping[str, Any],
    formation_ref: str,
    destination_ref: str,
    at: str,
) -> bool:
    formation = _formation_eligible(planner, formation_ref, owner_ref)
    if not isinstance(formation, Mapping):
        return False
    if str(formation.get("location_ref") or "") == destination_ref:
        return False

    order_ref = str(order.get("order_ref") or "")
    if not order_ref:
        raise ValueError("campaign march order lacks order_ref")
    existing = _active_host_for_formation(runtime, formation_ref)
    if existing is not None:
        host_id, host = existing
        if (
            str(host.get("operation_ref", "")) == operation_ref
            and str(host.get("order_ref", "")) == order_ref
            and str(host.get("destination_ref", "")) == destination_ref
        ):
            return False
        _remove_host(runtime, host_id)

    plan = _next_leg_plan(planner, formation, destination_ref, at)
    if plan is None:
        return False
    departure = CampaignTime.parse(at)
    due = departure.add_seconds(int(plan["hours"]) * 3600)
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    host_id, event_id = _host_ids(operation_ref, order_ref, formation_ref, destination_ref)
    hosts[host_id] = {
        "host_id": host_id,
        "kind": CAMPAIGN_MARCH_HOST_KIND,
        "owner_ref": operation_ref,
        "operation_ref": operation_ref,
        "order_ref": order_ref,
        "formation_ref": formation_ref,
        "destination_ref": destination_ref,
        "leg_origin_ref": plan["origin_ref"],
        "leg_destination_ref": plan["next_ref"],
        "leg_departure_at": at,
        "leg_hours": int(plan["hours"]),
        "recurrence_seconds": int(plan["hours"]) * 3600,
        "next_due": str(due),
        "resolved_through": at,
        "safe_through": str(due.add_seconds(-1)),
        "retire_after_settlement": False,
    }
    events.append({
        "event_id": event_id,
        "kind": CAMPAIGN_MARCH_HOST_KIND,
        "priority": _MARCH_PRIORITY,
        "target_host": host_id,
        "due_at": str(due),
    })
    return True


def _order_by_ref(operation: Mapping[str, Any], order_ref: str) -> tuple[list[Any], int] | None:
    orders = operation.get("operational_orders")
    if not isinstance(orders, list):
        return None
    for index in range(len(orders) - 1, -1, -1):
        row = orders[index]
        if isinstance(row, Mapping) and str(row.get("order_ref", "")) == order_ref:
            return orders, index
    return None


def _update_order_status(
    planner: Any,
    operation_path: str,
    operation: dict[str, Any],
    *,
    order_ref: str,
    status: str,
    at: str,
    reason: str | None = None,
) -> None:
    matched = _order_by_ref(operation, order_ref)
    if matched is None:
        return
    orders, index = matched
    order = copy.deepcopy(dict(orders[index]))
    packet = copy.deepcopy(dict(order.get("mission_packet", {}))) if isinstance(order.get("mission_packet"), Mapping) else {}
    order["status"] = status
    if status == "completed":
        order["actionability_status"] = "completed"
        packet["phase_status"] = "completed"
        packet["completed_at"] = at
        packet["actual_arrival_ref"] = packet.get("destination_ref")
    elif status == "executing":
        order["actionability_status"] = "executing"
        packet["phase_status"] = "executing"
        packet.setdefault("execution_started_at", at)
    elif status == "execution_blocked":
        order["actionability_status"] = "actionable"
        packet["phase_status"] = "blocked"
        packet["blocked_at"] = at
        if reason:
            packet["blocked_reason"] = reason[:240]
    order["mission_packet"] = packet
    orders[index] = order
    operation["operational_orders"] = orders
    if str(operation.get("last_operational_order_ref", "")) == order_ref:
        operation["order_status"] = status
    planner.put(operation_path, operation)


def _all_order_formations_arrived(planner: Any, operation: Mapping[str, Any], order: Mapping[str, Any], destination_ref: str) -> bool:
    op_refs = {str(ref) for ref in operation.get("formation_refs", []) if isinstance(ref, str)}
    refs = [str(ref) for ref in order.get("applies_to_formation_refs", []) if isinstance(ref, str) and ref in op_refs]
    if not refs:
        return False
    for ref in refs:
        try:
            _path, formation = planner._load_formation(ref)
        except (FileNotFoundError, KeyError, ValueError):
            return False
        if int(formation.get("personnel", 0) or 0) > 0 and str(formation.get("location_ref") or "") != destination_ref:
            return False
    return True


def _prune_stale_routes(planner: Any, runtime: dict[str, Any]) -> None:
    hosts = runtime.get("hosts")
    if not isinstance(hosts, dict):
        raise ValueError("runtime causal hosts are invalid")
    stale: list[str] = []
    for host_id, host in hosts.items():
        if not isinstance(host_id, str) or not isinstance(host, Mapping) or host.get("kind") != CAMPAIGN_MARCH_HOST_KIND:
            continue
        operation_ref = str(host.get("operation_ref") or host.get("owner_ref") or "")
        resolved = exact_operation_record(planner, operation_ref) if operation_ref else None
        if resolved is None:
            stale.append(host_id)
            continue
        _path, operation = resolved
        executable = _executable_order(operation)
        if executable is None:
            stale.append(host_id)
            continue
        order, destination_ref, applies = executable
        if (
            str(host.get("order_ref", "")) != str(order.get("order_ref", ""))
            or str(host.get("destination_ref", "")) != destination_ref
            or str(host.get("formation_ref", "")) not in set(applies)
        ):
            stale.append(host_id)
    for host_id in stale:
        _remove_host(runtime, host_id)


def sync_campaign_march_routes(planner: Any, runtime: dict[str, Any] | None = None, *, at: str | None = None) -> list[str]:
    """Register missing march legs from exact executable participant orders only."""
    owns_runtime = runtime is None
    if runtime is None:
        runtime = copy.deepcopy(planner.read(_RUNTIME_PATH))
    if not isinstance(runtime, dict):
        raise ValueError("runtime causal registry is invalid")
    if at is None:
        at = runtime.get("world_time")
    if not isinstance(at, str) or not at:
        return []

    _prune_stale_routes(planner, runtime)
    registered: list[str] = []
    for operation_ref, operation_path, raw in iter_exact_operation_records(planner):
        operation = copy.deepcopy(dict(raw))
        executable = _executable_order(operation)
        if executable is None:
            continue
        order, destination_ref, applies = executable
        owner_ref = str(operation.get("institutional_owner_ref") or operation.get("administrative_authority") or "")
        order_ref = str(order.get("order_ref") or "")
        if _all_order_formations_arrived(planner, operation, order, destination_ref):
            if str(order.get("status", "")) != "completed":
                _update_order_status(
                    planner,
                    operation_path,
                    operation,
                    order_ref=order_ref,
                    status="completed",
                    at=at,
                )
            continue
        for formation_ref in applies:
            try:
                if _register_host(
                    planner,
                    runtime,
                    operation_ref=operation_ref,
                    owner_ref=owner_ref,
                    order=order,
                    formation_ref=formation_ref,
                    destination_ref=destination_ref,
                    at=at,
                ):
                    registered.append(formation_ref)
            except ValueError as exc:
                _update_order_status(
                    planner,
                    operation_path,
                    operation,
                    order_ref=order_ref,
                    status="execution_blocked",
                    at=at,
                    reason=str(exc),
                )
    if owns_runtime:
        planner.put(_RUNTIME_PATH, runtime)
    return registered


def _mutable_runtime_host(planner: Any, host: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    runtime = copy.deepcopy(planner.read(_RUNTIME_PATH))
    hosts = runtime.get("hosts")
    if not isinstance(hosts, dict):
        raise ValueError("runtime causal hosts are invalid")
    active_id = getattr(planner, "_active_host_id", None)
    if isinstance(active_id, str) and isinstance(hosts.get(active_id), dict):
        return runtime, hosts[active_id]
    host_id = host.get("host_id")
    if isinstance(host_id, str) and isinstance(hosts.get(host_id), dict):
        return runtime, hosts[host_id]
    return runtime, None


def _retire_current_host(planner: Any, host: Mapping[str, Any], at: str, reason: str) -> None:
    runtime, current = _mutable_runtime_host(planner, host)
    if isinstance(current, dict):
        current["recurrence_seconds"] = 0
        current["retire_after_settlement"] = True
        current["terminal_at"] = at
        current["terminal_reason"] = reason[:240]
        planner.put(_RUNTIME_PATH, runtime)


def _set_next_leg(planner: Any, host: Mapping[str, Any], plan: Mapping[str, Any], at: str) -> None:
    runtime, current = _mutable_runtime_host(planner, host)
    if not isinstance(current, dict):
        raise ValueError("campaign march settlement lost its active scheduler host")
    hours = max(1, int(plan.get("hours", 1) or 1))
    current["leg_origin_ref"] = plan.get("origin_ref")
    current["leg_destination_ref"] = plan.get("next_ref")
    current["leg_departure_at"] = at
    current["leg_hours"] = hours
    current["recurrence_seconds"] = hours * 3600
    current["retire_after_settlement"] = False
    current["last_leg_settled_at"] = at
    planner.put(_RUNTIME_PATH, runtime)


def settle_campaign_march_host(planner: Any, host: Mapping[str, Any], due_text: str) -> dict[str, Any] | None:
    """Settle one previously scheduled physical route leg at its arrival instant."""
    operation_ref = str(host.get("operation_ref") or host.get("owner_ref") or "")
    order_ref = str(host.get("order_ref") or "")
    formation_ref = str(host.get("formation_ref") or "")
    destination_ref = str(host.get("destination_ref") or "")
    leg_origin_ref = str(host.get("leg_origin_ref") or "")
    leg_destination_ref = str(host.get("leg_destination_ref") or "")
    departure_at = str(host.get("leg_departure_at") or "")
    leg_hours = int(host.get("leg_hours", 0) or 0)
    if not all((operation_ref, order_ref, formation_ref, destination_ref, leg_origin_ref, leg_destination_ref, departure_at)) or leg_hours <= 0:
        raise ValueError("campaign march host routing is invalid")
    expected_due = CampaignTime.parse(departure_at).add_seconds(leg_hours * 3600)
    if expected_due != CampaignTime.parse(due_text):
        raise ValueError("campaign march host due time diverged from its planned leg")

    resolved = exact_operation_record(planner, operation_ref)
    if resolved is None:
        _retire_current_host(planner, host, due_text, "operation_missing")
        return None
    operation_path, raw_operation = resolved
    operation = copy.deepcopy(dict(raw_operation))
    executable = _executable_order(operation)
    if executable is None:
        _retire_current_host(planner, host, due_text, "order_no_longer_executable")
        return None
    order, live_destination, applies = executable
    if str(order.get("order_ref", "")) != order_ref or live_destination != destination_ref or formation_ref not in set(applies):
        _retire_current_host(planner, host, due_text, "order_superseded")
        return None

    owner_ref = str(operation.get("institutional_owner_ref") or operation.get("administrative_authority") or "")
    formation = _formation_eligible(planner, formation_ref, owner_ref)
    if not isinstance(formation, Mapping):
        _retire_current_host(planner, host, due_text, "formation_no_longer_eligible")
        return None
    if str(formation.get("location_ref") or "") != leg_origin_ref:
        _retire_current_host(planner, host, due_text, "formation_moved_outside_registered_leg")
        return None

    if str(order.get("status", "")) != "executing":
        _update_order_status(
            planner,
            operation_path,
            operation,
            order_ref=order_ref,
            status="executing",
            at=departure_at,
        )
        operation = copy.deepcopy(dict(planner.read(operation_path)))
        order = _latest_order(operation) or order

    try:
        movement = planner._autonomy_move_formation_step(
            formation_ref,
            destination_ref,
            departure_at,
        )
    except ValueError as exc:
        _update_order_status(
            planner,
            operation_path,
            operation,
            order_ref=order_ref,
            status="execution_blocked",
            at=due_text,
            reason=str(exc),
        )
        _retire_current_host(planner, host, due_text, "canonical_route_blocked")
        return {
            "operation_ref": operation_ref,
            "formation_ref": formation_ref,
            "destination_ref": destination_ref,
            "location_ref": leg_origin_ref,
            "status": "blocked",
        }

    moved_to = str(movement.get("location_ref") or "") if isinstance(movement, Mapping) else ""
    moved_hours = int(movement.get("hours", leg_hours) or leg_hours) if isinstance(movement, Mapping) else leg_hours
    moved_status = str(movement.get("status") or "") if isinstance(movement, Mapping) else ""
    if moved_status == "commander_detached":
        _update_order_status(
            planner,
            operation_path,
            operation,
            order_ref=order_ref,
            status="execution_blocked",
            at=due_text,
            reason="formation commander detached from the registered march",
        )
        _retire_current_host(planner, host, due_text, "commander_detached")
        return dict(movement)
    if moved_to != leg_destination_ref or moved_hours != leg_hours:
        raise ValueError("canonical movement result diverged from the registered campaign leg")

    operation = copy.deepcopy(dict(planner.read(operation_path)))
    latest = _latest_order(operation)
    if isinstance(latest, Mapping) and _all_order_formations_arrived(planner, operation, latest, destination_ref):
        operation["location_ref"] = destination_ref
        operation["status"] = "active"
        operation["last_campaign_march_arrival_at"] = due_text
        planner.put(operation_path, operation)
        operation = copy.deepcopy(dict(planner.read(operation_path)))
        _update_order_status(
            planner,
            operation_path,
            operation,
            order_ref=order_ref,
            status="completed",
            at=due_text,
        )
        _retire_current_host(planner, host, due_text, "order_completed")
        return {
            "operation_ref": operation_ref,
            "formation_ref": formation_ref,
            "destination_ref": destination_ref,
            "location_ref": moved_to,
            "status": "arrived",
            "operation_concentrated": True,
        }

    _path, moved_formation = planner._load_formation(formation_ref)
    try:
        next_plan = _next_leg_plan(planner, moved_formation, destination_ref, due_text)
    except ValueError as exc:
        operation = copy.deepcopy(dict(planner.read(operation_path)))
        _update_order_status(
            planner,
            operation_path,
            operation,
            order_ref=order_ref,
            status="execution_blocked",
            at=due_text,
            reason=str(exc),
        )
        _retire_current_host(planner, host, due_text, "next_leg_blocked")
        return {
            "operation_ref": operation_ref,
            "formation_ref": formation_ref,
            "destination_ref": destination_ref,
            "location_ref": moved_to,
            "status": "blocked",
        }
    if next_plan is None:
        _retire_current_host(planner, host, due_text, "formation_arrived")
    else:
        _set_next_leg(planner, host, next_plan, due_text)
    return {
        "operation_ref": operation_ref,
        "formation_ref": formation_ref,
        "destination_ref": destination_ref,
        "location_ref": moved_to,
        "status": moved_status or "marching",
        "operation_concentrated": False,
    }


__all__ = [
    "CAMPAIGN_MARCH_HOST_KIND",
    "settle_campaign_march_host",
    "sync_campaign_march_routes",
]
