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

from sword_runtime.operational_intent import operational_intent_contract
from sword_runtime.api.gm_scene_context import build_gm_scene_context

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
    families = {
        family: {"operation_count": len(command_types)}
        for family, command_types in sorted(grouped.items())
    }
    result: dict[str, Any] = {
        "mechanic_families": families,
        "catalog_role": "durable mechanics only; never a fictional-action whitelist",
        "scene_only_action_rule": "reversible scene behavior may require no command",
        "intent_orchestration_rule": "Interpret the full natural-language objective first; one player intent and one narrated scene may span several exact consequence operations, with fresh context between writes.",
        "scene_boundary_rule": "Runtime operation boundaries never start or end narrative scenes; gm_scene_context.scene_direction.scene_lifecycle gives the LLM the presentation-session affordance when continuity needs persistence.",
        "family_count": len(grouped),
        "operation_count": sum(len(v) for v in grouped.values()),
        "family_lookup": "For a hard consequence, load only the relevant mechanic family.",
        "contract_lookup": "Then load only the selected operation contract before preview.",
    }
    for key in (
        "availability_scope",
        "temporarily_available_command_types",
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


def _refs(value: Any, maximum: int = 16) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item and item not in out:
            out.append(item)
        if len(out) >= maximum:
            break
    return out


def _text(value: Any, maximum: int = 240) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    return value if len(value) <= maximum else value[: maximum - 3].rstrip() + "..."


def _compact_mapping_rows(value: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_pick(row, keys) for row in value if isinstance(row, Mapping)]


def _compact_narration_guidance(value: Any) -> dict[str, Any] | None:
    """Keep only runtime-varying presentation exceptions in the MCP handoff.

    Stable voice, agency, knowledge-boundary, and choice doctrine belongs to the
    installed GM Skill. Re-sending that prose on every play-context call wastes
    hot context and creates a second place for stable GM procedure to drift.
    """
    if not isinstance(value, Mapping):
        return None
    out: dict[str, Any] = {}
    if "stale_scene_policy" in value:
        out["stale_scene_policy"] = (
            "revision_matched_projection_is_current; continuity_anchor_is_presentation_only"
        )
    if "campaign_entry_authority" in value:
        out["campaign_entry_authority"] = (
            "entry_authority.authorized=true already establishes hostile-entry authority; "
            "new movement, orders, ceasefire, treaty, or war termination still use their owners"
        )
    return out or None


def _compact_march_planning(planning: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only campaign shape hot; route/assignment detail is demand-loaded."""
    out = _pick(
        planning,
        (
            "kind", "strategic_target_ref", "strategic_target_name",
            "campaign_region_ref", "campaign_region_name",
        ),
    )
    scheme = planning.get("campaign_scheme")
    if isinstance(scheme, Mapping):
        compact_scheme = _pick(
            scheme,
            (
                "kind", "status", "campaign_scope_kind", "campaign_region_ref",
                "campaign_region_name", "strategic_anchor_ref", "strategic_anchor_name",
                "primary_objective_ref", "primary_objective_name", "concentration_mode",
                "objective_count", "state_owned_planned_strength", "command_span_planned_strength",
                "non_state_subordinate_strength", "excluded_non_state_strength",
            ),
        )
        compact_scheme["objectives"] = _compact_mapping_rows(
            scheme.get("objectives"),
            ("objective_ref", "objective_name", "priority", "kind", "fortified", "axis_role", "assigned_strength"),
        )[:6]
        hierarchy = scheme.get("command_hierarchy")
        if isinstance(hierarchy, Mapping):
            compact_scheme["command_hierarchy"] = {
                **_pick(hierarchy, ("kind", "root_role", "state_owned_strength", "command_span_strength", "non_state_subordinate_strength")),
                "subordinate_command_count": len(hierarchy.get("subordinate_command_refs") or []),
                "main_body_command_count": len(hierarchy.get("main_body_command_refs") or []),
                "strategic_reserve_command_count": len(hierarchy.get("strategic_reserve_command_refs") or []),
            }
        assignments = scheme.get("command_assignments")
        if isinstance(assignments, list):
            compact_scheme["command_assignment_count"] = len(assignments)
        reserves = scheme.get("strategic_reserve_commands")
        if isinstance(reserves, list):
            compact_scheme["strategic_reserve_command_count"] = len(reserves)
        out["campaign_scheme"] = compact_scheme

    routes = planning.get("command_routes")
    if isinstance(routes, list):
        out["command_route_count"] = len(routes)
    bottlenecks = planning.get("shared_bottlenecks")
    if isinstance(bottlenecks, list):
        out["shared_bottleneck_count"] = len(bottlenecks)
    out["detail_rule"] = "demand_load_exact_operation_for_route_assignment_or_bottleneck_detail"
    return out


def _compact_identity_awareness(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    out = _pick(value, ("status",))
    return out or None


def _compact_scene_people(value: Any) -> list[dict[str, Any]]:
    rows = _compact_mapping_rows(
        value,
        ("person_id", "name", "role"),
    )
    source_rows = value if isinstance(value, list) else []
    for out, source in zip(rows, [row for row in source_rows if isinstance(row, Mapping)]):
        awareness = _compact_identity_awareness(source.get("player_identity_awareness"))
        if awareness:
            out["player_identity_awareness"] = awareness
    return rows


_GM_PRIVATE_BULK_KEYS = frozenset({
    "attributes", "martial_skills", "skills", "capabilities", "equipment_manifest",
    "inventory", "participant_sheets", "focus_participants", "participants",
    "positions", "team_plans", "obstacles", "raw_state", "full_state",
})


def _compact_gm_private_extension(value: Any, *, depth: int = 0) -> Any:
    if depth >= 3:
        if isinstance(value, str):
            return value[:1200]
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        return None
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in list(value.items())[:32]:
            key_text = str(key)
            if key_text in _GM_PRIVATE_BULK_KEYS:
                continue
            compact = _compact_gm_private_extension(item, depth=depth + 1)
            if compact not in (None, {}, []):
                out[key_text] = compact
        return out
    if isinstance(value, list):
        rows = []
        for item in value[:16]:
            compact = _compact_gm_private_extension(item, depth=depth + 1)
            if compact not in (None, {}, []):
                rows.append(compact)
        return rows
    if isinstance(value, tuple):
        return _compact_gm_private_extension(list(value), depth=depth)
    if isinstance(value, str):
        return value[:1200]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return None


def _compact_gm_private_director_context(value: Any) -> Any:
    """Keep private scene direction without embedding full numeric person sheets."""
    if not isinstance(value, Mapping):
        return value
    out = dict(value)
    present_context = value.get("present_people_context")
    if not isinstance(present_context, Mapping):
        return out

    context_out = _pick(
        present_context,
        (
            "privacy", "candidate_present_people_count", "present_people_context_count",
            "present_people_context_truncated",
        ),
    )
    handled_context = {
        "privacy", "candidate_present_people_count", "present_people_context_count",
        "present_people_context_truncated", "present_people", "relationship_edges",
    }
    for key, item in present_context.items():
        if key in handled_context:
            continue
        compact = _compact_gm_private_extension(item)
        if compact not in (None, {}, []):
            context_out[str(key)] = compact
    rows: list[dict[str, Any]] = []
    present_people = present_context.get("present_people")
    if isinstance(present_people, list):
        for source in present_people:
            if not isinstance(source, Mapping):
                continue
            row = _pick(source, ("person_ref", "name", "behavior_profile"))
            truth = source.get("character_truth")
            if isinstance(truth, Mapping):
                truth_out = _pick(
                    truth,
                    (
                        "life_status", "health_status", "fatigue", "role",
                        "authority", "command_assignment", "military_command", "private_knowledge",
                        "hidden_goals", "secret_notes", "autonomy_private",
                    ),
                )
                career = truth.get("career_state")
                if isinstance(career, Mapping):
                    truth_out["career_state"] = _pick(
                        career,
                        ("current_billet", "current_command_span", "office_or_command"),
                    )
                row["character_truth"] = truth_out
            cognition = source.get("cognition")
            if isinstance(cognition, Mapping):
                row["cognition"] = {
                    key: item for key, item in cognition.items()
                    if key not in {"privacy", "use_rule"}
                }
            rows.append(row)
    context_out["present_people"] = rows

    edges = present_context.get("relationship_edges")
    if isinstance(edges, list):
        context_out["relationship_edges"] = edges
    context_out["capability_detail"] = "demand_load_exact_person_when_material"
    out["present_people_context"] = context_out
    return out



def _compact_active_scene_session(value: object) -> dict[str, Any] | None:
    """Keep lifecycle/presence truth hot without repeating the whole thread ledger."""
    if not isinstance(value, Mapping):
        return None
    out = _pick(value, (
        "schema", "authority", "mechanical_consequence_authority",
        "session_ref", "kind", "status", "location_ref", "process_ref",
        "started_at", "soft_end_at", "last_updated_at", "purpose",
        "participant_count", "durable_participant_count",
        "physical_scene_viable", "lifecycle_reconciliation_recommended",
        "lifecycle_reconciliation_reason", "participant_projection_rule",
        "physically_absent_participant_count",
    ))
    participants = value.get("participant_refs")
    if isinstance(participants, list):
        out["participant_refs"] = _refs(participants, 24)
        out["participant_count"] = len(participants)
        if len(participants) > 24:
            out["participant_refs_truncated"] = True
    absent = value.get("physically_absent_participant_refs")
    if isinstance(absent, list):
        out["physically_absent_participant_refs"] = _refs(absent, 24)
        out["physically_absent_participant_count"] = len(absent)
        if len(absent) > 24:
            out["physically_absent_participant_refs_truncated"] = True
    agenda = value.get("agenda")
    if isinstance(agenda, list):
        out["agenda"] = [item for item in agenda[:12] if isinstance(item, str)]
        out["agenda_count"] = len(agenda)
        if len(agenda) > 12:
            out["agenda_truncated"] = True
    open_refs = value.get("open_thread_refs", value.get("open_question_refs"))
    if isinstance(open_refs, list):
        out["open_thread_count"] = len([ref for ref in open_refs if isinstance(ref, str) and ref])
        # Exact live thread identity is supplied by active_threads/read hints.
        # Durable opaque refs are intentionally not repeated here because they
        # may belong to physically absent participants.
        out["open_thread_detail"] = "use_active_threads_or_exact_scene_open_threads_read"
    return out

def _compact_scene(
    scene: Mapping[str, Any],
    root_session: Any,
    *,
    gm_scene_context_available: bool = False,
) -> dict[str, Any]:
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

    local_contract = scene.get("scene_local_narration_contract")
    if isinstance(local_contract, Mapping) and gm_scene_context_available:
        out["scene_local_narration_contract"] = {
            "mode": local_contract.get("mode"),
            "gm_scene_context_is_primary_writer_workspace": True,
            "persistent_consequences_require_runtime": local_contract.get("persistent_consequences_require_runtime", True),
            "interaction_attempt_establishes_external_outcome": local_contract.get("interaction_attempt_establishes_external_outcome", False),
            "contested_physical_actions_remain_runtime_owned": True,
        }

    cast = scene.get("scene_cast")
    if isinstance(cast, Mapping):
        cast_out = dict(cast)
        for key in ("generic_participation_rule", "active_session_presence_rule", "presence_rule"):
            cast_out.pop(key, None)
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
        # Broad-site nearby routing is not immediate scene presence. Keep its
        # existence hot, but demand-load identities only when one becomes relevant.
        if nearby:
            cast_out.pop("nearby_people", None)
            cast_out["nearby_people_count"] = len(nearby)
            cast_out["nearby_people_detail"] = "demand_load_when_scene_relevant"
        else:
            cast_out["nearby_people"] = []
        cast_out["referenced_people"] = referenced
        out["scene_cast"] = cast_out
    if "gm_private_director_context" in scene:
        if gm_scene_context_available:
            # gm_scene_context is the canonical writer-facing private projection.
            # Do not transmit a second near-identical private character packet.
            out["gm_private_director_context"] = {
                "available_in_gm_scene_context": True,
                "privacy": "gm_private_not_player_knowledge",
            }
        else:
            out["gm_private_director_context"] = _compact_gm_private_director_context(
                scene.get("gm_private_director_context")
            )
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
    commanders = value.get("reported_commanders")
    if isinstance(commanders, list):
        out["reported_commanders"] = _compact_mapping_rows(
            commanders[:4], ("person_ref", "name", "confidence_milli")
        )
        out["reported_commander_count"] = len(commanders)
        if len(commanders) > 4:
            out["reported_commanders_truncated"] = True
    return out


def _compact_campaign_context(value: Mapping[str, Any], *, live_scheme: bool) -> dict[str, Any]:
    """Project only campaign facts needed to direct the current scene.

    Exact campaign owners remain demand-loadable.  Never fall back to returning the
    raw context merely because one upstream convenience flag failed to notice a
    campaign scheme; that was the main source of live-context bloat.
    """
    out = _pick(
        value,
        (
            "arc_ref", "target_state_ref", "objective", "own_strength", "own_assigned_strength",
            "own_auxiliary_strength", "own_location_refs", "friendly_total_strength",
            "campaign_commander_ref", "campaign_commander_name", "coordination_authority_ref",
        ),
    )
    planning = value.get("march_planning")
    # The current campaign-command scheme is the one hot planning projection.
    # Repeating the briefing/campaign-context copy wastes context and encourages
    # report-like narration. Keep it only as a fallback when no live scheme exists.
    if isinstance(planning, Mapping) and not live_scheme:
        out["march_planning"] = _compact_march_planning(planning)
        if isinstance(planning.get("campaign_scheme"), Mapping):
            live_scheme = True
    if live_scheme:
        out["live_campaign_scheme"] = True

    participants = value.get("other_friendly_participants")
    if isinstance(participants, list):
        out["other_friendly_participant_count"] = len(participants)
        # A live staff scheme already represents campaign participants through
        # command hierarchy/assignment structure. Exact rows remain demand-loadable.
        if not live_scheme:
            compact_participants: list[dict[str, Any]] = []
            for source in participants[:8]:
                if not isinstance(source, Mapping):
                    continue
                row = _pick(source, ("operation_ref", "strength", "formation_count"))
                commanders = source.get("commanders")
                if isinstance(commanders, list):
                    row["commanders"] = _compact_mapping_rows(commanders, ("name",))[:6]
                compact_participants.append(row)
            out["other_friendly_participants"] = compact_participants
            if len(participants) > len(compact_participants):
                out["other_friendly_participants_truncated"] = True

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



def _compact_operational_intent_contract(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    out = _pick(
        value,
        (
            "operational_intent", "deliberate_battle_commitment_authorized",
            "field_command_relationship", "independent_detachment",
            "contact_is_not_synonymous_with_battle", "self_defense_preserved",
            "general_attack_requires_explicit_attack_authority_or_player_commitment",
            "campaign_commander_ref", "friendly_campaign_participant_operation_count",
        ),
    )
    if "support_continuity_rule" in value:
        out["parent_campaign_support_remains_real"] = True
    if "movement_rule" in value:
        out["movement_is_choice_within_order_scope"] = True
    return out or None


def _compact_upward_reports(value: Any) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(value, list):
        return [], 0
    rows: list[dict[str, Any]] = []
    for source in value[-2:]:
        if not isinstance(source, Mapping):
            continue
        row = _pick(
            source,
            (
                "report_ref", "event_ref", "phase", "reported_at", "from_ref", "to_ref",
                "order_ref", "directive_ref", "personnel", "information_refs",
                "follow_on_request_refs",
            ),
        )
        rows.append(row)
    return rows, len(value)

def _compact_operational_order(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    out = _pick(
        value,
        (
            "order_ref", "issued_at", "issuer_ref", "arc_ref", "status",
            "actionability_status", "superior_commander_ref",
            "coordination_authority_ref",
        ),
    )
    objective = _text(value.get("objective"), 180)
    if objective:
        out["objective"] = objective
    follow_on = _text(value.get("follow_on_requirement"), 160)
    if follow_on:
        out["follow_on_requirement"] = follow_on
    packet = value.get("mission_packet")
    if isinstance(packet, Mapping):
        packet_out = _pick(
            packet,
            (
                "entry_status", "hostile_entry_authorized", "mission_phase",
                "next_phase_trigger", "strategic_target_name", "strategic_target_ref",
                "operational_intent", "battle_commitment_authorized", "independent_detachment",
            ),
        )
        for key in ("success_condition", "contact_goal"):
            text = _text(packet.get(key), 180)
            if text:
                packet_out[key] = text
        if packet.get("support_continuity_rule") is not None:
            packet_out["parent_campaign_support_remains_real"] = True
        out["mission_packet"] = packet_out
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
    out = _pick(
        value,
        (
            "directive_ref", "issued_at", "issuer_ref", "issuing_commander_ref",
            "kind", "status", "base_operational_order_ref", "coordination_authority_ref",
        ),
    )
    text = _text(value.get("directive_text"), 240)
    if text:
        out["directive_text"] = text
    return out


def _compact_campaign_command(value: Mapping[str, Any], operational_order: Any) -> tuple[dict[str, Any], bool]:
    out = _pick(
        value,
        (
            "cycle_ref", "status", "venue_ref", "forum_kind", "court_state_ref",
            "coordination_authority_ref", "supreme_commander_ref", "superior_command_ref",
        ),
    )
    participant_ops = value.get("participant_operation_refs")
    if isinstance(participant_ops, list):
        out["participant_operation_count"] = len(participant_ops)
    participant_commanders = value.get("participant_commander_refs")
    if isinstance(participant_commanders, list):
        out["participant_commander_count"] = len(participant_commanders)
    delivered = value.get("delivered_superior_order_refs")
    if isinstance(delivered, list):
        out["delivered_superior_order_count"] = len(delivered)

    planning = value.get("march_planning")
    live_scheme = isinstance(planning, Mapping) and isinstance(planning.get("campaign_scheme"), Mapping)
    if isinstance(planning, Mapping):
        out["march_planning"] = _compact_march_planning(planning)

    council = value.get("war_council")
    if isinstance(council, Mapping):
        # Hot context needs lifecycle identity/status, not the whole historical
        # council record. Exact timing/session detail stays on the operation and
        # can be demand-loaded when it changes the current scene.
        out["war_council"] = _pick(
            council,
            ("event_ref", "status", "held_at", "scheduled_at"),
        )
        out["war_council"]["detail_rule"] = "demand_load_exact_operation_when_council_detail_matters"

    directive = value.get("current_superior_directive")
    if isinstance(directive, Mapping):
        # Do not feed directive prose back into the primary writer packet. The
        # current operational order already carries the decision-bearing mission
        # scope; the exact operation remains the source for directive wording.
        out["current_superior_directive"] = _pick(
            directive,
            ("directive_ref", "status", "kind", "issuing_commander_ref"),
        )
        out["current_superior_directive"]["detail_rule"] = "demand_load_exact_operation_for_directive_text"

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

    reviews = value.get("after_action_reviews")
    if isinstance(reviews, list) and reviews:
        out["after_action_review_count"] = len(reviews)
        out["recent_after_action_reviews"] = _compact_mapping_rows(
            reviews[-3:], ("review_ref", "event_ref", "status", "reviewed_at", "operation_ref")
        )

    upward_reports = value.get("upward_reports")
    if isinstance(upward_reports, list) and upward_reports:
        # Historical report rows are useful for exact inspection, but keeping them
        # hot strongly biases the LLM toward briefing recap. Preserve only the
        # existence/count signal in compact play context.
        out["upward_report_count"] = len(upward_reports)
        out["upward_report_detail_rule"] = "demand_load_exact_operation_for_report_history"
    return out, live_scheme


def _compact_controlled_operation(operation: Mapping[str, Any]) -> dict[str, Any]:
    out = _pick(
        operation,
        (
            "operation_ref", "status", "objective", "location_ref", "order_status",
            "campaign_phase", "campaign_arc_ref", "campaign_commander_ref",
            "briefing_information_ref", "last_phase_information_ref", "operational_area_ref",
            "strategic_target_ref", "entry_status",
        ),
    )
    formation_refs = operation.get("controlled_formation_refs")
    if isinstance(formation_refs, list):
        out["controlled_formation_refs"] = _refs(formation_refs, 12)
        out["controlled_formation_count"] = len(formation_refs)
        if len(formation_refs) > 12:
            out["controlled_formation_refs_truncated"] = True
    participant_refs = operation.get("campaign_participant_operation_refs")
    if isinstance(participant_refs, list):
        out["campaign_participant_operation_refs"] = _refs(participant_refs, 8)
        out["campaign_participant_operation_count"] = len(participant_refs)
    operational_order = operation.get("current_operational_order")
    compact_order = _compact_operational_order(operational_order)
    if compact_order is not None:
        out["current_operational_order"] = compact_order
        intent_contract = _compact_operational_intent_contract(
            operational_intent_contract(operation, operational_order)
        )
        if intent_contract is not None:
            out["operational_intent_contract"] = intent_contract

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
    # The hot list is routing/identity context, not nineteen miniature status
    # sheets. Readiness, morale, cohesion, fatigue and experience remain on the
    # exact formation owner and are demand-loaded when they can change a choice.
    return _compact_mapping_rows(
        value,
        (
            "formation_ref", "name", "personnel", "location_ref", "status",
            "mobilized", "commander_ref",
        ),
    )


def _compact_controlled_command_groups(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for source in value:
        if not isinstance(source, Mapping):
            continue
        row = _pick(source, (
            "command_group_ref", "display_name", "context", "location_ref", "commander_ref",
            "integrity_status",
        ))
        roles = source.get("role_assignments")
        if isinstance(roles, Mapping) and roles:
            row["role_assignments"] = dict(list(roles.items())[:6])
        direct = source.get("direct_units")
        if isinstance(direct, list):
            row["direct_unit_count"] = len(direct)
        org = source.get("organizational_state")
        if isinstance(org, Mapping):
            row["organizational_state"] = _pick(org, (
                "status", "current_recursive_strength", "reorganization_need",
            ))
        rows.append(row)
    return rows


def _compact_retinue_groups(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for source in value:
        if not isinstance(source, Mapping):
            continue
        row = _pick(source, (
            "command_group_ref", "display_name", "context", "commander_ref",
            "active_context_ref", "current_location_ref",
        ))
        units = source.get("units")
        if isinstance(units, list):
            row["unit_count"] = len(units)
        rows.append(row)
    return rows


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


def _compact_interaction_handles(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for source in value[:4]:
        if not isinstance(source, Mapping):
            continue
        row = _pick(source, (
            "interaction_ref", "kind", "triggered_at", "source_ref", "target_ref",
            "operation_ref", "campaign_command_cycle_ref",
        ))
        refs = source.get("present_person_refs")
        if isinstance(refs, list):
            row["present_person_refs"] = _refs(refs, 6)
            row["present_person_ref_count"] = len(refs)
        if source.get("summary"):
            row["detail_available_via_exact_interaction_read"] = True
        rows.append(row)
    return rows


def _compact_recent_interaction_attempts(value: Any) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(value, list):
        return [], 0
    rows: list[dict[str, Any]] = []
    for source in value[:3]:
        if not isinstance(source, Mapping):
            continue
        row = _pick(source, (
            "event_id", "attempt_ref", "at", "action", "target_ref", "process_ref",
            "posture", "topic", "scene_session_ref", "thread_status", "resolved_at", "response_ref",
        ))
        statement = _text(source.get("player_statement"), 650)
        if statement:
            row["player_statement"] = statement
        formations = source.get("formation_refs")
        if isinstance(formations, list):
            row["formation_refs"] = _refs(formations, 4)
            row["formation_ref_count"] = len(formations)
            if len(formations) > 4:
                row["formation_refs_truncated"] = True
        rows.append(row)
    return rows, len(value)


def compact_play_context(context: Mapping[str, Any]) -> dict[str, Any]:
    result = {"gm_scene_context": build_gm_scene_context(context), **dict(context)}
    compact_session = _compact_active_scene_session(context.get("active_scene_session"))
    if compact_session is not None:
        result["active_scene_session"] = compact_session
    commands = context.get("commands")
    if isinstance(commands, Mapping):
        result["commands"] = compact_commands(commands)

    guidance = _compact_narration_guidance(context.get("narration_guidance"))
    if guidance is None:
        result.pop("narration_guidance", None)
    else:
        result["narration_guidance"] = guidance

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
        result["scene"] = _compact_scene(
            scene,
            context.get("active_scene_session"),
            gm_scene_context_available=bool(result.get("gm_scene_context")),
        )

    if isinstance(context.get("controlled_formations"), list):
        result["controlled_formations"] = _compact_controlled_formations(context["controlled_formations"])
    if isinstance(context.get("controlled_command_groups"), list):
        result["controlled_command_groups"] = _compact_controlled_command_groups(context["controlled_command_groups"])
    if isinstance(context.get("retinue_command_groups"), list):
        result["retinue_command_groups"] = _compact_retinue_groups(context["retinue_command_groups"])
    if isinstance(context.get("known_information"), list) and briefing_refs:
        result["known_information"] = _compact_known_information(context["known_information"], briefing_refs)

    handles = context.get("interaction_handles")
    if isinstance(handles, list):
        result["interaction_handles"] = _compact_interaction_handles(handles)

    attempts, attempt_count = _compact_recent_interaction_attempts(context.get("recent_interaction_attempts"))
    active_session = context.get("active_scene_session")
    if attempts and isinstance(active_session, Mapping):
        session_ref = active_session.get("session_ref")
        scene_attempts = [
            row for row in attempts
            if not session_ref or row.get("scene_session_ref") == session_ref
        ]
        if scene_attempts:
            result["recent_interaction_attempts"] = scene_attempts
            result["recent_interaction_attempts_compact_source_count"] = attempt_count
            if attempt_count > len(scene_attempts):
                result["recent_interaction_attempts_compact_truncated"] = True
    elif attempt_count:
        result.pop("recent_interaction_attempts", None)
        result["recent_interaction_attempt_count"] = attempt_count
        result["recent_interaction_attempts_rule"] = "historical_attempts_demand_loaded_without_active_scene_session"

    history = context.get("recent_scene_history")
    if isinstance(history, list) and len(history) > 4:
        result["recent_scene_history"] = history[-4:]
        result["recent_scene_history_truncated"] = True
    result["semantic_action_contract"] = {
        "intent_before_mechanics": True,
        "attempt_is_not_outcome": True,
        "ordinary_reversible_scene_action_needs_command": False,
        "mechanic_discovery_after_interpretation": True,
        "compound_declaration_preserves_scene_components": True,
        "player_authored_external_outcomes_forbidden": True,
        "gm_private_director_truth_may_exceed_player_knowledge": True,
        "player_output_remains_knowledge_bounded": True,
        "unsupported_rule": "Unsupported hard consequences fail closed; plausible reversible scene behavior remains allowed.",
    }
    return result


__all__ = [
    "command_domain",
    "grouped_commands",
    "compact_commands",
    "compact_command_family",
    "compact_play_context",
]
