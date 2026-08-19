from __future__ import annotations

from sword_runtime.production_planner import ProductionCampaignPlanner
from conftest import execute_production_internal


def tx_result(execution):
    return execution.receipt.result


def planner_for(root):
    p = ProductionCampaignPlanner(root)
    p._reset()
    return p


def test_local_justice_registration_is_not_guilt_and_resolves_explicitly(campaign):
    result = tx_result(execute_production_internal(campaign, "settlement_civic_action", {
        "action": "register_local_case",
        "location_ref": "loc_kanyou",
        "case_kind": "property",
        "severity": 35,
        "subject_ref": "char_tang_wei",
    }, request_id="local-justice-register"))
    p = planner_for(campaign)
    case_ref = result["case_ref"]
    idx = p.read("state/civic/justice/index.json")
    case = p.read(idx["cases"][case_ref])
    assert case["status"] == "open"
    assert case["subject_ref"] == "char_tang_wei"
    assert case["evidence_refs"] == []
    assert "guilt" not in case
    assert "verdict" not in case

    result = tx_result(execute_production_internal(campaign, "settlement_civic_action", {
        "action": "resolve_local_case",
        "case_ref": case_ref,
        "disposition": "dismissed",
    }, request_id="local-justice-resolve"))
    p = planner_for(campaign)
    case = p.read(p.read("state/civic/justice/index.json")["cases"][case_ref])
    assert result["status"] == "resolved"
    assert case["resolution"]["disposition"] == "dismissed"
    assert case_ref not in p.read("state/civic/justice/index.json")["open_refs"]


def test_outbreak_deaths_conserve_local_and_parent_population(campaign):
    p = planner_for(campaign)
    pop_before = p.read("state/population/qin.json")
    total_before = int(pop_before["population_total"])
    local_before = int(pop_before["local_population"]["sites"]["loc_kanyou"]["civilian_population"])

    started = tx_result(execute_production_internal(campaign, "settlement_civic_action", {
        "action": "start_outbreak",
        "location_ref": "loc_kanyou",
        "syndrome": "acute febrile respiratory syndrome",
        "transmission_route": "respiratory",
        "known_cases": 1000,
        "exposed_population": 0,
        "exposure_pressure": 0,
        "population_resistance": 0,
        "severity_band": "severe",
        "incubation_hours": 48,
        "infectious_hours": 120,
    }, request_id="outbreak-start-conservation"))
    reviewed = tx_result(execute_production_internal(campaign, "settlement_civic_action", {
        "action": "review_outbreak",
        "outbreak_ref": started["outbreak_ref"],
    }, request_id="outbreak-review-conservation"))
    assert reviewed["deaths"] > 0

    p = planner_for(campaign)
    pop_after = p.read("state/population/qin.json")
    total_after = int(pop_after["population_total"])
    local_after = int(pop_after["local_population"]["sites"]["loc_kanyou"]["civilian_population"])
    assert total_before - total_after == reviewed["deaths"]
    assert local_before - local_after == reviewed["deaths"]
    assert total_after == sum(max(0, int(v)) for v in pop_after["strata"].values())


def test_outbreak_propagates_only_to_routed_demographic_sites(campaign):
    started = tx_result(execute_production_internal(campaign, "settlement_civic_action", {
        "action": "start_outbreak",
        "location_ref": "loc_qin_regional_01",
        "syndrome": "route-borne febrile syndrome",
        "transmission_route": "close_contact",
        "known_cases": 400,
        "exposed_population": 4000,
        "exposure_pressure": 80,
        "population_resistance": 0,
        "severity_band": "moderate",
        "incubation_hours": 48,
        "infectious_hours": 120,
    }, request_id="outbreak-start-propagation"))
    reviewed = tx_result(execute_production_internal(campaign, "settlement_civic_action", {
        "action": "review_outbreak",
        "outbreak_ref": started["outbreak_ref"],
    }, request_id="outbreak-review-propagation"))
    assert reviewed["propagated_outbreak_refs"]

    p = planner_for(campaign)
    routes = p.read("game/data/world/routes.json")["routes"]
    neighbors = set()
    for route in routes:
        a, b = str(route.get("a", "")), str(route.get("b", ""))
        if a == "loc_qin_regional_01": neighbors.add(b)
        if b == "loc_qin_regional_01": neighbors.add(a)
    index = p.read("state/civic/outbreaks/index.json")
    for child_ref in reviewed["propagated_outbreak_refs"]:
        child = p.read(index["outbreaks"][child_ref])
        # A facility/gate can resolve through containment to its demographic anchor,
        # but direct strategic population nodes must be physically adjacent.
        assert child["parent_outbreak_ref"] == started["outbreak_ref"]
        assert child["location_ref"] in neighbors or child["location_ref"] == "loc_tang_manor"
        assert child["known_cases"] > 0


def test_advance_time_reviews_due_outbreaks_automatically(campaign):
    started = tx_result(execute_production_internal(campaign, "settlement_civic_action", {
        "action": "start_outbreak",
        "location_ref": "loc_sai",
        "syndrome": "contained enteric syndrome",
        "transmission_route": "water_food",
        "known_cases": 30,
        "exposed_population": 100,
        "exposure_pressure": 20,
        "population_resistance": 15,
        "severity_band": "mild",
        "incubation_hours": 24,
        "infectious_hours": 72,
    }, request_id="outbreak-auto-start"))
    p = planner_for(campaign)
    idx = p.read("state/civic/outbreaks/index.json")
    before = p.read(idx["outbreaks"][started["outbreak_ref"]])
    last_before = before["last_review_at"]

    execute_production_internal(campaign, "advance_time", {"hours": 30}, request_id="outbreak-auto-advance")
    p = planner_for(campaign)
    after = p.read(p.read("state/civic/outbreaks/index.json")["outbreaks"][started["outbreak_ref"]])
    assert after["last_review_at"] != last_before
    assert after["review_history"]
