from __future__ import annotations

import json


def test_tang_manor_uses_shared_land_labor_food_close(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner

    planner = ProductionCampaignPlanner(campaign)
    before = planner.read("state/economy/private/qin.json")
    row0 = before["local_regions"]["regions"]["loc_tang_manor"]
    grain0 = int(row0["commodity_stock"].get("grain_kg", 0))
    planner._settle_private_production("qin", 1, "244-BCE-09-01T07:22:48+08:00")
    after = planner.read("state/economy/private/qin.json")
    row = after["local_regions"]["regions"]["loc_tang_manor"]
    close = row["production_runtime"]["last_food_close"]
    population = planner.read("state/population/qin.json")
    exact_local = population["local_population"]["sites"]["loc_tang_manor"]
    assert row["resident_population"] == exact_local["civilian_population"]
    assert close["produced_grain_kg"] > 0
    assert close["grain_consumed_kg"] > 0
    assert close["grain_shortfall_kg_before_internal_transfer"] == 0
    from sword_runtime.land_development import productive_land_area_km2, productive_labor_access_factor
    land = planner.read("state/development/land.json")
    rules = planner.read("game/data/mechanics/land-development.json")
    assert productive_land_area_km2(land, "loc_tang_manor", "agriculture") == 4300.0
    access = productive_labor_access_factor(land, site_ref="loc_tang_manor", commuting_workers=int(exact_local["agricultural_available"]), rules=rules)
    assert float(access["factor"]) <= 1.0
    assert int(row["commodity_stock"]["grain_kg"]) >= 0
    assert int(row["commodity_stock"]["grain_kg"]) != grain0 or close["produced_grain_kg"] == close["grain_consumed_kg"]


def test_tang_manor_commute_access_is_physical_not_owner_bonus(campaign):
    from sword_runtime.land_development import productive_labor_access_factor
    land = json.loads((campaign / "state/development/land.json").read_text())
    rules = json.loads((campaign / "game/data/mechanics/land-development.json").read_text())
    out = productive_labor_access_factor(land, site_ref="loc_tang_manor", commuting_workers=250000, rules=rules)
    assert 0.0 < float(out["factor"]) <= 1.0
    assert out.get("resident_site_ref") == "loc_tang_inner_walls"
