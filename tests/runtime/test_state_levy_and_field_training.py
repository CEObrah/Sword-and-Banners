from __future__ import annotations

import copy
import json

import pytest

from sword_runtime.state_levy import call_state_levy, demobilize_state_levy, levy_eligibility
from sword_runtime.training_facilities import prepare_field_training_area, training_environment


def planner_for(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    p = ProductionCampaignPlanner(campaign)
    p._reset()
    return p


def _sum_civilian_strata(pop):
    return sum(int(v) for k, v in pop["strata"].items() if k not in {"active_military", "private_household_military", "foreign_military_service", "rebel_military"})


def test_training_environment_is_physical_not_regimen_identity(campaign):
    p = planner_for(campaign)
    bare = training_environment(p, location_ref="loc_qin_regional_02", simultaneous_trainees=4000)
    permanent = training_environment(p, location_ref="loc_sword_manor", simultaneous_trainees=4000)
    assert bare["environment"] == "bare_suitable_field"
    assert bare["facility_grade"] == "none"
    assert bare["capacity_factor"] == 1.0
    assert permanent["environment"] == "excellent_permanent"
    assert permanent["facility_grade"] == "excellent"
    assert permanent["capacity_factor"] == 1.0


def test_all_field_armies_can_prepare_real_temporary_training_ground(campaign):
    p = planner_for(campaign)
    formation_ref = "formation_house_ouki_household_01"
    fpath = p.owner_path(formation_ref)
    formation = copy.deepcopy(p.read(fpath))
    assert formation["location_ref"] == "loc_qin_regional_02"
    formation.setdefault("logistics", {})["construction_material_units"] = 500
    p.put(fpath, formation)
    at = str(p.read("state/meta.json")["time"])
    record = prepare_field_training_area(
        p,
        location_ref="loc_qin_regional_02",
        simultaneous_trainees=4000,
        formation_ref=formation_ref,
        available_workers=1000,
        at=at,
    )
    assert record["area_km2"] == pytest.approx(0.48)
    assert record["construction_material_units_consumed"] == 400
    assert record["labor_hours"] == 16000
    after = p.read(fpath)
    assert after["logistics"]["construction_material_units"] == 100
    env = training_environment(p, location_ref="loc_qin_regional_02", simultaneous_trainees=4000)
    assert env["environment"] == "prepared_field"
    assert env["facility_grade"] == "basic"
    assert env["capacity_factor"] == 1.0


def test_state_levy_call_and_demobilization_conserve_bodies_equipment_and_cash(campaign):
    p = planner_for(campaign)
    at = str(p.read("state/meta.json")["time"])
    state = "qin"
    location = "loc_kanyou"
    role = "line_infantry"
    n = 5000
    before_pop = copy.deepcopy(p.read("state/population/qin.json"))
    before_state = copy.deepcopy(p.read("state/states/qin.json"))
    before_force = copy.deepcopy(p.read("state/forces/state-qin.json"))
    before_total = int(before_pop["population_total"])
    before_active = int(before_pop["strata"]["active_military"])
    before_eq = int(before_force["available_equipment_units_by_role"].get(role, 0))
    before_local_eq = int(before_force["available_equipment_by_location"][location].get(role, 0))
    elig = levy_eligibility(p, state=state, location_ref=location)
    assert elig["currently_callable_personnel"] >= n

    result = call_state_levy(
        p, state=state, personnel=n, location_ref=location, role=role,
        levy_ref="test_qin_levy", at=at,
    )
    pop = p.read("state/population/qin.json")
    force = p.read(p.owner_path(result["force_ref"]))
    formation = p.read(p.owner_path(result["formation_ref"]))
    state_doc = p.read("state/states/qin.json")
    state_force = p.read("state/forces/state-qin.json")
    assert int(pop["population_total"]) == before_total
    assert int(pop["strata"]["active_military"]) == before_active + n
    assert int(force["headcount"]) == n
    assert int(formation["personnel"]) == n
    assert force["service_class"] == "state_levy"
    assert formation["training_regimen_ref"] == "levy_basic"
    assert 0 <= result["equipment_issued"] <= n
    assert int(state_force["available_equipment_units_by_role"].get(role, 0)) == before_eq - result["equipment_issued"]
    assert int(state_force["available_equipment_by_location"][location].get(role, 0)) == before_local_eq - result["equipment_issued"]
    assert int(state_doc["treasury_silver"]) == int(before_state["treasury_silver"]) - n * 2
    cohorts = force["cohort_ledger"]["cohorts"]
    assert cohorts
    assert {c["origin"]["source_stratum"] for c in cohorts.values()} <= {"agricultural", "household_and_service", "merchant_and_transport", "craft_and_industry"}
    assert all(c["origin"].get("selection_profile") in (None, "") for c in cohorts.values())

    demob = demobilize_state_levy(p, state=state, levy_ref="test_qin_levy", at=at)
    final_pop = p.read("state/population/qin.json")
    final_state_force = p.read("state/forces/state-qin.json")
    final_state = p.read("state/states/qin.json")
    assert demob["survivors_returned"] == n
    assert demob["casualties_or_missing"] == 0
    assert int(final_pop["population_total"]) == before_total
    assert int(final_pop["strata"]["active_military"]) == before_active
    assert int(final_state_force["available_equipment_units_by_role"].get(role, 0)) == before_eq
    assert int(final_state_force["available_equipment_by_location"][location].get(role, 0)) == before_local_eq
    assert result["force_ref"] not in final_state.get("active_levy_refs", [])


def test_player_or_house_cannot_invoke_sovereign_levy_authority(campaign):
    from sword_runtime.commands import CommandEnvelope
    from sword_runtime.engine import RepositoryCommandPlanner
    meta = json.loads((campaign / "state/meta.json").read_text())
    planner = RepositoryCommandPlanner(campaign)
    command = CommandEnvelope(
        meta["campaign_id"], "unauthorized-levy", "char_tang_wei", "state_levy_call",
        meta["revision"], meta["time"],
        {"state": "qin", "levy_ref": "illegal_house_levy", "personnel": 500, "location_ref": "loc_kanyou", "role": "line_infantry"},
    )
    with pytest.raises((ValueError, PermissionError)):
        planner.preview(command)
