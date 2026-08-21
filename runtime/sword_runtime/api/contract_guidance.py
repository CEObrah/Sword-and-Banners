"""Player-facing MCP contract guidance that depends on composed runtime behavior.

Static command guidance covers ordinary payload ranges. This module adds the
cross-command sequencing rules that are easy to lose when a natural-language
wait carries standing activity or a military travel order carries exact command
staff with the selected formations.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_ADVANCE_TIME_ACTIVITY_POLICY: Mapping[str, Any] = {
    "type": "object",
    "rule": (
        "activity_policy is an optional per-interval override/addition. Tang Wei's persisted automatic standing-training plan continues by default when "
        "his saved activity contract has auto_settle_standing_training=true; callers do not need to restate that routine on every time advance"
    ),
    "fields": {
        "player_standing_training": {
            "type": "boolean",
            "rule": (
                "omit this field to follow Tang Wei's saved automatic standing-training setting; set false to suspend that routine for this interval, "
                "or true to explicitly apply the saved standing plan"
            ),
        },
        "formation_refs": {
            "type": "array",
            "maximum_items": 128,
            "rule": (
                "use unique exact controlled formation refs only when those formations are explicitly ordered to train during the interval; "
                "mere co-location, readiness, escort duty, or waiting does not authorize extra player-directed formation training, and ordinary institutional force development is scheduler-owned"
            ),
        },
        "household_standing_person_refs": {
            "type": "array",
            "maximum_items": 128,
            "rule": (
                "use exact House Tang people only when explicit interim accrual under their already-saved autonomous standing-role activity is required; "
                "their ordinary autonomous activity remains scheduler-owned and the player does not choose their focus or immediate skill result"
            ),
        },
    },
    "autonomy_rule": (
        "advancing chronology automatically settles due Runtime-owned causal work for NPCs, Houses, states, forces, recruitment/development systems, institutions, world arcs, reports, and other registered hosts; "
        "the caller must not enumerate or replay those autonomous actions merely to make the world catch up"
    ),
    "event_boundary_rule": (
        "standing credit is earned only through the campaign time actually reached; stop_on_player_event may end the interval early for a true direct "
        "player-facing boundary, while informational campaign-event notices are delivered without stopping the standing order"
    ),
    "settlement_rule": (
        "the same advance_time transaction consumes whole earned credit for explicitly targeted formations and configured Tang Wei auto-settlement, "
        "leaving only fractional credit banked; standing_training_settle is reserved for pre-existing or manually deferred credit and advances no campaign time"
    ),
}

_TRAVEL_ESCORT_RULE = (
    "optional exact controlled escort formations; all formations must be mobilized and co-located with the player. "
    "Selecting a formation for travel implicitly includes its saved exact commander and deputy plus its aggregate officer structure. "
    "An assigned exact commander/deputy who is detached at another routable location physically musters to the formation before departure; "
    "those muster routes run in parallel and consume the slowest route time once, never teleporting staff. "
    "The column then advances time once and draws only minimum route grain/fodder from a co-located lawful material depot when carried supply is short."
)


def enrich_command_contract(command_type: str, contract: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of one public contract with cross-command guidance attached."""
    result = dict(contract)
    guidance = dict(result.get("input_guidance", {})) if isinstance(result.get("input_guidance"), Mapping) else {}

    if command_type == "advance_time":
        guidance["activity_policy"] = dict(_ADVANCE_TIME_ACTIVITY_POLICY)
        result["input_guidance"] = guidance
        return result

    if command_type == "travel":
        formation_guidance = (
            dict(guidance.get("formation_refs", {}))
            if isinstance(guidance.get("formation_refs"), Mapping)
            else {}
        )
        formation_guidance["rule"] = _TRAVEL_ESCORT_RULE
        guidance["formation_refs"] = formation_guidance
        result["input_guidance"] = guidance
        return result

    return result


__all__ = ["enrich_command_contract"]
