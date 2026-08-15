"""Read-only helpers for explicit gameplay transaction invalidations.

Invalidation records are provenance, not a second mutable campaign authority.
They identify committed transactions that must not continue to project as live
player intent after an explicit state repair restored an earlier revision.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_INVALIDATIONS_PATH = "runtime/contracts/transaction-invalidations.json"


def _read_optional(reader: Any, path: str) -> Any:
    try:
        if hasattr(reader, "read"):
            return reader.read(path)
        return reader.read_json(path)
    except (FileNotFoundError, KeyError, OSError, ValueError):
        return None


def invalidated_request_ids(reader: Any, campaign_id: str | None = None) -> set[str]:
    """Return exact invalidated request IDs, optionally scoped to one campaign."""
    doc = _read_optional(reader, _INVALIDATIONS_PATH)
    records = doc.get("records", []) if isinstance(doc, Mapping) else []
    if not isinstance(records, list):
        raise ValueError("transaction invalidation registry is invalid")
    values: set[str] = set()
    for row in records:
        if not isinstance(row, Mapping):
            raise ValueError("transaction invalidation record is invalid")
        if campaign_id is not None and row.get("campaign_id") != campaign_id:
            continue
        request_id = row.get("request_id")
        if isinstance(request_id, str) and request_id:
            values.add(request_id)
    return values


__all__ = ["invalidated_request_ids"]
