"""Fail closed when strategic Qin pressure is not yet an executable field order.

The autonomous world-arc layer may lawfully retask Qin-owned formations that are
under Tang Wei's accepted field command. That authority is strategic: it does
not itself establish the staff work needed to execute a march.

Underspecified directives remain durable strategic pressure, but they must not
silently displace a distinct actionable field mission while staff work is still
pending. A pending directive becomes the current operational order only when no
older executable order remains, or when staff later turns that exact directive
into an actionable mission packet.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from sword_runtime.operation_routing import exact_operation_record


_PENDING_OPERATION_STATUS = "awaiting_operational_briefing"
_PENDING_ORDER_STATUS = "strategic_directive_pending_operational_briefing"
_ACTIONABLE = "actionable"
_PENDING = "pending_operational_briefing"
_TERMINAL_ORDER_STATUSES = {
    "completed",
    "superseded",
    "cancelled",
    "canceled",
    "phase_complete_awaiting_follow_on_direction",
    "staged_awaiting_entry_authority",
}


def _operation_path(planner: Any, operation_ref: str) -> str | None:
    resolved = exact_operation_record(planner, operation_ref)
    return resolved[0] if resolved is not None else None


def _matching_order(operation: Mapping[str, Any], order_ref: str) -> tuple[list[Any], int] | None:
    orders = operation.get("operational_orders")
    if not isinstance(orders, list):
        return None
    for index in range(len(orders) - 1, -1, -1):
        row = orders[index]
        if isinstance(row, Mapping) and str(row.get("order_ref", "")) == order_ref:
            return orders, index
    return None


def _prior_executable_order(orders: list[Any], before_index: int) -> Mapping[str, Any] | None:
    """Return only the order directly displaced by a newly appended directive."""
    if before_index <= 0:
        return None
    row = orders[before_index - 1]
    if not isinstance(row, Mapping):
        return None
    if str(row.get("actionability_status", "")) != _ACTIONABLE:
        return None
    if str(row.get("status", "")) in _TERMINAL_ORDER_STATUSES:
        return None
    return row


def _downgrade_underspecified_qin_order(planner: Any, evidence: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(evidence))
    if str(result.get("kind", "")) != "player_command_operational_order_issued":
        return result
    if str(result.get("issuer_ref", "")) != "state_qin":
        return result

    operation_ref = str(result.get("operation_ref", ""))
    order_ref = str(result.get("order_ref", ""))
    if not operation_ref or not order_ref:
        return result
    path = _operation_path(planner, operation_ref)
    if path is None:
        return result

    raw_operation = planner.read(path)
    if not isinstance(raw_operation, Mapping):
        return result
    operation = copy.deepcopy(dict(raw_operation))
    matched = _matching_order(operation, order_ref)
    if matched is None:
        return result
    orders, index = matched
    order = copy.deepcopy(dict(orders[index]))

    # Only an explicit staff/operation owner may certify actionability. Do not
    # infer it from broad world-arc targets such as a state, court actor, or arc
    # driver because those are strategic metadata, not marching instructions.
    if str(order.get("actionability_status", "")) == _ACTIONABLE:
        return result

    strategic_target = order.get("target_ref")
    if isinstance(strategic_target, str) and strategic_target:
        order["strategic_pressure_target_ref"] = strategic_target
    order["status"] = _PENDING_ORDER_STATUS
    order["actionability_status"] = _PENDING
    orders[index] = order
    operation["operational_orders"] = orders

    # A strategic directive is real and remains in order history, but staff
    # latency must not revoke an already executable mission. Preserve the newest
    # prior actionable order until this exact directive receives a concrete
    # packet. If no executable predecessor exists, retain the historical
    # fail-closed behavior and make the pending directive current.
    prior = _prior_executable_order(orders, index)
    if isinstance(prior, Mapping):
        prior_ref = str(prior.get("order_ref", ""))
        if prior_ref:
            operation["last_operational_order_ref"] = prior_ref
            prior_status = str(prior.get("status", ""))
            if prior_status:
                operation["order_status"] = prior_status
        else:
            operation["order_status"] = _PENDING_OPERATION_STATUS
            operation["last_operational_order_ref"] = order_ref
    else:
        operation["order_status"] = _PENDING_OPERATION_STATUS
        operation["last_operational_order_ref"] = order_ref
    planner.put(path, operation)

    result["actionability_status"] = _PENDING
    result["order_status"] = _PENDING_OPERATION_STATUS
    result["movement_committed"] = False
    result["tactical_decision_committed"] = False
    if isinstance(strategic_target, str) and strategic_target:
        result["strategic_pressure_target_ref"] = strategic_target
    return result


class QinOperationalOrderGuardMixin:
    """Keep under-specified autonomous Qin directives non-executable."""

    def _priority_operation_evidence(self, *args: Any, **kwargs: Any) -> Any:
        evidence = super()._priority_operation_evidence(*args, **kwargs)
        if not isinstance(evidence, Mapping):
            return evidence
        return _downgrade_underspecified_qin_order(self, evidence)


__all__ = ["QinOperationalOrderGuardMixin"]
