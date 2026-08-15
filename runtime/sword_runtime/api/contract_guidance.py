"""Player-facing MCP contract guidance that depends on composed runtime behavior.

Static command guidance covers ordinary payload ranges.  This module adds the
cross-command sequencing rules that are easy to lose when a natural-language
wait also carries an explicit standing activity.
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
        "credit is earned only through the campaign time actually reached; stop_on_player_event may end the interval early"
    ),
    "settlement_rule": (
        "after the time advance commits, consume earned whole-hour credit with standing_training_settle for each intended target "
        "before narrating training gains; settlement advances no campaign time"
    ),
}


def enrich_command_contract(command_type: str, contract: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of one public contract with cross-command guidance attached."""
    result = dict(contract)
    if command_type != "advance_time":
        return result
    guidance = dict(result.get("input_guidance", {})) if isinstance(result.get("input_guidance"), Mapping) else {}
    guidance["activity_policy"] = dict(_ADVANCE_TIME_ACTIVITY_POLICY)
    result["input_guidance"] = guidance
    return result


__all__ = ["enrich_command_contract"]
