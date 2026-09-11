"""Pure player-safe selection helpers for campaign-command courier reports.

The campaign command owner may retain a mixture of unresolved physical courier
work and delivered report history.  Every consumer that projects "what is still
pending" must use the same priority rule so a response-bearing request cannot
vanish in a later compact layer and delivered history can never be mislabeled as
an active handoff.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

_ROUTINE_PHASES = frozenset({"dawn", "evening"})


def _valid_rows(value: Any) -> list[tuple[int, Mapping[str, Any]]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [(index, row) for index, row in enumerate(value) if isinstance(row, Mapping)]


def is_unresolved_upward_report(row: Mapping[str, Any]) -> bool:
    """Return whether a durable report still lacks confirmed superior receipt."""
    return str(row.get("delivery_status", "")) != "delivered"


def select_pending_upward_reports(value: Any, *, maximum: int = 4) -> list[dict[str, Any]]:
    """Select a bounded unresolved window without losing response-bearing work.

    Priority is response-bearing requests, then non-routine/material reports,
    then routine dawn/evening traffic.  Within a class, the newest reports win.
    Returned rows preserve original chronological order so downstream scene
    consumers can read them naturally.
    """
    maximum = max(0, int(maximum))
    if maximum == 0:
        return []
    pending = [(index, row) for index, row in _valid_rows(value) if is_unresolved_upward_report(row)]
    if not pending:
        return []

    response = [(index, row) for index, row in pending if bool(row.get("follow_on_request_refs"))]
    material = [
        (index, row) for index, row in pending
        if not bool(row.get("follow_on_request_refs"))
        and str(row.get("phase", "")) not in _ROUTINE_PHASES
    ]
    routine = [
        (index, row) for index, row in pending
        if not bool(row.get("follow_on_request_refs"))
        and str(row.get("phase", "")) in _ROUTINE_PHASES
    ]

    selected: list[tuple[int, Mapping[str, Any]]] = []
    remaining = maximum
    for bucket in (response, material, routine):
        if remaining <= 0:
            break
        take = bucket[-remaining:]
        selected.extend(take)
        remaining -= len(take)
    selected.sort(key=lambda item: item[0])
    return [copy.deepcopy(dict(row)) for _, row in selected]


def select_recent_delivered_upward_reports(value: Any, *, maximum: int = 2) -> list[dict[str, Any]]:
    """Return only delivered history, never an active/pending handoff surface."""
    maximum = max(0, int(maximum))
    if maximum == 0:
        return []
    delivered = [row for _, row in _valid_rows(value) if not is_unresolved_upward_report(row)]
    return [copy.deepcopy(dict(row)) for row in delivered[-maximum:]]


def pending_upward_report_count(value: Any) -> int:
    return sum(1 for _, row in _valid_rows(value) if is_unresolved_upward_report(row))


__all__ = [
    "is_unresolved_upward_report",
    "pending_upward_report_count",
    "select_pending_upward_reports",
    "select_recent_delivered_upward_reports",
]
