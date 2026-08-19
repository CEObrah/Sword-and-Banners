from __future__ import annotations


def test_shield_can_be_perforated_without_total_structural_failure():
    from sword_runtime.contact_physics import shield_contact_resolution

    shield = {"structural_resistance": 100, "coverage_arc_degrees": 135, "handling": 1.0}
    result = shield_contact_resolution(
        shield,
        impact_index=80,
        penetration_index=120,
        mode="thrust",
        condition_pct=100,
        timing_factor=1.0,
        block_control_ratio=1.0,
    )
    assert result["penetrated"] is True
    assert result["failed"] is False
    assert result["residual_penetration_index"] > 0
    assert result["remaining_condition_pct"] > 0


def test_armor_reduces_penetration_and_transmitted_impact_before_anatomy():
    from sword_runtime.contact_physics import armor_contact_resolution

    armor = {
        "schema": "human_armor",
        "primary_plate_cut_resistance": 100,
        "primary_plate_thrust_resistance": 120,
        "primary_plate_blunt_resistance": 90,
        "articulated_joint_cut_resistance": 55,
        "articulated_joint_thrust_resistance": 60,
        "articulated_joint_blunt_resistance": 45,
    }
    bare = armor_contact_resolution(None, mode="thrust", impact_index=100, penetration_index=110, structure="upper_torso")
    protected = armor_contact_resolution(armor, mode="thrust", impact_index=100, penetration_index=110, structure="upper_torso")
    assert protected["residual_penetration_index"] < bare["residual_penetration_index"]
    assert protected["residual_impact_index"] < bare["residual_impact_index"]
    assert protected["penetrated"] is False


def test_adaptive_attack_planner_penalizes_repeated_failed_best_mode(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    weapon = {
        "family": "sword", "base_force_cut": 0.90, "base_force_thrust": 0.78,
        "base_force_blunt": 0.18, "mass_kg": 1.2, "handling": 1.0,
    }
    repeated = [
        {"mode": "cut", "aim_structure": "wrist", "result": "parried"},
        {"mode": "cut", "aim_structure": "wrist", "result": "parried"},
        {"mode": "cut", "aim_structure": "wrist", "result": "blocked"},
    ]
    plan = planner._personal_attack_mode_plan(
        weapon,
        aim_zone="forearms_hands",
        aim_structure="wrist",
        declared_intent=None,
        target_eq={"loadout": {}},
        recent_actions=repeated,
        target_last_defense="parry",
    )
    assert plan["mode"] != "cut", plan
    assert plan["selection_basis"] == "adaptive_physical_sequence"
    assert "repeat" not in plan["decision_reason"] or plan["mode"] != "cut"


def test_explicit_player_attack_method_overrides_adaptive_sequence(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    weapon = {
        "family": "sword", "base_force_cut": 0.90, "base_force_thrust": 0.78,
        "base_force_blunt": 0.18, "mass_kg": 1.2, "handling": 1.0,
    }
    plan = planner._personal_attack_mode_plan(
        weapon,
        aim_zone="forearms_hands",
        aim_structure="wrist",
        declared_intent="cut hard across his right wrist",
        target_eq={"loadout": {}},
        recent_actions=[{"mode": "cut", "aim_structure": "wrist", "result": "parried"}] * 4,
        target_last_defense="parry",
    )
    assert plan["mode"] == "cut"
    assert plan["selection_basis"] == "declared_intent"


def test_formation_penetration_pressure_interacts_with_opposing_protection(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    own = [{
        "count": 1000, "melee_score": 150, "melee_force": 1.0, "melee_penetration_factor": 1.15,
        "shield_structure": 0, "melee_weapon_family": "spear", "melee_reach_m": 2.2,
        "mounted": False, "formation_fighting": 120, "formation_cohesion": 90, "formation_training": 90,
        "depth_support_factor": 0.35,
    }]
    light = [{
        "count": 1000, "protection_index": 20, "shield_structure": 0, "melee_weapon_family": "sword",
        "melee_reach_m": 0.9, "mounted": False, "formation_fighting": 80,
        "formation_cohesion": 80, "formation_training": 80,
    }]
    heavy = [{
        "count": 1000, "protection_index": 130, "shield_structure": 150, "shield_coverage_degrees": 120,
        "melee_weapon_family": "sword", "melee_reach_m": 0.9, "mounted": False,
        "formation_fighting": 80, "formation_cohesion": 80, "formation_training": 80,
    }]
    formation = {"personnel": 1000, "cohesion": 90, "training_progress": 90}
    vs_light = planner._combat_formation_method_profile(own, formation, light, "open")
    vs_heavy = planner._combat_formation_method_profile(own, formation, heavy, "open")
    assert vs_light["penetration_ratio"] > vs_heavy["penetration_ratio"]
    assert vs_light["opposing_protection_layer"] < vs_heavy["opposing_protection_layer"]


def test_mount_speed_mass_and_barding_feed_charge_physics():
    from sword_runtime.contact_physics import mount_effective_speed_mps, mounted_charge_resolution

    horse = {
        "mass_kg": 480, "Speed": 150, "Strength": 140, "Endurance": 130, "Agility": 125,
        "charge_training": True,
    }
    barding = {"mass_kg": 45, "articulation_factor": 0.90, "heat_modifier": 1.08}
    naked = mount_effective_speed_mps(horse, rider_mass_kg=75, rider_equipment_kg=20)
    armored = mount_effective_speed_mps(horse, barding=barding, rider_mass_kg=75, rider_equipment_kg=20)
    assert naked["effective_speed_mps"] > armored["effective_speed_mps"]
    assert armored["total_mass_kg"] > naked["total_mass_kg"]
    lance = {"family": "spear", "variant": "cavalry_lance", "couched_grip_force_factor": 1.18}
    fast = mounted_charge_resolution(naked, riding=140, coordination=140, awareness=120, composure=120,
                                     horse_training=120, relative_speed_mps=naked["effective_speed_mps"], weapon=lance)
    slow = mounted_charge_resolution(naked, riding=140, coordination=140, awareness=120, composure=120,
                                     horse_training=120, relative_speed_mps=naked["effective_speed_mps"] * 0.55, weapon=lance)
    assert fast["collision_energy_j"] > slow["collision_energy_j"]
    assert fast["body_collision_impact_index"] > slow["body_collision_impact_index"]
    assert fast["weapon_motion_multiplier"] > slow["weapon_motion_multiplier"]


def test_real_shields_and_long_spears_create_shieldwall_phalanx_and_brace(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    formation = {"personnel": 1000, "cohesion": 100, "training_progress": 100}
    rows = [{
        "count": 1000, "shield_structure": 120, "shield_coverage_degrees": 120,
        "melee_weapon_family": "spear", "melee_reach_m": 2.3, "mounted": False,
        "formation_fighting": 130, "formation_cohesion": 100, "formation_training": 100,
        "depth_support_factor": 0.45, "melee_score": 120, "melee_force": 1.0,
        "melee_penetration_factor": 1.1,
    }]
    cavalry = [{
        "count": 1000, "mounted": True, "charge_legal": True, "mount_total_mass_kg": 600,
        "mount_speed_mps": 10.0, "riding": 120, "melee_weapon_family": "spear", "melee_reach_m": 2.7,
        "formation_fighting": 80, "formation_cohesion": 90, "formation_training": 90,
    }]
    profile = planner._combat_formation_method_profile(rows, formation, cavalry, "open")
    assert "shield_wall" in profile["methods"]
    assert "phalanx_or_spear_wall" in profile["methods"]
    assert "braced_anti_cavalry" in profile["methods"]
    assert profile["brace_integrity"] > 0


def test_formation_shield_methods_use_serviceable_shield_quantity(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    formation = {"personnel": 1000, "cohesion": 100, "training_progress": 100}
    full = [{
        "count": 1000, "shield_units": 1000, "shield_structure": 120, "shield_coverage_degrees": 120,
        "melee_weapon_family": "spear", "melee_reach_m": 2.3, "mounted": False,
        "formation_fighting": 130, "formation_cohesion": 100, "formation_training": 100,
        "depth_support_factor": 0.45, "melee_score": 120, "melee_force": 1.0,
        "melee_penetration_factor": 1.1,
    }]
    half = [{**full[0], "shield_units": 500}]
    unshielded_enemy = [{
        "count": 1000, "shield_structure": 0, "melee_weapon_family": "sword", "melee_reach_m": 0.9,
        "mounted": False, "formation_fighting": 80, "formation_cohesion": 80, "formation_training": 80,
    }]
    full_profile = planner._combat_formation_method_profile(full, formation, unshielded_enemy, "open")
    half_profile = planner._combat_formation_method_profile(half, formation, unshielded_enemy, "open")
    assert full_profile["shield_share"] == 1.0
    assert half_profile["shield_share"] == 0.5
    assert half_profile["shieldwall_integrity"] < full_profile["shieldwall_integrity"]
    assert half_profile["phalanx_integrity"] < full_profile["phalanx_integrity"]


def test_ranged_shield_interception_uses_serviceable_shield_quantity(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    shooter = [{
        "count": 1000, "ranged_effective_range_m": 120, "ranged_max_direct_range_m": 180,
        "ranged_score": 100, "ammunition_item": "ammo_arrow_standard", "ammunition_resource": "arrows",
        "ranged_weapon_id": "weapon_bow_composite", "ranged_strength": 100, "ranged_coordination": 100,
        "ranged_awareness": 100, "equipment_condition_pct": 100,
    }]
    ammo = {"consumed_by_resource": {"arrows": 1000}}
    base_target = {
        "count": 1000, "shield_structure": 120, "shield_coverage_degrees": 120,
        "formation_cohesion": 100, "formation_training": 100, "armor_protection_index": 60,
    }
    full = planner._combat_ranged_contact_profile(shooter, ammo, [{**base_target, "shield_units": 1000}])
    half = planner._combat_ranged_contact_profile(shooter, ammo, [{**base_target, "shield_units": 500}])
    assert half["shield_intercept_fraction"] < full["shield_intercept_fraction"]
    assert half["shield_intercept_fraction"] > 0


def test_combat_snapshot_limits_shields_to_actual_equipment_units_and_zero_condition(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    formation = {
        "personnel": 1000,
        "composition": {"line_infantry": 1000},
        "cohort_composition": [{"cohort_id": "cohort_test", "count": 1000}],
        "equipment_units_by_role": {"line_infantry": 500},
        "equipment_completeness": "0.5000",
        "shield_condition_by_role": {"line_infantry": 100},
        "cohesion": 90,
        "training_progress": 90,
    }
    force = {"cohort_ledger": {"cohorts": {"cohort_test": {
        "role": "line_infantry",
        "attribute_means": {"Strength": 80, "Agility": 80, "Coordination": 80, "Endurance": 80, "Awareness": 80},
        "skill_means": {"Spear": 80, "Formation Fighting": 80},
    }}}}
    row = planner._combat_cohort_snapshot(formation, force)[0]
    assert row["shield_units"] == 500
    assert row["shield_availability"] == 0.5
    assert row["shield_structure"] > 0
    formation["shield_condition_by_role"]["line_infantry"] = 0
    broken = planner._combat_cohort_snapshot(formation, force)[0]
    assert broken["shield_units"] == 0
    assert broken["shield_availability"] == 0
    assert broken["shield_structure"] == 0


def test_shield_breakage_tracks_destroyed_units_separately_from_survivor_condition(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    fresh = planner._combat_shield_breakage_resolution(500, 100, 20)
    weakened = planner._combat_shield_breakage_resolution(500, 40, 20)
    exhausted = planner._combat_shield_breakage_resolution(500, 10, 20)
    assert 0 < fresh["units_destroyed"] < 500
    assert weakened["units_destroyed"] > fresh["units_destroyed"]
    assert exhausted["units_after"] == 0
    assert exhausted["condition_after_pct"] == 0


def test_fresh_replacement_shields_restore_quantity_and_weighted_condition(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner
    from sword_runtime.formation_armory_issue import _replace_serviceable_shields

    planner = RepositoryCommandPlanner(campaign)
    formation = {
        "composition": {"line_infantry": 1000},
        "registered_loadouts_by_role": {"line_infantry": "loadout_house_guard"},
        "equipment_units_by_role": {"line_infantry": 1000},
        "shield_units_by_role": {"line_infantry": 500},
        "shield_condition_by_role": {"line_infantry": 40.0},
        "equipment_staging_by_item": {"shield_tang": 500},
    }
    replaced = _replace_serviceable_shields(planner, formation, "shield_tang")
    assert replaced == 500
    assert formation["shield_units_by_role"]["line_infantry"] == 1000
    assert formation["shield_condition_by_role"]["line_infantry"] == 70.0
    assert "shield_tang" not in formation["equipment_staging_by_item"]

    formation["shield_units_by_role"]["line_infantry"] = 0
    formation["shield_condition_by_role"]["line_infantry"] = 0.0
    formation["equipment_staging_by_item"]["shield_tang"] = 1000
    replaced = _replace_serviceable_shields(planner, formation, "shield_tang")
    assert replaced == 1000
    assert formation["shield_condition_by_role"]["line_infantry"] == 100.0


def test_braced_spear_line_reduces_charge_expression_and_raises_mount_risk(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    cavalry_formation = {"personnel": 1000, "cohesion": 95, "training_progress": 95}
    cavalry = [{
        "count": 1000, "mounted": True, "charge_legal": True, "mount_total_mass_kg": 610,
        "mount_speed_mps": 10.5, "riding": 135, "melee_weapon_family": "spear", "melee_reach_m": 2.75,
        "formation_fighting": 100, "formation_cohesion": 95, "formation_training": 95,
        "mount_protection_index": 55, "melee_score": 120, "melee_force": 1.1, "melee_penetration_factor": 1.2,
    }]
    swords = [{
        "count": 1000, "mounted": False, "melee_weapon_family": "sword", "melee_reach_m": 0.9,
        "formation_fighting": 80, "formation_cohesion": 90, "formation_training": 90,
        "protection_index": 50,
    }]
    braced = [{
        "count": 1000, "mounted": False, "melee_weapon_family": "spear", "melee_reach_m": 2.4,
        "formation_fighting": 120, "formation_cohesion": 100, "formation_training": 100,
        "protection_index": 50,
    }]
    vs_swords = planner._combat_formation_method_profile(cavalry, cavalry_formation, swords, "open")
    vs_braced = planner._combat_formation_method_profile(cavalry, cavalry_formation, braced, "open")
    assert vs_braced["brace_absorption"] > vs_swords["brace_absorption"]
    assert vs_braced["combat_factor"] < vs_swords["combat_factor"]
    assert vs_braced["mount_casualty_risk"] > vs_swords["mount_casualty_risk"]


def test_mass_battle_trace_exposes_penetration_and_hero_contact_facts_for_narration():
    from sword_runtime.battle_trace import build_battle_causal_trace

    formations = {
        "formation_a": ("state/formations/a.json", {"personnel": 950}),
        "formation_b": ("state/formations/b.json", {"personnel": 940}),
    }
    score_details = {
        "formation_a": {
            "formation_method": {
                "methods": ["shield_wall", "phalanx_or_spear_wall"],
                "shieldwall_integrity": 0.8,
                "phalanx_integrity": 0.75,
                "brace_integrity": 0.6,
                "average_melee_reach_m": 2.3,
                "melee_penetration_pressure": 145.0,
                "opposing_protection_layer": 92.0,
                "penetration_ratio": 1.576,
            },
            "hero_interventions": [{
                "person_ref": "char_tang_wei",
                "representation": "full",
                "role": "formation_commander",
                "active_window_seconds": 45.0,
                "action_interval_seconds": 0.72,
                "physical_contacts": 8,
                "casualty_pressure": 5,
                "frontage_displacement_m": 2.2,
                "mounted": False,
                "weapon_id": "weapon_tang_wei_katana",
                "attack_mode": "cut",
                "impact_index": 178.0,
                "penetration_index": 201.0,
                "opposing_protection_index": 94.0,
            }],
        },
        "formation_b": {"formation_method": {"methods": ["shield_wall"]}},
    }
    trace, contract = build_battle_causal_trace(
        attackers=["formation_a"], defenders=["formation_b"],
        battlefield_ref="loc_test", terrain_kind="open",
        formations=formations,
        killed={"formation_a": 50, "formation_b": 60},
        material_losses={}, score_details=score_details,
        named_person_outcomes={}, attacker_won=True,
    )
    method = next(row for row in trace if row["kind"] == "formed_weapon_methods")
    row = method["formations"]["formation_a"]
    assert row["melee_penetration_pressure"] == 145.0
    assert row["opposing_protection_layer"] == 92.0
    assert row["penetration_ratio"] == 1.576
    hero = next(row for row in trace if row["kind"] == "named_local_interventions")["interventions"][0]
    assert hero["attack_mode"] == "cut"
    assert hero["impact_index"] == 178.0
    assert hero["penetration_index"] == 201.0
    assert hero["opposing_protection_index"] == 94.0
    assert set(contract["must_render"]).issubset({row["id"] for row in trace})


def test_active_wrist_and_leg_wounds_penalize_the_functions_they_physically_affect(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    wrist = {
        "injuries": [{"active": True, "severity": "serious", "body_zone": "forearms_hands", "functional_impairment": 60}],
    }
    leg = {
        "injuries": [{"active": True, "severity": "serious", "body_zone": "lower_legs_feet", "functional_impairment": 60}],
    }
    wf = planner._personal_transient_injury_factors(wrist)
    lf = planner._personal_transient_injury_factors(leg)
    assert wf["attack_factor"] < lf["attack_factor"]
    assert wf["parry_factor"] < lf["parry_factor"]
    assert lf["movement_factor"] < wf["movement_factor"]


def test_injured_but_conscious_exact_opponent_can_continue_personal_combat(campaign):
    import json
    import subprocess
    from conftest import execute, execute_internal

    opponent = "char_test_injured_continuation"
    player = json.loads((campaign / "state/player.json").read_text())
    execute_internal(campaign, "person_materialize", {
        "state": "qin", "person_ref": opponent, "name": "Injured Continuation Opponent",
        "birth_date": "270-BCE-01-01", "role": "command_personnel",
        "source_location_ref": player["location"],
    })
    owners = json.loads((campaign / "state/index/owner-index.json").read_text())["owners"]
    path = campaign / owners[opponent]
    person = json.loads(path.read_text())
    if isinstance(person.get("health"), dict):
        person["health"]["status"] = "injured"
    else:
        person["health_status"] = "injured"
    person["injury_state"] = {
        "label": "moderate cut wound to forearms hands", "severity": "moderate",
        "body_zone": "forearms_hands", "functional_impairment": 22,
        "active": True, "minimum_recovery_hours": 24, "recovered_hours": 0,
    }
    path.write_text(json.dumps(person, indent=2, sort_keys=True) + "\n")
    subprocess.run(["git", "-C", str(campaign), "add", str(path.relative_to(campaign))], check=True)
    subprocess.run(["git", "-C", str(campaign), "commit", "--quiet", "-m", "test injured combat continuation"], check=True)
    result = execute(campaign, "personal_combat", {
        "opponent_ref": opponent, "objective": "controlled spar", "duration_minutes": 5,
    }).receipt.result
    assert result["scale"] == "exact_personal"
    assert result["causal_trace"]


def test_declared_ride_down_uses_horse_body_collision_not_a_magic_weapon_bonus(campaign):
    import json
    from conftest import execute, execute_internal

    opponent = "char_test_ride_down_target"
    player = json.loads((campaign / "state/player.json").read_text())
    execute_internal(campaign, "person_materialize", {
        "state": "qin", "person_ref": opponent, "name": "Ride Down Target",
        "birth_date": "270-BCE-01-01", "role": "command_personnel",
        "source_location_ref": player["location"],
    })
    result = execute(campaign, "personal_combat", {
        "opponent_ref": opponent,
        "objective": "controlled spar",
        "duration_minutes": 5,
        "intent_sequence": ["ride down his center line"],
    }).receipt.result
    contacts = [row for row in result["causal_trace"] if row.get("kind") == "contact" and row.get("mounted_body_collision")]
    assert contacts, result["causal_trace"]
    contact = contacts[0]
    charge = contact["mounted_charge"]
    assert float(charge["body_collision_impact_index"]) > 0
    assert float(charge["total_mass_kg"]) > 0
    assert float(charge["relative_speed_mps"]) > 0
    assert contact["attack_mode"] == "blunt"


def test_anatomy_consumes_the_established_aim_structure_instead_of_rederiving_a_broad_zone():
    from sword_runtime.anatomy import resolve_anatomical_contact

    result = resolve_anatomical_contact(
        zone="head", mode="thrust", impact_index=90, penetration_index=90,
        channel_protection=30, contact_grade="clean", declared_intent=None,
        seed=2, lethal_intent=False, aim_side="right", aim_structure="eye",
    )
    assert result["side"] == "right"
    assert result["structure"] == "eye"


def test_wei_doctrine_aim_structure_flows_unchanged_into_contact_anatomy(campaign):
    import json
    from conftest import execute, execute_internal

    opponent = "char_test_precision_aim_flow"
    player = json.loads((campaign / "state/player.json").read_text())
    execute_internal(campaign, "person_materialize", {
        "state": "qin", "person_ref": opponent, "name": "Precision Aim Flow Opponent",
        "birth_date": "270-BCE-01-01", "role": "command_personnel",
        "source_location_ref": player["location"],
    })
    result = execute(campaign, "personal_combat", {
        "opponent_ref": opponent, "objective": "controlled spar", "duration_minutes": 5,
    }).receipt.result
    for contact in [row for row in result["causal_trace"] if row.get("kind") == "contact"]:
        if contact.get("actor_ref") != "char_tang_wei":
            continue
        anatomy = contact.get("anatomical_resolution") or {}
        assert anatomy.get("structure") == contact.get("aim_structure")
        assert anatomy.get("side") == contact.get("aim_side")


def test_formation_armor_protection_uses_serviceable_armor_quantity(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    formation = {
        "personnel": 1000,
        "composition": {"line_infantry": 1000},
        "cohort_composition": [{"cohort_id": "cohort_test", "count": 1000}],
        "equipment_units_by_role": {"line_infantry": 1000},
        "equipment_completeness": "1.0000",
        "armor_units_by_role": {"line_infantry": 500},
        "armor_condition_by_role": {"line_infantry": 100},
        "cohesion": 90,
        "training_progress": 90,
    }
    force = {"cohort_ledger": {"cohorts": {"cohort_test": {
        "role": "line_infantry",
        "attribute_means": {"Strength": 80, "Agility": 80, "Coordination": 80, "Endurance": 80, "Awareness": 80},
        "skill_means": {"Spear": 80, "Formation Fighting": 80},
    }}}}
    row = planner._combat_cohort_snapshot(formation, force)[0]
    assert row["armor_units"] == 500
    assert row["armor_availability"] == 0.5
    assert row["armor_protection_index"] > 0
    full = dict(formation)
    full["armor_units_by_role"] = {"line_infantry": 1000}
    full_row = planner._combat_cohort_snapshot(full, force)[0]
    assert full_row["armor_protection_index"] > row["armor_protection_index"]
    formation["armor_condition_by_role"]["line_infantry"] = 0
    broken = planner._combat_cohort_snapshot(formation, force)[0]
    assert broken["armor_units"] == 0
    assert broken["armor_availability"] == 0
    assert broken["armor_protection_index"] == 0


def test_armor_breakage_tracks_destroyed_sets_separately_from_survivor_condition(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    fresh = planner._combat_armor_breakage_resolution(500, 100, 20)
    weakened = planner._combat_armor_breakage_resolution(500, 40, 20)
    exhausted = planner._combat_armor_breakage_resolution(500, 8, 20)
    assert 0 < fresh["units_destroyed"] < 500
    assert weakened["units_destroyed"] > fresh["units_destroyed"]
    assert exhausted["units_after"] == 0
    assert exhausted["condition_after_pct"] == 0


def test_fresh_protective_components_restore_armor_sets_and_weighted_condition(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner
    from sword_runtime.formation_armory_issue import _replace_serviceable_armor_sets

    planner = RepositoryCommandPlanner(campaign)
    formation = {
        "composition": {"line_infantry": 1000},
        "registered_loadouts_by_role": {"line_infantry": "loadout_state_line_infantry"},
        "equipment_units_by_role": {"line_infantry": 1000},
        "armor_units_by_role": {"line_infantry": 500},
        "armor_condition_by_role": {"line_infantry": 40.0},
        "equipment_staging_by_item": {"armor_lamellar_military": 500, "helmet_lamellar": 500},
    }
    replaced = _replace_serviceable_armor_sets(planner, formation)
    assert replaced == 500
    assert formation["armor_units_by_role"]["line_infantry"] == 1000
    assert formation["armor_condition_by_role"]["line_infantry"] == 70.0
    assert "armor_lamellar_military" not in formation["equipment_staging_by_item"]
    assert "helmet_lamellar" not in formation["equipment_staging_by_item"]

    formation["armor_units_by_role"]["line_infantry"] = 0
    formation["armor_condition_by_role"]["line_infantry"] = 0.0
    formation["equipment_staging_by_item"].update({"armor_lamellar_military": 1000, "helmet_lamellar": 700})
    replaced = _replace_serviceable_armor_sets(planner, formation)
    assert replaced == 700
    assert formation["armor_units_by_role"]["line_infantry"] == 700
    assert formation["armor_condition_by_role"]["line_infantry"] == 100.0
    assert formation["equipment_staging_by_item"]["armor_lamellar_military"] == 300
    assert "helmet_lamellar" not in formation["equipment_staging_by_item"]
