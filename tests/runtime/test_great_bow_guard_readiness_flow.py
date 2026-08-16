from __future__ import annotations

import copy

from sword_runtime.causal_event_store import get_causal_event
from sword_runtime.great_bow_guard_personal_integrity import repair_great_bow_guard_personal_ownership
from sword_runtime.great_bow_guard_readiness_flow import (
    _cohort_stats,
    settle_great_bow_guard_readiness,
    sync_great_bow_guard_readiness,
)
from sword_runtime.production_planner import ProductionCampaignPlanner


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    meta = copy.deepcopy(planner.read("state/meta.json"))
    planner.PLAYER_ACTOR = str(meta["player_id"])
    planner._reset()
    return planner


def _inventory_fact(inventory, record_id: str, key: str) -> int:
    row = next(record for record in inventory["records"] if record.get("record_id") == record_id)
    return int(row.get("facts", {}).get(key, 0))


def test_gbg_combat_profile_uses_registered_tang_loadout(campaign) -> None:
    planner = _planner(campaign)
    profile = planner._combat_role_profile("great_bow_guard")
    assert profile["loadout_id"] == "loadout_tang_great_bow_guard"
    loadout = planner._combat_loadout(profile["loadout_id"])
    assert loadout["ranged_weapon"] == "weapon_bow_great_war"
    assert loadout["body_armor"] == "armor_tang"
    assert loadout["helmet"] == "helmet_tang"
    assert loadout["shield"] == "shield_tang"
    assert loadout["primary_melee_weapon"] == "weapon_spear_long"
    assert loadout["sidearm"] == "weapon_sword_one_hand_long"
    assert loadout["carried_ammunition"] == 36


def test_gbg_readiness_forms_personal_unit_exposes_exact_stats_and_conserves_stock(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    repair_great_bow_guard_personal_ownership(planner, at=at)

    personal_before = copy.deepcopy(planner.read("state/forces/tang-wei-personal.json"))
    stats_before = _cohort_stats(personal_before)
    assert stats_before["personnel"] == 300
    assert float(stats_before["verified_training_hours_per_person"]) == 224.0
    assert stats_before["attribute_means"]
    assert stats_before["skill_means"]

    house = copy.deepcopy(planner.read("state/houses/house_tang.json"))
    prep = house.setdefault("administrative_programs", {}).setdefault("wei_field_preparation", {})
    prep.update({
        "status": "staging_and_shortfall_review",
        "request_id": "test-gbg-readiness",
        "requested_at": at,
    })
    prep.pop("readiness_event_ref", None)
    planner.put("state/houses/house_tang.json", house)

    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    sync_great_bow_guard_readiness(planner, runtime)
    host = next(host for host in runtime["hosts"].values() if host.get("kind") == "great_bow_guard_field_readiness")

    inventory_before = copy.deepcopy(planner.read("state/inv/inventories.json"))
    treasury_before = copy.deepcopy(planner.read("state/treasury/treasury-house-tang.json"))
    champions_before = copy.deepcopy(planner.read("state/formations/tang-champions-first.json"))

    wake = settle_great_bow_guard_readiness(planner, host, at)
    assert wake is not None
    assert wake["formation_ref"] == "formation_tang_wei_great_bow_guard_first"

    formation = planner.read("state/formations/tang-wei-great-bow-guard-first.json")
    assert formation["owner_force_ref"] == "force_tang_wei_personal"
    assert formation["administrative_owner"] == "char_tang_wei"
    assert formation["command_authority"] == "char_tang_wei"
    assert formation["commander_ref"] is None
    assert formation["personnel"] == 300
    assert formation["composition"] == {"great_bow_guard": 300}
    assert formation["registered_loadout_ref"] == "loadout_tang_great_bow_guard"

    personal_after = planner.read("state/forces/tang-wei-personal.json")
    assert personal_after["available_by_role"].get("great_bow_guard", 0) == 0
    assert personal_after["allocated_to_formations"]["formation_tang_wei_great_bow_guard_first"]["personnel"] == 300
    assert personal_after["headcount"] == personal_before["headcount"]

    house_after = planner.read("state/houses/house_tang.json")
    prep_after = house_after["administrative_programs"]["wei_field_preparation"]
    stats = prep_after["great_bow_guard_stats"]
    assert stats["personnel"] == 300
    assert float(stats["verified_training_hours_per_person"]) == 224.0
    assert stats["attribute_means"] == stats_before["attribute_means"]
    assert stats["skill_means"] == stats_before["skill_means"]
    assert prep_after["great_bow_guard_formation_ref"] == "formation_tang_wei_great_bow_guard_first"

    inventory_after = planner.read("state/inv/inventories.json")
    issued = prep_after["issued_loadout_items"]
    assert _inventory_fact(inventory_before, "tang_restricted_equipment", "Tang Armor unissued reserve") - _inventory_fact(inventory_after, "tang_restricted_equipment", "Tang Armor unissued reserve") == issued["armor_tang"]
    assert _inventory_fact(inventory_before, "tang_restricted_equipment", "Tang Helmet unissued reserve") - _inventory_fact(inventory_after, "tang_restricted_equipment", "Tang Helmet unissued reserve") == issued["helmet_tang"]
    assert _inventory_fact(inventory_before, "tang_restricted_equipment", "Tang Shield unissued reserve") - _inventory_fact(inventory_after, "tang_restricted_equipment", "Tang Shield unissued reserve") == issued["shield_tang"]
    assert _inventory_fact(inventory_before, "bows", "Great War Bow armory reserve") - _inventory_fact(inventory_after, "bows", "Great War Bow armory reserve") == issued["weapon_bow_great_war"]
    assert _inventory_fact(inventory_before, "ammunition", "War Arrows strategic reserve") - _inventory_fact(inventory_after, "ammunition", "War Arrows strategic reserve") == prep_after["field_war_arrows"]

    treasury_after = planner.read("state/treasury/treasury-house-tang.json")
    champions_after = planner.read("state/formations/tang-champions-first.json")
    staged = prep_after["supply_staging"]
    assert int(treasury_before["food_kg"]) - int(treasury_after["food_kg"]) == staged["great_bow_guard_food_kg"] + staged["champions_food_kg"]
    assert int(treasury_before["fodder_kg"]) - int(treasury_after["fodder_kg"]) == staged["champions_fodder_kg"]
    assert int(champions_after["logistics"]["food_kg"]) - int(champions_before["logistics"]["food_kg"]) == staged["champions_food_kg"]
    assert int(champions_after["logistics"]["fodder_kg"]) - int(champions_before["logistics"]["fodder_kg"]) == staged["champions_fodder_kg"]

    event_ref = str(host["readiness_event_ref"])
    assert get_causal_event(planner, event_ref) is not None
    inventory_once = copy.deepcopy(planner.read("state/inv/inventories.json"))
    treasury_once = copy.deepcopy(planner.read("state/treasury/treasury-house-tang.json"))
    assert settle_great_bow_guard_readiness(planner, host, at) is None
    assert planner.read("state/inv/inventories.json") == inventory_once
    assert planner.read("state/treasury/treasury-house-tang.json") == treasury_once
