"""Compact semantic-command discovery for the public MCP handoff.

Rich payload guidance remains available internally and through the dedicated
get_command_contract read.  Ordinary live context carries only intent routing,
command names, and material availability scope so long campaigns do not pay the
full command-schema context cost every turn.
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
    ("formations", ("formation_", "force_assignment", "command_assign", "command_transfer", "resupply")),
    ("training", ("individual_training", "cohort_training", "standing_training_")),
    ("people", ("person_materialize", "health_", "medical_", "career_", "office_", "affiliation_")),
    ("retinue", ("command_group_", "retinue_")),
    ("information", ("information_", "investigation_", "scouting_")),
    ("relationships", ("relationship_", "reputation_", "family_", "commitment_")),
    ("institutions", ("institution_", "house_", "commission_", "sword_manor_")),
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


def compact_commands(command_surface: Mapping[str, Any]) -> dict[str, Any]:
    supported = [str(x) for x in command_surface.get("supported_command_types", []) if isinstance(x, str)]
    grouped: dict[str, list[str]] = {}
    for command_type in sorted(set(supported)):
        grouped.setdefault(command_domain(command_type), []).append(command_type)
    result: dict[str, Any] = {
        "supported_command_types": sorted(set(supported)),
        "intent_domains": grouped,
        "contract_lookup": "Call get_command_contract for the one selected command before preview.",
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


def compact_play_context(context: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(context)
    commands = context.get("commands")
    if isinstance(commands, Mapping):
        result["commands"] = compact_commands(commands)
    return result


__all__ = ["command_domain", "compact_commands", "compact_play_context"]
