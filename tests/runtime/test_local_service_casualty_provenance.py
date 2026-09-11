from __future__ import annotations

from collections.abc import Mapping
import copy

import pytest

from sword_runtime.production_runtime_planner import ProductionCampaignPlanner


def _native_local_total(population: Mapping[str, object]) -> int:
    local = population.get("local_population", {})
    sites = local.get("sites", {}) if isinstance(local, Mapping) else {}
    return sum(
        max(0, int(row.get("serving_native_military", 0)))
        for row in sites.values()
        if isinstance(row, Mapping)
    ) if isinstance(sites, Mapping) else 0


def _local_deaths(population: Mapping[str, object]) -> int:
    local = population.get("local_population", {})
    sites = local.get("sites", {}) if isinstance(local, Mapping) else {}
    return sum(
        max(0, int(row.get("deaths_cumulative", 0)))
        for row in sites.values()
        if isinstance(row, Mapping)
    ) if isinstance(sites, Mapping) else 0


def test_legacy_baseline_cohort_casualty_debits_local_partition_without_second_global_debit(campaign) -> None:
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    force_ref = "force_state_han"
    force = planner.read(planner.owner_path(force_ref))
    cohorts = force.get("cohort_ledger", {}).get("cohorts", {})
    legacy_cohort_ref = next(
        ref
        for ref, cohort in cohorts.items()
        if isinstance(cohort, Mapping)
        and isinstance(cohort.get("origin"), Mapping)
        and not cohort["origin"].get("population_ref")
        and not cohort["origin"].get("source_location_ref")
        and sum(max(0, int(v)) for v in cohort.get("allocated_by_formation", {}).values()) > 0
    )

    population_path = "state/population/han.json"
    before = planner.read(population_path)
    before_total = int(before["population_total"])
    before_active = int(before["strata"]["active_military"])
    before_local = _native_local_total(before)
    before_deaths = _local_deaths(before)

    result = planner._reconcile_local_state_service_casualties(
        force_ref,
        {legacy_cohort_ref: 17},
        at=str(planner.read("state/runtime.json")["world_time"]),
        evidence_ref="test_legacy_baseline_local_casualty_reconciliation",
    )

    after = planner.read(population_path)
    assert int(after["population_total"]) == before_total
    assert int(after["strata"]["active_military"]) == before_active
    assert _native_local_total(after) == before_local - 17
    assert _local_deaths(after) == before_deaths + 17
    assert sum(sum(by_location.values()) for by_location in result.values()) == 17


def test_missing_local_origin_fails_closed_for_nonlegacy_state_cohort(campaign) -> None:
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    force_ref = "force_state_han"
    force_path = planner.owner_path(force_ref)
    force = copy.deepcopy(planner.read(force_path))
    cohorts = force.get("cohort_ledger", {}).get("cohorts", {})
    cohort_ref = next(
        ref
        for ref, cohort in cohorts.items()
        if isinstance(cohort, Mapping)
        and isinstance(cohort.get("origin"), Mapping)
        and cohort["origin"].get("source_location_ref")
        and str(cohort["origin"].get("kind", "")) != "baseline_formation_allocation"
    )
    force["cohort_ledger"]["cohorts"][cohort_ref]["origin"]["source_location_ref"] = None
    force["cohort_ledger"]["cohorts"][cohort_ref]["origin"]["population_ref"] = None
    planner.put(force_path, force)

    with pytest.raises(ValueError, match="not a legacy baseline cohort"):
        planner._reconcile_local_state_service_casualties(
            force_ref,
            {cohort_ref: 1},
            at=str(planner.read("state/runtime.json")["world_time"]),
            evidence_ref="test_nonlegacy_missing_local_origin_fails_closed",
        )
