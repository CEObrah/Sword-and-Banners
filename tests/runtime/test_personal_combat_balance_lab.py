from __future__ import annotations

import copy
import json
import subprocess


def _commit(campaign, *paths: str) -> None:
    subprocess.run(["git", "-C", str(campaign), "add", *paths], check=True)
    subprocess.run(["git", "-C", str(campaign), "commit", "--quiet", "-m", "combat balance lab fixture"], check=True)


def test_registered_handling_adjustment_has_neutral_one_and_bounded_penalties():
    from sword_runtime.personal_combat import _registered_handling_adjustment

    assert _registered_handling_adjustment(1.0) == 0.0
    assert round(_registered_handling_adjustment(0.8), 6) == -8.0
    assert _registered_handling_adjustment(2.0) == 16.0
    assert _registered_handling_adjustment(0.0) == -16.0


def test_personal_controls_consume_registered_handling_model(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner

    mechanics_path = campaign / "game/data/mechanics/combat.json"
    mechanics = json.loads(mechanics_path.read_text())
    person = {
        "fatigue": 0,
        "attributes": {"Strength": 100, "Agility": 100, "Coordination": 100, "Awareness": 100, "Composure": 100, "Endurance": 100},
        "skills": {"Sword": 100, "Shield": 100, "Athletics": 100},
    }
    eq = {
        "skill_name": "Sword",
        "weapon": {"family": "sword", "handling": 1.25, "recovery_class": "standard"},
        "burden": {"movement_factor": 1.0, "recovery_factor": 1.0, "articulation_factor": 1.0, "vision_factor": 1.0, "hearing_factor": 1.0},
    }
    maintained = RepositoryCommandPlanner(campaign)._personal_controls(person, eq, {})
    mechanics["handling_adjustment_model"]["slope"] = 0.0
    mechanics_path.write_text(json.dumps(mechanics, ensure_ascii=False, indent=2) + "\n")
    registry_changed = RepositoryCommandPlanner(campaign)._personal_controls(person, eq, {})
    assert maintained["attack"] > registry_changed["attack"]
    assert maintained["parry"] > registry_changed["parry"]


def test_reach_advantage_is_contextual_and_reverses_inside_long_weapon_minimum(campaign):
    from sword_runtime.personal_combat import _registered_reach_advantage_points

    bands = json.loads((campaign / "game/data/mechanics/combat.json").read_text())["reach_advantage_points"]
    # At standoff distance the spear can threaten while the sword cannot.
    spear_standoff = _registered_reach_advantage_points(
        2.15, 0.85, 1.50,
        attacker_minimum_m=0.65, defender_minimum_m=0.12, bands=bands,
    )
    # Once the sword gets inside the spear's minimum range, the geometry reverses.
    sword_inside = _registered_reach_advantage_points(
        0.85, 2.15, 0.50,
        attacker_minimum_m=0.12, defender_minimum_m=0.65, bands=bands,
    )
    mutual_range = _registered_reach_advantage_points(
        2.15, 0.85, 0.72,
        attacker_minimum_m=0.65, defender_minimum_m=0.12, bands=bands,
    )
    assert spear_standoff == float(bands["decisive_one_sided_threat"])
    assert sword_inside == float(bands["decisive_one_sided_threat"])
    assert mutual_range == float(bands["0.75_plus"])


def test_better_relevant_stats_monotonically_improve_control_and_tempo(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    eq = {
        "skill_name": "Sword",
        "weapon": {"family": "sword", "handling": 1.0, "recovery_class": "standard"},
        "burden": {
            "movement_factor": 1.0, "recovery_factor": 1.0, "articulation_factor": 1.0,
            "vision_factor": 1.0, "hearing_factor": 1.0, "total_load_kg": 0.0,
        },
    }

    def person(value: int) -> dict:
        return {
            "fatigue": 0,
            "attributes": {
                "Strength": value, "Agility": value, "Coordination": value,
                "Awareness": value, "Composure": value, "Endurance": value,
            },
            "skills": {
                "Sword": value, "Shield": value, "Athletics": value,
                "Formation Fighting": value,
            },
        }

    low = person(60)
    high = person(180)
    low_control = planner._personal_controls(low, eq, {})
    high_control = planner._personal_controls(high, eq, {})
    assert high_control["attack"] > low_control["attack"]
    assert high_control["parry"] > low_control["parry"]
    assert high_control["dodge"] > low_control["dodge"]
    assert high_control["block"] > low_control["block"]

    low_timing = planner._personal_timing_profile(low, eq, low_control, {})
    high_timing = planner._personal_timing_profile(high, eq, high_control, {})
    assert high_timing["tempo"] > low_timing["tempo"]
    assert high_timing["minimum_action_interval_seconds"] < low_timing["minimum_action_interval_seconds"]
    assert high_timing["movement_speed_mps"] > low_timing["movement_speed_mps"]
    assert high_timing["reaction_seconds"] < low_timing["reaction_seconds"]


def test_multiple_readied_melee_weapons_consider_actor_proficiency(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    player = json.loads((campaign / "state/player.json").read_text())
    profile = planner._personal_equipment_profile("char_tang_wei", player)
    # Live Tang Wei is much better with the sword than the spear. The engine
    # should not ignore that proficiency just because the spear has more reach.
    assert player["skills"]["Sword"] > player["skills"]["Polearms"]
    assert profile["best_weapon"] == "weapon_sword"
    assert profile["skill_name"] == "Sword"

    spear_specialist = copy.deepcopy(player)
    spear_specialist["skills"]["Sword"] = 70
    spear_specialist["skills"]["Polearms"] = 220
    spear_profile = planner._personal_equipment_profile("char_tang_wei", spear_specialist)
    assert spear_profile["best_weapon"] == "weapon_spear"
    assert spear_profile["skill_name"] == "Polearms"


def test_high_stat_sword_fighter_can_close_on_spear_and_reach_attack(campaign):
    from conftest import execute, execute_internal

    opponent = "char_test_balance_spear"
    player_path = campaign / "state/player.json"
    player = json.loads(player_path.read_text())
    execute_internal(campaign, "person_materialize", {
        "state": "qin", "person_ref": opponent, "name": "Balance Spearman",
        "birth_date": "270-BCE-01-01", "role": "command_personnel",
        "source_location_ref": player["location"],
    })
    owners = json.loads((campaign / "state/index/owner-index.json").read_text())["owners"]
    opponent_path = campaign / owners[opponent]

    player = json.loads(player_path.read_text())
    player.setdefault("attributes", {}).update({
        "Strength": 180, "Agility": 230, "Coordination": 230,
        "Awareness": 230, "Composure": 220, "Endurance": 210,
    })
    player.setdefault("skills", {}).update({"Sword": 260, "Polearms": 60, "Athletics": 220, "Shield": 180})
    player["current_location"] = player["location"]
    player_path.write_text(json.dumps(player, ensure_ascii=False, indent=2) + "\n")

    # Make the player's exact combat inventory unambiguous for this fixture.
    player_manifest_rel = "state/player-detail/equipment-manifest.json"
    player_manifest_path = campaign / player_manifest_rel
    player_manifest = json.loads(player_manifest_path.read_text())
    player_manifest["equipment_manifest"] = [
        row for row in player_manifest["equipment_manifest"]
        if row.get("item_id") in {"weapon_sword", "armor_heavy", "helmet_standard"}
    ]
    player_manifest_path.write_text(json.dumps(player_manifest, ensure_ascii=False, indent=2) + "\n")

    other = json.loads(opponent_path.read_text())
    other.setdefault("attributes", {}).update({
        "Strength": 75, "Agility": 70, "Coordination": 70,
        "Awareness": 70, "Composure": 70, "Endurance": 75,
    })
    other.setdefault("skills", {}).update({"Polearms": 80, "Sword": 30, "Athletics": 65, "Shield": 40})
    opponent_manifest_rel = f"state/test-person-equipment/{opponent}.json"
    opponent_manifest_path = campaign / opponent_manifest_rel
    opponent_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    opponent_manifest_path.write_text(json.dumps({
        "schema": "player-equipment-manifest",
        "authority": "player_equipment_manifest",
        "player_ref": opponent,
        "equipment_manifest": [
            {"item_id": "weapon_spear", "quantity": 1, "custody": "balance fixture", "current_state": "equipped/readied"},
        ],
    }, ensure_ascii=False, indent=2) + "\n")
    other["equipment_manifest_ref"] = opponent_manifest_rel
    opponent_path.write_text(json.dumps(other, ensure_ascii=False, indent=2) + "\n")
    _commit(campaign, "state/player.json", player_manifest_rel, owners[opponent], opponent_manifest_rel)

    result = execute(campaign, "personal_combat", {
        "opponent_ref": opponent,
        "objective": "controlled spar",
        "duration_minutes": 1,
        "participant_positions": {
            "char_tang_wei": {"x_m": 0, "y_m": 0, "facing_deg": 0},
            opponent: {"x_m": 4, "y_m": 0, "facing_deg": 180},
        },
    }).receipt.result

    player_moves = [
        row for row in result["causal_trace"]
        if row.get("kind") == "movement" and row.get("actor_ref") == "char_tang_wei"
    ]
    player_attacks = [
        row for row in result["causal_trace"]
        if row.get("kind") == "attack" and row.get("actor_ref") == "char_tang_wei"
    ]
    assert player_moves, result["causal_trace"]
    assert player_attacks, result["causal_trace"]
    first_attack = player_attacks[0]
    assert float(first_attack["surface_gap_m"]) <= 0.95
    assert min(float(row["complete_at_s"]) for row in player_moves) <= float(first_attack["contact_at_s"])
    assert first_attack["weapon_id"] == "weapon_sword"


def test_equal_inputs_have_no_hidden_player_or_npc_control_bonus(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    person = {
        "fatigue": 0,
        "attributes": {"Strength": 100, "Agility": 100, "Coordination": 100, "Awareness": 100, "Composure": 100, "Endurance": 100},
        "skills": {"Sword": 100, "Shield": 100, "Athletics": 100},
    }
    eq = {
        "skill_name": "Sword",
        "weapon": {"family": "sword", "handling": 1.0, "recovery_class": "standard"},
        "burden": {"movement_factor": 1.0, "recovery_factor": 1.0, "articulation_factor": 1.0, "vision_factor": 1.0, "hearing_factor": 1.0},
    }
    assert planner._personal_controls(copy.deepcopy(person), copy.deepcopy(eq), {}) == planner._personal_controls(copy.deepcopy(person), copy.deepcopy(eq), {})


def test_fatigue_reduces_control_and_movement_without_special_case_immunity(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    base = {
        "attributes": {"Strength": 120, "Agility": 140, "Coordination": 140, "Awareness": 140, "Composure": 140, "Endurance": 120},
        "skills": {"Sword": 140, "Shield": 120, "Athletics": 130},
    }
    fresh = copy.deepcopy(base); fresh["fatigue"] = 0
    tired = copy.deepcopy(base); tired["fatigue"] = 90
    eq = {
        "skill_name": "Sword",
        "weapon": {"family": "sword", "handling": 1.0, "recovery_class": "standard"},
        "burden": {"movement_factor": 1.0, "recovery_factor": 1.0, "articulation_factor": 1.0, "vision_factor": 1.0, "hearing_factor": 1.0},
    }
    fc = planner._personal_controls(fresh, eq, {})
    tc = planner._personal_controls(tired, eq, {})
    assert tc["attack"] < fc["attack"]
    assert tc["parry"] < fc["parry"]
    assert tc["dodge"] < fc["dodge"]


def test_localized_injury_penalties_do_not_act_like_generic_hit_points(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    wrist = {"injuries": [{"active": True, "severity": "serious", "body_zone": "forearms_hands", "functional_impairment": 60}]}
    leg = {"injuries": [{"active": True, "severity": "serious", "body_zone": "lower_legs_feet", "functional_impairment": 60}]}
    wf = planner._personal_transient_injury_factors(wrist)
    lf = planner._personal_transient_injury_factors(leg)
    assert wf["attack_factor"] < lf["attack_factor"]
    assert wf["parry_factor"] < lf["parry_factor"]
    assert lf["movement_factor"] < wf["movement_factor"]


def test_reach_delta_is_antisymmetric_when_both_weapons_can_threaten(campaign):
    from sword_runtime.personal_combat import _registered_reach_advantage_points

    bands = json.loads((campaign / "game/data/mechanics/combat.json").read_text())["reach_advantage_points"]
    spear = _registered_reach_advantage_points(2.15, 0.85, 0.72, attacker_minimum_m=0.65, defender_minimum_m=0.12, bands=bands)
    sword = _registered_reach_advantage_points(0.85, 2.15, 0.72, attacker_minimum_m=0.12, defender_minimum_m=0.65, bands=bands)
    assert spear == -sword
    assert spear > 0


def test_strength_does_not_magically_raise_sword_accuracy_but_does_help_block(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    def person(strength: int) -> dict:
        return {
            "fatigue": 0,
            "attributes": {"Strength": strength, "Agility": 120, "Coordination": 120, "Awareness": 120, "Composure": 120, "Endurance": 120},
            "skills": {"Sword": 120, "Shield": 120, "Athletics": 120},
        }
    eq = {
        "skill_name": "Sword",
        "weapon": {"family": "sword", "handling": 1.0, "recovery_class": "standard"},
        "burden": {"movement_factor": 1.0, "recovery_factor": 1.0, "articulation_factor": 1.0, "vision_factor": 1.0, "hearing_factor": 1.0},
    }
    weak = planner._personal_controls(person(60), eq, {})
    strong = planner._personal_controls(person(200), eq, {})
    assert strong["attack"] == weak["attack"]
    assert strong["parry"] == weak["parry"]
    assert strong["block"] > weak["block"]


def test_default_weapon_choice_consumes_registered_selection_weights(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner

    mechanics_path = campaign / "game/data/mechanics/combat.json"
    mechanics = json.loads(mechanics_path.read_text())
    weights = mechanics["default_melee_weapon_selection"]
    assert weights["proficiency_weight"] > 0
    assert weights["reach_weight"] > 0

    player = json.loads((campaign / "state/player.json").read_text())
    # With the maintained registered weights, Tang Wei's much higher Sword
    # proficiency makes the sword the default among the weapons already readied.
    maintained = RepositoryCommandPlanner(campaign)._personal_equipment_profile("char_tang_wei", player)
    assert maintained["best_weapon"] == "weapon_sword"

    # Prove the runtime is not carrying a private duplicate of the coefficient:
    # zero only the registered proficiency contribution and create a fresh
    # planner. The spear's physical force/reach then wins the default heuristic.
    mechanics["default_melee_weapon_selection"]["proficiency_weight"] = 0.0
    mechanics_path.write_text(json.dumps(mechanics, ensure_ascii=False, indent=2) + "\n")
    registry_changed = RepositoryCommandPlanner(campaign)._personal_equipment_profile("char_tang_wei", player)
    assert registry_changed["best_weapon"] == "weapon_spear"
