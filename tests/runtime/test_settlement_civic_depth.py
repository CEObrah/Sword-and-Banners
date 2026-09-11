from __future__ import annotations

import copy
import pytest
from sword_runtime.production_runtime_planner import ProductionCampaignPlanner
from sword_runtime.settlement_civic_depth import (
    _open_justice_records,
    _outbreak_route_ids,
    sync_outbreak_routes,
)
from conftest import execute_hosted_production_internal


def tx_result(execution):
    return execution.receipt.result


def planner_for(root):
    p = ProductionCampaignPlanner(root)
    p._reset()
    return p


def test_local_justice_registration_is_not_guilt_and_resolves_explicitly(campaign):
    result = tx_result(execute_hosted_production_internal(campaign, "settlement_civic_action", {
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

    result = tx_result(execute_hosted_production_internal(campaign, "settlement_civic_action", {
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

    started = tx_result(execute_hosted_production_internal(campaign, "settlement_civic_action", {
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
    reviewed = tx_result(execute_hosted_production_internal(campaign, "settlement_civic_action", {
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
    started = tx_result(execute_hosted_production_internal(campaign, "settlement_civic_action", {
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
    reviewed = tx_result(execute_hosted_production_internal(campaign, "settlement_civic_action", {
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
    started = tx_result(execute_hosted_production_internal(campaign, "settlement_civic_action", {
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

    execute_hosted_production_internal(campaign, "advance_time", {"hours": 30}, request_id="outbreak-auto-advance")
    p = planner_for(campaign)
    after = p.read(p.read("state/civic/outbreaks/index.json")["outbreaks"][started["outbreak_ref"]])
    assert after["last_review_at"] != last_before
    assert after["review_history"]


def test_autonomous_pressure_can_seed_first_outbreak_and_exact_named_exposure(campaign):
    p = planner_for(campaign)
    at = str(p.read("state/runtime.json")["world_time"])

    # Place one exact named person at Sai and prove the bounded location index
    # follows exact-person writes instead of scanning all character files.
    person_path = p.owner_path("char_tou")
    person = copy.deepcopy(p.read(person_path))
    person["location"] = "loc_sai"
    person["location_scope"] = "loc_sai"
    p.put(person_path, person)
    loc_index = p.read("state/index/person-location-index.json")
    assert loc_index["person_location"]["char_tou"] == "loc_sai"

    # Create committed physical pressure, not a random disease roll.
    infra = copy.deepcopy(p.read("state/infrastructure/settlements.json"))
    support = infra["sites"]["loc_sai"]["physical_support"]
    support["water_capacity_people"] = 0
    support["sanitation_capacity_people"] = 0
    p.put("state/infrastructure/settlements.json", infra)

    result = p._autonomous_civic_pressure_review("qin", at, 1)
    assert result["outbreak_ref"]
    idx = p.read("state/civic/outbreaks/index.json")
    outbreak = p.read(idx["outbreaks"][result["outbreak_ref"]])
    assert outbreak["status"] == "active"
    assert outbreak["location_ref"] == "loc_sai"
    assert any(row.get("person_ref") == "char_tou" for row in outbreak.get("named_exposures", []))
    seed = idx["autonomous_seed_history"][-1]
    assert seed["outbreak_ref"] == result["outbreak_ref"]
    assert seed["basis"]["water_shortfall_fraction"] > 0
    assert seed["basis"]["sanitation_shortfall_fraction"] > 0


def test_autonomous_civic_case_is_pressure_backed_and_does_not_imply_guilt(campaign):
    p = planner_for(campaign)
    at = str(p.read("state/runtime.json")["world_time"])
    state = copy.deepcopy(p.read("state/states/qin.json"))
    state["internal_stability"] = 10
    p.put("state/states/qin.json", state)

    result = p._autonomous_civic_pressure_review("qin", at, 1)
    assert result["case_ref"]
    idx = p.read("state/civic/justice/index.json")
    case = p.read(idx["cases"][result["case_ref"]])
    assert case["autonomous_seed"] is True
    assert case.get("subject_ref") is None
    assert case.get("evidence_refs", []) == []
    assert "guilt" not in case and "verdict" not in case
    assert case["causal_basis"]["state_stability"] == 10


def test_person_lite_location_projection_participates_in_named_outbreak_routing(campaign):
    p = planner_for(campaign)
    at = str(p.read("state/runtime.json")["world_time"])
    person_ref = "officer.qin.kankoku.army.chief_of_staff"
    person_path = p.owner_path(person_ref)
    person = copy.deepcopy(p.read(person_path))
    assert person.get("schema") == "person-lite"

    # Representation must not change physical presence. Moving the exact
    # fragment-backed officer updates the same bounded location projection used
    # by full characters, so a site-local outbreak can route to that body.
    person["current_location"] = "loc_sai"
    p.put(person_path, person)
    loc_index = p.read("state/index/person-location-index.json")
    assert loc_index["person_location"][person_ref] == "loc_sai"
    assert person_ref in p._named_people_at_demographic_site("loc_sai")

    outbreak = {
        "outbreak_ref": "outbreak.person-lite.routing.fixture",
        "population_resistance": 0,
        "infectious_hours": 120,
        "syndrome": "fixture syndrome",
        "named_exposures": [{"person_ref": person_ref, "first_exposed_at": at, "status": "exposed"}],
    }
    result = p._settle_named_outbreak_exposures(outbreak, at, 1.0)
    row = outbreak["named_exposures"][0]
    assert row["status"] in {"exposed", "infected"}
    assert row.get("status") != "unavailable"
    assert row.get("last_exposure_review_at") == at or row.get("infected_at") == at
    assert result["infected"] in {0, 1}


def test_named_outbreak_routing_revalidates_authoritative_person_location_not_stale_index(campaign):
    p = planner_for(campaign)
    person_ref = "char_tou"
    person = p.read(p.owner_path(person_ref))
    authoritative_location = person.get("current_location") or person.get("location")
    assert authoritative_location != "loc_sai"

    # Corrupt only the non-authoritative routing accelerator. Physical outbreak
    # exposure must still come from the exact person owner, never this index.
    index = copy.deepcopy(p.read("state/index/person-location-index.json"))
    prior = index.setdefault("person_location", {}).get(person_ref)
    if isinstance(prior, str):
        index.setdefault("by_location", {})[prior] = [
            ref for ref in index.get("by_location", {}).get(prior, []) if ref != person_ref
        ]
    index["person_location"][person_ref] = "loc_sai"
    index.setdefault("by_location", {}).setdefault("loc_sai", []).append(person_ref)
    p.put("state/index/person-location-index.json", index)

    assert person_ref not in p._named_people_at_demographic_site("loc_sai")


def test_stale_justice_index_cannot_substitute_or_veto_exact_case(campaign):
    p = planner_for(campaign)
    at = str(p.read("state/runtime.json")["world_time"])
    a_ref = "case.routing.a"
    b_ref = "case.routing.b"
    p._register_local_case({
        "case_ref": a_ref, "location_ref": "loc_kanyou", "case_kind": "property", "severity": 20,
    }, at)
    p._register_local_case({
        "case_ref": b_ref, "location_ref": "loc_kanyou", "case_kind": "violence", "severity": 25,
    }, at)
    idx = copy.deepcopy(p.read("state/civic/justice/index.json"))
    a_path = idx["cases"][a_ref]
    b_path = idx["cases"][b_ref]

    # The routing index is authority:false. Redirecting A to B must not make an
    # A disposition mutate B; exact case_ref identity wins.
    idx["cases"][a_ref] = b_path
    p.put("state/civic/justice/index.json", idx)
    p._resolve_local_case({"case_ref": a_ref, "disposition": "dismissed"}, at)
    assert p.read(a_path)["status"] == "resolved"
    assert p.read(b_path)["status"] == "open"

    # Nor may a stale key veto creation when no exact owner for that ref exists.
    ghost_ref = "case.routing.ghost"
    idx = copy.deepcopy(p.read("state/civic/justice/index.json"))
    idx.setdefault("cases", {})[ghost_ref] = b_path
    p.put("state/civic/justice/index.json", idx)
    created = p._register_local_case({
        "case_ref": ghost_ref, "location_ref": "loc_kanyou", "case_kind": "other", "severity": 10,
    }, at)
    assert created["case_ref"] == ghost_ref
    repaired = p.read("state/civic/justice/index.json")
    assert repaired["cases"][ghost_ref] != b_path
    assert p.read(repaired["cases"][ghost_ref])["case_ref"] == ghost_ref


def test_stale_outbreak_index_cannot_substitute_or_veto_exact_outbreak(campaign):
    p = planner_for(campaign)
    at = str(p.read("state/runtime.json")["world_time"])
    common = {
        "location_ref": "loc_sai", "transmission_route": "close_contact", "known_cases": 1,
        "exposed_population": 0, "exposure_pressure": 1, "population_resistance": 50,
        "severity_band": "mild", "incubation_hours": 48, "infectious_hours": 72,
    }
    a_ref = "outbreak.routing.a"
    b_ref = "outbreak.routing.b"
    p._start_outbreak({**common, "outbreak_ref": a_ref, "syndrome": "routing syndrome a"}, at)
    p._start_outbreak({**common, "outbreak_ref": b_ref, "syndrome": "routing syndrome b"}, at)
    idx = copy.deepcopy(p.read("state/civic/outbreaks/index.json"))
    a_path = idx["outbreaks"][a_ref]
    b_path = idx["outbreaks"][b_ref]

    idx["outbreaks"][a_ref] = b_path
    p.put("state/civic/outbreaks/index.json", idx)
    p._set_outbreak_quarantine({
        "outbreak_ref": a_ref, "active": True, "quarantine_strength": 77, "supply_days": 3,
    }, at)
    assert p.read(a_path)["quarantine"]["strength"] == 77
    assert p.read(b_path)["quarantine"]["strength"] == 0

    ghost_ref = "outbreak.routing.ghost"
    idx = copy.deepcopy(p.read("state/civic/outbreaks/index.json"))
    idx.setdefault("outbreaks", {})[ghost_ref] = b_path
    p.put("state/civic/outbreaks/index.json", idx)
    created = p._start_outbreak({**common, "outbreak_ref": ghost_ref, "syndrome": "routing syndrome ghost"}, at)
    assert created["outbreak_ref"] == ghost_ref
    repaired = p.read("state/civic/outbreaks/index.json")
    assert repaired["outbreaks"][ghost_ref] != b_path
    assert p.read(repaired["outbreaks"][ghost_ref])["outbreak_ref"] == ghost_ref


def test_exact_outbreak_repairs_missing_active_and_route_cache(campaign):
    p = planner_for(campaign)
    at = str(p.read("state/runtime.json")["world_time"])
    outbreak_ref = "outbreak.routing.recover.exact"
    p._start_outbreak({
        "outbreak_ref": outbreak_ref,
        "location_ref": "loc_sai",
        "syndrome": "routing recovery syndrome",
        "transmission_route": "close_contact",
        "known_cases": 1,
        "exposed_population": 0,
        "exposure_pressure": 1,
        "population_resistance": 50,
        "severity_band": "mild",
        "incubation_hours": 48,
        "infectious_hours": 72,
    }, at)
    exact_path = p.owner_path(outbreak_ref)

    idx = copy.deepcopy(p.read("state/civic/outbreaks/index.json"))
    idx.setdefault("outbreaks", {}).pop(outbreak_ref, None)
    idx["active_refs"] = [ref for ref in idx.get("active_refs", []) if ref != outbreak_ref]
    p.put("state/civic/outbreaks/index.json", idx)

    runtime = copy.deepcopy(p.read("state/runtime.json"))
    host_id, _event_id = _outbreak_route_ids(outbreak_ref)
    runtime.setdefault("hosts", {}).pop(host_id, None)
    p.put("state/runtime.json", runtime)

    sync_outbreak_routes(p, runtime)
    assert host_id in runtime["hosts"]
    repaired = p.read("state/civic/outbreaks/index.json")
    assert repaired["outbreaks"][outbreak_ref] == exact_path
    assert outbreak_ref in repaired["active_refs"]


def test_exact_justice_case_repairs_missing_open_and_route_cache(campaign):
    p = planner_for(campaign)
    at = str(p.read("state/runtime.json")["world_time"])
    case_ref = "case.routing.recover.exact"
    p._register_local_case({
        "case_ref": case_ref,
        "location_ref": "loc_kanyou",
        "case_kind": "other",
        "severity": 15,
    }, at)
    exact_path = p.owner_path(case_ref)

    idx = copy.deepcopy(p.read("state/civic/justice/index.json"))
    idx.setdefault("cases", {}).pop(case_ref, None)
    idx["open_refs"] = [ref for ref in idx.get("open_refs", []) if ref != case_ref]
    p.put("state/civic/justice/index.json", idx)

    rows = _open_justice_records(p, p.read("state/civic/justice/index.json"))
    assert any(ref == case_ref and path == exact_path for ref, path, _doc in rows)
    repaired = p.read("state/civic/justice/index.json")
    assert repaired["cases"][case_ref] == exact_path
    assert case_ref in repaired["open_refs"]


def test_civic_explicit_refs_cannot_escape_civic_owner_directories(campaign):
    p = planner_for(campaign)
    at = str(p.read("state/runtime.json")["world_time"])
    with pytest.raises(ValueError, match="invalid civic record ref"):
        p._register_local_case({
            "case_ref": "../../state/player", "location_ref": "loc_kanyou", "case_kind": "other", "severity": 10,
        }, at)
    with pytest.raises(ValueError, match="invalid civic record ref"):
        p._start_outbreak({
            "outbreak_ref": "../../state/player", "location_ref": "loc_sai", "syndrome": "invalid",
            "transmission_route": "close_contact", "known_cases": 1, "exposed_population": 0,
            "exposure_pressure": 1, "population_resistance": 50, "severity_band": "mild",
            "incubation_hours": 48, "infectious_hours": 72,
        }, at)
