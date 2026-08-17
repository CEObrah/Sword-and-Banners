from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def test_tang_war_departure_is_campaign_scale() -> None:
    policy = _read("game/data/mechanics/house-tang-field-service.json")["field_service_preparation"]
    assert policy["reserve_days"] == 120
    assert policy["arrow_loads_total"] == 30
    assert policy["spare_equipment_basis_points"] == 5000
    assert policy["logistics_mode"] == "campaign_wagon_train"


def test_sword_manor_trainee_uses_tang_protection_and_composite_bow() -> None:
    loadout = _read("game/data/loadout-records/loadout_sword_manor_trainee.json")["loadout"]
    assert loadout["body_armor"] == "armor_tang"
    assert loadout["helmet"] == "helmet_tang"
    assert loadout["shield"] == "shield_tang"
    assert loadout["ranged_weapon"] == "weapon_bow_composite"
    assert loadout["primary_melee_weapon"] == "weapon_spear_long"
    assert loadout["sidearm"] == "weapon_sword_one_hand_long"


def test_obsolete_trainee_lamellar_is_retired_from_house_production() -> None:
    rules = _read("game/data/mechanics/house-tang-production.json")
    text = json.dumps(rules)
    assert "Heavy Lamellar reserve" not in text
    assert "Lamellar Helmet reserve" not in text
    assert "Medium Shield reserve" not in text
    assert sum(
        row["work_share_basis_points"]
        for row in rules["items"]
        if row["workforce"] == "forge_and_armory_workers"
    ) == 10000


def test_armory_rebalance_and_arrow_capacity_are_internally_consistent() -> None:
    inv = _read("state/inv/inventories.json")
    records = {row["record_id"]: row for row in inv["records"]}
    assert "sword_manor_trainee_equipment" not in records
    tang = records["tang_restricted_equipment"]["facts"]
    bows = records["bows"]["facts"]
    assert tang["Tang Armor issued"] == 60000
    assert tang["Tang Armor total"] == tang["Tang Armor issued"] + tang["Tang Armor unissued reserve"]
    assert tang["Long Spear total"] == tang["Long Spear issued"] + tang["Long Spear unissued reserve"]
    assert tang["One-Handed Long Sword total"] == tang["One-Handed Long Sword issued"] + tang["One-Handed Long Sword unissued reserve"]
    assert tang["Cavalry Lance total"] == tang["Cavalry Lance issued"] + tang["Cavalry Lance unissued reserve"]
    assert bows["Composite Bow active issued"] == 20000
    depot = _read("state/depots/house-tang.json")
    assert depot["stocks"]["war_arrows"] == 2500000000
    assert depot["infrastructure_capacity"]["arrow_storage_capacity"] >= depot["stocks"]["war_arrows"]
