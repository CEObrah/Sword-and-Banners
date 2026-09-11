from __future__ import annotations

from copy import deepcopy

import pytest

from sword_runtime.service_runtime import CommandRoutedProductionPlanner


def _activity_host(planner):
    runtime = planner.read("state/runtime.json")
    hosts = [
        deepcopy(host)
        for host in runtime["hosts"].values()
        if isinstance(host, dict) and host.get("kind") == "person_activity"
    ]
    assert hosts
    return hosts[0]


def _routed_people(planner) -> set[str]:
    runtime = planner.read("state/runtime.json")
    return {
        str(person_ref)
        for host in runtime["hosts"].values()
        if isinstance(host, dict) and host.get("kind") == "person_activity"
        for person_ref in host.get("routed_person_refs", [])
    }


def test_external_named_npc_gets_role_derived_monthly_development(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    planner._ensure_activity_routes()
    assert "char_ouki" in _routed_people(planner)

    before = deepcopy(planner.read("state/char/ouki.json"))
    due = before["autonomous_activity_state"]["next_due"]
    planner._settle_activity_host(_activity_host(planner), due)
    after = planner.read("state/char/ouki.json")

    assert after["autonomous_activity_state"]["completed_cycles"] >= 1
    assert after["autonomous_activity_state"]["last_training"]["hours"] > 0
    assert "autonomous_development_history" not in after


def test_person_lite_command_staff_develops_without_force_double_owner(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    planner._ensure_activity_routes()
    person_ref = "staff.chu.karin.chu_yan"
    assert person_ref in _routed_people(planner)

    path = planner.owner_path(person_ref)
    before = deepcopy(planner.read(path))
    due = before["autonomous_activity_state"]["next_due"]
    planner._settle_activity_host(_activity_host(planner), due)
    after = planner.read(path)

    assert after["development_state"]["verified_training_hours"] > 0
    assert after["development_state"]["verified_role_exposure_hours"] > 0
    assert after["autonomous_activity_state"]["completed_cycles"] >= 1


def test_generic_force_training_advances_embedded_person_lites(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    force = deepcopy(planner.read("state/forces/state-qin.json"))
    person_ref = "officer.qin.kankoku.army.chief_of_staff"
    assert person_ref in force["materialized_people"]
    path = planner.owner_path(person_ref)
    before = deepcopy(planner.read(path)).get("development_state", {})

    planner._fc_train(force, "regular_army", 1, "test:qin")
    after = planner.read(path)["development_state"]
    assert float(after["verified_training_hours"]) > float(before.get("verified_training_hours", 0.0))
    assert float(after["verified_role_exposure_hours"]) > float(before.get("verified_role_exposure_hours", 0.0))

def test_house_review_does_not_double_train_dedicated_house_tang_force(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    runtime = planner.read("state/runtime.json")
    host = deepcopy(runtime["hosts"]["host_house_tang"])
    force = planner.read("state/forces/house-tang.json")
    person_ref = sorted(force["materialized_people"])[0]
    path = planner.owner_path(person_ref)
    before = deepcopy(planner.read(path)).get("development_state")

    planner._autonomy_house(host, 1, host["next_due"])
    after = planner.read(path).get("development_state")
    assert after == before


def test_qin_embedded_person_lite_gets_one_target_regimen(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    runtime = planner.read("state/runtime.json")
    host = deepcopy(runtime["hosts"]["host_state_qin"])
    force = planner.read("state/forces/state-qin.json")
    person_ref = "officer.qin.kankoku.army.chief_of_staff"
    assert person_ref in force["materialized_people"]
    path = planner.owner_path(person_ref)
    before = deepcopy(planner.read(path))["development_state"]

    planner._autonomy_state(host, 1, host["next_due"])
    after = planner.read(path)["development_state"]
    assert float(after["verified_training_hours"]) - float(before.get("verified_training_hours", 0.0)) == pytest.approx(205.714, abs=1e-3)
    assert float(after["verified_role_exposure_hours"]) - float(before.get("verified_role_exposure_hours", 0.0)) == pytest.approx(96.0, abs=1e-3)

def test_full_formal_deputies_resolve_and_route_as_exact_characters(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    planner._ensure_activity_routes()
    routed = _routed_people(planner)
    refs = [
        "char_lin_zhen",
        "char_han_shou",
        "char_pei_rong",
        "char_deng_kai",
        "char_lu_cheng",
    ]
    for ref in refs:
        person = planner.read(planner.owner_path(ref))
        assert person["schema"] == "sab_character"
        assert person["military_command"]["external_to_fighting_strength"] is True
        assert person["attributes"]
        assert person["skills"]
        assert ref in routed


def test_current_active_force_cohorts_have_trainable_capability(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    owners = planner.read("state/index/owner-index.json")["owners"]
    stale = []
    for owner_ref, path in owners.items():
        if not str(owner_ref).startswith("force_"):
            continue
        force = planner.read(path)
        if force.get("schema") != "sword-force":
            continue
        ledger = force.get("cohort_ledger", {})
        for cohort_id, cohort in ledger.get("cohorts", {}).items():
            active = (
                sum(int(v) for v in cohort.get("reserve_by_location", {}).values())
                + sum(int(v) for v in cohort.get("allocated_by_formation", {}).values())
                + sum(int(v) for v in cohort.get("allocated_external_by_formation", {}).values())
            )
            if active > 0 and (not cohort.get("attribute_means") or not cohort.get("skill_means")):
                stale.append((owner_ref, cohort_id, cohort.get("role")))
    assert stale == []


def test_all_active_exact_command_people_get_life_hosts_and_training_routes(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    planner._ensure_activity_routes()
    runtime = planner.read("state/runtime.json")
    life_owned = {
        str(host.get("owner_ref"))
        for host in runtime["hosts"].values()
        if isinstance(host, dict) and host.get("kind") == "person"
    }
    routed = _routed_people(planner)
    records = planner.read("state/cmd/command-personnel.json")["record_index"]
    missing_life = []
    missing_activity = []
    for ref, path in sorted(records.items()):
        if ref == planner.PLAYER_ACTOR or not str(path).startswith("state/char/"):
            continue
        person = planner.read(path)
        if person.get("schema") != "sab_character":
            continue
        if str(person.get("life_status", person.get("status", "active"))).lower() in {"dead", "deceased"}:
            continue
        if ref not in life_owned:
            missing_life.append(ref)
        contract = planner._command_activity_contract(person)
        if contract and contract.get("autonomous_enabled") is not False and planner._activity_focuses(person, contract):
            profiles = planner.read("game/data/mil/recruitment-cohort-profiles.json")
            cadence = int(person.get("autonomous_activity_state", {}).get("cadence_seconds", 30 * 86400))
            from sword_runtime.training_rates import verified_activity_hours_per_cycle
            if verified_activity_hours_per_cycle(person, contract, profiles, cadence) > 0 and ref not in routed:
                missing_activity.append(ref)
    assert missing_life == []
    assert missing_activity == []


def test_existing_exact_command_route_reconciles_stale_cached_rate(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    path = planner.owner_path("char_han_qiu")
    person = deepcopy(planner.read(path))
    person.setdefault("autonomous_activity_state", {})["verified_hours_per_cycle"] = 56.0
    planner.put(path, person)

    planner._ensure_activity_routes()
    after = planner.read(path)
    assert after["autonomous_activity_state"]["verified_hours_per_cycle"] == pytest.approx(205.714, abs=1e-3)
    assert after["autonomous_activity_state"]["verified_hours_per_cycle"] == pytest.approx(205.714, abs=1e-3)


def test_partial_house_tang_command_contract_is_completed_without_losing_program(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    ref = "char_pei_an"
    path = planner.owner_path(ref)
    before = deepcopy(planner.read(path))
    assert before["activity_contract"]["training_program_ref"] == "program.commander_combined_arms"
    # Recreate the partial-contract migration shape that caused the stale fallback.
    before["activity_contract"] = {
        "training_program_ref": "program.commander_combined_arms",
        "smart_rotation": "registered_program_adaptive_rotation",
    }
    before.pop("autonomous_activity_state", None)
    planner.put(path, before)

    planner._ensure_activity_routes()
    after = planner.read(path)
    contract = after["activity_contract"]
    assert contract["training_program_ref"] == "program.commander_combined_arms"
    assert contract["mode"] == "standing_role_training"
    assert contract["autonomous_enabled"] is True
    assert contract["training_regimen_ref"] == "house_tang_max_sustainable"
    assert after["autonomous_activity_state"]["verified_hours_per_cycle"] == pytest.approx(205.714, abs=1e-3)
    assert ref in _routed_people(planner)


def test_house_tang_current_setting_baseline_and_monthly_training_owner(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    runtime = planner.read("state/runtime.json")
    host = deepcopy(runtime["hosts"]["host_house_tang_training"])
    force_path = "state/forces/house-tang.json"
    before_force = deepcopy(planner.read(force_path))
    cohort_ref = "cohort_force_house_tang_house_guard_standing"
    before = before_force["cohort_ledger"]["cohorts"][cohort_ref]
    before_training_hours = float(before.get("verified_training_hours_per_person", 0.0))
    before_exposure_hours = float(before.get("verified_role_exposure_hours_per_person", 0.0))

    planner._autonomy_house_tang_training(host, 1, host["next_due"])
    after_force = planner.read(force_path)
    after = after_force["cohort_ledger"]["cohorts"][cohort_ref]
    assert float(after["verified_training_hours_per_person"]) > before_training_hours
    assert float(after["verified_role_exposure_hours_per_person"]) > before_exposure_hours
    assert after.get("last_training")
    assert "training_history" not in after

def test_nested_manor_training_locations_inherit_only_containing_site_capacity(campaign):
    from sword_runtime.training_facilities import training_environment

    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    for location_ref in ("loc_tang_manor_defense_camp", "loc_tang_manor_garrison_yard"):
        env = training_environment(planner, location_ref=location_ref, simultaneous_trainees=1000)
        assert env["source"] == "permanent_home_garrison_infrastructure"
        assert env["source_site_ref"] == "loc_tang_inner_walls"
        assert env["simultaneous_capacity"] == 500000
        assert env["capacity_factor"] == 1.0
