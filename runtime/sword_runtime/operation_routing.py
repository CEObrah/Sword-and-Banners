"""Identity-checked routing for exact campaign operation owners.

``state/operations/index.json`` is a bounded routing/cache owner.  It may help
locate an operation but it may never substitute another operation, erase an
exact owner when one cache entry is missing, or become the source of operation
identity.  Resolve through the authoritative owner index first and validate the
saved operation's own identity on every fallback.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any, Iterator

_OPERATION_INDEX = "state/operations/index.json"
_OWNER_INDEX = "state/index/owner-index.json"


def _read_routing_optional(source: Any, path: str) -> Any | None:
    """Read a non-authoritative routing document with planner-local reuse."""
    fn = getattr(source, "routing_document_optional", None)
    if callable(fn):
        try:
            return fn(path)
        except (FileNotFoundError, KeyError, ValueError):
            return None
    return _read_optional(source, path)


def _read_optional(source: Any, path: str) -> Any | None:
    if callable(source):
        try:
            return source(path)
        except (FileNotFoundError, KeyError, ValueError):
            return None
    fn = getattr(source, "read_optional", None)
    if callable(fn):
        try:
            return fn(path)
        except (FileNotFoundError, KeyError, ValueError):
            return None
    fn = getattr(source, "read", None)
    if callable(fn):
        try:
            return fn(path)
        except (FileNotFoundError, KeyError, ValueError):
            return None
    raise TypeError("operation routing requires bounded read access")


def _validated_operation(row: Any, operation_ref: str) -> dict[str, Any] | None:
    if not isinstance(row, Mapping) or str(row.get("schema") or "") != "sword-operation":
        return None
    if str(row.get("operation_ref") or "") != operation_ref:
        return None
    owner_id = row.get("owner_id")
    if owner_id not in (None, "", operation_ref):
        return None
    return dict(row)


def operational_order_slot(operation: Mapping[str, Any], order_ref: object) -> tuple[list[Any], int] | None:
    """Resolve one order-history row by exact identity, failing closed on duplicates."""
    if not isinstance(order_ref, str) or not order_ref:
        return None
    rows = operation.get("operational_orders")
    if not isinstance(rows, list):
        return None
    found: tuple[list[Any], int] | None = None
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or str(row.get("order_ref", "")) != order_ref:
            continue
        if found is not None:
            return None
        found = (rows, index)
    return found


def operational_order_by_ref(operation: Mapping[str, Any], order_ref: object) -> Mapping[str, Any] | None:
    """Return one uniquely identified order-history row without collection-order semantics."""
    slot = operational_order_slot(operation, order_ref)
    if slot is None:
        return None
    rows, index = slot
    row = rows[index]
    return row if isinstance(row, Mapping) else None


def current_operational_order_slot(operation: Mapping[str, Any]) -> tuple[list[Any], int] | None:
    """Resolve the one explicitly current operational order by exact identity.

    ``operational_orders`` is durable history, not an implicit current-order stack.
    Collection position therefore has no authority. A missing pointer, a pointer
    that does not resolve, or duplicate rows for the pointed identity all fail
    closed instead of falling back to the history tail.
    """
    return operational_order_slot(operation, operation.get("last_operational_order_ref"))


def current_operational_order(operation: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Return the explicitly current order, never the newest historical row."""
    slot = current_operational_order_slot(operation)
    if slot is None:
        return None
    rows, index = slot
    row = rows[index]
    return row if isinstance(row, Mapping) else None


def append_operational_order(operation: dict[str, Any], order: Mapping[str, Any]) -> str:
    """Append one exact order to operation-local durable history.

    Order history is identity-bearing evidence. Writers may not silently trim it,
    replace an existing identity, or make collection position carry current-order
    authority. Current identity is changed separately through
    ``last_operational_order_ref`` at the lawful lifecycle boundary.
    """
    order_ref = order.get("order_ref")
    if not isinstance(order_ref, str) or not order_ref:
        raise ValueError("operational order requires a non-empty order_ref")
    rows = operation.setdefault("operational_orders", [])
    if not isinstance(rows, list):
        raise ValueError("operation operational_orders must be a list")
    if any(isinstance(row, Mapping) and str(row.get("order_ref", "")) == order_ref for row in rows):
        raise ValueError(f"duplicate operational order identity: {order_ref}")
    rows.append(copy.deepcopy(dict(order)))
    operation["operational_orders"] = rows
    return order_ref


def exact_operation_record(source: Any, operation_ref: str) -> tuple[str, dict[str, Any]] | None:
    """Resolve one exact operation by identity, never by route alone."""
    if not isinstance(operation_ref, str) or not operation_ref:
        return None
    candidates: list[str] = []
    owner_index = _read_routing_optional(source, _OWNER_INDEX)
    owners = owner_index.get("owners", {}) if isinstance(owner_index, Mapping) else {}
    owner_path = owners.get(operation_ref) if isinstance(owners, Mapping) else None
    if isinstance(owner_path, str) and owner_path:
        candidates.append(owner_path.split("#", 1)[0])

    routing = _read_routing_optional(source, _OPERATION_INDEX)
    routes = routing.get("operations", {}) if isinstance(routing, Mapping) else {}
    routed = routes.get(operation_ref) if isinstance(routes, Mapping) else None
    if isinstance(routed, str) and routed:
        candidates.append(routed.split("#", 1)[0])

    # Canonical path is only a final compatibility fallback.  Identity inside
    # the owner must still match exactly.
    candidates.append(f"state/operations/{operation_ref}.json")

    seen: set[str] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        row = _validated_operation(_read_optional(source, path), operation_ref)
        if row is not None:
            return path, row
    return None


def iter_exact_operation_records(source: Any) -> Iterator[tuple[str, str, dict[str, Any]]]:
    """Enumerate exact operations through bounded identity refs.

    The owner index is primary.  The secondary operation index contributes only
    compatibility candidate refs, after which every row is identity-checked.
    This is bounded by already-registered operation owners and never scans the
    repository filesystem.
    """
    refs: set[str] = set()
    owner_index = _read_routing_optional(source, _OWNER_INDEX)
    owners = owner_index.get("owners", {}) if isinstance(owner_index, Mapping) else {}
    if isinstance(owners, Mapping):
        for ref, path in owners.items():
            if isinstance(ref, str) and isinstance(path, str) and path.split("#", 1)[0].startswith("state/operations/"):
                refs.add(ref)
    routing = _read_routing_optional(source, _OPERATION_INDEX)
    routes = routing.get("operations", {}) if isinstance(routing, Mapping) else {}
    if isinstance(routes, Mapping):
        refs.update(str(ref) for ref in routes if isinstance(ref, str) and ref)

    for ref in sorted(refs):
        resolved = exact_operation_record(source, ref)
        if resolved is None:
            continue
        path, row = resolved
        yield ref, path, row


__all__ = [
    "exact_operation_record",
    "iter_exact_operation_records",
    "operational_order_by_ref",
    "operational_order_slot",
    "current_operational_order",
    "current_operational_order_slot",
    "append_operational_order",
]
