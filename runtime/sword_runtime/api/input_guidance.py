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
        "war_bolts": {"type": "integer", "minimum": 0, "maximum": 1000000000},
        "formation_ref": {"rule": "use an exact controlled formation ref"},
    },
    "recruitment_campaign_start": {
        "applicant_count": {"type": "integer", "minimum": 2, "maximum": 100000, "rule": "reserves real civilians from the registered source mix; it does not create soldiers or individual NPC sheets"},
        "campaign_ref": {"rule": "new stable recruitment-campaign ref"},
        "destination_force_ref": {"rule": "use the exact controlled personal-force ref; current Wei personal recruitment uses force_tang_wei_personal"},
        "role": {"rule": "use a registered destination military role"},
        "location_ref": {"rule": "use an exact lawful recruiting/training location ref"},
    },
    "recruitment_campaign_stage": {
        "campaign_ref": {"rule": "use an active recruitment campaign ref"},
        "selection_profile": {"rule": "must be a registered selection profile; ChatGPT must never invent stat bonuses or thresholds"},
        "retain_count": {"type": "integer", "minimum": 1, "rule": "provide exactly one of retain_count or retain_fraction; rejected candidates return to their conserved source population"},
        "retain_fraction": {"type": "number", "minimum": 0.0001, "maximum": 0.9999, "rule": "provide exactly one of retain_count or retain_fraction"},
    },
    "recruitment_campaign_train": {
        "campaign_ref": {"rule": "use an active recruitment campaign ref"},
        "hours": {"type": "integer", "minimum": 1, "maximum": 56, "rule": "real training consumes elapsed time, food and registered capacity; it changes development, unlike selection"},
    },
    "recruitment_campaign_finalize": {
        "campaign_ref": {"rule": "accepts the surviving candidate cohort into the destination force; acceptance remains cohort-first and does not auto-materialize individuals"},
    },
    "recruitment_campaign_cancel": {
        "campaign_ref": {"rule": "returns remaining reserved candidates to their original population strata; already spent recruiting/training costs are not refunded"},
    },
    "person_materialize": {
        "person_ref": {"rule": "new stable identity for one already-conserved cohort body; materialization never creates headcount"},
        "representation": {"allowed_values": ["person_lite", "exact"], "default": "person_lite"},
        "formation_ref": {"rule": "optional exact formation whose existing cohort slot is being materialized"},
        "source_cohort_ref": {"rule": "optional exact known source cohort; starting stats are sampled deterministically from that cohort and cannot be caller supplied"},
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
        "formation_refs": {"type": "array", "minimum_items": 1, "maximum_items": 512, "rule": "transport payload bound only; use exact controlled formation refs. Larger campaign forces remain lawful as multiple operations or battle sectors rather than disappearing from the world"},
        "location_ref": {"rule": "use an exact player-known registered location ref"},
    },
    "operation_transition": {"status": {"allowed_values": ["planned", "mobilizing", "active", "engaged", "occupied", "completed", "cancelled"]}},
    "battle_resolve": {
        "attacker_formation_refs": {"type": "array", "minimum_items": 1, "maximum_items": 128, "rule": "per-contact payload bound, not a force-size limit; a larger saved operation may be resolved through multiple disjoint battlefield sectors sharing exact operation evidence"},
        "defender_formation_refs": {"type": "array", "minimum_items": 1, "maximum_items": 128, "rule": "per-contact payload bound, not a force-size limit; every participating formation remains an exact persistent owner outside this call"},
        "operation_ref": {"rule": "exact active operation proving contact; larger operations may continue through multiple sector/contact resolutions"},
        "battlefield_ref": {"rule": "optional active operational battlefield inside operation_ref; when supplied sector_ref is also required and all contact formations must actually be assigned there"},
        "sector_ref": {"rule": "optional exact sector inside battlefield_ref; exact battle casualties/outcome reconcile back into only this local sector"},
    },
    "battlefield_control": {
        "action": {"allowed_values": ["open", "assign", "redeploy", "set_order", "close"]},
        "layout_ref": {"allowed_values": ["battlefield.layout.line_three", "battlefield.layout.deep_five"], "applies_to": ["open"]},
        "side_refs": {"type": "array", "minimum_items": 2, "maximum_items": 2, "applies_to": ["open"], "rule": "two stable operational side labels; they do not transfer formation ownership"},
        "sector_ref": {"rule": "exact sector assignment for one present participating formation", "applies_to": ["assign"]},
        "target_sector_ref": {"rule": "exact different sector; movement takes battlefield time and the formation contributes to neither endpoint while in transit", "applies_to": ["redeploy"]},
        "pace": {"allowed_values": ["forced", "standard", "cautious"], "default": "standard", "applies_to": ["redeploy"]},
        "order": {"allowed_values": ["hold", "attack", "breakthrough", "delay", "reserve", "withdraw"], "default": "hold", "applies_to": ["assign", "redeploy", "set_order"]},
        "rule": "operational battlefield state owns sector geometry, command pressure, redeployment clocks, contacts and messenger delay only; battle_resolve remains casualty/outcome authority"
    },
    "state_action": {
        "action": {"allowed_values": ["strategic_goal", "appointment", "enemy_action", "record_threat", "recognize_polity"], "default": "strategic_goal"},
        "severity": {"type": "integer", "minimum": 0, "maximum": 100, "applies_to": ["enemy_action", "record_threat"]},
        "information_ref": {"rule": "optional exact saved information claim that the acting player already knows; autonomous callers may attach only an existing claim ref", "applies_to": ["enemy_action", "record_threat"]},
    },
    "fortification_materialize": {
        "integrity": {"type": "integer", "minimum": 1, "maximum": 100, "default": 100},
        "food_kg": {"type": "integer", "minimum": 0, "maximum": 1000000000, "default": 0},
        "fodder_kg": {"type": "integer", "minimum": 0, "maximum": 1000000000, "default": 0},
        "garrison_formation_refs": {"type": "array", "minimum_items": 1, "maximum_items": 512, "rule": "fortification custody payload bound only; the garrison remains an exact saved formation set and large assaults are resolved by explicit battlefield sectors"},
    },
    "siege_start": {"attacker_formation_refs": {"type": "array", "minimum_items": 1, "maximum_items": 512, "rule": "saved siege-force payload bound only; use exact controlled formation refs. Assaults involving more than 128 formations on either side continue through explicit disjoint battlefield sectors"}},
    "siege_action": {
        "action": {"allowed_values": ["blockade", "repair", "assault", "withdraw", "settle", "relief"]},
        "days": {"type": "integer", "minimum": 1, "maximum": 30, "default": 7, "applies_to": ["blockade"]},
        "points": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5, "applies_to": ["repair"]},
        "attacker_formation_refs": {"type": "array", "minimum_items": 1, "maximum_items": 128, "applies_to": ["assault"], "rule": "optional explicit assault-sector attacker subset; required with defender_formation_refs when the saved siege exceeds one contact payload"},
        "defender_formation_refs": {"type": "array", "minimum_items": 1, "maximum_items": 128, "applies_to": ["assault"], "rule": "optional exact garrison subset for this assault sector; the unselected saved garrison remains present for later sectors"},
        "outcome_rule": "assault damage/outcome is runtime-owned and must not be caller supplied",
    },
    "family_event": {
        "kind": {"accepted_values": ["proposal", "engagement", "marriage", "pregnancy", "birth", "death", "widowhood", "succession_review"]},
        "player_authored_kinds": ["proposal", "engagement", "marriage"],
        "runtime_only_involuntary_kinds": ["pregnancy", "birth", "death", "widowhood", "succession_review"],
        "marriage_rule": "a player-authored marriage requires the player actor to be one marrying party and a previously accepted betrothal; NPC-only marriages remain autonomous/runtime consequences",
    },
    "career_event": {
        "kind": {"allowed_values": ["qualification", "promotion", "office_appointment", "office_removal", "affiliation_add", "affiliation_remove", "merit"]},
        "grade": {"allowed_values": ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10"], "applies_to": ["promotion"]},
        "merit": {"type": "integer", "minimum": 1, "maximum": 1000, "applies_to": ["merit"]},
        "office": {"type": "string", "applies_to": ["office_appointment", "office_removal"]},
        "affiliation_ref": {"type": "string", "applies_to": ["affiliation_add", "affiliation_remove"]},
        "rule": "career grade, active office, and institutional affiliation are independent saved dimensions; legacy appointment remains accepted internally as office_appointment",
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
    "project_cancel": {
        "institution_ref": {"rule": "exact institution authority"},
        "project_ref": {"rule": "exact active funded project; cancellation releases reserved workers and returns only unconsumed/recoverable inputs"},
    },
    "house_action": {
        "action": {"allowed_values": ["assign_duty", "set_policy", "proclaim_territorial_authority"], "default": "assign_duty"},
        "subject_ref": {"rule": "assign_duty requires an exact person already within House Tang or Tang Wei personal-retinue authority", "applies_to": ["assign_duty"]},
        "duty": {"type": "string", "maximum_length": 160, "applies_to": ["assign_duty"]},
        "policy_key": {"type": "string", "maximum_length": 120, "applies_to": ["set_policy"]},
        "policy_value": {"type": "string", "maximum_length": 400, "applies_to": ["set_policy"]},
        "location_ref": {"rule": "proclamation requires an exact currently occupied seat", "applies_to": ["proclaim_territorial_authority"]},
        "operation_ref": {"rule": "exact surviving House-backed occupation evidence", "applies_to": ["proclaim_territorial_authority"]},
        "polity_name": {"type": "string", "maximum_length": 120, "applies_to": ["proclaim_territorial_authority"]},
    },
    "command_group_action": {
        "action": {"allowed_values": ["create", "add_person", "remove_person", "attach_formation", "detach_formation", "set_deputy", "set_successors", "set_order", "set_communication"]},
        "command_group_ref": {"rule": "use an exact command-group ref already controlled by Tang Wei, except create which allocates a new command-group ref"},
        "rule": "command groups are retinue/command structure only and never create manpower; named people and formations remain exact conserved owners",
    },
    "command_group_train": {
        "hours": {"type": "integer", "minimum": 1, "maximum": 12},
        "command_group_ref": {"rule": "use an exact player-controlled command-group ref whose participating exact people are co-located"},
        "rule": "advances time once, improves bounded group familiarity, and may train one explicit exact-person skill focus without duplicating elapsed time",
    },
    "information_create": {
        "claim": {"type": "string", "maximum_length": 4000},
        "knowers": {"type": "array", "minimum_items": 1, "maximum_items": 128, "rule": "use exact person refs; gameplay creation must include the player actor as an exact knower"},
        "epistemic_kind": {"allowed_values": ["observation", "report", "rumor", "testimony", "document", "captured_document", "inference", "estimate", "official_report"]},
        "confidence_milli": {"type": "integer", "minimum": 0, "maximum": 1000},
        "rule": "creates Tang Wei's saved assertion with provenance, not world truth; gameplay callers cannot supply evidence_refs or discoverability, and authoritative evidence must come from persisted runtime-owned observation/document/report paths",
    },
    "information_deliver": {
        "channel": {"allowed_values": ["spoken", "written_message", "official_report", "courier", "scout_report", "merchant_network", "prisoner_testimony"]},
        "rule": "delivery preserves provenance and can reduce confidence; it does not turn a report into direct observation",
    },
    "investigation_action": {
        "action": {"allowed_values": ["start", "work", "close"]},
        "hours": {"type": "integer", "minimum": 1, "maximum": 24, "applies_to": ["work"]},
        "rule": "the player may choose investigator, place, scope, and time but may not declare culprit, clue, or result; only runtime-established discoverable claims backed by lawful evidence can be found",
    },
    "commission_action": {
        "action": {"allowed_values": ["request", "accept", "decline", "report"]},
        "rule": "requests are processed durably by the world; issuer eligibility is validated, assignment objective/location are committed before tactics, hidden risk is only an issuer assessment rather than proof of opposition, and reports settle only from relevant runtime-established evidence; location-only evidence is accepted only for reconnaissance/inspection/investigation/intelligence work",
    },
    "medical_treatment": {
        "treatment": {"allowed_values": ["stabilize", "treat", "surgery", "rehabilitation"]},
        "rule": "requires exact co-location, procedure-specific Medicine qualification, and for facility-backed care an exact co-located facility owner/location; treatment consequences are runtime-owned and surgery preview is hidden until execute",
    },
    "commitment_action": {
        "action": {"allowed_values": ["create", "fulfill", "confirm_fulfillment", "breach", "release"]},
        "rule": "gameplay may create only Tang Wei's own voluntary obligation; fulfill submits a runtime-established evidence-backed claim, the beneficiary confirms fulfillment, and only the beneficiary may release it",
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
