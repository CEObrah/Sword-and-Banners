"""Generic semantic-wait matching for causally owned player-facing events.

The base downtime matcher intentionally works from player-facing event records.
Some domain events carry their durable causal owner inside the event provenance
rather than duplicating that owner into a top-level ``source_ref`` field.  Hosted
chronology must treat those canonical provenance refs as exact semantic sources
so a standing wait can stop when the requested causal process actually delivers
its result.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_CAUSAL_PROVENANCE_SOURCE_KEYS = (
    "source_owner_ref",
    "source_work_ref",
    "work_ref",
)


class CausalWaitProvenanceMixin:
    """Extend exact wait-source matching through canonical event provenance."""

    @classmethod
    def _event_matches_wait_clause(
        cls,
        event_ref: str,
        event: Mapping[str, Any],
        policy: Mapping[str, Any],
    ) -> bool:
        parent_match = super(CausalWaitProvenanceMixin, cls)._event_matches_wait_clause
        if parent_match(event_ref, event, policy):
            return True

        requested_sources = {
            str(value) for value in policy.get("source_refs", [])
            if isinstance(value, str) and value
        }
        if not requested_sources:
            return False

        provenance = event.get("provenance") if isinstance(event.get("provenance"), Mapping) else {}
        causal_sources = [
            str(provenance[key])
            for key in _CAUSAL_PROVENANCE_SOURCE_KEYS
            if isinstance(provenance.get(key), str) and provenance.get(key)
        ]
        if requested_sources.isdisjoint(causal_sources):
            return False

        # Re-run the existing matcher with one provenance source promoted at a
        # time.  This preserves every other wait criterion (kind, operation,
        # classification, topic) instead of teaching this mixin a second copy of
        # the semantic-wait rules.
        for source_ref in causal_sources:
            if source_ref not in requested_sources:
                continue
            enriched = dict(event)
            enriched["source_ref"] = source_ref
            if parent_match(event_ref, enriched, policy):
                return True
        return False


__all__ = ["CausalWaitProvenanceMixin"]
