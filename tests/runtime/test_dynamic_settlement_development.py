from __future__ import annotations
import copy


def test_dynamic_settlement_foundation_moves_real_households_and_routes_site(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    from sword_runtime.settlement_development import complete_settlement_foundation, refresh_dynamic_settlement_class
    planner = ProductionCampaignPlanner(campaign)
    pop_path = "state/population/qin.json"
    before = copy.deepcopy(planner.read(pop_path))
    before_total = int(before["population_total"])
    source = "loc_qin_regional_01"
    source_before = int(before["local_population"]["sites"][source]["civilian_population"])
    project = {
        "project_ref": "test_settlement_foundation",
        "kind": "settlement_foundation",
        "effect": {"source_site_ref": source, "new_settlement_name": "Test River Hamlet", "initial_settlers": 600},
    }
    result = complete_settlement_foundation(planner, institution={"administrative_owner": "state_qin"}, project=project, at=planner.read("state/meta.json")["time"])
    ref = result["settlement_ref"]
    after_departure = planner.read(pop_path)
    assert int(after_departure["population_total"]) == before_total
    assert int(after_departure["local_population"]["sites"][source]["civilian_population"]) == source_before - 600
    assert int(after_departure["local_population"]["sites"][ref]["civilian_population"]) == 0
    mobility = planner.read("state/mobility/population-transit.json")
    cohort = mobility["cohorts"][result["migration_ref"]]
    planner._settle_population_mobility_arrival({"cohort_ref": result["migration_ref"]}, str(cohort["arrives_at"]))
    arrived = planner.read(pop_path)
    assert int(arrived["population_total"]) == before_total
    assert int(arrived["local_population"]["sites"][ref]["civilian_population"]) == 600
    assert refresh_dynamic_settlement_class(planner, ref) == "village"
    land = planner.read("state/development/land.json")
    assert ref in land["sites"]
    assert land["sites"][ref]["parcel_area_km2"] == 1.0
    assert land["sites"][ref]["enclosed_area_km2"] == 0.0
    dynamic = planner.read("state/geography/dynamic.json")
    assert any(row["ref"] == ref for row in dynamic["locations"])
    assert any(row["ref"] == result["route_ref"] for row in dynamic["routes"])
    plan = planner._find_route(source, ref, mode="foot")
    assert result["route_ref"] in plan["route_refs"]
