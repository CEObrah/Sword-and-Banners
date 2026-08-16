from __future__ import annotations

import copy

from sword_runtime.formation_armory_issue import issue_house_armory_to_formation
from sword_runtime.production_planner import ProductionCampaignPlanner


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    meta = copy.deepcopy(planner.read("state/meta.json"))
    planner.PLAYER_ACTOR = str(meta["player_id"])
    planner._reset()
    return planner


def _fact(planner, record_id: str, key: str) -> int:
    registry = planner.read("state/inv/inventories.json")
    row = next(item for item in registry["records"] if item.get("record_id") == record_id)
    return int(row["facts"].get(key, 0))


def test_partial_house_issue_is_conserved_and_does_not_fake_complete_loadouts(campaign) -> None:
    planner = _planner(campaign)
    formation_ref = "formation_tang_wei_great_bow_guard_first"
    at = str(planner.read("state/runtime.json")["world_time"])
    before = _fact(planner, "tang_restricted_equipment", "Tang Armor unissued reserve")

    result = issue_house_armory_to_formation(
        planner,
        formation_ref=formation_ref,
        item_key="armor_tang",
        quantity=300,
        actor_ref="char_tang_wei",
        at=at,
    )
    assert _fact(planner, "tang_restricted_equipment", "Tang Armor unissued reserve") == before - 300
    formation = planner.read("state/formations/tang-wei-great-bow-guard-first.json")
    assert formation["equipment_staging_by_item"]["armor_tang"] == 300
    assert formation["equipment_units_by_role"]["great_bow_guard"] == 0
    assert float(formation["equipment_completeness"]) == 0.0
    assert result["complete_loadout_units_converted"] == 0


def test_complete_registered_loadout_converts_staging_to_equipment_units(campaign) -> None:
    planner = _planner(campaign)
    formation_ref = "formation_tang_wei_great_bow_guard_first"
    at = str(planner.read("state/runtime.json")["world_time"])
    # Current save has four exact House counters; seed the two deliberately
    # missing weapon counters only inside this test fixture to prove conversion.
    registry = copy.deepcopy(planner.read("state/inv/inventories.json"))
    restricted = next(row for row in registry["records"] if row.get("record_id") == "tang_restricted_equipment")
    restricted["facts"]["Long Spear test reserve"] = 300
    restricted["facts"]["Long Spear test issued"] = 0
    restricted["facts"]["Long Sword test reserve"] = 300
    restricted["facts"]["Long Sword test issued"] = 0
    planner.put("state/inv/inventories.json", registry)

    from sword_runtime import formation_armory_issue as module
    old = copy.deepcopy(module._ARMORY_COUNTERS)
    module._ARMORY_COUNTERS["weapon_spear_long"] = ("tang_restricted_equipment", "Long Spear test reserve", "Long Spear test issued")
    module._ARMORY_COUNTERS["weapon_sword_one_hand_long"] = ("tang_restricted_equipment", "Long Sword test reserve", "Long Sword test issued")
    try:
        for item in (
            "armor_tang", "helmet_tang", "shield_tang", "weapon_bow_great_war",
            "weapon_spear_long", "weapon_sword_one_hand_long",
        ):
            issue_house_armory_to_formation(
                planner,
                formation_ref=formation_ref,
                item_key=item,
                quantity=300,
                actor_ref="char_tang_wei",
                at=at,
            )
    finally:
        module._ARMORY_COUNTERS.clear()
        module._ARMORY_COUNTERS.update(old)

    formation = planner.read("state/formations/tang-wei-great-bow-guard-first.json")
    assert formation["equipment_units_by_role"]["great_bow_guard"] == 300
    assert float(formation["equipment_completeness"]) == 1.0
    assert formation.get("equipment_staging_by_item", {}) == {}


def test_unregistered_armory_item_fails_without_mutating_inventory(campaign) -> None:
    planner = _planner(campaign)
    before = copy.deepcopy(planner.read("state/inv/inventories.json"))
    try:
        issue_house_armory_to_formation(
            planner,
            formation_ref="formation_tang_wei_great_bow_guard_first",
            item_key="weapon_spear_long",
            quantity=300,
            actor_ref="char_tang_wei",
            at=str(planner.read("state/runtime.json")["world_time"]),
        )
    except ValueError as exc:
        assert "no exact armory reserve counter" in str(exc)
    else:
        raise AssertionError("unregistered House reserve must fail closed")
    assert planner.read("state/inv/inventories.json") == before
