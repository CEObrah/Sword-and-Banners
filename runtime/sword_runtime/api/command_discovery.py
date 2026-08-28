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
    ("interaction", ("interaction_action", "scene_session_action")),
    ("travel", ("travel",)),
    ("personal_combat", ("personal_combat", "recover_projectiles")),
    ("warfare", ("battle_", "battlefield_", "siege_", "operation_", "territorial_", "fortification_", "military_")),
    ("formations", ("formation_", "force_assignment", "command_assign", "command_transfer")),
    ("logistics", ("resupply", "strategic_crossing_action")),
    ("training", ("individual_training", "cohort_training", "standing_training_")),
    ("people", ("person_materialize", "health_", "medical_", "career_", "office_", "affiliation_")),
    ("retinue", ("command_group_", "retinue_")),
    ("information", ("information_", "investigation_")),
    ("relationships", ("relationship_", "reputation_", "family_", "commitment_")),
    ("institutions", ("institution_", "house_", "commission_", "inner_walls_")),
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


def _pick(mapping: Mapping[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: mapping.get(key) for key in keys if key in mapping}


def _compact_mapping_rows(value: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_pick(row, keys) for row in value if isinstance(row, Mapping)]


def _compact_march_planning(planning: Mapping[str, Any]) -> dict[str, Any]:
    """Keep decision-bearing campaign facts while dropping transport-heavy detail.

    Full REST/runtime reads retain exact formation membership and segment geometry.
    The ordinary MCP turn carries the hierarchy, objective allocation, reserve,
    route summaries, and real bottlenecks needed to run the council naturally.
    """
    out = _pick(
        planning,
        (
            "kind",
            "strategic_target_ref",
            "strategic_target_name",
            "campaign_region_ref",
            "campaign_region_name",
            "authority_rule",
            "capacity_rule",
            "knowledge_rule",
        ),
    )
    scheme = planning.get("campaign_scheme")
    if isinstance(scheme, Mapping):
        compact_scheme = _pick(
            scheme,
            (
                "kind",
                "status",
                "campaign_scope_kind",
                "campaign_region_ref",
                "campaign_region_name",
                "geography_region_name",
                "strategic_anchor_ref",
                "strategic_anchor_name",
                "primary_objective_ref",
                "primary_objective_name",
                "concentration_mode",
                "objective_count",
                "state_owned_planned_strength",
                "excluded_non_state_strength",
                "operational_end_state",
                "authority_rule",
                "ownership_rule",
            ),
        )
        compact_scheme["objectives"] = _compact_mapping_rows(
            scheme.get("objectives"),
            (
                "objective_ref",
                "objective_name",
                "priority",
                "kind",
                "fortified",
                "regional_role",
                "axis_role",
                "assigned_command_refs",
                "assigned_commanders",
                "assigned_strength",
            ),
        )
        hierarchy = scheme.get("command_hierarchy")
        if isinstance(hierarchy, Mapping):
            hierarchy_out = _pick(
                hierarchy,
                (
                    "kind",
                    "root_role",
                    "subordinate_command_refs",
                    "main_body_command_refs",
                    "strategic_reserve_command_refs",
                    "state_owned_strength",
                    "subordination_rule",
                    "separation_rule",
                ),
            )
            hierarchy_out["operational_detachments"] = _compact_mapping_rows(
                hierarchy.get("operational_detachments"),
                (
                    "command_ref",
                    "commander_name",
                    "objective_ref",
                    "objective_name",
                    "personnel",
                    "detachment_basis",
                ),
            )
            compact_scheme["command_hierarchy"] = hierarchy_out
        assignment_keys = (
            "command_ref",
            "commander_ref",
            "commander_name",
            "personnel",
            "role",
            "objective_ref",
            "objective_name",
        )
        compact_scheme["command_assignments"] = _compact_mapping_rows(
            scheme.get("command_assignments"), assignment_keys
        )
        compact_scheme["strategic_reserve_commands"] = _compact_mapping_rows(
            scheme.get("strategic_reserve_commands"),
            ("command_ref", "commander_ref", "commander_name", "personnel", "role"),
        )
        out["campaign_scheme"] = compact_scheme

    out["command_routes"] = _compact_mapping_rows(
        planning.get("command_routes"),
        (
            "command_ref",
            "commander_name",
            "role",
            "strength",
            "origin_ref",
            "origin_name",
            "objective_ref",
            "objective_name",
            "duration_hours",
            "path_names",
        ),
    )
    out["shared_bottlenecks"] = _compact_mapping_rows(
        planning.get("shared_bottlenecks"),
        (
            "route_ref",
            "from_name",
            "to_name",
            "daily_troop_throughput",
            "daily_wagon_throughput",
            "command_refs",
            "objective_refs",
            "combined_strength",
            "minimum_troop_clearance_days_floor",
        ),
    )
    return out


def _compact_controlled_operation(operation: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(operation)
    campaign_command = operation.get("campaign_command")
    live_scheme = False
    if isinstance(campaign_command, Mapping):
        command_out = dict(campaign_command)
        planning = campaign_command.get("march_planning")
        if isinstance(planning, Mapping):
            command_out["march_planning"] = _compact_march_planning(planning)
            live_scheme = isinstance(planning.get("campaign_scheme"), Mapping)
        out["campaign_command"] = command_out

    campaign_context = operation.get("campaign_context")
    if isinstance(campaign_context, Mapping):
        context_out = dict(campaign_context)
        participants = context_out.get("other_friendly_participants")
        if live_scheme and isinstance(participants, list):
            context_out["other_friendly_participant_count"] = len(participants)
            context_out.pop("other_friendly_participants", None)
        out["campaign_context"] = context_out
    return out


def compact_play_context(context: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(context)
    commands = context.get("commands")
    if isinstance(commands, Mapping):
        result["commands"] = compact_commands(commands)

    controlled = context.get("controlled_operations")
    if isinstance(controlled, list):
        result["controlled_operations"] = [
            _compact_controlled_operation(row) if isinstance(row, Mapping) else row
            for row in controlled
        ]

    # Exact older speech remains demand-loadable through scene history. Four
    # recent attributed lines are enough to preserve the immediate exchange and
    # reclaim the small amount of headroom needed by the stable compact contract.
    history = context.get("recent_scene_history")
    if isinstance(history, list) and len(history) > 4:
        result["recent_scene_history"] = history[-4:]
        result["recent_scene_history_truncated"] = True
    return result


__all__ = [
    "command_domain",
    "grouped_commands",
    "compact_commands",
    "compact_command_family",
    "compact_play_context",
]
