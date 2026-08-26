from __future__ import annotations

from copy import deepcopy

import sword_runtime.force_cohort_living_world as life_module
from sword_runtime.production_runtime_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.cohort_personnel import validate_cohort_ledger


def test_person_lite_annual_review_uses_derived_schedule_and_conserves_death(campaign, monkeypatch):
    planner = ProductionCampaignPlanner(campaign)
    force_path = planner.owner_path("force_state_qin")
    force = deepcopy(planner.read(force_path))
    person_ref = "officer.qin.kankoku.army.chief_of_staff"
    before_headcount = int(force["headcount"])
    before_pop = deepcopy(planner.read("state/population/qin.json"))
    monkeypatch.setattr(life_module, "annual_mortality_basis_points", lambda _age, _health: 10000)

    start = CampaignTime.parse("244-BCE-01-01T00:00:00+08:00")
    end = CampaignTime.parse("244-BCE-12-31T23:59:59+08:00")
    deaths = planner._fc_review_person_lite_life(force, start, end, ref_prefix=person_ref)

    assert deaths == 1
    assert person_ref not in force["materialized_people"]
    assert int(force["headcount"]) == before_headcount - 1
    after_pop = planner.read("state/population/qin.json")
    assert int(after_pop["population_total"]) == int(before_pop["population_total"]) - 1
    assert int(after_pop["strata"]["active_military"]) == int(before_pop["strata"]["active_military"]) - 1
    validate_cohort_ledger(force)


def test_person_lite_review_schedule_is_stable_and_not_persisted(campaign):
    planner = ProductionCampaignPlanner(campaign)
    a = planner._fc_person_lite_review_time("officer.qin.kankoku.army.chief_of_staff", 4756, "+08:00")
    b = planner._fc_person_lite_review_time("officer.qin.kankoku.army.chief_of_staff", 4756, "+08:00")
    assert a == b
    assert a.sort_year == 4756
    person_path, person = planner._command_person("officer.qin.kankoku.army.chief_of_staff")
    assert "last_life_course_review_at" not in person.get("runtime", {})
    assert "completed_life_course_reviews" not in person.get("runtime", {})


def test_dead_person_lite_is_never_trained(campaign):
    planner = ProductionCampaignPlanner(campaign)
    force = deepcopy(planner.read(planner.owner_path("force_state_qin")))
    person_ref = "officer.qin.kankoku.army.chief_of_staff"
    person_path, person = planner._command_person(person_ref)
    person["life_status"] = "dead"
    planner.put(person_path, person)
    rules = planner.read("game/data/mechanics/training.json")
    trained = planner._fc_train_person_lite_batch(
        force,
        deliberate_hours=10.0,
        role_exposure_hours=2.0,
        training_rules=rules,
        facility_grade="home_garrison",
        equipment_grade="adequate",
        recovery_grade="adequate",
        evidence_prefix="dead-person-test",
        ref_prefix=person_ref,
        window_start="244-BCE-09-01T00:00:00+08:00",
        window_end="244-BCE-09-02T00:00:00+08:00",
    )
    assert trained == 0
