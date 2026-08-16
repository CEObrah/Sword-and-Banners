"""Keep Great Bow Guard readiness events inside the closed causal-event schema.

The readiness lifecycle persists rich numeric details in their authoritative House,
formation, recruitment and inventory owners.  The causal event is only the player-
visible delivery envelope.  Do not duplicate owner fields onto that closed event
record: staged transaction validation correctly rejects unknown properties.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sword_runtime.causal_event_store import read_causal_event_owner, write_causal_event_owner

_GBG_KIND = "great_bow_guard_field_readiness"
_DUPLICATE_OWNER_FIELDS = (
    "formation_ref",
    "great_bow_guard_stats",
    "issued_loadout_items",
    "remaining_shortfalls",
)


def sanitize_great_bow_guard_readiness_event(planner: Any, event_ref: str) -> bool:
    """Remove only GBG owner-detail fields that the event schema does not own."""
    if not event_ref:
        return False
    _path, owner = read_causal_event_owner(planner)
    events = owner.get("causal_events", {})
    event = events.get(event_ref) if isinstance(events, Mapping) else None
    if not isinstance(event, dict) or str(event.get("process_kind", "")) != _GBG_KIND:
        return False
    changed = False
    for key in _DUPLICATE_OWNER_FIELDS:
        if key in event:
            event.pop(key, None)
            changed = True
    if changed:
        write_causal_event_owner(planner, owner)
    return changed


class GreatBowGuardReadinessEventSchemaMixin:
    """Sanitize the readiness delivery event before staged validation runs."""

    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        if host.get("kind") != _GBG_KIND:
            return super()._run_due_host(host, due_text)
        super()._run_due_host(host, due_text)
        sanitize_great_bow_guard_readiness_event(self, str(host.get("readiness_event_ref", "")))


__all__ = ["GreatBowGuardReadinessEventSchemaMixin", "sanitize_great_bow_guard_readiness_event"]
