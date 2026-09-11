from __future__ import annotations

import copy

from sword_runtime.causal_event_store import read_causal_event_owner, write_causal_event_owner
from sword_runtime.house_tang_development import MONTH_SECONDS, _is_expansion_request
from sword_runtime.household_request_flow import _house_tang_force_status, _perform_house_requested_military_intake
from sword_runtime.infrastructure_projects import infrastructure_work_spec
from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    meta = copy.deepcopy(planner.read("state/meta.json"))
    planner.PLAYER_ACTOR = str(meta["player_id"])
    planner._reset()
    return planner


def _fund_registered_expansion_materials(planner):
    rules = planner.read("game/data/mechanics/house-tang-development.json")["inner_walls_expansion"]
    required = 0
    for row in rules["capacity_projects"]:
        work = infrastructure_work_spec(
            planner.read,
            blueprint_ref=row["blueprint_ref"],
            target_site_ref=rules["target_site_ref"],
            quantity=row["quantity"],
        )
        required += int(work["construction_material_units"])
    ep, eco = planner._private_economy("qin")
    _ref, local = planner._local_economy_region("qin", eco, rules["economic_source_site_ref"])
    local.setdefault("commodity_stock", {})["construction_material_units"] = max(
        required, int(local.get("commodity_stock", {}).get("construction_material_units", 0))
    )
    planner._sync_local_economy_aggregate(eco)
    planner._write_private_economy(ep, eco)
    return required


def test_exact_inner_walls_expansion_intent_is_classified() -> None:
    attempt = {
        "actor_id": "char_tang_wei",
        "action": "request",
        "target_ref": "char_tang_ling",
        "player_statement": (
            "Mother, Father: expand Inner Walls infrastructure and replacement capacity so we can recruit "
            "replacement soldiers when real House Infantry or House Cavalry vacancies open. Keep training sustainable."
        ),
    }
    assert _is_expansion_request(attempt)
    assert not _is_expansion_request({**attempt, "player_statement": "Recruit replacement soldiers."})


def test_old_sword_host_is_migrated_to_unified_monthly_house_training(campaign) -> None:
    planner = _planner(campaign)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    runtime["hosts"]["host_sword_manor"] = {
        "host_id": "host_sword_manor",
        "kind": "sword_manor",
        "owner_ref": "force_sword_manor",
        "recurrence_seconds": MONTH_SECONDS,
        "next_due": str(CampaignTime.parse(str(runtime["world_time"])).add_seconds(MONTH_SECONDS)),
        "resolved_through": str(runtime["world_time"]),
        "safe_through": str(runtime["world_time"]),
    }
    planner._normalize_house_tang_training_host(runtime)
    assert "host_sword_manor" not in runtime["hosts"]
    host = runtime["hosts"]["host_house_tang_training"]
    assert host["kind"] == "house_tang_training"
    assert host["owner_ref"] == "force_house_tang"
    assert host["recurrence_seconds"] == MONTH_SECONDS
    assert any(row.get("target_host") == "host_house_tang_training" for row in runtime["events"])


def test_monthly_house_training_never_mints_replacement_bodies(campaign) -> None:
    planner = _planner(campaign)
    force0 = copy.deepcopy(planner.read("state/forces/house-tang.json"))
    pop0 = copy.deepcopy(planner.read("state/population/qin.json"))
    planner._autonomy_house_tang_training(
        {"owner_ref": "force_house_tang"}, 1, str(planner._world_time().add_seconds(MONTH_SECONDS))
    )
    force1 = planner.read("state/forces/house-tang.json")
    pop1 = planner.read("state/population/qin.json")
    assert int(force1["headcount"]) == int(force0["headcount"])
    assert force1["authorized_by_role"] == force0["authorized_by_role"]
    assert int(pop1["strata"]["private_household_military"]) == int(pop0["strata"]["private_household_military"])
    assert _house_tang_force_status(planner)["practical_intake_now"] == 0


def test_requested_house_replacement_intake_reclassifies_population_one_for_one(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    force = copy.deepcopy(planner.read("state/forces/house-tang.json"))
    qin0 = copy.deepcopy(planner.read("state/population/qin.json"))
    force["authorized_by_role"]["house_infantry"] += 12
    force["authorized_strength"] += 12
    planner.put("state/forces/house-tang.json", force)
    result = _perform_house_requested_military_intake(planner, at, "test:inner-walls-replacement")
    qin1 = planner.read("state/population/qin.json")
    assert result["intake_count"] == 12
    assert result["intake_by_role"] == {"house_infantry": 12}
    assert int(qin1["population_total"]) == int(qin0["population_total"])
    assert int(qin1["strata"]["private_household_military"]) == int(qin0["strata"]["private_household_military"]) + 12


def test_expansion_start_spends_once_and_reserves_current_physical_work(campaign) -> None:
    planner = _planner(campaign)
    _fund_registered_expansion_materials(planner)
    at = str(planner._world_time())
    request_ref = "interaction:test-inner-walls-expansion"
    house = copy.deepcopy(planner.read("state/houses/house_tang.json"))
    house.setdefault("development_requests", {})[request_ref] = {
        "request_ref": request_ref,
        "kind": "inner_walls_infrastructure_expansion",
        "status": "queued",
        "requested_at": at,
        "target_ref": "char_tang_ling",
        "player_statement": "Expand Inner Walls infrastructure for future lawful replacement intake and training.",
    }
    planner.put("state/houses/house_tang.json", house)
    before_force = copy.deepcopy(planner.read("state/forces/house-tang.json"))
    before_treasury = copy.deepcopy(planner.read("state/treasury/treasury-house-tang.json"))
    _ep, before_eco = planner._private_economy("qin")
    _ref, before_local = planner._local_economy_region("qin", before_eco, "loc_tang_manor")
    before_material = int(before_local["commodity_stock"]["construction_material_units"])
    before_cash = int(before_local["cash_silver"])

    planner._settle_expansion_request({"request_ref": request_ref}, at)

    treasury = planner.read("state/treasury/treasury-house-tang.json")
    settled_house = planner.read("state/houses/house_tang.json")
    project = settled_house["administrative_programs"]["inner_walls_expansion"]
    reserved = project["inputs_reserved"]
    assert project["status"] == "active"
    assert len(project["physical_work_specs"]) == 3
    assert len(project["land_reservations"]) == 3
    assert treasury["silver"] == before_treasury["silver"] - int(reserved["silver"])
    _ep, after_eco = planner._private_economy("qin")
    _ref, after_local = planner._local_economy_region("qin", after_eco, "loc_tang_manor")
    assert int(after_local["commodity_stock"]["construction_material_units"]) == before_material - int(reserved["construction_material_units"])
    assert int(after_local["cash_silver"]) == before_cash + int(reserved["silver"])
    assert project["project_ref"] in after_eco["labor_allocation"]["projects"]
    assert int(planner.read("state/forces/house-tang.json")["headcount"]) == int(before_force["headcount"])
    assert project["initial_intake_count"] == 0
    assert settled_house["development_requests"][request_ref]["status"] == "settled"


def test_expansion_completion_adds_registered_physical_works_only(campaign) -> None:
    planner = _planner(campaign)
    _fund_registered_expansion_materials(planner)
    at = str(planner._world_time())
    request_ref = "interaction:test-inner-walls-expansion-complete"
    house = copy.deepcopy(planner.read("state/houses/house_tang.json"))
    house.setdefault("development_requests", {})[request_ref] = {
        "request_ref": request_ref,
        "kind": "inner_walls_infrastructure_expansion",
        "status": "queued",
        "requested_at": at,
        "target_ref": "char_tang_ling",
        "player_statement": "Expand Inner Walls infrastructure for future lawful replacement intake and training.",
    }
    planner.put("state/houses/house_tang.json", house)
    before_force = copy.deepcopy(planner.read("state/forces/house-tang.json"))
    before_infrastructure = copy.deepcopy(planner.read("state/infrastructure/settlements.json"))
    before_land = copy.deepcopy(planner.read("state/development/land.json"))
    planner._settle_expansion_request({"request_ref": request_ref}, at)
    project = planner.read("state/houses/house_tang.json")["administrative_programs"]["inner_walls_expansion"]
    planner._settle_expansion_completion({"project_ref": project["project_ref"]}, project["completion_due_at"])
    infrastructure = planner.read("state/infrastructure/settlements.json")
    physical_before = before_infrastructure["sites"]["loc_tang_inner_walls"]
    physical = infrastructure["sites"]["loc_tang_inner_walls"]
    assert physical["military_support"]["permanent_bed_capacity_people"] == physical_before["military_support"]["permanent_bed_capacity_people"] + 2000
    assert physical["training_support"]["simultaneous_trainee_capacity"] == physical_before["training_support"]["simultaneous_trainee_capacity"] + 2000
    assert physical["institutional_support"]["medical_support_capacity_people"] == physical_before["institutional_support"]["medical_support_capacity_people"] + 2000
    completed = planner.read("state/houses/house_tang.json")["administrative_programs"]["inner_walls_expansion"]
    assert completed["status"] == "completed"
    assert len(completed["completed_work_refs"]) == 3
    assert "physical_work_specs" not in completed
    assert not planner._private_economy("qin")[1]["labor_allocation"]["projects"].get(project["project_ref"])
    land_after = planner.read("state/development/land.json")
    assert land_after["sites"]["loc_tang_inner_walls"]["enclosed_land_use_km2"]["open_developable"] < before_land["sites"]["loc_tang_inner_walls"]["enclosed_land_use_km2"]["open_developable"]
    assert int(planner.read("state/forces/house-tang.json")["headcount"]) == int(before_force["headcount"])


def test_material_world_arc_report_adds_bounded_evidence_detail(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner._world_time())
    source_ref = "event_test_material_world_arc"
    report_ref = source_ref + ".report"
    _path, owner = read_causal_event_owner(planner)
    owner["causal_events"][source_ref] = {
        "event_ref": source_ref,
        "kind": "world_arc_activity",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "arc_ref": "arc_ryo_fui_northern_wei_campaign",
        "actor_ref": "state_qin",
        "target_ref": "state_wei",
        "result": "material_action_settled",
        "summary": "material work settled",
        "provenance": {"kind": "world_arc_orchestration", "material_evidence": {
            "kind": "exact_operation_created", "operation_ref": "operation_test",
            "formation_ref": "formation_secret_ref", "formation_status_before": "formed", "formation_status_after": "formed",
        }},
    }
    owner["causal_events"][report_ref] = {
        "event_ref": report_ref, "kind": "world_arc_report", "status": "triggered", "due_at": at,
        "triggered_at": at, "arc_ref": "arc_ryo_fui_northern_wei_campaign", "source_event_ref": source_ref,
        "summary": "Reports reaching Tang Wei concern northern Wei. Material work settled.",
        "provenance": {"kind": "world_arc_information_propagation"},
    }
    write_causal_event_owner(planner, owner)
    planner._enrich_world_arc_report(source_ref)
    _path, after = read_causal_event_owner(planner)
    summary = after["causal_events"][report_ref]["summary"]
    assert "Qin has opened an actual military operation directed at Wei" in summary
    assert "assigned an existing formation" in summary
    assert "formation_secret_ref" not in summary
    assert "do not establish the formation's size, exact route, supply state, combat contact, or result" in summary
