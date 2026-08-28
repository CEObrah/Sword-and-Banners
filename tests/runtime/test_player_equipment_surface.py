from __future__ import annotations

import json
import subprocess

from conftest import execute_production
from sword_runtime.api.equipment_operations import EquipmentAwareCampaignOperations
from sword_runtime.engine import SwordRuntime


def _manifest(root):
    return json.loads((root / "state/player-detail/equipment-manifest.json").read_text())


def _entry(root, item_key):
    return next(row for row in _manifest(root)["equipment_manifest"] if row["item_id"] == item_key)


def _reset_equipment(root, *, location="loc_tang_manor_inner_citadel_family_hall"):
    manifest = _manifest(root)
    baseline = {
        "armor_heavy": "stored in adjacent ready room",
        "helmet_standard": "stored in adjacent ready room",
        "weapon_bow": "stored in adjacent ready room",
        "ammo_arrow": "quivered with bow",
        "weapon_spear": "stored with mounted issue",
        "shield_standard": "stored in adjacent ready room",
        "weapon_sword": "stored in adjacent ready room",
        "horse": "cavalry stables",
        "tack_standard": "cavalry stables",
        "horse_armor_heavy": "cavalry stables",
    }
    for row in manifest["equipment_manifest"]:
        row["current_state"] = baseline[row["item_id"]]
    manifest_path = root / "state/player-detail/equipment-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    )

    player_path = root / "state/player.json"
    player = json.loads(player_path.read_text())
    player["location"] = location
    player["current_location"] = location
    player["current_equipment_state"] = {
        "bow": "stored",
        "spear": "stored_with_mounted_issue",
        "mount_location": "House Tang cavalry stables",
        "mounted": False,
        "shield": "stored",
        "sword": "sheathed_and_stored",
        "worn": "ceremonial birthday clothing",
    }
    player_path.write_text(json.dumps(player, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    subprocess.run(
        ["git", "-C", str(root), "add", "state/player.json", "state/player-detail/equipment-manifest.json"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "commit", "--quiet", "-m", "test equipment baseline"],
        check=True,
    )


def test_play_context_exposes_exact_player_owned_equipment_keys(campaign):
    runtime = SwordRuntime(campaign)
    context = EquipmentAwareCampaignOperations(runtime).play_context()
    equipment = context["player"]["owned_equipment"]
    keys = {row["item_key"] for row in equipment}
    assert {
        "armor_heavy",
        "helmet_standard",
        "weapon_bow",
        "weapon_spear",
        "shield_standard",
        "weapon_sword",
        "horse",
        "tack_standard",
        "horse_armor_heavy",
    } <= keys
    assert context["player"]["owned_equipment_count"] == len(equipment)
    equipment_state = context["player"]["equipment_state"]
    assert "spear" in equipment_state
    assert "lance" not in equipment_state
    assert context["commands"]["command_types"]["equipment_equip"]["input_guidance"]["item_key"]["rule"].startswith("use an exact item_key")
    horse_rule = context["commands"]["command_types"]["travel"]["input_guidance"]["mode"]["horse_rule"]
    assert "mounts Tang Wei only at departure" in horse_rule


def test_production_equipment_equip_synchronizes_compact_player_state(campaign):
    _reset_equipment(campaign)
    execute_production(campaign, "equipment_equip", {"item_key": "armor_heavy", "quantity": 1})
    player = json.loads((campaign / "state/player.json").read_text())
    assert "armor_heavy" in player["current_equipment_state"]["worn"]
    assert "spear" in player["current_equipment_state"]
    assert "lance" not in player["current_equipment_state"]
    assert player["current_equipment_state"]["mounted"] is False
    assert "equipped" in _entry(campaign, "armor_heavy")["current_state"]


def test_production_mount_and_barding_prepare_without_mounting_indoors(campaign):
    _reset_equipment(campaign)
    execute_production(campaign, "equipment_equip", {"item_key": "horse", "quantity": 1})
    execute_production(campaign, "equipment_equip", {"item_key": "tack_standard", "quantity": 1})
    execute_production(campaign, "equipment_equip", {"item_key": "horse_armor_heavy", "quantity": 1})

    assert "assigned/prepared" in _entry(campaign, "horse")["current_state"]
    assert "fitted/prepared" in _entry(campaign, "tack_standard")["current_state"]
    assert "fitted/prepared" in _entry(campaign, "horse_armor_heavy")["current_state"]

    player = json.loads((campaign / "state/player.json").read_text())
    assert player["location"] == "loc_tang_manor_inner_citadel_family_hall"
    assert player["current_equipment_state"]["mounted"] is False
    assert player["current_equipment_state"]["mount_location"] == "House Tang cavalry stables"


def test_horse_travel_mounts_at_departure_and_secures_spear(campaign):
    _reset_equipment(campaign, location="loc_tang_manor_garrison_yard")
    execute_production(campaign, "equipment_equip", {"item_key": "horse", "quantity": 1})
    execute_production(campaign, "equipment_equip", {"item_key": "tack_standard", "quantity": 1})
    execute_production(campaign, "equipment_equip", {"item_key": "horse_armor_heavy", "quantity": 1})
    execute_production(campaign, "travel", {"destination_ref": "loc_kanyou", "mode": "horse"})

    player = json.loads((campaign / "state/player.json").read_text())
    assert player["location"] == "loc_kanyou"
    assert player["current_equipment_state"]["mounted"] is True
    assert player["current_equipment_state"]["mount_location"] == "loc_kanyou"
    assert player["current_equipment_state"]["spear"] == "carried/secured"
    assert "lance" not in player["current_equipment_state"]
    assert "mounted by Tang Wei" in _entry(campaign, "horse")["current_state"]
    assert "fitted to mounted horse" in _entry(campaign, "tack_standard")["current_state"]
    assert "fitted to mounted horse" in _entry(campaign, "horse_armor_heavy")["current_state"]
    assert "secured with mounted issue" in _entry(campaign, "weapon_spear")["current_state"]


def test_foot_travel_from_mounted_state_leaves_horse_at_origin(campaign):
    _reset_equipment(campaign, location="loc_tang_manor_garrison_yard")
    execute_production(campaign, "travel", {"destination_ref": "loc_kanyou", "mode": "horse"})
    execute_production(
        campaign,
        "travel",
        {"destination_ref": "loc_tang_manor_inner_citadel_family_hall", "mode": "foot"},
    )

    player = json.loads((campaign / "state/player.json").read_text())
    assert player["location"] == "loc_tang_manor_inner_citadel_family_hall"
    assert player["current_equipment_state"]["mounted"] is False
    assert player["current_equipment_state"]["mount_location"] == "loc_kanyou"
    assert "spear" in player["current_equipment_state"]
    assert "lance" not in player["current_equipment_state"]
    assert "assigned/prepared at loc_kanyou" in _entry(campaign, "horse")["current_state"]
    assert _entry(campaign, "weapon_spear")["current_state"] == "stored with mounted issue"


def test_prepared_mount_can_be_unequipped_through_existing_equipment_contract(campaign):
    _reset_equipment(campaign)
    execute_production(campaign, "equipment_equip", {"item_key": "horse", "quantity": 1})
    execute_production(campaign, "equipment_unequip", {"item_key": "horse", "quantity": 1})
    assert _entry(campaign, "horse")["current_state"] == "cavalry stables"
