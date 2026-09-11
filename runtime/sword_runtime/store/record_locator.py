"""Compact exact-record locators for sharded JSON authorities.

A locator keeps a mutable exact object individually addressable without requiring
one filesystem file per low-resolution record. The base shard remains the only
physical write target; ``#record=...`` selects one exact record inside its
``records`` mapping.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_RECORD_MARKER = "#record="


def make_record_locator(base_path: str, record_id: str) -> str:
    base = str(base_path)
    ref = str(record_id)
    if not base.endswith(".json") or _RECORD_MARKER in base:
        raise ValueError("record locator base must be one JSON path")
    if not ref or _RECORD_MARKER in ref or any(ch in ref for ch in "\r\n"):
        raise ValueError("invalid record locator id")
    return f"{base}{_RECORD_MARKER}{ref}"


def split_record_locator(locator: object) -> tuple[str, str | None]:
    value = str(locator)
    if _RECORD_MARKER not in value:
        return value, None
    base, record_id = value.rsplit(_RECORD_MARKER, 1)
    if not base.endswith(".json") or not record_id:
        raise ValueError("invalid record locator")
    return base, record_id


def record_from_shard(document: Any, record_id: str) -> Any:
    if not isinstance(document, Mapping):
        raise ValueError("record shard must be an object")
    records = document.get("records")
    if not isinstance(records, Mapping):
        raise ValueError("record shard is missing records")
    if record_id not in records:
        raise KeyError(record_id)
    return records[record_id]


def empty_person_lite_shard(shard_id: str) -> dict[str, Any]:
    return {
        "kind": "person_lite_shard",
        "id": str(shard_id),
        "authority": True,
        "count": 0,
        "records": {},
        "rule": "Exact person-lite records are individually addressable through the owner index; the shard is only their compact physical storage container.",
    }
