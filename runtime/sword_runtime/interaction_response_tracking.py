"""Non-authoritative routing updates when a causal response answers an interaction.

The interaction ledger never owns the response itself. This helper only links an
already-authoritative response event back to the player attempt so current routing
and OOC diagnostics do not mistake an answered request for an orphan.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_LEDGER_PATH = "state/index/interaction-attempts.json"


def _read_optional(store: Any, path: str) -> Any:
    if hasattr(store, "read_optional"):
        return store.read_optional(path)
    if hasattr(store, "read_json"):
        try:
            return store.read_json(path)
        except FileNotFoundError:
            return None
    raise TypeError("interaction response tracker requires a JSON reader")


def mark_interaction_attempt_response(store: Any, attempt_ref: str, *, at: str, response_ref: str) -> bool:
    """Attach one exact causal response pointer to a saved player attempt."""
    if not all(isinstance(value, str) and value for value in (attempt_ref, at, response_ref)):
        raise ValueError("interaction response tracking requires exact non-empty refs")
    ledger = _read_optional(store, _LEDGER_PATH)
    if not isinstance(ledger, Mapping):
        return False
    rows = ledger.get("attempts", [])
    if not isinstance(rows, list):
        return False
    changed = False
    updated: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        if str(row.get("event_id", "")) == attempt_ref:
            prior = row.get("response_ref")
            if prior not in (None, response_ref):
                raise ValueError("interaction attempt already points to a different response")
            if prior != response_ref or row.get("resolved_at") != at:
                row["response_ref"] = response_ref
                row["resolved_at"] = at
                if row.get("thread_status") == "open":
                    row["thread_status"] = "answered"
                changed = True
        updated.append(row)
    if changed:
        out = dict(ledger)
        out["attempts"] = updated
        store.put(_LEDGER_PATH, out)
    return changed


__all__ = ["mark_interaction_attempt_response"]
