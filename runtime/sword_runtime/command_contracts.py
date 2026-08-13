from __future__ import annotations

# Production semantic payload surface. Every command is fail-closed: fields not
# listed here are rejected before authority checks/reducers. This prevents
# ignored caller data from becoming a shadow control channel as reducers evolve.
#
# scene_consequence remains listed only for replay/backward compatibility inside
# the legacy reducer. Player-facing catalogs must not advertise it. New social
# and institutional interaction enters through interaction_action, which is
# translated by the stable API into a server-authored attempt record.
COMMAND_PAYLOAD_KEYS: dict[str, frozenset[str]] = {
    "advance_time": frozenset({"hours", "target_time"}),
    "battle_resolve": frozenset({"attacker_formation_refs", "defender_formation_refs", "operation_ref", "controlled_side", "objective"}),
    "career_event": frozenset({"person_ref", "kind", "merit", "qualification_ref", "grade", "office", "evidence_ref", "grantor_ref"}),
    "cohort_training": frozenset({"hours", "cohort_ref"}),
    "command_assign": frozenset({"formation_ref", "commander_ref", "command_authority"}),
    "command_transfer": frozenset({"formation_ref", "commander_ref", "command_authority"}),
    "economy_transfer": frozenset({"state", "direction", "amount_silver"}),
    "enlisted_service_pay": frozenset({"state", "amount_silver"}),
    "equipment_consume": frozenset({"item_key", "quantity"}),
    "equipment_drop": frozenset({"item_key", "quantity"}),
    "equipment_equip": frozenset({"item_key", "quantity"}),
    "equipment_issue": frozenset({"item_key", "quantity", "target_ref"}),
    "equipment_loot": frozenset({"item_key", "quantity"}),
    "equipment_return": frozenset({"item_key", "quantity", "target_ref"}),
    "equipment_transfer": frozenset({"item_key", "quantity", "target_ref"}),
    "equipment_unequip": frozenset({"item_key", "quantity"}),
    "family_event": frozenset({"house_ref", "kind", "person_ref", "partner_ref", "proposal_ref", "mother_ref", "father_ref", "child_ref", "name", "succession_ref"}),
    "force_assignment": frozenset({"formation_ref", "commander_ref", "command_authority"}),
    "formation_assign": frozenset({"formation_ref", "commander_ref", "command_authority"}),
    "formation_create": frozenset({"state", "formation_ref", "role", "personnel", "equipment_units", "location_ref", "commander_ref", "name", "command_authority", "doctrine_ref", "training_ref"}),
    "formation_demobilize": frozenset({"formation_ref"}),
    "formation_dissolve": frozenset({"formation_ref"}),
    "formation_doctrine_set": frozenset({"formation_ref", "doctrine_ref", "doctrine_behavior"}),
    "formation_merge": frozenset({"formation_refs"}),
    "formation_mobilize": frozenset({"formation_ref", "formation_refs"}),
    "formation_move": frozenset({"formation_ref", "destination_ref"}),
    "formation_reconstitute": frozenset({"formation_ref", "target_personnel", "equipment_units"}),
    "formation_split": frozenset({"formation_ref", "new_formation_ref", "personnel", "name"}),
    "formation_train": frozenset({"formation_ref", "hours"}),
    "formation_training_set": frozenset({"formation_ref", "training_ref"}),
    "fortification_materialize": frozenset({"fortification_ref", "location_ref", "garrison_formation_refs", "food_kg", "fodder_kg", "state", "commander_ref", "integrity"}),
    "health_injury": frozenset({"injury", "severity"}),
    "health_recovery": frozenset({"hours"}),
    "house_action": frozenset({"house_ref", "action", "subject_ref", "duty", "policy_key", "policy_value"}),
    "individual_training": frozenset({"focus", "hours"}),
    "information_create": frozenset({"information_ref", "claim", "knowers", "confidence", "provenance"}),
    "information_deliver": frozenset({"information_ref", "target_ref", "source_ref"}),
    "institution_project": frozenset({"institution_ref", "project_ref", "duration_hours", "kind", "magnitude", "effect"}),
    "interaction_action": frozenset({"target_ref", "action", "process_ref", "player_statement", "formation_refs", "posture"}),
    "market_purchase": frozenset({"item_key", "quantity"}),
    "market_sell": frozenset({"item_key", "quantity"}),
    "mercenary_contract": frozenset({"mercenary_ref", "action", "contract_ref", "amount_silver", "term_days", "location_ref", "reason"}),
    "operation_create": frozenset({"operation_ref", "objective", "formation_refs", "location_ref"}),
    "operation_transition": frozenset({"operation_ref", "status"}),
    "person_materialize": frozenset({"state", "person_ref", "role", "name", "birth_date"}),
    "personal_combat": frozenset({"opponent_ref", "objective", "duration_minutes"}),
    "population_transfer": frozenset({"state", "personnel", "source_stratum", "destination_stratum"}),
    "project_resolve": frozenset({"institution_ref", "project_ref"}),
    "recruitment": frozenset({"state", "personnel", "source_stratum", "role"}),
    "relationship_change": frozenset({"source_ref", "target_ref", "kind", "delta", "basis_ref"}),
    "repair": frozenset({"path", "changes", "reason"}),
    "reputation_event": frozenset({"subject_ref", "audience_ref", "delta", "event_type", "dimension", "source_event_ref", "basis", "witnesses"}),
    "resupply": frozenset({"formation_ref", "food_kg", "fodder_kg", "war_arrows"}),
    "scene_consequence": frozenset({"summary"}),
    "siege_action": frozenset({"siege_ref", "action", "days", "points"}),
    "siege_start": frozenset({"siege_ref", "fortification_ref", "attacker_formation_refs"}),
    "state_action": frozenset({"state", "action", "goal", "person_ref", "office", "capabilities", "source_state", "severity", "provenance"}),
    "territorial_consequence": frozenset({"location_ref", "controller", "siege_ref", "operation_ref"}),
    "travel": frozenset({"destination_ref", "mode", "formation_refs"}),
}

HOSTILE_DIMENSIONS = (
    "negative_or_zero",
    "absurd_magnitude",
    "nonexistent_reference",
    "wrong_location",
    "wrong_state_or_owner",
)
