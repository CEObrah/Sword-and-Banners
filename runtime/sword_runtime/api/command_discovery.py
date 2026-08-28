"""Demand-loaded semantic-command discovery for the public MCP handoff.

The engine deliberately keeps strict per-operation command enums. Ordinary live
context should not pay to transmit every one of those internal operation names or
payload schemas. It advertises compact intent families; the GM opens one family,
then fetches one exact command contract.

The compact handoff also removes redundant copies of information that remain
available through exact reads. Decision-bearing scene, command, campaign, and
formation facts stay hot; duplicate ceremony, historical briefing prose, detailed
road geometry, and inspectable subordinate records are demand-loaded instead.
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
    """Keep decision-bearing campaign facts while dropping transport-heavy detail."""
    out = _pick(
        planning,
        (
            "kind", "strategic_target_ref", "strategic_target_name",
            "campaign_region_ref", "campaign_region_name",
            "authority_rule", "capacity_rule", "knowledge_rule",
        ),
    )
    scheme = planning.get("campaign_scheme")
    if isinstance(scheme, Mapping):
        compact_scheme = _pick(
            scheme,
            (
                "kind", "status", "campaign_scope_kind", "campaign_region_ref",
                "campaign_region_name", "geography_region_name",
                "strategic_anchor_ref", "strategic_anchor_name",
                "primary_objective_ref", "primary_objective_name",
                "concentration_mode", "objective_count", "state_owned_planned_strength",
                "excluded_non_state_strength", "operational_end_state",
                "authority_rule", "ownership_rule",
            ),
        )
        compact_scheme["objectives"] = _compact_mapping_rows(
            scheme.get("objectives"),
            (
                "objective_ref", "objective_name", "priority", "kind", "fortified",
                "regional_role", "axis_role", "assigned_command_refs",
                "assigned_commanders", "assigned_strength",
            ),
        )
        hierarchy = scheme.get("command_hierarchy")
        if isinstance(hierarchy, Mapping):
            hierarchy_out = _pick(
                hierarchy,
                (
                    "kind", "root_role", "subordinate_command_refs",
                    "main_body_command_refs", "strategic_reserve_command_refs",
                    "state_owned_strength", "subordination_rule", "separation_rule",
                ),
            )
            hierarchy_out["operational_detachments"] = _compact_mapping_rows(
                hierarchy.get("operational_detachments"),
                (
                    "command_ref", "commander_name", "objective_ref", "objective_name",
                    "personnel", "detachment_basis",
                ),
            )
            compact_scheme["command_hierarchy"] = hierarchy_out
        compact_scheme["command_assignments"] = _compact_mapping_rows(
            scheme.get("command_assignments"),
            (
                "command_ref", "commander_ref", "commander_name", "personnel", "role",
                "objective_ref", "objective_name",
            ),
        )
        compact_scheme["strategic_reserve_commands"] = _compact_mapping_rows(
            scheme.get("strategic_reserve_commands"),
            ("command_ref", "commander_ref", "commander_name", "personnel", "role"),
        )
        out["campaign_scheme"] = compact_scheme

    out["command_routes"] = _compact_mapping_rows(
        planning.get("command_routes"),
        (
            "command_ref", "commander_name", "role", "strength", "origin_ref",
            "origin_name", "objective_ref", "objective_name", "duration_hours", "path_names",
        ),
    )
    out["shared_bottlenecks"] = _compact_mapping_rows(
        planning.get("shared_bottlenecks"),
        (
            "route_ref", "from_name", "to_name", "daily_troop_throughput",
            "daily_wagon_throughput", "command_refs", "objective_refs",
            "combined_strength", "minimum_troop_clearance_days_floor",
        ),
    )
    return out


def _compact_identity_awareness(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    out = _pick(value, ("status", "known_fact_classes"))
    return out or None


def _compact_scene_people(value: Any) -> list[dict[str, Any]]:
    rows = _compact_mapping_rows(
        value,
        ("person_id", "name", "role", "location", "scene_basis"),
    )
    source_rows = value if isinstance(value, list) else []
    for out, source in zip(rows, [row for row in source_rows if isinstance(row, Mapping)]):
        awareness = _compact_identity_awareness(source.get("player_identity_awareness"))
        if awareness:
            out["player_identity_awareness"] = awareness
    return rows


def _compact_scene(scene: Mapping[str, Any], root_session: Any) -> dict[str, Any]:
    out = dict(scene)
    local_session = scene.get("active_scene_session")
    if isinstance(local_session, Mapping) and isinstance(root_session, Mapping):
        if local_session.get("session_ref") == root_session.get("session_ref"):
            out.pop("active_scene_session", None)
            out["active_scene_session_ref"] = local_session.get("session_ref")

    physical = scene.get("physical_scene")
    if isinstance(physical, Mapping):
        physical_out = dict(physical)
        refs = physical.get("controlled_formation_refs_at_player_location")
        if isinstance(refs, list):
            physical_out.pop("controlled_formation_refs_at_player_location", None)
            physical_out["controlled_formation_count_at_player_location"] = len(refs)
        out["physical_scene"] = physical_out

    cast = scene.get("scene_cast")
    if isinstance(cast, Mapping):
        cast_out = dict(cast)
        present = _compact_scene_people(cast.get("present_people"))
        visible = _compact_scene_people(cast.get("visible_people"))
        nearby = _compact_scene_people(cast.get("nearby_people"))
        referenced = _compact_scene_people(cast.get("referenced_people"))
        cast_out["present_people"] = present
        present_ids = [row.get("person_id") for row in present]
        visible_ids = [row.get("person_id") for row in visible]
        if visible_ids == present_ids:
            cast_out.pop("visible_people", None)
            cast_out["visible_people_same_as_present"] = True
        else:
            cast_out["visible_people"] = visible
        cast_out["nearby_people"] = nearby
        cast_out["referenced_people"] = referenced
        out["scene_cast"] = cast_out
    return out


def _compact_enemy_intelligence(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    out = _pick(
        value,
        (
            "estimated_strength_low", "estimated_strength_high", "reported_formation_count",
            "confidence_milli", "basis", "contact_status", "confirmed_contact",
        ),
    )
    out["reported_commanders"] = _compact_mapping_rows(
        value.get("reported_commanders"),
        ("person_ref", "name", "confidence_milli"),
    )
    return out


def _compact_campaign_context(value: Mapping[str, Any], *, live_scheme: bool) -> dict[str, Any]:
    if not live_scheme:
        return dict(value)
    out = _pick(
        value,
        (
            "arc_ref", "target_state_ref", "own_strength", "own_assigned_strength",
            "own_auxiliary_strength", "own_location_refs", "friendly_total_strength",
            "campaign_commander_ref", "campaign_commander_name", "coordination_authority_ref",
        ),
    )
    participants = value.get("other_friendly_participants")
    if isinstance(participants, list):
        out["other_friendly_participant_count"] = len(participants)
    area = value.get("operational_area")
    if isinstance(area, Mapping):
        out["operational_area"] = _pick(
            area,
            (
                "destination_ref", "destination_name", "strategic_target_ref",
                "strategic_target_name", "target_state_ref", "hostile_entry_authorized",
                "entry_status", "route_hours_from_current_assembly",
            ),
        )
    enemy = _compact_enemy_intelligence(value.get("enemy_intelligence"))
    if enemy:
        out["enemy_intelligence"] = enemy
    return out


def _compact_operational_order(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    out = _pick(
        value,
        (
            "order_ref", "issued_at", "issuer_ref", "arc_ref", "status",
            "actionability_status", "follow_on_requirement", "superior_commander_ref",
            "coordination_authority_ref",
        ),
    )
    packet = value.get("mission_packet")
    if isinstance(packet, Mapping):
        out["mission_packet"] = _pick(
            packet,
            (
                "agency_rule", "entry_status", "hostile_entry_authorized", "mission_phase",
                "next_phase_trigger", "strategic_target_name", "strategic_target_ref",
                "success_condition",
            ),
        )
    return out


def _compact_war_council(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    return _pick(
        value,
        (
            "event_ref", "status", "held_at", "scheduled_at", "soft_end_at",
            "scene_session_ref", "forum_kind", "court_state_ref",
        ),
    )


def _compact_superior_directive(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    return _pick(
        value,
        (
            "directive_ref", "directive_text", "issued_at", "issuer_ref",
            "issuing_commander_ref", "kind", "status", "base_operational_order_ref",
            "coordination_authority_ref",
        ),
    )


def _compact_campaign_command(value: Mapping[str, Any], operational_order: Any) -> tuple[dict[str, Any], bool]:
    out = dict(value)
    planning = value.get("march_planning")
    live_scheme = isinstance(planning, Mapping) and isinstance(planning.get("campaign_scheme"), Mapping)
    if isinstance(planning, Mapping):
        out["march_planning"] = _compact_march_planning(planning)

    council = _compact_war_council(value.get("war_council"))
    if council is not None:
        out["war_council"] = council

    directive = _compact_superior_directive(value.get("current_superior_directive"))
    if directive is not None:
        out["current_superior_directive"] = directive

    superior_order = value.get("current_superior_order")
    if isinstance(superior_order, Mapping):
        superior_ref = superior_order.get("order_ref")
        operation_ref = operational_order.get("order_ref") if isinstance(operational_order, Mapping) else None
        if superior_ref and superior_ref == operation_ref:
            out["current_superior_order"] = {
                "order_ref": superior_ref,
                "same_as_current_operational_order": True,
            }
        else:
            compact_order = _compact_operational_order(superior_order)
            if compact_order is not None:
                out["current_superior_order"] = compact_order

    daily = value.get("daily_cycle")
    if isinstance(daily, Mapping):
        out["daily_cycle"] = _pick(daily, ("status", "paused_campaign_phase", "last_dawn_at", "last_evening_at"))
    if value.get("after_action_reviews") == []:
        out.pop("after_action_reviews", None)
    if value.get("upward_reports") == []:
        out.pop("upward_reports", None)
    return out, live_scheme


def _compact_controlled_operation(operation: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(operation)
    operational_order = operation.get("current_operational_order")
    compact_order = _compact_operational_order(operational_order)
    if compact_order is not None:
        out["current_operational_order"] = compact_order

    campaign_command = operation.get("campaign_command")
    live_scheme = False
    if isinstance(campaign_command, Mapping):
        command_out, live_scheme = _compact_campaign_command(campaign_command, operational_order)
        out["campaign_command"] = command_out

    campaign_context = operation.get("campaign_context")
    if isinstance(campaign_context, Mapping):
        out["campaign_context"] = _compact_campaign_context(campaign_context, live_scheme=live_scheme)
    return out


def _compact_controlled_formations(value: Any) -> list[dict[str, Any]]:
    return _compact_mapping_rows(
        value,
        (
            "formation_ref", "name", "personnel", "location_ref", "status", "mobilized",
            "commander_ref", "command_authority", "readiness", "morale", "cohesion",
            "fatigue", "experience",
        ),
    )


def _compact_controlled_command_groups(value: Any) -> list[dict[str, Any]]:
    return _compact_mapping_rows(
        value,
        (
            "command_group_ref", "display_name", "context", "location_ref", "commander_ref",
            "role_assignments", "active_context_ref", "integrity_status", "direct_units",
            "organizational_state",
        ),
    )


def _compact_retinue_groups(value: Any) -> list[dict[str, Any]]:
    return _compact_mapping_rows(
        value,
        (
            "command_group_ref", "display_name", "context", "commander_ref", "units",
            "active_context_ref", "current_location_ref",
        ),
    )


def _compact_known_information(value: Any, briefing_refs: set[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for source in value:
        if not isinstance(source, Mapping):
            continue
        out = dict(source)
        ref = source.get("information_ref")
        if isinstance(ref, str) and ref in briefing_refs and "claim" in out:
            out.pop("claim", None)
            out["claim_projected_in_controlled_operation"] = True
        rows.append(out)
    return rows


def compact_play_context(context: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(context)
    commands = context.get("commands")
    if isinstance(commands, Mapping):
        result["commands"] = compact_commands(commands)

    controlled = context.get("controlled_operations")
    briefing_refs: set[str] = set()
    if isinstance(controlled, list):
        result["controlled_operations"] = [
            _compact_controlled_operation(row) if isinstance(row, Mapping) else row
            for row in controlled
        ]
        briefing_refs = {
            str(row.get("briefing_information_ref"))
            for row in controlled
            if isinstance(row, Mapping) and isinstance(row.get("briefing_information_ref"), str)
        }

    scene = context.get("scene")
    if isinstance(scene, Mapping):
        result["scene"] = _compact_scene(scene, context.get("active_scene_session"))

    if isinstance(context.get("controlled_formations"), list):
        result["controlled_formations"] = _compact_controlled_formations(context["controlled_formations"])
    if isinstance(context.get("controlled_command_groups"), list):
        result["controlled_command_groups"] = _compact_controlled_command_groups(context["controlled_command_groups"])
    if isinstance(context.get("retinue_command_groups"), list):
        result["retinue_command_groups"] = _compact_retinue_groups(context["retinue_command_groups"])
    if isinstance(context.get("known_information"), list) and briefing_refs:
        result["known_information"] = _compact_known_information(context["known_information"], briefing_refs)

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
