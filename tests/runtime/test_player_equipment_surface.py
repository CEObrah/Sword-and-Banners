from __future__ import annotations

import json

from conftest import execute_production
from sword_runtime.api.equipment_support import EquipmentAwareCampaignOperations
from sword_runtime.engine import SwordRuntime


def _manifest(root):
    return json.loads((root / "state/player-detail/equipment-manifest.json").read_text())


def _entry(root, item_key):
    return next(row for row in _manifest(root)["equipment_manifest"] if row["item_id"] == item_key)


def test_play_context_exposes_exact_player_owned_equipment_keys(campaign):
    runtime = SwordRuntime(campaign)
    context = EquipmentAwareCampaignOperations(runtime).play_context()
    equipment = context["player"]["owned_equipment"]
    keys = {row["item_key"] for row in equipment}
    assert {
        "armor_tang",
        "helmet_tang",
        "weapon_bow_great_war",
        "weapon_lance_cavalry",
        "shield_tang",
        "weapon_sword_one_hand_long",
        "horse_tang_heavy_war",
        "tack_tang",
        "horse_armor_tang",
    } <= keys
    assert context["player"]["owned_equipment_count"] == len(equipment)
    assert context["commands"]["command_types"]["equipment_equip"]["input_guidance"]["item_key"]["rule"].startswith("use an exact item_key")


def test_production_equipment_equip_synchronizes_compact_player_state(campaign):
    execute_production(campaign, "equipment_equip", {"item_key": "armor_tang", "quantity": 1})
    player = json.loads((campaign / "state/player.json").read_text())
    assert "armor_tang" in player["current_equipment_state"]["worn"]
    assert "equipped" in _entry(campaign, "armor_tang")["current_state"]


def test_production_mount_and_barding_prepare_without_teleporting_mount(campaign):
    execute_production(campaign, "equipment_equip", {"item_key": "horse_tang_heavy_war", "quantity": 1})
    execute_production(campaign, "equipment_equip", {"item_key": "tack_tang", "quantity": 1})
    execute_production(campaign, "equipment_equip", {"item_key": "horse_armor_tang", "quantity": 1})

    assert "assigned/prepared" in _entry(campaign, "horse_tang_heavy_war")["current_state"]
    assert "fitted" in _entry(campaign, "tack_tang")["current_state"]
    assert "fitted" in _entry(campaign, "horse_armor_tang")["current_state"]

    player = json.loads((campaign / "state/player.json").read_text())
    assert player["current_equipment_state"]["mounted"] is False
    assert player["current_equipment_state"]["mount_location"] == "House Tang cavalry stables"


def test_prepared_mount_can_be_unequipped_through_existing_equipment_contract(campaign):
    execute_production(campaign, "equipment_equip", {"item_key": "horse_tang_heavy_war", "quantity": 1})
    execute_production(campaign, "equipment_unequip", {"item_key": "horse_tang_heavy_war", "quantity": 1})
    assert _entry(campaign, "horse_tang_heavy_war")["current_state"] == "cavalry stables"
