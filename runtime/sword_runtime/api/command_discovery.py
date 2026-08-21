"""Demand-loaded semantic-command discovery for the public MCP handoff.

The engine deliberately keeps strict per-operation command enums. Ordinary live
context should not pay to transmit every one of those internal operation names or
payload schemas. It advertises compact intent families; the GM opens one family,
then fetches one exact command contract.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_DOMAIN_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("time", ("advance_time", "standing_training_settle")),
    ("interaction", ("interaction_action",)),
    ("travel", ("travel",)),
    ("personal_combat", ("personal_combat", "recover_projectiles")),
    ("warfare", ("battle_", "battlefield_", "siege_", "operation_", "territorial_", "fortification_", "military_")),
    ("formations", ("formation_", "force_assignment", "command_assign", "command_transfer")),
    ("logistics", ("resupply", "army_train_action", "strategic_crossing_action")),
    ("training", ("individual_training", "cohort_training", "standing_training_")),
    ("people", ("person_materialize", "health_", "medical_", "career_", "office_", "affiliation_")),
    ("retinue", ("command_group_", "retinue_")),
    ("information", ("information_", "investigation_", "scouting_")),
    ("relationships", ("relationship_", "reputation_", "family_", "commitment_")),
    ("institutions", ("institution_", "house_", "commission_", "sword_manor_")),
    ("organizations", ("organization_action",)),
    ("custody", ("custody_action",)),
    ("civic", ("settlement_civic_action",)),
    ("population", ("population_", "recruitment_", "recruitment")),
    ("economy", ("market_", "economy_", "enlisted_", "equipment_", "mercenary_")),
    ("statecraft", ("state_", "polity_")),
    ("projects", ("project_",)),
)


def command_domain(command_type: str) -> str:
    for domain, prefixes in _DOMAIN_RULES:
        if any(command_type == prefix or command_type.startswith(prefix) for prefix in prefixes):
            return domain
    return "other"


def grouped_commands(command_surface: Mapping[str, Any]) -> dict[str, list[str]]:
    supported = [str(x) for x in command_surface.get("supported_command_types", []) if isinstance(x, str)]
    grouped: dict[str, list[str]] = {}
    for command_type in sorted(set(supported)):
        grouped.setdefault(command_domain(command_type), []).append(command_type)
    return grouped


def compact_commands(command_surface: Mapping[str, Any]) -> dict[str, Any]:
    grouped = grouped_commands(command_surface)
    result: dict[str, Any] = {
        "intent_families": {
            family: {"operation_count": len(command_types)}
            for family, command_types in sorted(grouped.items())
        },
        "family_count": len(grouped),
        "operation_count": sum(len(v) for v in grouped.values()),
        "family_lookup": "Call get_command_family for the one selected intent family.",
        "contract_lookup": "Then call get_command_contract for the one selected operation before preview.",
    }
    for key in (
        "availability_scope",
        "temporarily_available_command_types",
        "hidden_internal_command_types",
        "input_guidance_policy",
    ):
        if key in command_surface:
            result[key] = command_surface[key]
    return result


def compact_command_family(command_surface: Mapping[str, Any], family: str) -> dict[str, Any]:
    grouped = grouped_commands(command_surface)
    if family not in grouped:
        raise KeyError(family)
    command_types = grouped[family]
    out: dict[str, Any] = {
        "family": family,
        "operation_count": len(command_types),
        "command_types": command_types,
        "contract_lookup": "Call get_command_contract for the one selected operation before preview.",
    }
    temporary = command_surface.get("temporarily_available_command_types")
    if isinstance(temporary, list):
        allowed = {str(x) for x in temporary if isinstance(x, str)}
        out["temporarily_available_command_types"] = [c for c in command_types if c in allowed]
        out["availability_scope"] = command_surface.get("availability_scope", "pending_wake_response")
    return out


def compact_play_context(context: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(context)
    commands = context.get("commands")
    if isinstance(commands, Mapping):
        result["commands"] = compact_commands(commands)
    return result


__all__ = ["command_domain", "grouped_commands", "compact_commands", "compact_command_family", "compact_play_context"]
