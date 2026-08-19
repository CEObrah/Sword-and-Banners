from __future__ import annotations

import copy
import json


def test_broken_personal_equipment_remains_in_custody_but_is_not_combat_usable(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner

    planner = ProductionCampaignPlanner(campaign)
    player = json.loads((campaign / "state/player.json").read_text())

    broken_shield = copy.deepcopy(player)
    broken_shield.setdefault("equipment_condition", {})["shield_tang"] = 0
    shield_profile = planner._personal_equipment_profile("char_tang_wei", broken_shield)
    assert "shield_tang" in shield_profile["equipped_item_ids"]
    assert shield_profile["loadout"].get("shield") is None

    broken_armor = copy.deepcopy(player)
    broken_armor.setdefault("equipment_condition", {})["armor_tang"] = 0
    armor_profile = planner._personal_equipment_profile("char_tang_wei", broken_armor)
    assert "armor_tang" in armor_profile["equipped_item_ids"]
    assert armor_profile["loadout"].get("body_armor") is None
    assert float(armor_profile["protection_index"]) < float(planner._personal_equipment_profile("char_tang_wei", player)["protection_index"])

    broken_lance = copy.deepcopy(player)
    broken_lance.setdefault("equipment_condition", {})["weapon_lance_cavalry"] = 0
    lance_profile = planner._personal_equipment_profile("char_tang_wei", broken_lance)
    assert "weapon_lance_cavalry" in lance_profile["equipped_item_ids"]
    assert lance_profile["melee_weapon_id"] != "weapon_lance_cavalry"


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
