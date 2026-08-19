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
    assert policy["logistics_mode"] == "campaign_wagon_train"


def test_sword_manor_trainee_current_loadout_uses_tang_protection_and_composite_bow() -> None:
    loadout = _read("game/data/loadout-records/loadout_sword_manor_trainee.json")["loadout"]
    assert loadout["body_armor"] == "armor_tang"
    assert loadout["helmet"] == "helmet_tang"
    assert loadout["shield"] == "shield_tang"
    assert loadout["ranged_weapon"] == "weapon_bow_composite"
    assert loadout["primary_melee_weapon"] == "weapon_spear_long"
    assert loadout["sidearm"] == "weapon_sword_one_hand_long"


def test_house_tang_armory_work_shares_are_fully_allocated() -> None:
    rules = _read("game/data/mechanics/house-tang-production.json")
    assert sum(
        row["work_share_basis_points"]
        for row in rules["items"]
        if row["workforce"] == "forge_and_armory_workers"
    ) == 10000


def test_current_armory_and_arrow_capacity_are_internally_consistent() -> None:
    inv = _read("state/inv/inventories.json")
    records = {row["record_id"]: row for row in inv["records"]}
    tang = records["tang_restricted_equipment"]["facts"]
    bows = records["bows"]["facts"]
    force_paths = [
        "state/forces/house-tang.json",
        "state/forces/sword-manor.json",
        "state/forces/bastion-iron-rampart.json",
        "state/forces/bastion-red-crane.json",
        "state/forces/bastion-white-lantern.json",
        "state/forces/bastion-deep-earth.json",
    ]
    forces = [_read(path) for path in force_paths]
    sword = forces[1]
    current_aggregate = sum(int(force["headcount"]) for force in forces)
    assert current_aggregate == 170060
    assert tang["Tang Armor issued"] == current_aggregate
    assert tang["Tang Armor total"] == tang["Tang Armor issued"] + tang["Tang Armor unissued reserve"]
    assert tang["Long Spear total"] == tang["Long Spear issued"] + tang["Long Spear unissued reserve"]
    assert tang["One-Handed Long Sword total"] == tang["One-Handed Long Sword issued"] + tang["One-Handed Long Sword unissued reserve"]
    assert tang["Cavalry Lance total"] == tang["Cavalry Lance issued"] + tang["Cavalry Lance unissued reserve"]
    trainee_strength = int(sword["authorized_by_role"]["trainee"])
    assert trainee_strength == 20060
    assert bows["Composite Bow active issued"] == trainee_strength
    assert bows["active aggregate standing bow loadouts"] == (
        int(bows["Great War Bow active issued"])
        + int(bows["Heavy War Bow active issued"])
        + int(bows["Composite Bow active issued"])
    )
    depot = _read("state/depots/house-tang.json")
    assert records["ammunition"]["facts"]["War Arrows strategic reserve"] == depot["stocks"]["war_arrows"]
    assert depot["storage_capacity"]["war_arrows"] >= depot["stocks"]["war_arrows"]
