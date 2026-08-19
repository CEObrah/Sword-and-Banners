from __future__ import annotations

import json
import subprocess


def _commit(campaign, *paths: str) -> None:
    subprocess.run(["git", "-C", str(campaign), "add", *paths], check=True)
    subprocess.run(["git", "-C", str(campaign), "commit", "--quiet", "-m", "test: formation equipment repair"], check=True)


def _private_materials(campaign) -> int:
    economy = json.loads((campaign / "state/economy/private/qin.json").read_text())
    rules = json.loads((campaign / "game/data/mechanics/house-tang-production.json").read_text())
    rows = economy["local_regions"]["regions"]
    return sum(int(rows[ref]["commodity_stock"].get("construction_material_units", 0)) for ref in rules["procurement_regions"])


def test_formation_repair_consumes_real_labor_material_and_silver_without_regenerating_destroyed_shields(campaign):
    from conftest import execute

    owners = json.loads((campaign / "state/index/owner-index.json").read_text())["owners"]
    formation_ref = "formation_bastion_iron_rampart_03"
    rel = owners[formation_ref]
    path = campaign / rel
    formation = json.loads(path.read_text())
    formation["command_authority"] = "char_tang_wei"
    # 3,000 heavy infantry exist, but only 1,500 physical shields survived.
    # Repair may improve those 1,500. It must not mint the missing 1,500.
    formation.setdefault("shield_units_by_role", {})["bastion_heavy_infantry"] = 1500
    formation.setdefault("shield_condition_by_role", {})["bastion_heavy_infantry"] = 50.0
    path.write_text(json.dumps(formation, ensure_ascii=False, indent=2) + "\n")
    _commit(campaign, rel)

    before_materials = _private_materials(campaign)
    treasury_path = campaign / "state/treasury/treasury-house-tang.json"
    before_silver = int(json.loads(treasury_path.read_text())["silver"])
    before_house = json.loads((campaign / "state/houses/house_tang.json").read_text())
    before_pending = float(before_house["administrative_programs"]["house_equipment_production"].get("repair_worker_hours_pending", 0) or 0)

    result = execute(campaign, "formation_equipment_repair", {
        "formation_ref": formation_ref,
        "hours": 1,
        "categories": ["shield"],
    }).receipt.result

    after = json.loads(path.read_text())
    after_materials = _private_materials(campaign)
    after_silver = int(json.loads(treasury_path.read_text())["silver"])
    house = json.loads((campaign / "state/houses/house_tang.json").read_text())
    pending = float(house["administrative_programs"]["house_equipment_production"].get("repair_worker_hours_pending", 0) or 0)

    assert after["shield_units_by_role"]["bastion_heavy_infantry"] == 1500
    assert 50.0 < float(after["shield_condition_by_role"]["bastion_heavy_infantry"]) < 100.0
    assert int(result["construction_material_units_consumed"]) > 0
    assert int(result["silver_paid"]) > 0
    assert after_materials == before_materials - int(result["construction_material_units_consumed"])
    assert after_silver == before_silver - int(result["silver_paid"])
    assert pending > before_pending
    assert float(result["worker_hours_used"]) > 0


def test_repair_worker_hours_reduce_next_monthly_armory_manufacture_capacity(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner
    from sword_runtime.house_tang_production import settle_house_tang_equipment_production

    planner = RepositoryCommandPlanner(campaign)
    house = json.loads((campaign / "state/houses/house_tang.json").read_text())
    program = house["administrative_programs"]["house_equipment_production"]
    # Consume an entire forge-worker month in repair. The next close must not
    # also grant a full free forge month of manufactured equipment.
    workers = int(program.get("forge_and_armory_workers", 7000) or 7000)
    program["repair_worker_hours_pending"] = workers * 720
    planner.put("state/houses/house_tang.json", house)
    # Ensure a deterministic reserve shortage exists while preserving exact stock.
    inv = planner.read("state/inv/inventories.json")
    target_key = "Tang Shield unissued reserve"
    for row in inv["records"]:
        if row.get("record_id") == "tang_restricted_equipment":
            row["facts"][target_key] = 0
    planner.put("state/inv/inventories.json", inv)

    out = settle_house_tang_equipment_production(planner, "244-BCE-08-29T06:00:00+08:00")
    assert out is not None
    assert int(out["produced"].get(target_key, 0)) == 0
    updated = planner.read("state/houses/house_tang.json")["administrative_programs"]["house_equipment_production"]
    assert float(updated["repair_worker_hours_pending"]) == 0.0
    assert float(updated["last_repair_worker_hours_deducted"]) == workers * 720
