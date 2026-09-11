from __future__ import annotations

import copy

from sword_runtime.household_request_flow import _house_tang_force_status, _perform_house_requested_military_intake
from sword_runtime.production_planner import ProductionCampaignPlanner


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    return planner


def _cohort_total(row: dict) -> int:
    return (
        sum(int(v) for v in row.get("reserve_by_location", {}).values())
        + sum(int(v) for v in row.get("allocated_by_formation", {}).values())
        + sum(int(v) for v in row.get("allocated_external_by_formation", {}).values())
    )


def _mean_skill(row: dict) -> float:
    skills = row.get("skill_means", {})
    return sum(float(v) for v in skills.values()) / max(1, len(skills))


def test_current_house_intake_has_zero_phantom_vacancies(campaign) -> None:
    planner = _planner(campaign)
    status = _house_tang_force_status(planner)
    assert status["current_by_role"] == {"house_infantry": 164060, "house_cavalry": 12000}
    assert status["vacancy_by_role"] == {"house_infantry": 0, "house_cavalry": 0}
    assert status["practical_intake_now"] == 0


def test_real_infantry_vacancy_reclassifies_existing_qin_population_one_for_one(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    force_path = "state/forces/house-tang.json"
    qin_path = "state/population/qin.json"
    force0 = copy.deepcopy(planner.read(force_path))
    qin0 = copy.deepcopy(planner.read(qin_path))
    before_ids = set(force0["cohort_ledger"]["cohorts"])
    force = copy.deepcopy(force0)
    force["authorized_by_role"]["house_infantry"] += 12
    force["authorized_strength"] += 12
    planner.put(force_path, force)
    result = _perform_house_requested_military_intake(planner, at, "test:unified-house-intake")
    assert result["intake_count"] == 12
    assert result["intake_by_role"] == {"house_infantry": 12}
    force1 = planner.read(force_path)
    qin1 = planner.read(qin_path)
    assert force1["headcount"] == force0["headcount"] + 12
    assert qin1["population_total"] == qin0["population_total"]
    source_roles = ("agricultural", "craft_and_industry", "household_and_service", "merchant_and_transport")
    assert sum(qin1["strata"][r] for r in source_roles) == sum(qin0["strata"][r] for r in source_roles) - 12
    assert qin1["strata"]["private_household_military"] == qin0["strata"]["private_household_military"] + 12
    new_rows = [row for cid, row in force1["cohort_ledger"]["cohorts"].items() if cid not in before_ids]
    assert sum(_cohort_total(row) for row in new_rows) == 12


def test_fresh_replacement_cohort_does_not_inherit_veteran_average(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    force_path = "state/forces/house-tang.json"
    force0 = copy.deepcopy(planner.read(force_path))
    before_ids = set(force0["cohort_ledger"]["cohorts"])
    veteran = force0["cohort_ledger"]["cohorts"]["cohort_force_house_tang_house_guard_standing"]
    force = copy.deepcopy(force0)
    force["authorized_by_role"]["house_infantry"] += 8
    force["authorized_strength"] += 8
    planner.put(force_path, force)
    result = _perform_house_requested_military_intake(planner, at, "test:fresh-weaker")
    assert result["intake_count"] == 8
    force1 = planner.read(force_path)
    fresh = [row for cid, row in force1["cohort_ledger"]["cohorts"].items() if cid not in before_ids]
    assert fresh
    assert max(_mean_skill(row) for row in fresh) < _mean_skill(veteran)


def test_cavalry_replacement_requires_real_mounted_issue_capacity(campaign) -> None:
    planner = _planner(campaign)
    force = copy.deepcopy(planner.read("state/forces/house-tang.json"))
    force["authorized_by_role"]["house_cavalry"] += 5
    force["authorized_strength"] += 5
    planner.put("state/forces/house-tang.json", force)
    inv = copy.deepcopy(planner.read("state/inv/inventories.json"))
    facts = next(row["facts"] for row in inv["records"] if row["record_id"] == "house_tang_outfitting_sets")
    facts["mounted_harness_sets_reserve"] = 0
    planner.put("state/inv/inventories.json", inv)
    status = _house_tang_force_status(planner)
    assert status["vacancy_by_role"]["house_cavalry"] == 5
    assert status["role_intake_capacity"]["house_cavalry"] == 0
