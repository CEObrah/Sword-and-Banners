"""Bounded player-safe command input guidance.

These records expose exact enum/range constraints that are useful for natural-
language command construction without exposing hidden campaign state. They are
not a replacement for runtime validation. Exact object/person references must
still come from fresh play context or bounded inspection.
"""
from __future__ import annotations

from typing import Any, Mapping


COMMAND_INPUT_GUIDANCE: Mapping[str, Mapping[str, Any]] = {
    "advance_time": {
        "rule": "provide exactly one of hours or target_time",
        "hours": {"type": "integer", "minimum": 1, "maximum": 876000},
        "target_time": {"type": "campaign_time", "rule": "not earlier than current world time and no more than 100 years ahead"},
    },
    "travel": {
        "mode": {"allowed_values": ["foot", "horse"], "default": "foot"},
        "destination_ref": {"rule": "use an exact player-known registered location ref"},
        "formation_refs": {"type": "array", "minimum_items": 1, "maximum_items": 128, "rule": "optional exact controlled escort formations; all must be mobilized and co-located with the player; the column advances time once and draws only minimum route grain/fodder from a co-located lawful material depot when carried supply is short"},
    },
    "individual_training": {"hours": {"type": "integer", "minimum": 1, "maximum": 12}},
    "cohort_training": {"hours": {"type": "integer", "minimum": 1, "maximum": 12}},
    "formation_train": {
        "hours": {"type": "integer", "minimum": 1, "maximum": 12},
        "formation_ref": {"rule": "use an exact controlled formation ref"},
    },
    "formation_mobilize": {
        "rule": "provide exactly one of formation_ref or formation_refs",
        "formation_ref": {"rule": "use one exact controlled formation ref"},
        "formation_refs": {"type": "array", "minimum_items": 1, "maximum_items": 128, "rule": "use unique exact controlled formation refs; grouped formations mobilize in parallel and consume the normal mobilization duration once"},
    },
    "health_injury": {"severity": {"allowed_values": ["minor", "moderate", "severe", "critical"], "default": "minor"}},
    "health_recovery": {"hours": {"type": "integer", "minimum": 1, "maximum": 168}},
    "relationship_change": {
        "kind": {"allowed_values": ["trust", "affection", "respect", "fear", "resentment", "loyalty"], "default": "trust"},
        "delta": {"type": "integer", "minimum": -5, "maximum": 5, "forbidden_values": [0]},
        "target_ref": {"rule": "use an exact permitted person ref"},
    },
    "market_purchase": {"quantity": {"type": "integer", "minimum": 1, "maximum": 10000}},
    "market_sell": {"quantity": {"type": "integer", "minimum": 1, "maximum": 10000}},
    "economy_transfer": {
        "direction": {"allowed_values": ["player_to_state", "state_to_player"]},
        "amount_silver": {"type": "integer", "minimum": 1, "maximum": 1000000000},
    },
    "enlisted_service_pay": {"amount_silver": {"type": "integer", "minimum": 1, "maximum": 1000000000, "default": 7}},
    "resupply": {
        "rule": "provide at least one positive requested material quantity",
        "food_kg": {"type": "integer", "minimum": 0, "maximum": 1000000000},
        "fodder_kg": {"type": "integer", "minimum": 0, "maximum": 1000000000},
        "war_arrows": {"type": "integer", "minimum": 0, "maximum": 1000000000},
        "formation_ref": {"rule": "use an exact controlled formation ref"},
    },
    "formation_create": {
        "personnel": {"type": "integer", "minimum": 1, "maximum": 1000000},
        "equipment_units": {"type": "integer", "minimum": 0, "maximum": 1000000},
    },
    "formation_reconstitute": {
        "target_personnel": {"type": "integer", "minimum": 1, "maximum": 1000000, "rule": "must exceed current formation personnel"},
        "equipment_units": {"type": "integer", "minimum": 0, "maximum": 1000000},
        "formation_ref": {"rule": "use an exact controlled formation ref"},
    },
    "formation_split": {
        "personnel": {"type": "integer", "minimum": 1, "maximum": 1000000},
        "formation_ref": {"rule": "use an exact controlled formation ref"},
    },
    "formation_doctrine_set": {
        "doctrine_ref": {"rule": "must be an exact registered doctrine ref; do not guess hidden doctrine IDs"},
        "doctrine_behavior.reserve_commitment": {"type": "integer", "minimum": 0, "maximum": 100},
        "doctrine_behavior.withdrawal_threshold": {"type": "integer", "minimum": 0, "maximum": 100},
        "doctrine_behavior.casualty_tolerance": {"allowed_values": ["low", "moderate", "high", "extreme"]},
    },
    "formation_training_set": {"training_ref": {"rule": "must be an exact registered training-profile ref; do not guess hidden training IDs"}},
    "personal_combat": {
        "duration_minutes": {"type": "integer", "minimum": 5, "maximum": 240, "default": 60},
        "opponent_ref": {"rule": "use an exact permitted person ref"},
    },
    "operation_create": {
        "formation_refs": {"type": "array", "minimum_items": 1, "maximum_items": 128, "rule": "use exact controlled formation refs"},
        "location_ref": {"rule": "use an exact player-known registered location ref"},
    },
    "operation_transition": {"status": {"allowed_values": ["planned", "mobilizing", "active", "engaged", "occupied", "completed", "cancelled"]}},
    "information_create": {
        "claim": {"type": "string", "maximum_length": 4000},
        "knowers": {"type": "array", "minimum_items": 1, "maximum_items": 128, "rule": "use exact person refs; gameplay creation must include the player actor as an exact knower"},
    },
    "state_action": {
        "action": {"allowed_values": ["strategic_goal", "appointment", "enemy_action", "record_threat"], "default": "strategic_goal"},
        "severity": {"type": "integer", "minimum": 0, "maximum": 100, "applies_to": ["enemy_action", "record_threat"]},
    },
    "fortification_materialize": {
        "integrity": {"type": "integer", "minimum": 1, "maximum": 100, "default": 100},
        "food_kg": {"type": "integer", "minimum": 0, "maximum": 1000000000, "default": 0},
        "fodder_kg": {"type": "integer", "minimum": 0, "maximum": 1000000000, "default": 0},
        "garrison_formation_refs": {"type": "array", "minimum_items": 1, "maximum_items": 64},
    },
    "siege_start": {"attacker_formation_refs": {"type": "array", "minimum_items": 1, "maximum_items": 128, "rule": "use exact controlled formation refs"}},
    "siege_action": {
        "action": {"allowed_values": ["blockade", "repair", "assault", "withdraw", "settle", "relief"]},
        "days": {"type": "integer", "minimum": 1, "maximum": 30, "default": 7, "applies_to": ["blockade"]},
        "points": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5, "applies_to": ["repair"]},
        "outcome_rule": "assault damage/outcome is runtime-owned and must not be caller supplied",
    },
    "family_event": {
        "kind": {"accepted_values": ["proposal", "engagement", "marriage", "pregnancy", "birth", "death", "widowhood", "succession_review"]},
        "player_authored_kinds": ["proposal", "engagement", "marriage"],
        "runtime_only_involuntary_kinds": ["pregnancy", "birth", "death", "widowhood", "succession_review"],
        "marriage_rule": "a player-authored marriage requires the player actor to be one marrying party and a previously accepted betrothal; NPC-only marriages remain autonomous/runtime consequences",
    },
    "career_event": {
        "kind": {"allowed_values": ["qualification", "promotion", "appointment", "merit"]},
        "grade": {"allowed_values": ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10"], "applies_to": ["promotion"]},
        "merit": {"type": "integer", "minimum": 1, "maximum": 1000, "applies_to": ["merit"]},
        "player_rule": "career_event is a derived world consequence and is not directly player-authored",
    },
    "mercenary_contract": {
        "action": {"allowed_values": ["offer", "accept", "pay", "deploy", "breach", "renew", "complete"]},
        "amount_silver": {"type": "integer", "minimum": 1, "maximum": 100000000, "applies_to": ["offer", "pay", "renew"]},
        "term_days": {"type": "integer", "minimum": 1, "maximum": 3650, "default": 90, "applies_to": ["offer"]},
        "player_rule": "mercenary acceptance is an autonomous company decision and cannot be player-authored",
    },
    "institution_project": {
        "duration_hours": {"type": "integer", "minimum": 1, "maximum": 8760, "default": 168},
        "magnitude": {"type": "integer", "minimum": 1, "maximum": 1000000, "default": 1},
    },
    "house_action": {
        "action": {"allowed_values": ["assign_duty", "set_policy"], "default": "assign_duty"},
        "subject_ref": {"rule": "assign_duty requires an exact person already within House Tang or Tang Wei personal-retinue authority", "applies_to": ["assign_duty"]},
        "duty": {"type": "string", "maximum_length": 160, "applies_to": ["assign_duty"]},
        "policy_key": {"type": "string", "maximum_length": 120, "applies_to": ["set_policy"]},
        "policy_value": {"type": "string", "maximum_length": 400, "applies_to": ["set_policy"]},
    },
    "scene_consequence": {"summary": {"type": "string", "maximum_length": 4000}},
}


INPUT_GUIDANCE_POLICY = (
    "Exact enum/range constraints are shown where the player-facing runtime can safely advertise them. "
    "Absent constraints remain governed by live validation. Exact person, formation, location, doctrine, "
    "training, operation, institution, mercenary, and other object refs must come from fresh context or "
    "bounded player-visible inspection; never guess hidden IDs."
)


__all__ = ["COMMAND_INPUT_GUIDANCE", "INPUT_GUIDANCE_POLICY"]
