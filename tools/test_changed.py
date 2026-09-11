#!/usr/bin/env python3
"""Run the smallest maintained regression slice for changed repository paths."""
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_CHANGED_NAMESPACE = hashlib.sha256(str(ROOT.resolve()).encode("utf-8")).hexdigest()[:12]
TEST_CHANGED_TMP_BASE = Path("/tmp/sword-test-changed") / TEST_CHANGED_NAMESPACE
TEST_CHANGED_RUN_BASE = Path("/tmp/sword-test-changed-runs") / TEST_CHANGED_NAMESPACE
TEST_CHANGED_CHECKPOINT_DIR = TEST_CHANGED_TMP_BASE / "checkpoints"
TEST_CHANGED_LOCK_PATH = TEST_CHANGED_TMP_BASE / "gate.lock"
NODE_TIMEOUT_SECONDS = 90
NODE_ONLY_MODULES = {
    "tests/runtime/test_army_train_logistics.py",
    "tests/runtime/test_causal_connections.py",
    "tests/runtime/test_hosted_horizon_performance.py",
    "tests/runtime/test_interaction_surface.py",
    "tests/runtime/test_long_horizon.py",
    "tests/runtime/test_personal_combat_multi_actor.py",
    "tests/runtime/test_personal_combat_physical_rework.py",
    "tests/runtime/test_real_campaign_acceptance.py",
    "tests/runtime/test_rules_parity_adversarial.py",
    "tests/runtime/test_warfare.py",
}
SERIAL_NODE_TIMEOUTS = {
    "tests/runtime/test_long_horizon.py::test_horizons_are_bounded_and_alive": 180,
    "tests/runtime/test_long_horizon.py::test_20_year_world_changes_without_global_scans": 180,
    "tests/runtime/test_long_horizon.py::test_named_person_identity_survives_5_and_20_years": 180,
    "tests/runtime/test_living_world_intelligence.py::test_current_campaign_120_day_replay_is_stable_for_same_saved_seed": 360,
    "tests/runtime/test_real_campaign_acceptance.py::test_state_house_institution_autonomy": 180,
    "tests/runtime/test_rules_parity_adversarial.py::test_fifty_year_world_produces_exact_human_and_interstate_history": 180,
    "tests/runtime/test_hosted_horizon_performance.py::test_production_hosted_horizon_is_bounded_atomic_windows[90]": 180,
    "tests/runtime/test_hosted_horizon_performance.py::test_production_hosted_horizon_is_bounded_atomic_windows[365]": 600,
}
NATIVE_TEMP_MODULES = {
    "tests/runtime/test_command_staff_continuity.py",
}

API_TESTS = {
    "tests/runtime/test_architecture_service.py",
    "tests/runtime/test_stable_operations.py",
    "tests/runtime/test_interaction_surface.py",
    "tests/runtime/test_household_social_surface.py",
}
COMMAND_TESTS = {
    "tests/runtime/test_hostile_command_matrix.py",
    "tests/runtime/test_interaction_surface.py",
}
STRATEGIC_DEPTH_TESTS = {"tests/runtime/test_strategic_depth.py", "tests/runtime/test_autonomous_siege_terminal_depth.py"}
CIVIL_WORLD_TESTS = {
    "tests/runtime/test_civil_world.py",
    "tests/runtime/test_causal_connections.py",
    "tests/runtime/test_production_living_world.py",
    "tests/runtime/test_world_arcs.py",
    "tests/runtime/test_local_service_casualty_provenance.py",
}
LIVING_WORLD_TESTS = {
    "tests/runtime/test_campaign_event_liveness.py",
    "tests/runtime/test_living_world_intelligence.py",
    "tests/runtime/test_production_living_world.py",
    "tests/runtime/test_world_arcs.py",
}
ENVIRONMENT_TESTS = {"tests/runtime/test_environment.py"}
GROUP_ACTION_TESTS = {"tests/runtime/test_player_group_actions.py"}
COHORT_TESTS = {"tests/runtime/test_exact_aggregate_conservation.py", "tests/runtime/test_production_exceptional_progression.py", "tests/runtime/test_combat_cohort_integration.py", "tests/runtime/test_military_logistics.py"}
PERSON_TESTS = {"tests/runtime/test_exact_aggregate_conservation.py", "tests/runtime/test_character_progression_schema.py"}
TRANSACTION_TESTS = {"tests/runtime/test_transactions.py"}
REFERENCE_TESTS = {"tests/runtime/test_world_reference_search.py"}
PLAYER_STORY_TESTS = {"tests/runtime/test_player_story_flow.py"}
VITALITY_TESTS = {
    "tests/runtime/test_vitality_campaign_order_delivery.py",
    "tests/runtime/test_vitality_qin_briefing.py",
    "tests/runtime/test_vitality_qin_pending_response.py",
    "tests/runtime/test_vitality_report_eligibility.py",
}
QIN_COMMAND_TESTS = {"tests/runtime/test_qin_command_progression.py"}
MILITARY_CAREER_LOYALTY_TESTS = {"tests/runtime/test_military_career_loyalty.py"}
DEFAULT_TESTS = {"tests/runtime/test_architecture_service.py"}
ENGINE_CORE_TESTS = {
    "tests/runtime/test_architecture_service.py",
    "tests/runtime/test_transactions.py",
}
GEOGRAPHY_TESTS = {"tests/runtime/test_world_geography.py"}
COMBAT_TESTS = {
    "tests/runtime/test_personal_combat_crossgame_fairness.py",
    "tests/runtime/test_mass_battle_crossgame_fairness.py",
    "tests/runtime/test_battlefield_scale_model.py",
    "tests/runtime/test_wei_combat_doctrine.py",
    "tests/runtime/test_personal_combat_multi_actor.py",
    "tests/runtime/test_personal_combat_action_ready.py",
    "tests/runtime/test_personal_combat_physical_rework.py",
    "tests/runtime/test_personal_combat_integrity_policies.py",
    "tests/runtime/test_personal_combat_balance_lab.py",
    "tests/runtime/test_structural_injury_physiology.py",
    "tests/runtime/test_combat_penetration_sequence.py",
    "tests/runtime/test_ranged_contact_physics.py",
    "tests/runtime/test_hero_micro_contact_bridge.py",
    "tests/runtime/test_named_hero_ammunition_persistence.py",
    "tests/runtime/test_combat_completion_edges.py",
    "tests/runtime/test_combat_narration_contract.py",
    "tests/runtime/test_mount_phase_attrition.py",
    "tests/runtime/test_personal_projectile_recovery.py",
}
FORMATION_EQUIPMENT_TESTS = {
    "tests/runtime/test_formation_equipment_repair.py",
    "tests/runtime/test_combat_cohort_integration.py",
    "tests/runtime/test_mount_phase_attrition.py",
}
BATTLEFIELD_TESTS = {
    "tests/runtime/test_operational_battlefield.py",
    "tests/runtime/test_battlefield_scale_model.py",
}
PLAY_FAILURE_TESTS = {
    "tests/runtime/test_play_failure_matrix.py",
    "tests/runtime/test_play_regression_hardening.py",
}
SCHEMA_PARITY_TESTS = {"tests/runtime/test_closed_schema_runtime_write_parity.py"}
CAMPAIGN_MARCH_TESTS = {"tests/runtime/test_campaign_march_lifecycle.py"}
BATTLE_LIFECYCLE_TESTS = {"tests/runtime/test_battle_lifecycle.py"}
BATTLE_SUSTAINMENT_TESTS = {"tests/runtime/test_battlefield_sustainment.py"}
FORMATION_SUBSISTENCE_TESTS = {"tests/runtime/test_formation_subsistence.py"}
TIME_INTEGRATION_TESTS = {"tests/runtime/test_time_integration.py"}
SIEGE_COMBAT_TESTS = {"tests/runtime/test_siege_bed_crossbow_integration.py"}
TRAINING_TESTS = {
    "tests/runtime/test_deterministic_training_programs.py",
    "tests/runtime/test_training_session.py",
    "tests/runtime/test_standing_training_settlement.py",
    "tests/runtime/test_institutional_officer_training_standard.py",
}
FATIGUE_TESTS = {"tests/runtime/test_fatigue_recovery.py"}
INSTRUCTOR_TESTS = {"tests/runtime/test_instructor_time_and_quality.py"}
TRAINING_FACILITY_TESTS = {"tests/runtime/test_training_facilities.py"}
PROGRESSION_INTEGRITY_TESTS = {"tests/runtime/test_progression_integrity.py", "tests/runtime/test_current_development_routing.py", "tests/runtime/test_activity_living_world.py"}
UNIT_ESTABLISHMENT_TESTS = {
    "tests/runtime/test_scale_aware_command_establishment.py",
    "tests/runtime/test_current_command_hierarchy.py",
}
MILITARY_HIERARCHY_TESTS = {
    "tests/runtime/test_current_command_hierarchy.py",
    "tests/runtime/test_command_group_death_cleanup.py",
    "tests/runtime/test_army_organization_lifecycle.py",
}
STANDING_ARMY_MOBILIZATION_TESTS = {"tests/runtime/test_standing_army_mobilization.py"}
QIN_CAMPAIGN_HANDOFF_TESTS = {
    "tests/runtime/test_qin_command_support_flow.py",
    "tests/runtime/test_qin_command_support_mid_advance.py",
    "tests/runtime/test_qin_campaign_command_starvation_regression.py",
    "tests/runtime/test_campaign_command_to_arrival_e2e.py",
    "tests/runtime/test_command_staff_continuity.py",
    "tests/runtime/test_vitality_qin_briefing.py",
}
STATE_LEVY_TESTS = {"tests/runtime/test_state_levy_and_field_training.py"}
BATTLE_COMMAND_TESTS = {"tests/runtime/test_battle_command.py"}
CAMPAIGN_COMMAND_CYCLE_TESTS = {"tests/runtime/test_campaign_command_cycle.py"}
CAMPAIGN_REMOTE_HANDOFF_TESTS = {"tests/runtime/test_campaign_remote_command_handoff.py"}
CAMPAIGN_ORDER_AUTHORITY_TESTS = {
    "tests/runtime/test_current_operational_order_authority.py",
    "tests/runtime/test_campaign_command_decision_lifecycle.py",
    "tests/runtime/test_campaign_command_delivery_causality.py",
    "tests/runtime/test_startup_integrity.py",
    "tests/runtime/test_campaign_entry_authority.py",
    "tests/runtime/test_qin_operational_order_guard.py",
    "tests/runtime/test_fresh_snapshot_campaign_regressions.py",
}
SCHEDULER_TESTS = {"tests/runtime/test_scheduler_frontier.py", "tests/runtime/test_production_living_world.py", "tests/runtime/test_time_integration.py", "tests/runtime/test_hosted_horizon_performance.py"}
WORLD_ARC_REPORT_TESTS = {
    "tests/runtime/test_world_arc_report_salience.py",
    "tests/runtime/test_world_arc_player_safe_handoff.py",
}
SCENE_SESSION_TESTS = {
    "tests/runtime/test_scene_session_contract.py",
    "tests/runtime/test_interaction_surface.py",
    "tests/runtime/test_scene_continuity.py",
    "tests/runtime/test_scene_liveness_projection.py",
}
SEMANTIC_WAIT_TESTS = {
    "tests/runtime/test_semantic_wait_policy.py",
    "tests/runtime/test_time_integration.py",
}
DEPLOYMENT_TESTS = {
    "tests/runtime/test_bootstrap_repository_replacement.py",
    "tests/runtime/test_main_branch_bootstrap.py",
    "tests/runtime/test_branch_bootstrap.py",
    "tests/runtime/test_deployment_attestation.py",
}
DIRECTOR_CONTEXT_TESTS = {
    "tests/runtime/test_open_world_gm_architecture.py",
    "tests/runtime/test_live_campaign_planning_projection.py",
}
RELEASE_HARNESS_TESTS = {"tests/runtime/test_release_suite_harness_policy.py", "tests/runtime/test_release_campaign_state_contract.py"}
PLAYABILITY_DELIVERY_TESTS = {"tests/playability/test_delivery_chain_contract.py"}
PLAYABILITY_HANDOFF_TESTS = {"tests/playability/test_campaign_report_projection_fuzz.py"}
PLAYABILITY_PACKAGING_TESTS = {"tests/playability/test_release_packaging_contract.py"}
PLAYABILITY_LAB_SCOPE_TESTS = {"tests/playability/test_playability_lab_scope.py"}
MERCENARY_TESTS = {
    "tests/runtime/test_mercenary_tacticalization.py",
    "tests/runtime/test_house_tang_growth_and_mercenary_policy.py",
    "tests/runtime/test_second_order_audit_repairs.py",
}
PRISONER_TESTS = {
    "tests/runtime/test_prisoner_system.py",
    "tests/runtime/test_second_order_audit_repairs.py",
}


def normalize(value: str) -> str:
    path = Path(value)
    try:
        path = path.resolve().relative_to(ROOT.resolve())
    except (ValueError, OSError):
        pass
    return path.as_posix().lstrip("./")


def select(paths: list[str]) -> list[str]:
    selected: set[str] = set(ENGINE_CORE_TESTS)
    for raw in paths:
        path = normalize(raw)
        if path.startswith("runtime/sword_runtime/api/"):
            selected.update(API_TESTS)
            if path == "runtime/sword_runtime/api/mcp.py":
                selected.update(PLAYABILITY_DELIVERY_TESTS)
            if path == "runtime/sword_runtime/api/stable_operations.py":
                selected.add("tests/runtime/test_command_group_play_context.py")
        if path in {
            "runtime/sword_runtime/bootstrap.py",
            "runtime/sword_runtime/branch_bootstrap.py",
            "runtime/sword_runtime/release_baseline.py",
            "runtime/sword_runtime/deployment_attestation.py",
            "railway.toml",
            "docs/RUNTIME_SERVICE_DEPLOYMENT.md",
            "docs/RAILWAY_IAC_MIGRATION.md",
        }:
            selected.update(DEPLOYMENT_TESTS)
            selected.update(PLAYABILITY_DELIVERY_TESTS)
        if path == "runtime/sword_runtime/gm_skill_contract.py":
            selected.update(PLAYABILITY_DELIVERY_TESTS)
        if path == "runtime/sword_runtime/api/gm_scene_context.py":
            selected.update(DIRECTOR_CONTEXT_TESTS)
        if path in {
            "tools/run_release_suite.py", "tools/run_pytest_module.py", "tools/test_changed.py",
            "tools/validate_release.py", "tools/verify_release_state.py", "tools/mutation_audit.py",
            "tools/playability_lab.py", "tools/sync_gm_skill_contract.py", "tools/package_release.py",
            "runtime/contracts/release-campaign-state.json",
        }:
            selected.update(RELEASE_HARNESS_TESTS)
            selected.update(PLAYABILITY_DELIVERY_TESTS)
            if path == "runtime/contracts/release-campaign-state.json":
                selected.update(DEPLOYMENT_TESTS)
            if path == "tools/package_release.py":
                selected.update(PLAYABILITY_PACKAGING_TESTS)
            if path in {"tools/playability_lab.py"}:
                selected.update(PLAYABILITY_LAB_SCOPE_TESTS)
        if (
            path == "runtime/sword_runtime/scene_sessions.py"
            or path == "runtime/sword_runtime/api/interaction_surface.py"
            or path.startswith("game/schemas/sword-scene-")
            or path == "game/schemas/sword-interaction-attempt-ledger.schema.json"
            or path.startswith("state/history/scene-speech/")
            or path in {"state/index/active-scene-session.json", "state/index/scene-history-head.json", "state/index/interaction-attempts.json"}
        ):
            selected.update(SCENE_SESSION_TESTS)
        if (
            path in {
                "runtime/sword_runtime/scene_sessions.py",
                "runtime/sword_runtime/api/interaction_surface.py",
                "runtime/sword_runtime/api/stable_operations.py",
                "runtime/sword_runtime/api/warfare_operations.py",
            }
            or "scene-session" in path
            or "scene-history" in path
            or "interaction-attempt-ledger" in path
        ):
            selected.update(SCENE_SESSION_TESTS)
        if path in {
            "runtime/sword_runtime/downtime.py",
            "runtime/sword_runtime/time_integration.py",
            "runtime/sword_runtime/campaign_command_cycle.py",
        }:
            selected.update(SEMANTIC_WAIT_TESTS)
        if (
            path == "runtime/sword_runtime/geography.py"
            or path == "game/data/world/locations.json"
            or path == "game/data/world/location-functions.json"
            or path == "game/data/world/routes.json"
            or path == "game/data/world/fortification-profiles.json"
            or path == "game/data/world/minor-polities.json"
            or path == "game/data/mechanics/travel-geography.json"
            or path.startswith("state/population/")
            or path.startswith("state/forces/")
            or path.startswith("state/mounts/")
            or path.startswith("state/merc/")
            or path.startswith("state/fortifications/")
            or path.startswith("state/territory/")
            or path == "state/contract/tang-supply-contracts.json"
            or path == "tools/validate_world_geography.py"
        ):
            selected.update(GEOGRAPHY_TESTS)
        if path in {"runtime/sword_runtime/environment.py", "game/data/world/environment-climates.json", "runtime/contracts/environment.json", "tests/runtime/test_environment.py"}:
            selected.update(ENVIRONMENT_TESTS)
            selected.update(API_TESTS)
            selected.update(CIVIL_WORLD_TESTS)
            selected.update(COHORT_TESTS)
        if path in {"runtime/sword_runtime/scheduler_frontier.py", "state/runtime.json"}:
            selected.update(SCHEDULER_TESTS)
            selected.update(LIVING_WORLD_TESTS)
        if path == "runtime/sword_runtime/production_planner.py":
            selected.update(SCHEDULER_TESTS)
            selected.update(ENVIRONMENT_TESTS)
            selected.update(TRAINING_TESTS)
            selected.update(FATIGUE_TESTS)
            selected.update(INSTRUCTOR_TESTS)
            selected.update(GROUP_ACTION_TESTS)
            selected.update(CIVIL_WORLD_TESTS)
            selected.update(COHORT_TESTS)
            selected.update(PLAYER_STORY_TESTS)
            selected.update(QIN_COMMAND_TESTS)
            selected.update(MILITARY_CAREER_LOYALTY_TESTS)
        if path in {"runtime/sword_runtime/command_contracts.py", "game/data/mechanics/command-catalog.json", "game/data/mechanics/command-hostile-contracts.json"}:
            selected.update(COMMAND_TESTS)
        if (
            path.startswith("runtime/sword_runtime/living_world.py")
            or path.startswith("runtime/sword_runtime/causal_living_world.py")
            or path.startswith("runtime/sword_runtime/production_living_world.py")
            or path.startswith("runtime/sword_runtime/systems/campaign_events.py")
            or path.startswith("runtime/sword_runtime/campaign_event_planner.py")
            or path.startswith("runtime/sword_runtime/world_arcs.py")
            or path.startswith("runtime/sword_runtime/causal_event_store.py")
        ):
            selected.update(LIVING_WORLD_TESTS)
            if path.startswith("runtime/sword_runtime/causal_living_world.py"):
                selected.update(SCHEDULER_TESTS)
            if path.startswith("runtime/sword_runtime/world_arcs.py"):
                selected.update(WORLD_ARC_REPORT_TESTS)
            if path.startswith("runtime/sword_runtime/causal_event_store.py"):
                selected.add("tests/runtime/test_causal_connections.py")
        if (
            path.startswith("runtime/sword_runtime/civil_world.py")
            or path.startswith("game/data/mechanics/civil-economy.json")
            or path.startswith("game/data/politics/faction-profiles.json")
            or path.startswith("state/markets/")
            or path.startswith("state/economy/private/")
            or path.startswith("state/contract/tang-supply-contracts.json")
            or path.startswith("game/schemas/sword-polity.schema.json")
            or path.startswith("game/schemas/sword-diplomatic-proposal.schema.json")
            or path.startswith("state/politics/polities/")
            or path.startswith("state/politics/diplomatic-proposals/")
            or path.startswith("state/population/")
            or path.startswith("state/territory/")
            or path.startswith("state/factions/")
        ):
            selected.update(CIVIL_WORLD_TESTS)
            selected.update(STRATEGIC_DEPTH_TESTS)
        if (
            path.startswith("runtime/sword_runtime/history_store.py")
            or path.startswith("game/schemas/sword-history-segment.schema.json")
            or path.startswith("state/history/")
        ):
            selected.add("tests/runtime/test_history_store.py")
            selected.update(LIVING_WORLD_TESTS)
        if path == "runtime/sword_runtime/engine.py":
            # engine.py is a monolithic dispatcher. A blanket all-subsystem run
            # created unrelated baseline failures and made CI noisy rather than
            # diagnostic. Keep cross-cutting engine invariants here; companion
            # owner files and regression tests changed in the same PR select the
            # subsystem-specific suites.
            selected.update(ENGINE_CORE_TESTS)
        if (
            path.startswith("runtime/sword_runtime/personal_combat.py")
            or path.startswith("runtime/sword_runtime/combat_tactics.py")
            or path.startswith("runtime/sword_runtime/combat_commitment.py")
            or path.startswith("runtime/sword_runtime/combat_geometry.py")
            or path.startswith("runtime/sword_runtime/combat_doctrine.py")
            or path.startswith("runtime/sword_runtime/anatomy.py")
            or path.startswith("runtime/sword_runtime/contact_physics.py")
            or path.startswith("runtime/sword_runtime/combat_capability.py")
            or path.startswith("runtime/sword_runtime/battle_trace.py")
            or path.startswith("runtime/sword_runtime/officer_cadre.py")
            or path.startswith("game/data/mechanics/combat.json")
            or path.startswith("game/data/mechanics/injury.json")
            or path.startswith("game/rules/combat.md")
            or path.startswith("game/data/mil/doctrine-records/doc.tang_wei.personal_combat.json")
            or path.startswith("game/schemas/combat-mechanics.schema.json")
            or path.startswith("game/schemas/injury-mechanics.schema.json")
        ):
            selected.update(COMBAT_TESTS)
            if path.startswith("runtime/sword_runtime/combat_capability.py"):
                selected.update(PLAY_FAILURE_TESTS)
        if path.startswith("runtime/sword_runtime/fortified_site_runtime.py") or path.startswith("game/data/mechanics/siege.json"):
            selected.update(SIEGE_COMBAT_TESTS)
        if (
            path.startswith("runtime/sword_runtime/battle_sustainment.py")
            or path.startswith("game/data/mechanics/battlefield-sustainment.json")
            or path.startswith("game/schemas/battlefield-sustainment-rules.schema.json")
            or path.startswith("game/data/mechanics/unit-duties.json")
            or path.startswith("game/schemas/unit-duty-registry.schema.json")
        ):
            selected.update(BATTLE_SUSTAINMENT_TESTS)
        if (
            path.startswith("runtime/sword_runtime/battlefield.py")
            or path.startswith("game/data/mechanics/battlefield-operations.json")
            or path.startswith("game/schemas/sword-operational-battlefield.schema.json")
        ):
            selected.update(BATTLEFIELD_TESTS)
            selected.update(BATTLE_LIFECYCLE_TESTS)
            selected.update(COMBAT_TESTS)
            selected.update(PLAY_FAILURE_TESTS)
            selected.update(SCHEMA_PARITY_TESTS)
        if path in {
            "runtime/sword_runtime/military_echelon.py",
            "runtime/sword_runtime/campaign_march_lifecycle.py",
            "runtime/sword_runtime/campaign_command_cycle.py",
            "runtime/sword_runtime/campaign_briefing.py",
            "runtime/sword_runtime/api/stable_operations.py",
            "runtime/sword_runtime/downtime.py",
            "runtime/sword_runtime/time_integration.py",
        }:
            selected.update(PLAY_FAILURE_TESTS)
        if path in {
            "runtime/sword_runtime/campaign_march_lifecycle.py",
            "runtime/sword_runtime/battle_command.py",
            "game/schemas/sword-operation.schema.json",
            "game/schemas/sword-operational-battlefield.schema.json",
        }:
            selected.update(SCHEMA_PARITY_TESTS)
        if path == "runtime/sword_runtime/campaign_march_lifecycle.py":
            selected.update(CAMPAIGN_MARCH_TESTS)
        if (
            path.startswith("runtime/sword_runtime/battle_lifecycle.py")
            or path.startswith("game/data/mechanics/battle-lifecycle.json")
            or path.startswith("game/schemas/sword-battle-lifecycle.schema.json")
        ):
            selected.update(BATTLE_LIFECYCLE_TESTS)
            selected.update(BATTLEFIELD_TESTS)
            selected.update(BATTLE_SUSTAINMENT_TESTS)
        if (
            path.startswith("runtime/sword_runtime/field_supply.py")
            or path.startswith("runtime/sword_runtime/formation_subsistence.py")
            or path.startswith("game/data/mechanics/logistics.json")
            or path.startswith("game/schemas/logistics-mechanics.schema.json")
        ):
            selected.update(FORMATION_SUBSISTENCE_TESTS)
            selected.update(BATTLE_LIFECYCLE_TESTS)
            selected.update(BATTLE_SUSTAINMENT_TESTS)
        if path.startswith("runtime/sword_runtime/time_integration.py") or path.startswith("runtime/sword_runtime/production_runtime_planner.py"):
            selected.update(TIME_INTEGRATION_TESTS)
            selected.update(SCHEDULER_TESTS)
        if (
            path.startswith("runtime/sword_runtime/formation_armory_issue.py")
            or path.startswith("runtime/sword_runtime/formation_replacement.py")
            or path.startswith("game/data/mechanics/outfitting.json")
            or path.startswith("game/data/loadouts.json")
        ):
            selected.update(FORMATION_EQUIPMENT_TESTS)
        if path.startswith("runtime/sword_runtime/campaign_depth.py"):
            selected.add("tests/runtime/test_structural_injury_physiology.py")
            selected.update(PLAY_FAILURE_TESTS)
            selected.add("tests/runtime/test_command_group_deterministic_training.py")
            selected.update(TRAINING_TESTS)
            selected.update(FATIGUE_TESTS)
            selected.update(INSTRUCTOR_TESTS)
        if path.startswith("runtime/sword_runtime/strategic_war_operations.py"):
            selected.update(STRATEGIC_DEPTH_TESTS)
        if path in {
            "runtime/sword_runtime/formation_replacement.py",
            "runtime/sword_runtime/strategic_war_planning.py",
            "game/data/mechanics/military-career.json",
        }:
            selected.update(STANDING_ARMY_MOBILIZATION_TESTS)
            selected.update(MILITARY_HIERARCHY_TESTS)
            selected.update(STRATEGIC_DEPTH_TESTS)
        if path in {
            "runtime/sword_runtime/command_staff_movement.py",
            "runtime/sword_runtime/qin_command_support_flow.py",
            "runtime/sword_runtime/campaign_briefing.py",
        }:
            selected.update(QIN_CAMPAIGN_HANDOFF_TESTS)
        if path in {
            "runtime/sword_runtime/api/command_discovery.py",
            "runtime/sword_runtime/api/gm_scene_context.py",
            "runtime/sword_runtime/api/stable_operations.py",
            "runtime/sword_runtime/campaign_command_cycle.py",
            "runtime/sword_runtime/campaign_report_projection.py",
            "runtime/sword_runtime/campaign_command_decision.py",
            "runtime/sword_runtime/campaign_communications.py",
            "plugins/sword-and-banners/skill/sword-and-banners-game-master/references/waiting-and-handoffs.md",
            "tests/runtime/test_campaign_remote_command_handoff.py",
        }:
            selected.update(CAMPAIGN_REMOTE_HANDOFF_TESTS)
            selected.update(PLAYABILITY_HANDOFF_TESTS)
        if path in {
            "runtime/sword_runtime/operation_routing.py",
            "runtime/sword_runtime/campaign_command_decision.py",
            "runtime/sword_runtime/campaign_command_delivery.py",
            "runtime/sword_runtime/production_runtime_planner.py",
            "runtime/sword_runtime/campaign_briefing.py",
            "runtime/sword_runtime/campaign_command_cycle.py",
            "runtime/sword_runtime/campaign_command_requests.py",
            "runtime/sword_runtime/campaign_arrival_lifecycle.py",
            "runtime/sword_runtime/campaign_march_lifecycle.py",
            "runtime/sword_runtime/campaign_follow_on_order.py",
            "runtime/sword_runtime/campaign_follow_on_semantics.py",
            "runtime/sword_runtime/campaign_subordinate_orders.py",
            "runtime/sword_runtime/qin_command_support_flow.py",
            "runtime/sword_runtime/qin_command_support_reconciliation.py",
            "runtime/sword_runtime/qin_operational_order_guard.py",
            "runtime/sword_runtime/sovereign_campaign_authority.py",
            "runtime/sword_runtime/sovereign_campaign_authority_mixin.py",
            "runtime/sword_runtime/command_staff_movement.py",
            "runtime/sword_runtime/battle_command.py",
            "runtime/sword_runtime/campaign_depth.py",
            "runtime/sword_runtime/api/stable_operations.py",
            "runtime/sword_runtime/startup_integrity.py",
        }:
            selected.update(CAMPAIGN_ORDER_AUTHORITY_TESTS)
        if path in {
            "runtime/sword_runtime/state_levy.py",
            "game/data/mil/autonomy-blueprints.json",
        }:
            selected.update(STATE_LEVY_TESTS)
        if path in {
            "runtime/sword_runtime/battle_command.py",
            "game/schemas/sword-operation.schema.json",
        }:
            selected.update(BATTLE_COMMAND_TESTS)
            selected.update(PLAY_FAILURE_TESTS)
            selected.update(SCHEMA_PARITY_TESTS)
        if (
            path.startswith("runtime/sword_runtime/campaign_command_cycle.py")
            or path.startswith("runtime/sword_runtime/court_presence.py")
            or path.startswith("game/data/mechanics/campaign-command.json")
            or path.startswith("state/index/court-attendance-index.json")
        ):
            selected.update(CAMPAIGN_COMMAND_CYCLE_TESTS)
            selected.update(QIN_CAMPAIGN_HANDOFF_TESTS)
            selected.update(TIME_INTEGRATION_TESTS)
            selected.update(PLAY_FAILURE_TESTS)
        if path.startswith("state/fortifications/index.json"):
            selected.update(PLAY_FAILURE_TESTS)
            selected.update(SCHEMA_PARITY_TESTS)
        if path.startswith("runtime/sword_runtime/civil_world.py"):
            selected.add("tests/runtime/test_uncapped_character_stats.py")
        if (
            path.startswith("runtime/sword_runtime/training_programs.py")
            or path.startswith("runtime/sword_runtime/training_session.py")
            or path.startswith("runtime/sword_runtime/training_instructors.py")
            or path.startswith("runtime/sword_runtime/training_time.py")
            or path.startswith("runtime/sword_runtime/training_facilities.py")
            or path.startswith("runtime/sword_runtime/development.py")
            or path.startswith("runtime/sword_runtime/standing_training.py")
            or path.startswith("runtime/sword_runtime/activity_living_world.py")
            or path.startswith("runtime/sword_runtime/progression_integrity.py")
            or path.startswith("runtime/sword_runtime/service_runtime.py")
            or path.startswith("game/data/mil/deterministic-training-programs.json")
            or path.startswith("game/data/mil/training-records/")
            or path.startswith("game/data/mechanics/training.json")
            or path.startswith("game/data/mechanics/training-session.json")
            or path.startswith("game/schemas/deterministic-training-registry.schema.json")
            or path.startswith("game/schemas/training-record.schema.json")
        ):
            selected.update(TRAINING_TESTS)
            if path.startswith("runtime/sword_runtime/standing_training.py"):
                selected.update(PLAY_FAILURE_TESTS)
            if path.startswith("runtime/sword_runtime/training_instructors.py") or path.startswith("runtime/sword_runtime/training_time.py"):
                selected.update(INSTRUCTOR_TESTS)
            if path.startswith("runtime/sword_runtime/training_facilities.py") or path.startswith("runtime/sword_runtime/training_instructors.py") or path.startswith("runtime/sword_runtime/training_programs.py"):
                selected.update(TRAINING_FACILITY_TESTS)
        if (
            path.startswith("runtime/sword_runtime/progression_integrity.py")
            or path.startswith("runtime/sword_runtime/activity_living_world.py")
            or path.startswith("runtime/sword_runtime/service_runtime.py")
            or path.startswith("runtime/sword_runtime/cohort_tx_support.py")
        ):
            selected.update(PROGRESSION_INTEGRITY_TESTS)
        if path.startswith("runtime/sword_runtime/fatigue.py") or path.startswith("game/data/mechanics/fatigue.json") or path.startswith("game/schemas/fatigue-mechanics.schema.json"):
            selected.update(FATIGUE_TESTS)
            selected.update(GROUP_ACTION_TESTS)
        if (
            path.startswith("runtime/sword_runtime/mercenary_contracts.py")
            or path.startswith("state/merc/")
        ):
            selected.update(MERCENARY_TESTS)
        if (
            path.startswith("runtime/sword_runtime/prisoner_system.py")
            or path.startswith("state/prisoners/")
        ):
            selected.update(PRISONER_TESTS)
        if path.startswith("runtime/sword_runtime/tx/"):
            selected.update(TRANSACTION_TESTS)
        if path.startswith("runtime/sword_runtime/api/world_reference.py") or path.startswith("game/data/world/noble-houses.json"):
            selected.update(REFERENCE_TESTS)
        if (
            path.startswith("state/politics/treaties.json")
            or path.startswith("game/schemas/sword-treaty-registry.schema.json")
            or path.startswith("game/schemas/sword-diplomatic-proposal.schema.json")
            or path.startswith("state/politics/diplomatic-proposals/")
            or path.startswith("state/institutions/")
        ):
            selected.update(CIVIL_WORLD_TESTS)
        if path.startswith("game/schemas/sword-court-case.schema.json"):
            selected.update(STRATEGIC_DEPTH_TESTS)
        if path.startswith("state/arc/") or path.startswith("game/schemas/event-registry.schema.json"):
            selected.add("tests/runtime/test_world_arcs.py")
            if path.startswith("game/schemas/event-registry.schema.json"):
                selected.add("tests/runtime/test_causal_connections.py")
        if path.startswith("game/schemas/sword-causal-event-") or path.startswith("state/event/archive/") or path.startswith("state/event/index/route_"):
            selected.add("tests/runtime/test_causal_connections.py")
            selected.add("tests/runtime/test_world_arcs.py")
        if path.startswith("runtime/sword_runtime/unit_establishment.py"):
            selected.update(UNIT_ESTABLISHMENT_TESTS)
        if path.startswith("runtime/sword_runtime/bastion_personnel.py"):
            selected.add("tests/runtime/test_bastion_personnel_lifecycle.py")
            selected.update(TRAINING_TESTS)
            selected.update(INSTRUCTOR_TESTS)
        if path.startswith("runtime/sword_runtime/downtime.py"):
            selected.update(TRAINING_TESTS)
            selected.update(FATIGUE_TESTS)
            selected.update(INSTRUCTOR_TESTS)
            selected.update(SCENE_SESSION_TESTS)
        if path.startswith("runtime/sword_runtime/warfare_depth.py"):
            selected.add("tests/runtime/test_scale_aware_command_establishment.py")
            selected.update(TRAINING_TESTS)
            selected.update(INSTRUCTOR_TESTS)
        if path.startswith("runtime/sword_runtime/player_group_actions.py"):
            selected.update(GROUP_ACTION_TESTS)
            selected.update(TRAINING_TESTS)
            selected.update(FATIGUE_TESTS)
        if path.startswith("runtime/sword_runtime/player_story_flow.py"):
            selected.update(PLAYER_STORY_TESTS)
            selected.update(LIVING_WORLD_TESTS)
        if path.startswith("runtime/sword_runtime/vitality.py"):
            # Vitality is a read-only diagnostic projection. Keep its changed-path
            # gate focused on player-facing/liveness diagnostics instead of
            # rerunning the expensive 120-day deterministic world replay, which
            # belongs to deliberate release/soak verification.
            selected.update(PLAYER_STORY_TESTS)
            selected.update(VITALITY_TESTS)
            selected.add("tests/runtime/test_campaign_event_liveness.py")
        if path.startswith("game/data/mechanics/house-tang-programs.json"):
            selected.update(COHORT_TESTS)
        if (
            path.startswith("runtime/sword_runtime/qin_command_progression.py")
            or path.startswith("game/data/mechanics/career-progression.json")
            or path.startswith("runtime/sword_runtime/api/warfare_operations.py")
        ):
            selected.update(QIN_COMMAND_TESTS)
            selected.update(PLAYER_STORY_TESTS)
            selected.update(COHORT_TESTS)
            selected.update(API_TESTS)
        if (
            path.startswith("runtime/sword_runtime/military_career_loyalty.py")
            or path.startswith("runtime/sword_runtime/military_career_loyalty_integrity.py")
            or path.startswith("runtime/sword_runtime/military_career_loyalty_politics.py")
            or path.startswith("runtime/sword_runtime/military_career_service_authority.py")
            or path.startswith("game/data/mechanics/military-career-loyalty.json")
            or path.startswith("game/schemas/sword-military-career-petition.schema.json")
        ):
            selected.update(MILITARY_CAREER_LOYALTY_TESTS)
            selected.update(LIVING_WORLD_TESTS)
            selected.update(COHORT_TESTS)
            selected.update(PERSON_TESTS)
            selected.update(PLAYER_STORY_TESTS)
        if (
            path.startswith("runtime/sword_runtime/cohort_personnel.py")
            or path.startswith("runtime/sword_runtime/cohort_tx_support.py")
            or path.startswith("runtime/sword_runtime/combat_capability.py")
            or path.startswith("runtime/sword_runtime/force_cohort_living_world.py")
            or path.startswith("runtime/sword_runtime/house_tang_development.py")
            or path.startswith("game/data/mil/combat-role-profiles.json")
            or path.startswith("game/data/mil/standing-force-capability-profiles.json")
            or path.startswith("game/data/mechanics/formation.json")
            or path.startswith("game/data/mechanics/economy.json")
        ):
            selected.update(COHORT_TESTS)
            if path.startswith("runtime/sword_runtime/combat_capability.py") or path.startswith("game/data/mechanics/formation.json"):
                selected.update(FORMATION_EQUIPMENT_TESTS)
                selected.update(COMBAT_TESTS)
            if path.startswith("runtime/sword_runtime/force_cohort_living_world.py"):
                selected.update(MILITARY_CAREER_LOYALTY_TESTS)
                selected.update(LIVING_WORLD_TESTS)
        if path.startswith("runtime/sword_runtime/recruitment_campaigns.py") or path.startswith("runtime/sword_runtime/cohort_personnel.py") or path.startswith("game/data/mil/recruitment-cohort-profiles.json"):
            selected.update(PERSON_TESTS)
            selected.update(STRATEGIC_DEPTH_TESTS)
        if path in {"railway.toml", "pyproject.toml", "requirements.txt"} or path.startswith("runtime/contracts/"):
            selected.update(DEFAULT_TESTS)
            selected.update(PLAYABILITY_DELIVERY_TESTS)
        if path.startswith("plugins/sword-and-banners/skill/"):
            selected.update(DEFAULT_TESTS)
            selected.update(PLAYABILITY_DELIVERY_TESTS)
            selected.update({
                "tests/runtime/test_skill_repository_contract.py",
                "tests/runtime/test_interaction_depth_skill_contract.py",
                "tests/runtime/test_skill_contact_combat_packaging_guards.py",
                "tests/runtime/test_cross_game_audit_contract.py",
                "tests/runtime/test_campaign_movement_intent_skill_handoff.py",
            })
        if path == "state/meta.json":
            selected.add("tests/runtime/test_campaign_rebaseline.py")
        if path.startswith("tests/runtime/") and path.endswith(".py") and path != "tests/runtime/test_runtime_invariants.py":
            selected.add(path)
        if path.startswith("tests/playability/") and path.endswith(".py"):
            selected.add(path)
    if not selected:
        selected.update(DEFAULT_TESTS)
    return sorted(path for path in selected if (ROOT / path).is_file())


def _clean_path(path: Path, *, cwd: Path) -> None:
    # Native rm is materially faster than Python walking Git-backed disposable
    # campaign clones. Cleanup is test scaffolding only and never touches the
    # canonical repository tree. It is also bounded: a pathological filesystem
    # cleanup must not turn a green targeted gate into an infinite hang.
    try:
        subprocess.run(
            ["rm", "-rf", str(path)],
            cwd=cwd,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        print(f"test_changed: cleanup timeout ignored for disposable path {path}", flush=True)


def _fingerprint_path(digest: "hashlib._Hash", rel: str) -> None:
    digest.update(rel.encode("utf-8"))
    digest.update(b"\0")
    path = ROOT / rel
    if path.is_file():
        digest.update(path.read_bytes())
    elif path.is_dir():
        for child in sorted(p for p in path.rglob("*") if p.is_file()):
            child_rel = child.relative_to(ROOT).as_posix()
            digest.update(child_rel.encode("utf-8"))
            digest.update(b"\0")
            digest.update(child.read_bytes())
    else:
        digest.update(b"<missing>")
    digest.update(b"\0")


def _checkpoint_key(changed_paths: list[str], tests: list[str]) -> str:
    # A checkpoint is reusable only for the exact changed-source/test content.
    # This prevents an old green module from surviving a code or regression edit.
    digest = hashlib.sha256()
    for rel in sorted({normalize(path) for path in changed_paths}):
        _fingerprint_path(digest, rel)
    for rel in sorted({"tools/test_changed.py", "tools/run_pytest_module.py", *tests}):
        _fingerprint_path(digest, rel)
    return digest.hexdigest()[:24]


def _read_checkpoint_payload(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_checkpoint(path: Path, tests: list[str]) -> set[str]:
    payload = _read_checkpoint_payload(path)
    passed = payload.get("passed", [])
    valid = set(tests)
    return {str(test) for test in passed if isinstance(test, str) and test in valid}


def _load_node_checkpoint(path: Path, tests: list[str]) -> dict[str, set[str]]:
    payload = _read_checkpoint_payload(path)
    raw = payload.get("passed_nodes", {})
    if not isinstance(raw, dict):
        return {}
    valid = set(tests)
    result: dict[str, set[str]] = {}
    for module, nodes in raw.items():
        if module not in valid or not isinstance(nodes, list):
            continue
        result[str(module)] = {str(node) for node in nodes if isinstance(node, str)}
    return result


def _save_checkpoint(
    path: Path,
    passed: set[str],
    passed_nodes: dict[str, set[str]] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if passed_nodes is None:
        passed_nodes = _load_node_checkpoint(path, list(passed))
    payload = {
        "passed": sorted(passed),
        "passed_nodes": {module: sorted(nodes) for module, nodes in sorted(passed_nodes.items()) if nodes},
        "updated_at": int(time.time()),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _kill_process_group(proc: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except ProcessLookupError:
            pass


def _run_bounded(
    args: list[str],
    *,
    cwd: Path,
    timeout_seconds: int,
) -> tuple[int | None, bool, str]:
    """Run one isolated test command without letting descendants hold the gate open."""
    with tempfile.NamedTemporaryFile(mode="w+b", delete=True) as log:
        proc = subprocess.Popen(
            args,
            cwd=cwd,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        timed_out = False
        try:
            proc.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_process_group(proc)
        log.flush()
        log.seek(0)
        output = log.read().decode("utf-8", errors="replace")
    if output:
        print(output, end="" if output.endswith("\n") else "\n", flush=True)
    return proc.returncode, timed_out, output


def _collect_nodes(module: str, *, cwd: Path) -> list[str]:
    result = subprocess.run(
        [sys.executable, "tools/run_pytest_module.py", "--collect-only", "-q", module],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )
    nodes = [line.strip() for line in result.stdout.splitlines() if line.strip().startswith(module + "::")]
    if not nodes:
        raise RuntimeError(f"test_changed: no pytest nodes collected for {module}")
    return nodes


def _certify_module_nodes(
    module: str,
    *,
    index: int,
    total: int,
    token: str,
    cwd: Path,
    run_root: Path,
    passed: set[str],
    passed_nodes: dict[str, set[str]],
    checkpoint_path: Path | None,
) -> None:
    nodes = _collect_nodes(module, cwd=cwd)
    already = passed_nodes.setdefault(module, set())
    for node_index, node in enumerate(nodes, start=1):
        if node in already:
            print(
                f"test_changed: [{index}/{total}] {module} node {node_index}/{len(nodes)} (checkpointed)",
                flush=True,
            )
            continue
        basetemp = run_root / f"{index:03d}-{token}-node-{node_index:03d}"
        print(
            f"test_changed: [{index}/{total}] {module} node {node_index}/{len(nodes)}",
            flush=True,
        )
        try:
            returncode, timed_out, _output = _run_bounded(
                [
                    sys.executable,
                    "tools/run_pytest_module.py",
                    "-q",
                    f"--basetemp={basetemp}",
                    node,
                ],
                cwd=cwd,
                timeout_seconds=SERIAL_NODE_TIMEOUTS.get(node, NODE_TIMEOUT_SECONDS),
            )
            if timed_out:
                raise RuntimeError(f"test_changed: node timed out: {node}")
            if returncode != 0:
                raise subprocess.CalledProcessError(int(returncode or 1), node)
            already.add(node)
            if checkpoint_path is not None:
                _save_checkpoint(checkpoint_path, passed, passed_nodes)
        finally:
            _clean_path(basetemp, cwd=cwd)
    if not set(nodes).issubset(already):
        raise RuntimeError(f"test_changed: node certification incomplete for {module}")
    passed.add(module)
    passed_nodes.pop(module, None)
    if checkpoint_path is not None:
        _save_checkpoint(checkpoint_path, passed, passed_nodes)


def _run_tests(tests: list[str], *, cwd: Path, checkpoint_path: Path | None = None) -> None:
    if not tests:
        return

    # A broad changed-path slice can select dozens of integration modules, many
    # of which clone the campaign repository. One monolithic pytest session keeps
    # every module's basetemp alive until final teardown and can exhaust filesystem
    # inodes before pytest has a chance to report a meaningful gameplay failure.
    # Run each maintained module in a fresh process and delete its disposable
    # basetemp immediately. Successful modules are checkpointed immediately so a
    # host/tool cutoff between modules does not throw away already-proven work.
    run_root = TEST_CHANGED_RUN_BASE / str(os.getpid())
    _clean_path(run_root, cwd=cwd)
    run_root.mkdir(parents=True, exist_ok=True)
    passed = _load_checkpoint(checkpoint_path, tests) if checkpoint_path is not None else set()
    passed_nodes = _load_node_checkpoint(checkpoint_path, tests) if checkpoint_path is not None else {}
    try:
        total = len(tests)
        for index, test in enumerate(tests, start=1):
            if test in passed:
                print(f"test_changed: [{index}/{total}] {test} (checkpointed)", flush=True)
                continue
            token = hashlib.sha256(test.encode("utf-8")).hexdigest()[:10]

            if test in NATIVE_TEMP_MODULES:
                # This module's Git-backed campaign fixture finishes promptly under
                # pytest's native temporary-directory lifecycle, but explicit
                # --basetemp teardown can spend longer deleting the cloned tree than
                # running the green tests. Keep the module isolated in its own
                # process without forcing the pathological cleanup path.
                print(f"test_changed: [{index}/{total}] {test} (native-temp isolation)", flush=True)
                returncode, timed_out, _output = _run_bounded(
                    [sys.executable, "tools/run_pytest_module.py", "-q", test],
                    cwd=cwd, timeout_seconds=NODE_TIMEOUT_SECONDS,
                )
                if timed_out:
                    print(
                        f"test_changed: native-temp module timeout; certifying every node: {test}",
                        flush=True,
                    )
                    _certify_module_nodes(
                        test, index=index, total=total, token=token, cwd=cwd, run_root=run_root,
                        passed=passed, passed_nodes=passed_nodes, checkpoint_path=checkpoint_path,
                    )
                    continue
                if returncode != 0:
                    raise subprocess.CalledProcessError(int(returncode or 1), test)
                passed.add(test)
                if checkpoint_path is not None:
                    _save_checkpoint(checkpoint_path, passed, passed_nodes)
                continue

            if test in NODE_ONLY_MODULES:
                _certify_module_nodes(
                    test, index=index, total=total, token=token, cwd=cwd, run_root=run_root,
                    passed=passed, passed_nodes=passed_nodes, checkpoint_path=checkpoint_path,
                )
                continue

            basetemp = run_root / f"{index:03d}-{token}"
            print(f"test_changed: [{index}/{total}] {test}", flush=True)
            try:
                returncode, timed_out, _output = _run_bounded(
                    [
                        sys.executable,
                        "tools/run_pytest_module.py",
                        "-q",
                        f"--basetemp={basetemp}",
                        test,
                    ],
                    cwd=cwd,
                    timeout_seconds=NODE_TIMEOUT_SECONDS,
                )
                if timed_out:
                    print(
                        f"test_changed: normal module timeout; certifying every node: {test}",
                        flush=True,
                    )
                    _clean_path(basetemp, cwd=cwd)
                    _certify_module_nodes(
                        test, index=index, total=total, token=token, cwd=cwd, run_root=run_root,
                        passed=passed, passed_nodes=passed_nodes, checkpoint_path=checkpoint_path,
                    )
                    continue
                if returncode != 0:
                    raise subprocess.CalledProcessError(int(returncode or 1), test)
                passed.add(test)
                if checkpoint_path is not None:
                    _save_checkpoint(checkpoint_path, passed, passed_nodes)
            finally:
                _clean_path(basetemp, cwd=cwd)
    finally:
        _clean_path(run_root, cwd=cwd)


def main(argv: list[str]) -> int:
    if not argv:
        raise SystemExit("usage: python tools/test_changed.py <changed paths...>")
    tests = select(argv)
    print("test_changed: " + " ".join(tests), flush=True)
    checkpoint_path = TEST_CHANGED_CHECKPOINT_DIR / f"{_checkpoint_key(argv, tests)}.json"

    # Extracted audit workspaces may run certification concurrently. Serialize
    # one changed-path gate per repository root so two processes cannot race a
    # content-keyed checkpoint or delete each other's disposable basetemps.
    import fcntl
    TEST_CHANGED_TMP_BASE.mkdir(parents=True, exist_ok=True)
    with TEST_CHANGED_LOCK_PATH.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        _run_tests(tests, cwd=ROOT, checkpoint_path=checkpoint_path)
        checkpoint_path.unlink(missing_ok=True)
    print("test_changed: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
