from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def _read(rel: str):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def test_tang_field_service_uses_campaign_scale_reserves() -> None:
    policy = _read("game/data/mechanics/house-tang-field-service.json")["field_service_preparation"]
    assert policy["reserve_days"] == 120
    assert policy["arrow_loads_total"] == 30
    assert policy["spare_equipment_basis_points"] == 5000


def test_sword_manor_trainee_uses_consolidated_current_loadout() -> None:
    loadout = _read("game/data/loadout-records/loadout_sword_manor_trainee.json")["loadout"]
    assert loadout["body_armor"] == "armor_heavy"
    assert loadout["helmet"] == "helmet_standard"
    assert loadout["shield"] == "shield_standard"
    assert loadout["ranged_weapon"] == "weapon_bow"
    assert loadout["primary_melee_weapon"] == "weapon_spear"
    assert loadout["sidearm"] == "weapon_sword"


def test_house_tang_outfitting_reserve_is_aggregate_and_nonduplicating() -> None:
    rules = _read("game/data/mechanics/outfitting.json")
    inv = _read("state/inv/inventories.json")
    records = {row["record_id"]: row for row in inv["records"]}
    facts = records["house_tang_outfitting_sets"]["facts"]
    assert rules["house_tang_reserve"]["record_id"] == "house_tang_outfitting_sets"
    assert facts["standard_role_sets_reserve"] == 18765
    assert facts["crossbow_role_sets_reserve"] == 4625
    assert facts["mounted_harness_sets_reserve"] == 3000
    assert facts["ammunition_owner_ref"] == "depot_house_tang"
    assert facts["mount_stock_owner_ref"] == "depot_house_tang"
    assert not any("Armor issued" in key or "Lance" in key or "Great War Bow" in key for key in facts)


def test_house_tang_ammunition_is_only_physical_depot_stock() -> None:
    depot = _read("state/depots/house-tang.json")
    facts = {row["record_id"]: row["facts"] for row in _read("state/inv/inventories.json")["records"]}["house_tang_outfitting_sets"]
    assert facts["ammunition_owner_ref"] == "depot_house_tang"
    assert int(depot["stocks"]["war_arrows"]) <= int(depot["storage_capacity"]["war_arrows"])
    assert int(depot["stocks"]["war_bolts"]) <= int(depot["storage_capacity"]["war_bolts"])
    assert "war_arrows" not in facts and "war_bolts" not in facts
