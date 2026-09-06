from __future__ import annotations

import copy
from types import SimpleNamespace


def _planner(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    return planner


def _seed_project_local_economy(planner, *, material_units: int):
    eco_path = "state/economy/private/qin.json"
    eco = copy.deepcopy(planner.read(eco_path))
    institution = planner.read(planner.owner_path("inst_qin_fortification_bureau"))
    location_ref = str(institution.get("location_ref", ""))
    site_ref, local_eco = planner._local_economy_region("qin", eco, location_ref)
    assert site_ref
    local_eco.setdefault("commodity_stock", {})["construction_material_units"] = int(material_units)
    planner.put(eco_path, eco)
    return eco_path, location_ref, site_ref


def _local_economy(planner, eco_path: str, location_ref: str):
    eco = planner.read(eco_path)
    site_ref, local_eco = planner._local_economy_region("qin", eco, location_ref)
    return str(site_ref), local_eco


def _command(planner, *, digest: str, request_id: str, command_type: str):
    meta = planner.read("state/meta.json")
    return SimpleNamespace(
        command_type=command_type,
        digest=digest,
        semantic_digest=digest,
        request_id=request_id,
        actor_id="internal:sword-autonomy",
        expected_revision=int(meta["revision"]),
        submitted_at=str(meta["time"]),
    )


def test_project_cancellation_releases_regional_workers_and_refunds_unused_inputs(campaign):
    planner = _planner(campaign)
    eco_path, location_ref, source_site = _seed_project_local_economy(planner, material_units=10_000)
    _, local_before = _local_economy(planner, eco_path, location_ref)
    material_before = int(local_before["commodity_stock"]["construction_material_units"])
    state_before = int(planner.read("state/states/qin.json")["treasury_silver"])

    planner._start_funded_institution_project(
        _command(planner, digest="cancelregional1234", request_id="cancel-regional-start", command_type="institution_project"),
        {
            "institution_ref": "inst_qin_fortification_bureau",
            "project_ref": "project_cancel_regional_test",
            "duration_hours": 96,
            "kind": "construction",
            "magnitude": 10,
        },
    )
    site_after_start, local_after_start = _local_economy(planner, eco_path, location_ref)
    assert site_after_start == source_site
    assert "project_cancel_regional_test" in local_after_start["labor_allocation"]["projects"]
    assert int(planner.read("state/states/qin.json")["treasury_silver"]) < state_before

    result = planner._cancel_funded_project(
        _command(planner, digest="cancelregional5678", request_id="cancel-regional-do", command_type="project_cancel"),
        {"institution_ref": "inst_qin_fortification_bureau", "project_ref": "project_cancel_regional_test"},
    )
    assert result["status"] == "cancelled"
    assert result["refunds"]["construction_workers_released"] > 0
    assert result["refunds"]["silver_refunded"] > 0
    assert result["refunds"]["construction_material_units"] > 0

    site_after, local_after = _local_economy(planner, eco_path, location_ref)
    assert site_after == source_site
    assert "project_cancel_regional_test" not in local_after["labor_allocation"]["projects"]
    assert int(local_after["commodity_stock"]["construction_material_units"]) > material_before - 200
    project = next(
        row for row in planner.read(planner.owner_path("inst_qin_fortification_bureau"))["projects"]
        if row["project_ref"] == "project_cancel_regional_test"
    )
    assert project["status"] == "cancelled"
    assert 0 <= float(project["progress_at_cancellation"]) < 1


def test_project_workers_remain_reserved_in_exact_regional_economy_during_production(campaign):
    planner = _planner(campaign)
    eco_path, location_ref, source_site = _seed_project_local_economy(planner, material_units=1_000_000)
    meta = planner.read("state/meta.json")

    planner._start_funded_institution_project(
        _command(planner, digest="laborregional1234", request_id="labor-regional-start", command_type="institution_project"),
        {
            "institution_ref": "inst_qin_fortification_bureau",
            "project_ref": "project_labor_regional",
            "duration_hours": 24,
            "kind": "construction",
            "magnitude": 100,
        },
    )
    _, local_start = _local_economy(planner, eco_path, location_ref)
    allocation = local_start["labor_allocation"]["projects"]["project_labor_regional"]
    reserved = int(allocation["workers"])
    assert reserved > 0
    assert str(allocation["location_ref"]) == source_site
    before_output = copy.deepcopy(local_start.get("finished_goods", {}))

    planner._settle_private_production("qin", 1, str(meta["time"]))
    _, local_after = _local_economy(planner, eco_path, location_ref)
    assert int(local_after["labor_allocation"]["projects"]["project_labor_regional"]["workers"]) == reserved
    assert local_after["production_runtime"]["last_output"]
    assert local_after.get("finished_goods", {}) != before_output or reserved > 0
