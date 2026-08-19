from __future__ import annotations

from sword_runtime.combat_capability import CombatCapabilityMixin


class Harness(CombatCapabilityMixin):
    def __init__(self):
        self.items = {
            "sword": {"id": "sword", "family": "sword", "base_force_cut": 1.15, "base_force_thrust": 0.95, "base_force_blunt": 0.25, "mass_kg": 1.2, "handling": 1.0},
            "shield": {"id": "shield", "schema": "shield", "structural_resistance": 110, "coverage_arc_degrees": 120, "handling": 1.0},
            "armor": {"id": "armor", "schema": "human_armor", "primary_plate_cut_resistance": 125, "primary_plate_thrust_resistance": 115, "primary_plate_blunt_resistance": 90, "articulated_joint_cut_resistance": 70, "articulated_joint_thrust_resistance": 62, "articulated_joint_blunt_resistance": 55, "hand_and_foot_cut_resistance": 45, "hand_and_foot_thrust_resistance": 40, "hand_and_foot_blunt_resistance": 35, "coverage": "torso full arms full legs"},
            "bow": {"id": "bow", "family": "bow", "schema": "bow", "draw_power_index": 100, "effective_range_m": 175, "maximum_direct_range_m": 310, "base_shot_cycle_seconds": 7.2, "handling": 0.68},
            "arrow": {"id": "arrow", "family": "arrow", "schema": "projectile", "projectile_profile": 1.0, "armor_penetration": 1.05, "impact_transfer": 0.22, "recovery_base": 0.35, "mass_kg": 0.065},
        }
        self.loadouts = {
            "armored": {"id": "armored", "primary_melee_weapon": "sword", "shield": "shield", "body_armor": "armor"},
            "unarmored": {"id": "unarmored", "primary_melee_weapon": "sword"},
        }

    def _combat_weapon(self, item_id):
        if isinstance(item_id, dict):
            return item_id
        return self.items.get(str(item_id), {})

    def _combat_loadout(self, loadout_id):
        return self.loadouts.get(str(loadout_id), {})


def _hero(role="notable"):
    return {
        "person_ref": "hero",
        "representation": "sab_character",
        "role": role,
        "exposure_factor": 1.0,
        "included_in_personnel": False,
        "melee_direct_score": 240.0,
        "direct_combat_score": 240.0,
        "melee_weapon_id": "sword",
        "melee_force": 1.15,
        "melee_reach_m": 1.0,
        "minimum_action_interval_seconds": 0.8,
        "strength": 180.0,
        "awareness": 180.0,
        "combat_targeting_doctrine": {
            "lethal_priority": [
                {"zone": "forearms_hands", "structure": "wrist", "purpose": "disable_weapon_control"}
            ]
        },
    }


def _defended_hero(loadout_id="armored", defense=220.0):
    row = _hero()
    row.update({
        "loadout_id": loadout_id,
        "shield_id": "shield" if loadout_id == "armored" else "",
        "shield_condition_pct": 100.0,
        "armor_condition_pct": 100.0,
        "defense_skill_value": defense,
        "agility": defense,
        "coordination": defense,
        "composure": defense,
    })
    return row


def _target(loadout_id):
    return {
        "count": 100,
        "role": "line_infantry",
        "loadout_id": loadout_id,
        "melee_score": 100.0,
        "formation_fighting": 100.0,
        "formation_cohesion": 80.0,
        "formation_training": 80.0,
        "shield_id": "shield" if loadout_id == "armored" else "",
        "shield_condition_pct": 100.0,
        "armor_condition_pct": 100.0,
        "equipment_condition_pct": 100.0,
        "protection_index": 100.0 if loadout_id == "armored" else 0.0,
    }


def test_hero_micro_window_is_bounded_and_uses_saved_targeting_doctrine():
    result = Harness()._combat_hero_interventions([_hero()], [], [_target("armored")], battle_hours=4.0, terrain_kind="open")
    row = result["interventions"][0]
    assert row["active_window_seconds"] == 120.0
    assert row["available_personal_contact_seconds"] > 120.0
    assert row["local_window_bounded"] is True
    assert row["aim_structure"] == "wrist"
    assert row["aim_selection_basis"] == "saved_combat_targeting_doctrine"
    assert row["representative_contact_layers"][0]["shield_present"] is True
    assert "armor_severity" in row["representative_contact_layers"][0]


def test_real_shield_and_armor_layers_reduce_hero_injury_expression():
    harness = Harness()
    armored = harness._combat_hero_interventions([_hero()], [], [_target("armored")], battle_hours=2.0, terrain_kind="open")["interventions"][0]
    unarmored = harness._combat_hero_interventions([_hero()], [], [_target("unarmored")], battle_hours=2.0, terrain_kind="open")["interventions"][0]
    assert armored["weighted_post_layer_injury_expression"] < unarmored["weighted_post_layer_injury_expression"]
    assert armored["weighted_shield_condition_loss_pct"] > 0.0


def test_hero_window_returns_organizational_pressure_without_equivalent_bodies():
    result = Harness()._combat_hero_interventions([_hero()], [], [_target("unarmored")], battle_hours=3.0, terrain_kind="open")
    row = result["interventions"][0]
    assert row["physical_contacts"] > 0
    assert row["casualty_pressure"] >= 0
    assert row["officer_pressure"] >= 0.0
    assert row["cohesion_shock_pressure"] > 0.0
    assert "equivalent_bodies" not in row
    assert "equivalent_bodies" not in result


def test_commander_personal_contact_window_consumes_command_attention():
    row = Harness()._combat_hero_interventions([_hero("commander")], [], [_target("unarmored")], battle_hours=3.0, terrain_kind="open")["interventions"][0]
    assert 0.0 < row["command_attention_seconds"] <= 120.0


def test_hero_own_injury_risk_comes_from_incoming_physical_contact_layers():
    harness = Harness()
    armored = harness._combat_hero_interventions([_defended_hero("armored")], [], [_target("unarmored")], battle_hours=2.0, terrain_kind="open")["interventions"][0]
    unarmored = harness._combat_hero_interventions([_defended_hero("unarmored")], [], [_target("unarmored")], battle_hours=2.0, terrain_kind="open")["interventions"][0]
    assert armored["incoming_expected_contacts"] > 0.0
    assert armored["representative_incoming_contact_layers"]
    assert armored["incoming_injury_risk"] < unarmored["incoming_injury_risk"]
    assert armored["representative_incoming_contact_layers"][0]["shield_present"] is True


def test_higher_personal_defense_reduces_contact_hazard_without_stat_ceiling():
    harness = Harness()
    normal = harness._combat_hero_interventions([_defended_hero("unarmored", 120.0)], [], [_target("unarmored")], battle_hours=2.0, terrain_kind="open")["interventions"][0]
    exceptional = harness._combat_hero_interventions([_defended_hero("unarmored", 280.0)], [], [_target("unarmored")], battle_hours=2.0, terrain_kind="open")["interventions"][0]
    assert exceptional["incoming_hero_defense_control"] > normal["incoming_hero_defense_control"]
    assert exceptional["incoming_expected_contacts"] < normal["incoming_expected_contacts"]
    assert exceptional["incoming_injury_risk"] < normal["incoming_injury_risk"]


def test_remote_named_person_does_not_generate_frontline_hero_window():
    remote = _hero()
    remote["co_located"] = False
    result = Harness()._combat_hero_interventions([remote], [], [_target("unarmored")], battle_hours=3.0, terrain_kind="open")
    assert result["interventions"] == []
    assert result["casualty_pressure"] == 0


def test_ranged_hero_window_reports_exact_person_ammunition_and_recovery_basis():
    hero = _defended_hero("unarmored", 220.0)
    hero.update({
        "melee_direct_score": 40.0,
        "direct_combat_score": 280.0,
        "ranged_direct_score": 280.0,
        "ranged_skill_value": 260.0,
        "ranged_weapon_id": "bow",
        "ranged_effective_range_m": 175.0,
        "ranged_max_direct_range_m": 310.0,
        "ranged_cycle_seconds": 7.2,
        "ammunition_item": "arrow",
        "carried_ammunition": 12,
        "strength": 180.0,
    })
    row = Harness()._combat_hero_interventions([hero], [], [_target("unarmored")], battle_hours=2.0, terrain_kind="open")["interventions"][0]
    assert row["intervention_mode"] == "ranged"
    assert 0 < row["projectiles_released"] <= 12
    assert row["projectile_item_id"] == "arrow"
    assert 0.0 < row["projectile_recovery_base"] <= 1.0
    assert row["incoming_expected_contacts"] > 0.0


def test_hero_window_exposes_bounded_continuous_contact_timeline_without_materializing_anonymous_people():
    row = Harness()._combat_hero_interventions([_defended_hero("armored")], [], [_target("unarmored")], battle_hours=3.0, terrain_kind="open")["interventions"][0]
    timeline = row["local_contact_timeline"]
    assert timeline["mode"] == "transient_continuous_contact_adapter"
    assert timeline["persistent_anonymous_people_materialized"] is False
    assert timeline["outgoing_contact_count"] == row["physical_contacts"]
    events = timeline["representative_events"]
    assert events
    contact_times = [float(event.get("contact_at_s", event.get("start_at_s", 0))) for event in events]
    assert contact_times == sorted(contact_times)
    assert all(0.0 <= value <= row["active_window_seconds"] for value in contact_times)
    assert all(event.get("contact_group_id") for event in events)
