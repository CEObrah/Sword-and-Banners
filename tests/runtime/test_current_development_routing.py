from __future__ import annotations

from copy import deepcopy

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
    assert after.get("autonomous_development_history")
    assert after["autonomous_development_history"][-1]["planned_opportunity_hours_used"] is False


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
    force = deepcopy(planner.read("state/forces/house-tang.json"))
    person_ref = sorted(force["materialized_people"])[0]
    path = planner.owner_path(person_ref)
    before = deepcopy(planner.read(path)).get("development_state", {})

    planner._fc_train(force, "house_tang_max_sustainable", 1, "test:house_tang")
    after = planner.read(path)["development_state"]
    assert round(float(after["verified_training_hours"]) - float(before.get("verified_training_hours", 0)), 3) == 240.0
    assert round(float(after["verified_role_exposure_hours"]) - float(before.get("verified_role_exposure_hours", 0)), 3) == 137.143


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
    person_ref = sorted(
        ref for ref in force["materialized_people"]
        if ref.startswith("officer.qin.wei_designated.")
    )[0]
    path = planner.owner_path(person_ref)

    planner._autonomy_state(host, 1, host["next_due"])
    after = planner.read(path)
    assert after["development_state"]["verified_training_hours"] == 240.0
    assert after["development_state"]["verified_role_exposure_hours"] == 137.143


def test_full_formal_deputies_resolve_and_route_as_exact_characters(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    planner._ensure_activity_routes()
    routed = _routed_people(planner)
    refs = [
        "char_lin_zhen",
        "char_qin_wei_unit_01_deputy",
        "char_qin_wei_unit_02_deputy",
        "char_qin_wei_unit_03_deputy",
        "char_qin_wei_unit_04_deputy",
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
