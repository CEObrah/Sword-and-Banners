from __future__ import annotations

from copy import deepcopy

from sword_runtime.production_runtime_planner import ProductionCampaignPlanner
from sword_runtime.cohort_personnel import validate_cohort_ledger


def _local_service_total(pop: dict, force_ref: str) -> int:
    total = 0
    for row in pop.get("local_population", {}).get("sites", {}).values():
        rec = row.get("service_allocations", {}).get(force_ref) if isinstance(row, dict) else None
        if isinstance(rec, dict):
            total += int(rec.get("personnel", 0))
    return total


def test_full_exact_materialized_officer_life_death_conserves_force_and_population(campaign):
    planner = ProductionCampaignPlanner(campaign)
    person_ref = "char_qin_kankoku_central_gate_500_001"
    force_ref = "force_state_qin"
    force_path = planner.owner_path(force_ref)
    before_force = deepcopy(planner.read(force_path))
    before_pop = deepcopy(planner.read("state/population/qin.json"))
    person_path, person = planner._command_person(person_ref)

    planner._settle_person_death(
        person_ref, person_path, person, str(planner._world_time()), "test life death", settle_force_body=True
    )

    after_force = planner.read(force_path)
    after_pop = planner.read("state/population/qin.json")
    dead = planner.read(person_path)
    formation = planner.read(planner.owner_path("formation_qin_kankoku_central_gate"))
    assert dead["life_status"] == "dead"
    assert person_ref not in after_force["materialized_people"]
    assert int(after_force["headcount"]) == int(before_force["headcount"]) - 1
    assert int(after_pop["population_total"]) == int(before_pop["population_total"]) - 1
    assert int(after_pop["strata"]["active_military"]) == int(before_pop["strata"]["active_military"]) - 1
    assert _local_service_total(after_pop, force_ref) == _local_service_total(before_pop, force_ref) - 1
    assert person_ref not in formation.get("embedded_person_refs", [])
    validate_cohort_ledger(after_force)


def test_second_exact_internal_officer_life_death_removes_exact_formation_slot(campaign):
    planner = ProductionCampaignPlanner(campaign)
    person_ref = "char_qin_kankoku_mobile_reserve_500_001"
    force_ref = "force_state_qin"
    formation_ref = "formation_qin_kankoku_mobile_reserve"
    force_path = planner.owner_path(force_ref)
    formation_path = planner.owner_path(formation_ref)
    before_force = deepcopy(planner.read(force_path))
    before_formation = deepcopy(planner.read(formation_path))
    before_pop = deepcopy(planner.read("state/population/qin.json"))
    person_path, person = planner._command_person(person_ref)

    planner._settle_person_death(
        person_ref, person_path, person, str(planner._world_time()), "test person-lite death", settle_force_body=True
    )

    after_force = planner.read(force_path)
    after_formation = planner.read(formation_path)
    after_pop = planner.read("state/population/qin.json")
    dead = planner.read(person_path)
    assert str(dead.get("life_status", dead.get("status"))).lower() == "dead"
    assert person_ref not in after_force["materialized_people"]
    assert person_ref not in after_force["materialized_assignments"]
    assert int(after_force["headcount"]) == int(before_force["headcount"]) - 1
    assert int(after_formation["personnel"]) == int(before_formation["personnel"]) - 1
    assert int(after_formation["composition"]["cavalry"]) == int(before_formation["composition"]["cavalry"]) - 1
    assert int(after_pop["population_total"]) == int(before_pop["population_total"]) - 1
    assert int(after_pop["strata"]["active_military"]) == int(before_pop["strata"]["active_military"]) - 1
    assert _local_service_total(after_pop, force_ref) == _local_service_total(before_pop, force_ref) - 1
    validate_cohort_ledger(after_force)


def test_native_minor_polity_materialized_commander_death_uses_native_military_population(campaign):
    planner = ProductionCampaignPlanner(campaign)
    person_ref = "char_cmd_quanrong_field_host"
    force_ref = "force_quanrong"
    force_path = planner.owner_path(force_ref)
    before_force = deepcopy(planner.read(force_path))
    before_pop = deepcopy(planner.read("state/population/quanrong.json"))
    before_formation = deepcopy(planner.read(planner.owner_path("formation_quanrong_field_host")))
    person_path, person = planner._command_person(person_ref)

    planner._settle_person_death(
        person_ref, person_path, person, str(planner._world_time()), "test native polity death", settle_force_body=True
    )

    after_force = planner.read(force_path)
    after_pop = planner.read("state/population/quanrong.json")
    after_formation = planner.read(planner.owner_path("formation_quanrong_field_host"))
    assert int(after_force["headcount"]) == int(before_force["headcount"]) - 1
    assert int(after_pop["population_total"]) == int(before_pop["population_total"]) - 1
    assert int(after_pop["strata"]["active_military"]) == int(before_pop["strata"]["active_military"]) - 1
    assert _local_service_total(after_pop, force_ref) == _local_service_total(before_pop, force_ref) - 1
    # This commander is an external exact command body, not one of the 9,999
    # anonymous fighting bodies in the field-host formation.
    assert int(after_formation["personnel"]) == int(before_formation["personnel"])
    validate_cohort_ledger(after_force)
