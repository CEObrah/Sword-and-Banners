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
        "include activity_policy when the player's declared elapsed-time intent includes standing training; "
        "omitting it means the interval advances without awarding standing-training credit"
    ),
    "fields": {
        "player_standing_training": {
            "type": "boolean",
            "rule": "set true only when Tang Wei is explicitly spending the elapsed interval on his saved standing training plan",
        },
        "formation_refs": {
            "type": "array",
            "maximum_items": 128,
            "rule": (
                "use unique exact controlled formation refs only when those formations are explicitly ordered to train during the interval; "
                "mere co-location, readiness, escort duty, or waiting does not authorize formation training"
            ),
        },
        "household_standing_person_refs": {
            "type": "array",
            "maximum_items": 128,
            "rule": (
                "use exact House Tang people only to accrue their already-saved autonomous standing-role activity; "
                "the player does not choose their focus or immediate skill result"
            ),
        },
    },
    "event_boundary_rule": (
        "credit is earned only through the campaign time actually reached; stop_on_player_event may end the interval early for a true direct "
        "player-facing boundary, while informational campaign-event notices are delivered without stopping the standing order"
    ),
    "settlement_rule": (
        "the same advance_time transaction consumes whole earned credit for explicitly targeted formations and any configured Tang Wei auto-settlement, "
        "leaving only fractional credit banked; standing_training_settle is reserved for pre-existing or manually deferred credit and advances no campaign time"
    ),
}

_TRAVEL_ESCORT_RULE = (
    "optional exact controlled escort formations; all formations must be mobilized and co-located with the player. "
    "Selecting a formation for travel implicitly includes its saved exact top commander plus its aggregate officer structure. "
    "An assigned exact top commander who is detached at another routable location physically musters to the formation before departure; "
    "those muster routes run in parallel and consume the slowest route time once, never teleporting staff. "
    "The column then advances time once under the same derived strategic-supply rules as other field movement; escort travel never creates a separate ration inventory."
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
