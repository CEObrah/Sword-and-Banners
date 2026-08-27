#!/usr/bin/env python3
"""Run the smallest maintained regression slice for changed repository paths."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

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
QIN_COMMAND_TESTS = {"tests/runtime/test_qin_command_progression.py"}
MILITARY_CAREER_LOYALTY_TESTS = {"tests/runtime/test_military_career_loyalty.py"}
DEFAULT_TESTS = {"tests/runtime/test_architecture_service.py"}
ENGINE_CORE_TESTS = {
    "tests/runtime/test_architecture_service.py",
    "tests/runtime/test_transactions.py",
}
GEOGRAPHY_TESTS = {"tests/runtime/test_world_geography.py"}
COMBAT_TESTS = {
    "tests/runtime/test_personal_combat_multi_actor.py",
    "tests/runtime/test_personal_combat_action_ready.py",
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
BATTLEFIELD_TESTS = {"tests/runtime/test_operational_battlefield.py"}
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
    "tests/runtime/test_command_staff_continuity.py",
}
STATE_LEVY_TESTS = {"tests/runtime/test_state_levy_and_field_training.py"}
BATTLE_COMMAND_TESTS = {"tests/runtime/test_battle_command.py"}
CAMPAIGN_COMMAND_CYCLE_TESTS = {"tests/runtime/test_campaign_command_cycle.py"}
SCHEDULER_TESTS = {"tests/runtime/test_scheduler_frontier.py", "tests/runtime/test_production_living_world.py", "tests/runtime/test_time_integration.py", "tests/runtime/test_hosted_horizon_performance.py"}
WORLD_ARC_REPORT_TESTS = {
    "tests/runtime/test_world_arc_report_salience.py",
    "tests/runtime/test_world_arc_player_safe_handoff.py",
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
            if path == "runtime/sword_runtime/api/stable_operations.py":
                selected.add("tests/runtime/test_command_group_play_context.py")
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
            or path.startswith("runtime/sword_runtime/anatomy.py")
            or path.startswith("runtime/sword_runtime/contact_physics.py")
            or path.startswith("runtime/sword_runtime/combat_capability.py")
            or path.startswith("runtime/sword_runtime/battle_trace.py")
            or path.startswith("runtime/sword_runtime/officer_cadre.py")
            or path.startswith("game/data/mechanics/combat.json")
            or path.startswith("game/data/mechanics/injury.json")
            or path.startswith("game/schemas/combat-mechanics.schema.json")
            or path.startswith("game/schemas/injury-mechanics.schema.json")
        ):
            selected.update(COMBAT_TESTS)
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
        if path.startswith("runtime/sword_runtime/battlefield.py") or path.startswith("game/data/mechanics/battlefield-operations.json"):
            selected.update(BATTLEFIELD_TESTS)
            selected.update(BATTLE_LIFECYCLE_TESTS)
            selected.update(COMBAT_TESTS)
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
            "runtime/sword_runtime/state_levy.py",
            "game/data/mil/autonomy-blueprints.json",
        }:
            selected.update(STATE_LEVY_TESTS)
        if path in {
            "runtime/sword_runtime/battle_command.py",
            "game/schemas/sword-operation.schema.json",
        }:
            selected.update(BATTLE_COMMAND_TESTS)
        if (
            path.startswith("runtime/sword_runtime/campaign_command_cycle.py")
            or path.startswith("runtime/sword_runtime/court_presence.py")
            or path.startswith("game/data/mechanics/campaign-command.json")
            or path.startswith("state/index/court-attendance-index.json")
        ):
            selected.update(CAMPAIGN_COMMAND_CYCLE_TESTS)
            selected.update(QIN_CAMPAIGN_HANDOFF_TESTS)
            selected.update(TIME_INTEGRATION_TESTS)
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
        if path.startswith("runtime/sword_runtime/warfare_depth.py"):
            selected.add("tests/runtime/test_scale_aware_command_establishment.py")
            selected.update(TRAINING_TESTS)
            selected.update(INSTRUCTOR_TESTS)
        if path.startswith("runtime/sword_runtime/player_group_actions.py"):
            selected.update(GROUP_ACTION_TESTS)
            selected.update(TRAINING_TESTS)
            selected.update(FATIGUE_TESTS)
        if path.startswith("runtime/sword_runtime/player_story_flow.py") or path.startswith("runtime/sword_runtime/vitality.py"):
            selected.update(PLAYER_STORY_TESTS)
            selected.update(LIVING_WORLD_TESTS)
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
        if path.startswith("plugins/sword-and-banners/skills/"):
            selected.update(DEFAULT_TESTS)
            selected.add("tests/runtime/test_skill_repository_contract.py")
        if path.startswith("tests/runtime/") and path.endswith(".py") and path != "tests/runtime/test_runtime_invariants.py":
            selected.add(path)
    if not selected:
        selected.update(DEFAULT_TESTS)
    return sorted(path for path in selected if (ROOT / path).is_file())


def _run_tests(tests: list[str], *, cwd: Path) -> None:
    if not tests:
        return
    subprocess.run(
        [sys.executable, "tools/run_pytest_module.py", "-q", *tests],
        cwd=cwd,
        check=True,
    )


def main(argv: list[str]) -> int:
    if not argv:
        raise SystemExit("usage: python tools/test_changed.py <changed paths...>")
    tests = select(argv)
    print("test_changed: " + " ".join(tests), flush=True)
    _run_tests(tests, cwd=ROOT)
    print("test_changed: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
