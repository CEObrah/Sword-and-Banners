"""Interpret saved campaign orders as mechanical operational-intent constraints.

This module does not choose tactics and does not move forces.  It translates exact
saved mission/order fields into a compact invariant contract for API projections and
validation.  The contract exists so reconnaissance/contact missions are not mistaken
for permission to launch a general attack and so a vanguard/advance guard does not
silently become an independent army.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_INTENT_DEFAULTS: dict[str, dict[str, Any]] = {
    "screen": {
        "purpose": "protect_parent_force_and_deny_enemy_observation",
        "deliberate_battle_commitment_authorized": False,
        "contact_goal": "observe_delay_and_disengage_unless_further_authorized",
    },
    "probe": {
        "purpose": "test_enemy_disposition_without_general_commitment",
        "deliberate_battle_commitment_authorized": False,
        "contact_goal": "gain_information_and_break_contact_before_uncontrolled_escalation",
    },
    "reconnoiter": {
        "purpose": "locate_observe_and_report",
        "deliberate_battle_commitment_authorized": False,
        "contact_goal": "avoid_decisive_engagement_unless_self_defense_or_explicitly_ordered",
    },
    "develop_contact": {
        "purpose": "locate_confirm_observe_and_report_enemy_disposition",
        "deliberate_battle_commitment_authorized": False,
        "contact_goal": "establish_tactical_information_not_start_general_attack",
    },
    "fix": {
        "purpose": "hold_enemy_attention_or_position_for_parent_operation",
        "deliberate_battle_commitment_authorized": True,
        "contact_goal": "maintain_pressure_within_assigned_scope_without_inventing_breakthrough_authority",
    },
    "demonstrate": {
        "purpose": "threaten_or_distract_without_main_commitment",
        "deliberate_battle_commitment_authorized": False,
        "contact_goal": "create_visible_pressure_while_preserving_disengagement",
    },
    "harass": {
        "purpose": "inflict_limited_disruption_without_decisive_commitment",
        "deliberate_battle_commitment_authorized": True,
        "contact_goal": "bounded_attack_and_disengagement_not_general_assault",
    },
    "delay": {
        "purpose": "trade_space_or_time_against_enemy_advance",
        "deliberate_battle_commitment_authorized": True,
        "contact_goal": "bounded_resistance_with_withdrawal_preserved",
    },
    "pursue": {
        "purpose": "maintain_pressure_on_withdrawing_enemy",
        "deliberate_battle_commitment_authorized": True,
        "contact_goal": "pursue_within_saved_scope_and_physical_support_constraints",
    },
    "attack": {
        "purpose": "defeat_enemy_field_force_or_seize_assigned_objective",
        "deliberate_battle_commitment_authorized": True,
        "contact_goal": "general_offensive_action_within_exact_order_scope",
    },
    "assault": {
        "purpose": "force_entry_or_break_prepared_position",
        "deliberate_battle_commitment_authorized": True,
        "contact_goal": "close_assault_within_exact_authorized_objective",
    },
    "breakthrough": {
        "purpose": "rupture_enemy_position_and_pass_through",
        "deliberate_battle_commitment_authorized": True,
        "contact_goal": "decisive_penetration_within_exact_authorized_axis",
    },
}


_PHASE_TO_INTENT = {
    "contact_development": "develop_contact",
    "reconnaissance": "reconnoiter",
    "screening": "screen",
    "probing": "probe",
    "pursuit": "pursue",
    "attack": "attack",
    "assault": "assault",
    "breakthrough": "breakthrough",
}


def _packet(order: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(order, Mapping):
        return {}
    packet = order.get("mission_packet")
    return packet if isinstance(packet, Mapping) else {}


def operational_intent_name(operation: Mapping[str, Any] | None, order: Mapping[str, Any] | None) -> str | None:
    packet = _packet(order)
    explicit = packet.get("operational_intent") or (order.get("operational_intent") if isinstance(order, Mapping) else None)
    if isinstance(explicit, str) and explicit in _INTENT_DEFAULTS:
        return explicit
    phase = packet.get("mission_phase")
    if not isinstance(phase, str) and isinstance(operation, Mapping):
        phase = operation.get("campaign_phase")
    return _PHASE_TO_INTENT.get(str(phase or ""))


def operational_intent_contract(
    operation: Mapping[str, Any] | None,
    order: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Return a derived hard-semantics contract for an exact saved order.

    The result is a projection only.  It cannot create campaign authority.  Explicit
    saved fields may narrow or broaden the defaults, while phase-derived defaults keep
    older saves safe after this code upgrade.
    """
    intent = operational_intent_name(operation, order)
    if intent is None:
        return None
    packet = _packet(order)
    defaults = dict(_INTENT_DEFAULTS[intent])

    explicit_commit = packet.get("battle_commitment_authorized")
    if isinstance(explicit_commit, bool):
        defaults["deliberate_battle_commitment_authorized"] = explicit_commit

    independent = packet.get("independent_detachment") is True
    campaign_commander = operation.get("campaign_commander_ref") if isinstance(operation, Mapping) else None
    participants = operation.get("campaign_participant_operation_refs") if isinstance(operation, Mapping) else None
    in_campaign_chain = bool(
        isinstance(campaign_commander, str) and campaign_commander
        or isinstance(participants, list) and any(isinstance(ref, str) and ref for ref in participants)
    )

    relation = "independent_detachment" if independent else ("campaign_subordinate_component" if in_campaign_chain else "self_contained_command")
    contract: dict[str, Any] = {
        "schema": "sword-operational-intent-contract-1.0",
        "authority": "derived_from_exact_saved_order_and_operation",
        "operational_intent": intent,
        **defaults,
        "field_command_relationship": relation,
        "independent_detachment": independent,
        "contact_is_not_synonymous_with_battle": intent in {"screen", "probe", "reconnoiter", "develop_contact", "demonstrate"},
        "self_defense_preserved": True,
        "general_attack_requires_explicit_attack_authority_or_player_commitment": intent not in {"attack", "assault", "breakthrough"},
        "support_continuity_rule": (
            "A vanguard, advance guard, reconnaissance element, or subordinate field command remains part of its parent campaign unless an exact detachment order says otherwise. "
            "Friendly support does not vanish when the forward element makes contact; actual reinforcement, rescue, concentration, or mutual support still depends on physical distance, route, readiness, messenger/signaling delay, and lawful command response."
        ),
        "movement_rule": (
            "The mission purpose constrains why contact is sought, not a scripted route. Tang Wei retains lawful maneuver choice, but a non-independent forward element must not be represented as if the rest of its campaign army ceased to exist."
        ),
    }
    if isinstance(campaign_commander, str) and campaign_commander:
        contract["campaign_commander_ref"] = campaign_commander
    if isinstance(participants, list):
        refs = [str(ref) for ref in participants if isinstance(ref, str) and ref]
        if refs:
            contract["friendly_campaign_participant_operation_refs"] = refs[:16]
            contract["friendly_campaign_participant_operation_count"] = len(refs)
    return contract


__all__ = ["operational_intent_contract", "operational_intent_name"]
