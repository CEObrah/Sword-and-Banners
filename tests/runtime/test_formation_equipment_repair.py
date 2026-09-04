from __future__ import annotations

import json
import subprocess


def _commit(campaign, *paths: str) -> None:
    subprocess.run(["git", "-C", str(campaign), "add", *paths], check=True)
    subprocess.run(["git", "-C", str(campaign), "commit", "--quiet", "-m", "test: aggregate formation equipment repair"], check=True)


def _private_materials(campaign) -> int:
    economy = json.loads((campaign / "state/economy/private/qin.json").read_text())
    rules = json.loads((campaign / "game/data/mechanics/outfitting.json").read_text())
    rows = economy["local_regions"]["regions"]
    return sum(int(rows[ref]["commodity_stock"].get("construction_material_units", 0)) for ref in rules["procurement_region_refs"] if ref in rows)


def test_formation_repair_consumes_real_labor_material_and_silver_without_regenerating_destroyed_shields(campaign):
    from conftest import execute

    owners = json.loads((campaign / "state/index/owner-index.json").read_text())["owners"]
    formation_ref = "formation_house_tang_outer_wall_iron_wall_03"
    rel = owners[formation_ref]
    path = campaign / rel
    formation = json.loads(path.read_text())
    formation["command_authority"] = "char_tang_wei"
    formation.setdefault("shield_units_by_role", {})["house_infantry"] = 1500
    formation.setdefault("shield_condition_by_role", {})["house_infantry"] = 50.0
    path.write_text(json.dumps(formation, ensure_ascii=False, indent=2) + "\n")
    _commit(campaign, rel)

    before_materials = _private_materials(campaign)
    treasury_path = campaign / "state/treasury/treasury-house-tang.json"
    before_silver = int(json.loads(treasury_path.read_text())["silver"])
    result = execute(campaign, "formation_equipment_repair", {"formation_ref": formation_ref, "hours": 1, "categories": ["shield"]}).receipt.result

    after = json.loads(path.read_text())
    after_materials = _private_materials(campaign)
    after_silver = int(json.loads(treasury_path.read_text())["silver"])
    assert after["shield_units_by_role"]["house_infantry"] == 1500
    assert 50.0 < float(after["shield_condition_by_role"]["house_infantry"]) < 100.0
    assert int(result["construction_material_units_consumed"]) > 0
    assert int(result["silver_paid"]) > 0
    assert after_materials == before_materials - int(result["construction_material_units_consumed"])
    assert after_silver == before_silver - int(result["silver_paid"])
    assert float(result["worker_hours_used"]) > 0
    assert "last_repair" in after["equipment_service_runtime"]


def test_repair_has_no_monthly_item_factory_side_effect(campaign):
    from conftest import execute

    owners = json.loads((campaign / "state/index/owner-index.json").read_text())["owners"]
    formation_ref = "formation_house_tang_outer_wall_iron_wall_03"
    rel = owners[formation_ref]
    path = campaign / rel
    formation = json.loads(path.read_text())
    formation["command_authority"] = "char_tang_wei"
    formation.setdefault("armor_units_by_role", {})["house_infantry"] = 1000
    formation.setdefault("armor_condition_by_role", {})["house_infantry"] = 80.0
    path.write_text(json.dumps(formation, ensure_ascii=False, indent=2) + "\n")
    _commit(campaign, rel)
    inv_path = campaign / "state/inv/inventories.json"
    before = json.loads(inv_path.read_text())
    execute(campaign, "formation_equipment_repair", {"formation_ref": formation_ref, "hours": 1, "categories": ["armor"]})
    after = json.loads(inv_path.read_text())
    assert after == before, "condition repair must not regenerate or consume aggregate replacement sets"
    house = json.loads((campaign / "state/houses/house_tang.json").read_text())
    assert "house_equipment_production" not in house.get("administrative_programs", {})
