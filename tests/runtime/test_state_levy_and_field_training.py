from __future__ import annotations

import copy
import json

import pytest

from sword_runtime.state_levy import call_state_levy, demobilize_state_levy, levy_eligibility
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.training_facilities import training_environment


def planner_for(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    p = ProductionCampaignPlanner(campaign)
    p._reset()
    return p


def _sum_civilian_strata(pop):
    return sum(int(v) for k, v in pop["strata"].items() if k not in {"active_military", "private_household_military", "foreign_military_service", "rebel_military"})


def test_training_environment_uses_suitable_field_without_preparation(campaign):
    p = planner_for(campaign)
    field = training_environment(p, location_ref="loc_qin_regional_02", simultaneous_trainees=4000)
    permanent = training_environment(p, location_ref="loc_tang_inner_walls", simultaneous_trainees=4000)
    assert field["environment"] == "field"
    assert field["facility_grade"] == "field"
    assert field["capacity_factor"] == 1.0
    assert field["source"] == "suitable_field_ground"
    assert "temporary_area_ref" not in field
    assert permanent["environment"] == "home_garrison"
    assert permanent["facility_grade"] == "home_garrison"
    assert permanent["capacity_factor"] == 1.0



def test_major_settlements_use_one_home_garrison_context(campaign):
    p = planner_for(campaign)
    for ref in ("loc_kanyou", "loc_gyou", "loc_sanyou", "loc_bu_pass", "loc_tang_inner_walls"):
        env = training_environment(p, location_ref=ref, simultaneous_trainees=1000)
        assert env["environment"] == "home_garrison", ref
        assert env["facility_grade"] == "home_garrison", ref
        assert env["capacity_factor"] > 0, ref



def test_all_established_settlements_and_garrisons_use_home_training_context(campaign):
    p = planner_for(campaign)
    locations = p.read("game/data/world/locations.json").get("locations", [])
    home_kinds = {
        "capital", "city", "town", "fort", "fortress", "fortified_settlement",
        "pass", "military_compound", "military_district", "depot", "academy", "estate",
    }
    checked = 0
    for row in locations:
        if not isinstance(row, dict) or row.get("kind") not in home_kinds:
            continue
        env = training_environment(p, location_ref=str(row["ref"]), simultaneous_trainees=1000)
        assert env["environment"] == "home_garrison", row["ref"]
        assert env["facility_grade"] == "home_garrison", row["ref"]
        checked += 1
    assert checked >= 30


def test_training_rules_have_only_two_usable_facility_contexts(campaign):
    p = planner_for(campaign)
    facility = p.read("game/data/mechanics/training.json")["factor_tables"]["facility"]
    assert set(facility) == {"none", "field", "home_garrison"}
    assert facility["home_garrison"] > facility["field"] > facility["none"]

def test_field_training_needs_space_not_material_setup(campaign):
    p = planner_for(campaign)
    formation_ref = "formation_house_ouki_household_01"
    fpath = p.owner_path(formation_ref)
    formation = copy.deepcopy(p.read(fpath))
    assert formation["location_ref"] == "loc_qin_regional_02"
    before_materials = int(formation.get("logistics", {}).get("construction_material_units", 0))
    env = training_environment(
        p, location_ref=formation["location_ref"], simultaneous_trainees=int(formation["personnel"])
    )
    after = p.read(fpath)
    assert env["environment"] == "field"
    assert env["facility_grade"] == "field"
    assert env["capacity_factor"] > 0
    assert int(after.get("logistics", {}).get("construction_material_units", 0)) == before_materials

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
    assert formation["composition"] == {role: n}
    assert "levy" not in formation["composition"]
    assert formation["name"] == "QIN Mobilized Line Infantry"
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
    assert demob["mobilization_strain_after_demobilization_milli"] > 0
    immediate = levy_eligibility(p, state=state, location_ref=location, at=at)
    assert immediate["mobilization_strain_milli"] == demob["mobilization_strain_after_demobilization_milli"]
    assert immediate["effective_state_levy_cap_after_strain"] < immediate["state_active_levy_cap"]
    later = str(CampaignTime.parse(at).add_seconds(120 * 86400))
    recovered = levy_eligibility(p, state=state, location_ref=location, at=later)
    assert recovered["mobilization_strain_milli"] < immediate["mobilization_strain_milli"]
    assert recovered["effective_state_levy_cap_after_strain"] > immediate["effective_state_levy_cap_after_strain"]


def test_state_levy_rejects_levy_and_support_as_battlefield_roles(campaign):
    p = planner_for(campaign)
    at = str(p.read("state/meta.json")["time"])
    for role in ("levy", "command_personnel", "support", "engineer"):
        with pytest.raises(ValueError, match="manpower source"):
            call_state_levy(
                p, state="qin", personnel=500, location_ref="loc_kanyou",
                role=role, levy_ref=f"illegal_role_{role}", at=at,
            )


def test_state_levy_terminal_history_is_bounded_without_dropping_active_obligations():
    from sword_runtime.state_levy import LEVY_TERMINAL_HISTORY_LIMIT, _compact_levy_history

    history = {
        f"old_{i:03d}": {
            "status": "demobilized",
            "called_at": f"245-BCE-01-{(i % 28) + 1:02d}T00:00:00+08:00",
            "demobilized_at": f"244-BCE-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}T00:00:00+08:00",
        }
        for i in range(LEVY_TERMINAL_HISTORY_LIMIT + 17)
    }
    history["active_now"] = {"status": "active", "called_at": "244-BCE-09-01T00:00:00+08:00"}
    state_doc = {"levy_history": history}

    _compact_levy_history(state_doc)

    compacted = state_doc["levy_history"]
    assert compacted["active_now"]["status"] == "active"
    assert sum(1 for row in compacted.values() if row.get("status") != "active") == LEVY_TERMINAL_HISTORY_LIMIT
    assert len(compacted) == LEVY_TERMINAL_HISTORY_LIMIT + 1


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


def test_called_levy_is_a_real_independent_interstate_command_not_dead_unassigned_state(campaign):
    from sword_runtime.strategic_war_planning import build_interstate_strategic_plan

    p = planner_for(campaign)
    at = str(p.read("state/meta.json")["time"])
    result = call_state_levy(
        p, state="qin", personnel=5000, location_ref="loc_kanyou", role="line_infantry",
        levy_ref="test_qin_war_levy", at=at,
    )
    levy_formation = result["formation_ref"]
    config = p._interstate_theater_config(p.read("game/data/world/autonomous-theaters.json"))
    theater = next(row for row in config["theaters"] if row["theater_ref"] == "qin_zhao_gyou")
    plan = build_interstate_strategic_plan(
        p,
        theater_ref="test_qin_levy_war_admission",
        attacker="qin",
        defender="zhao",
        primary_target="loc_gyou",
        attacker_formation_refs=list(theater["formation_ref_lists"]["qin"]) + [levy_formation],
        defender_formation_refs=theater["formation_ref_lists"]["zhao"],
        at=at,
    )
    tracked = set(plan["formation_objectives"]["qin"]) | set(plan["strategic_reserve_formation_refs"]["qin"])
    assert levy_formation in tracked
    assert levy_formation not in set(plan["unassigned_formation_refs"]["qin"])
    rows = list(plan["command_assignments"]["qin"]) + list(plan["strategic_reserve_commands"]["qin"])
    command = next(row for row in rows if levy_formation in row.get("formation_refs", []))
    assert command["independent_formation_ref"] == levy_formation
    assert command["context"] == "standalone_mobilized_commitment"


def test_mobilization_strain_is_neutral_for_nonsovereign_economy_owner(campaign):
    from sword_runtime.state_levy import mobilization_strain_snapshot
    p = planner_for(campaign)
    at = str(p.read('state/meta.json')['time'])
    row = mobilization_strain_snapshot(p, state='northern_steppe', at=at)
    assert row['mobilization_strain_milli'] == 0
    assert row['civil_labor_factor_milli'] == 1000
    assert row['applicability'] == 'no_sovereign_state_levy_owner'
