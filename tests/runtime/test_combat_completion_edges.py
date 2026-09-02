from __future__ import annotations

import copy
import json


def test_broken_personal_equipment_remains_in_custody_but_is_not_combat_usable(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner

    planner = ProductionCampaignPlanner(campaign)
    player = json.loads((campaign / "state/player.json").read_text())

    broken_shield = copy.deepcopy(player)
    broken_shield.setdefault("equipment_condition", {})["shield_standard"] = 0
    shield_profile = planner._personal_equipment_profile("char_tang_wei", broken_shield)
    assert "shield_standard" in shield_profile["equipped_item_ids"]
    assert shield_profile["loadout"].get("shield") is None

    broken_armor = copy.deepcopy(player)
    broken_armor.setdefault("equipment_condition", {})["armor_heavy"] = 0
    armor_profile = planner._personal_equipment_profile("char_tang_wei", broken_armor)
    assert "armor_heavy" in armor_profile["equipped_item_ids"]
    assert armor_profile["loadout"].get("body_armor") is None
    assert float(armor_profile["protection_index"]) < float(planner._personal_equipment_profile("char_tang_wei", player)["protection_index"])

    broken_lance = copy.deepcopy(player)
    broken_lance.setdefault("equipment_condition", {})["weapon_spear"] = 0
    lance_profile = planner._personal_equipment_profile("char_tang_wei", broken_lance)
    assert "weapon_spear" in lance_profile["equipped_item_ids"]
    assert lance_profile["melee_weapon_id"] != "weapon_spear"


def test_restrained_mount_anatomy_has_structure_specific_collapse_and_eye_effect(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner

    planner = ProductionCampaignPlanner(campaign)
    leg_target = {}
    leg = planner._personal_apply_mount_wound(
        leg_target,
        severity="serious",
        mode="blunt",
        source_weapon="weapon_mace_test",
        at="244-BCE-08-19T10:00:00+08:00",
        seed=0,
    )
    assert leg["structure"] == "foreleg"
    assert leg["collapse"] is True
    assert float(leg_target["mount_combat_state"]["mobility_factor"]) <= 0.16
    assert leg_target["mount_combat_state"]["collapsed"] is True

    eye_target = {}
    eye = planner._personal_apply_mount_wound(
        eye_target,
        severity="serious",
        mode="blunt",
        source_weapon="weapon_mace_test",
        at="244-BCE-08-19T10:00:00+08:00",
        seed=4,
    )
    assert eye["structure"] == "eye"
    assert eye["collapse"] is False
    assert float(eye_target["mount_combat_state"]["awareness_factor"]) < 1.0
    assert not eye_target["mount_combat_state"].get("collapsed", False)


def test_exact_mount_state_distinguishes_dead_from_disabled_and_does_not_respawn_from_role_loadout(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner

    planner = ProductionCampaignPlanner(campaign)

    fatal_target = {}
    fatal = planner._personal_apply_mount_wound(
        fatal_target,
        severity="critical",
        mode="thrust",
        source_weapon="weapon_spear",
        at="244-BCE-08-19T10:00:00+08:00",
        seed=0,  # thrust ordering -> chest
    )
    assert fatal["structure"] == "chest"
    assert fatal_target["mount_combat_state"]["status"] == "dead"
    assert fatal_target["mount_combat_state"]["serviceable"] is False
    assert fatal_target["mount_combat_state"]["service_loss_pending"] is True

    disabled_target = {}
    disabled = planner._personal_apply_mount_wound(
        disabled_target,
        severity="serious",
        mode="blunt",
        source_weapon="weapon_mace_test",
        at="244-BCE-08-19T10:00:00+08:00",
        seed=0,  # blunt ordering -> foreleg
    )
    assert disabled["structure"] == "foreleg"
    assert disabled_target["mount_combat_state"]["status"] == "disabled"
    assert disabled_target["mount_combat_state"]["serviceable"] is False

    # Tang Zhu's static role loadout normally contains a horse. Exact casualty
    # state must override that template so the same horse cannot reappear in the
    # next combat slice without a real remount operation.
    tang_zhu = json.loads((campaign / "state/char/tang-zhu.json").read_text())
    assert planner._personal_equipment_profile("char_tang_zhu", tang_zhu)["mount"]
    tang_zhu["mount_combat_state"] = copy.deepcopy(disabled_target["mount_combat_state"])
    after = planner._personal_equipment_profile("char_tang_zhu", tang_zhu)
    assert after["mount"] == {}
    assert after["horse_armor"] == {}
    assert after["tack"] == {}


def test_nonterminal_mount_injury_reduces_mounted_speed_before_full_collapse(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner

    planner = ProductionCampaignPlanner(campaign)
    rider = json.loads((campaign / "state/char/tang-zhu.json").read_text())
    eq_before = planner._personal_equipment_profile("char_tang_zhu", rider)
    controls_before = planner._personal_controls(rider, eq_before, {"formation_mobility_milli": 1000})
    timing_before = planner._personal_timing_profile(rider, eq_before, controls_before, {"formation_mobility_milli": 1000})
    assert timing_before["mounted"] is True

    planner._personal_apply_mount_wound(
        rider,
        severity="moderate",
        mode="blunt",
        source_weapon="weapon_mace_test",
        at="244-BCE-08-19T10:00:00+08:00",
        seed=0,
    )
    assert rider["mount_combat_state"]["status"] == "injured"
    eq_after = planner._personal_equipment_profile("char_tang_zhu", rider)
    controls_after = planner._personal_controls(rider, eq_after, {"formation_mobility_milli": 1000})
    timing_after = planner._personal_timing_profile(rider, eq_after, controls_after, {"formation_mobility_milli": 1000})
    assert timing_after["mounted"] is True
    assert float(timing_after["movement_speed_mps"]) < float(timing_before["movement_speed_mps"])
