"""Derive lawful hostile-entry authority from exact sovereign campaign orders.

Diplomatic war status and an explicit ``war_intent`` remain first-class sovereign
facts, but they are not the only lawful basis for military entry. Once an exact
sovereign owner has issued an active offensive campaign order against another
sovereign and the owning world arc is already an active operation, requiring a
second synthetic declaration creates an impossible half-state: the state has
ordered the invasion while the movement layer still treats the target as neutral.

This module repairs that boundary without mutating campaign truth during reads.
It projects the already-saved state campaign order as an equivalent entry-authority
record. The projection never creates movement, battle, territorial control,
annexation, treaty terms, or troop ownership changes.
"""
from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from typing import Any

_ACTIVE_OPERATION_STATUSES = frozenset({"planned", "mobilizing", "active", "advancing", "engaged", "occupied"})
_ACTIVE_ARC_STAGES = frozenset({"active_operation", "campaign", "battle", "siege"})
_ACTIVE_AUTHORITY_STATUSES = frozenset({"authorized", "ready", "activated"})
_TERMINAL_ORDER_STATUSES = frozenset({"cancelled", "canceled", "withdrawn", "terminated", "superseded"})


def _reader(source: Any) -> Callable[[str], Any]:
    if callable(source):
        return source
    read = getattr(source, "read", None)
    if callable(read):
        return read
    read_json = getattr(source, "read_json", None)
    if callable(read_json):
        return read_json
    raise TypeError("campaign authority source must provide read/read_json")


def _arc_row(read: Callable[[str], Any], arc_ref: str) -> Mapping[str, Any] | None:
    if not arc_ref:
        return None
    registry = read("state/arc/kingdom-arcs.json")
    if not isinstance(registry, Mapping):
        return None
    # Current campaign saves use ``records``/``record_id`` while older fixtures
    # and some generated registries use ``arcs``/``arc_ref``. Both shapes encode
    # the same exact arc owner and must be read without rewriting campaign state.
    for key in ("arcs", "records"):
        rows = registry.get(key)
        if isinstance(rows, Mapping):
            row = rows.get(arc_ref)
            if isinstance(row, Mapping):
                return row
            continue
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            identity = (
                row.get("arc_ref")
                or row.get("record_id")
                or row.get("id")
                or row.get("label")
            )
            if str(identity or "") == arc_ref:
                return row
    return None


def _arc_is_active_campaign(read: Callable[[str], Any], arc_ref: str) -> bool:
    row = _arc_row(read, arc_ref)
    if not isinstance(row, Mapping):
        return False
    facts = row.get("facts") if isinstance(row.get("facts"), Mapping) else {}
    status = str(facts.get("status", row.get("status", "active"))).strip().lower().replace("_", " ")
    status_tokens = set(status.split())
    if not status_tokens.intersection({"active", "distant", "ongoing"}):
        return False
    stage = str(facts.get("stage", row.get("stage", "")))
    return stage in _ACTIVE_ARC_STAGES


def _latest_order(operation: Mapping[str, Any]) -> Mapping[str, Any] | None:
    orders = operation.get("operational_orders") if isinstance(operation.get("operational_orders"), list) else []
    last_ref = str(operation.get("last_operational_order_ref", ""))
    for row in reversed(orders):
        if not isinstance(row, Mapping):
            continue
        if last_ref and str(row.get("order_ref", "")) != last_ref:
            continue
        return row
    return None


def _foreign_target(
    operation: Mapping[str, Any], order: Mapping[str, Any], sovereign_ref: str
) -> str | None:
    direct = order.get("target_ref")
    if (
        isinstance(direct, str)
        and direct.startswith(("state_", "polity_"))
        and direct != sovereign_ref
    ):
        return direct
    for ref in operation.get("objective_refs", []) if isinstance(operation.get("objective_refs"), list) else []:
        if (
            isinstance(ref, str)
            and ref.startswith(("state_", "polity_"))
            and ref != sovereign_ref
        ):
            return ref
    return None


def projected_campaign_entry_authorities(
    source: Any, sovereign_ref: str
) -> list[dict[str, Any]]:
    """Return exact-order-derived foreign-entry authorities for one sovereign.

    A projection exists only when all structural facts line up: an active saved
    operation, the sovereign is the operation's administrative authority, the
    latest order was issued by that same sovereign, a foreign sovereign target is
    exact, and the linked world arc is already in an active military-operation
    stage. Mere strategic preparation, mobilization without a foreign campaign,
    court discussion, or an NPC's private intention does not qualify.
    """
    if not isinstance(sovereign_ref, str) or not sovereign_ref.startswith(("state_", "polity_")):
        return []
    read = _reader(source)
    try:
        index = read("state/operations/index.json")
    except (FileNotFoundError, KeyError, ValueError):
        return []
    operations = index.get("operations") if isinstance(index, Mapping) else None
    if not isinstance(operations, Mapping):
        return []

    authorities: list[dict[str, Any]] = []
    for operation_ref, path in sorted(operations.items()):
        if not isinstance(operation_ref, str) or not isinstance(path, str):
            continue
        try:
            operation = read(path)
        except (FileNotFoundError, KeyError, ValueError):
            continue
        if (
            not isinstance(operation, Mapping)
            or str(operation.get("status", "")) not in _ACTIVE_OPERATION_STATUSES
        ):
            continue
        owner = str(
            operation.get("institutional_owner_ref")
            or operation.get("administrative_authority")
            or ""
        )
        authorities_list = (
            operation.get("administrative_authorities")
            if isinstance(operation.get("administrative_authorities"), list)
            else []
        )
        if owner != sovereign_ref and sovereign_ref not in {
            str(ref) for ref in authorities_list if isinstance(ref, str)
        }:
            continue
        order = _latest_order(operation)
        if not isinstance(order, Mapping) or str(order.get("issuer_ref", "")) != sovereign_ref:
            continue
        if str(order.get("status", "")) in _TERMINAL_ORDER_STATUSES:
            continue
        target_ref = _foreign_target(operation, order, sovereign_ref)
        if not target_ref:
            continue
        arc_ref = str(order.get("arc_ref") or operation.get("campaign_arc_ref") or "")
        if not arc_ref:
            arc_ref = next(
                (
                    str(ref)
                    for ref in operation.get("objective_refs", [])
                    if isinstance(ref, str) and ref.startswith("arc_")
                ),
                "",
            )
        if not _arc_is_active_campaign(read, arc_ref):
            continue
        order_ref = str(order.get("order_ref", ""))
        authorities.append(
            {
                "intent_ref": f"projected_campaign_entry:{operation_ref}:{target_ref}",
                "target_ref": target_ref,
                "status": "authorized",
                "kind": "exact_state_campaign_order_entry_authority",
                "authorized_by": order_ref or sovereign_ref,
                "authorized_at": order.get("issued_at") or operation.get("created_at"),
                "operation_ref": operation_ref,
                "order_ref": order_ref or None,
                "arc_ref": arc_ref,
                "projection_only": True,
                "authority_rule": (
                    "an exact sovereign-issued active foreign campaign order is a lawful hostile-entry basis; "
                    "this projection does not itself move forces or change formal diplomacy"
                ),
            }
        )
    return authorities


def hostile_entry_authorized(
    source: Any, friendly_state: str | None, target_state: str | None
) -> bool:
    """Return whether exact sovereign facts provide lawful hostile entry."""
    if not friendly_state or not target_state or friendly_state == target_state:
        return False
    read = _reader(source)
    key = (
        friendly_state.removeprefix("state_")
        if friendly_state.startswith("state_")
        else friendly_state
    )
    state_path = f"state/states/{key}.json" if friendly_state.startswith("state_") else None
    state: Mapping[str, Any] = {}
    if state_path:
        try:
            raw = read(state_path)
            state = raw if isinstance(raw, Mapping) else {}
        except (FileNotFoundError, KeyError, ValueError):
            state = {}
    diplomacy = state.get("diplomacy") if isinstance(state.get("diplomacy"), Mapping) else {}
    relation = diplomacy.get(target_state) if isinstance(diplomacy, Mapping) else None
    if isinstance(relation, Mapping) and str(relation.get("status", "")) == "war":
        return True
    for intent in state.get("war_intents", []) if isinstance(state.get("war_intents"), list) else []:
        if not isinstance(intent, Mapping):
            continue
        if (
            str(intent.get("target_ref", "")) == target_state
            and str(intent.get("status", "")) in _ACTIVE_AUTHORITY_STATUSES
        ):
            return True
    return any(
        row.get("target_ref") == target_state
        for row in projected_campaign_entry_authorities(read, friendly_state)
    )


def project_sovereign_document(
    source: Any, sovereign_ref: str, document: Mapping[str, Any]
) -> dict[str, Any]:
    """Return a non-persistent sovereign view with exact campaign authority added.

    Existing diplomacy and war intents are untouched. Derived entries are added
    only to the returned copy so mechanics that already honor authorized war intents
    also honor an equivalent exact state campaign order. This avoids a read-time
    mutation and keeps formal diplomacy distinct from campaign-entry authority.
    """
    projected = copy.deepcopy(dict(document))
    if not sovereign_ref.startswith("state_"):
        return projected
    intents = projected.get("war_intents")
    if not isinstance(intents, list):
        intents = []
    else:
        intents = copy.deepcopy(intents)
    active_targets = {
        str(row.get("target_ref"))
        for row in intents
        if isinstance(row, Mapping)
        and str(row.get("status", "")) in _ACTIVE_AUTHORITY_STATUSES
    }
    for row in projected_campaign_entry_authorities(source, sovereign_ref):
        target = str(row.get("target_ref", ""))
        if target and target not in active_targets:
            intents.append(row)
            active_targets.add(target)
    projected["war_intents"] = intents
    return projected


def operation_entry_projection(
    source: Any,
    operation: Mapping[str, Any],
    campaign_context: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return a bounded player-safe correction for a stale entry-authority gate."""
    owner = str(
        operation.get("institutional_owner_ref")
        or operation.get("administrative_authority")
        or ""
    )
    if not owner.startswith("state_"):
        return None
    order = _latest_order(operation)
    if not isinstance(order, Mapping):
        return None
    target = None
    if isinstance(campaign_context, Mapping):
        target_value = campaign_context.get("target_state_ref")
        if isinstance(target_value, str):
            target = target_value
    if not target:
        target = _foreign_target(operation, order, owner)
    if not target or not hostile_entry_authorized(source, owner, target):
        return None
    derived = next(
        (
            row
            for row in projected_campaign_entry_authorities(source, owner)
            if row.get("target_ref") == target
        ),
        None,
    )
    return {
        "authorized": True,
        "entry_status": "authorized",
        "target_state_ref": target,
        "basis": "state_campaign_order" if isinstance(derived, Mapping) else "war_or_explicit_intent",
        "operation_ref": derived.get("operation_ref") if isinstance(derived, Mapping) else None,
        "order_ref": derived.get("order_ref") if isinstance(derived, Mapping) else None,
        "arc_ref": derived.get("arc_ref") if isinstance(derived, Mapping) else None,
        "projection_only": True,
    }


__all__ = [
    "hostile_entry_authorized",
    "operation_entry_projection",
    "project_sovereign_document",
    "projected_campaign_entry_authorities",
]
