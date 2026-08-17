from copy import deepcopy

from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime


def _activity_host(planner):
    runtime = planner.read("state/runtime.json")
    return deepcopy(runtime["hosts"]["host_named_person_activity"])


def test_external_named_npc_gets_role_derived_monthly_development(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    planner._ensure_activity_routes()
    runtime = planner.read("state/runtime.json")
    refs = set(runtime["hosts"]["host_named_person_activity"]["routed_person_refs"])
    assert "char_ouki" in refs

    before = deepcopy(planner.read("state/char/ouki.json"))
    activity = before["autonomous_activity_state"]
    due = activity["next_due"]
    planner._settle_activity_host(_activity_host(planner), due)
    after = planner.read("state/char/ouki.json")

    assert after["autonomous_activity_state"]["completed_cycles"] >= 1
    assert after.get("autonomous_development_history")
    assert after["autonomous_development_history"][-1]["planned_opportunity_hours_used"] is False
    # A derived contract is routing/runtime policy, not a fabricated saved NPC job.
    assert "activity_contract" not in after


def test_named_person_lite_command_staff_develops_without_force_double_owner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    planner._ensure_activity_routes()
    runtime = planner.read("state/runtime.json")
    refs = set(runtime["hosts"]["host_named_person_activity"]["routed_person_refs"])
    person_ref = "staff.chu.karin.chu_yan"
    assert person_ref in refs

    path = planner.owner_path(person_ref)
    before = deepcopy(planner.read(path))
    due = before["autonomous_activity_state"]["next_due"]
    planner._settle_activity_host(_activity_host(planner), due)
    after = planner.read(path)

    assert after["development_state"]["verified_training_hours"] > 0
    assert after["development_state"]["verified_role_exposure_hours"] > 0
    assert after["autonomous_activity_state"]["completed_cycles"] >= 1


def test_minor_polity_force_is_seeded_before_monthly_training(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    before = deepcopy(planner.read("state/forces/jo.json"))
    # Reproduce the stale pre-fix shape on a disposable test campaign.  The
    # checked-in current campaign is already repaired and should not need to
    # remain broken merely so this regression has something to assert first.
    for cohort in before["cohort_ledger"]["cohorts"].values():
        cohort["attribute_means"] = {}
        cohort["attribute_sd"] = {}
        cohort["skill_means"] = {}
        cohort["skill_sd"] = {}
        cohort["aptitude_means"] = {}
        cohort["tags"] = [x for x in cohort.get("tags", []) if x != "evidence_seeded_capability"]
    planner.put("state/forces/jo.json", before)

    planner._settle_minor_polity("polity_jo", 1, "244-BCE-08-22T01:22:48+08:00")
    after = planner.read("state/forces/jo.json")
    for cohort in after["cohort_ledger"]["cohorts"].values():
        assert cohort.get("attribute_means")
        assert cohort.get("skill_means")
        assert float(cohort.get("verified_training_hours_per_person", 0)) > 0

    scout = after["cohort_ledger"]["cohorts"]["cohort_jo_scout"]
    assert "Scouting" in scout["skill_means"]


def test_generic_force_training_advances_materialized_person_lites(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    force = deepcopy(planner.read("state/forces/house-tang.json"))
    person_ref = sorted(force["materialized_people"])[0]
    path = planner.owner_path(person_ref)
    assert not planner.read(path).get("development_state")

    planner._fc_train(force, "house_tang_max_sustainable", 1, "test:house_tang")
    after = planner.read(path)
    assert after["development_state"]["verified_training_hours"] == 240.0
    assert after["development_state"]["verified_role_exposure_hours"] == 137.143


def test_house_quarterly_review_does_not_double_train_dedicated_house_tang_force(campaign):
    planner = ProductionCampaignPlanner(campaign)
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


def test_qin_designated_person_lite_gets_target_regimen_not_two_full_regimens(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    runtime = planner.read("state/runtime.json")
    host = deepcopy(runtime["hosts"]["host_state_qin"])
    force = planner.read("state/forces/state-qin.json")
    person_ref = sorted(ref for ref in force["materialized_people"] if ref.startswith("officer.qin.wei_designated."))[0]
    path = planner.owner_path(person_ref)

    planner._autonomy_state(host, 1, host["next_due"])
    after = planner.read(path)
    assert after["development_state"]["verified_training_hours"] == 240.0
    assert after["development_state"]["verified_role_exposure_hours"] == 137.143


def test_current_explicit_named_activity_people_have_person_hosts(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    runtime = planner.read("state/runtime.json")
    hosted = {
        str(host.get("owner_ref"))
        for host in runtime["hosts"].values()
        if isinstance(host, dict) and host.get("kind") == "person"
    }
    owners = planner.read("state/index/owner-index.json")["owners"]
    missing = []
    for ref, path in owners.items():
        if not str(ref).startswith("char_"):
            continue
        person = planner.read(path)
        if person.get("schema") not in {"sab_character", "sword-materialized-person"}:
            continue
        if isinstance(person.get("activity_contract"), dict) and ref not in hosted:
            missing.append(ref)
    assert missing == []


def test_legacy_household_unknown_cohort_resolves_role_from_exact_force_evidence(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    force = deepcopy(planner.read("state/forces/house_ouki_household.json"))
    cohort = next(iter(force["cohort_ledger"]["cohorts"].values()))
    cohort["role"] = "unknown"
    cohort["attribute_means"] = {}
    cohort["skill_means"] = {}
    cohort["aptitude_means"] = {}
    cohort["tags"] = ["release_baseline", "quality_not_reconstructed"]

    planner._seed_force_baselines(force)

    assert cohort["role"] == "household_retainer"
    assert cohort["attribute_means"]
    assert cohort["skill_means"]
    assert "baseline_role_resolved" in cohort["tags"]
    assert "quality_not_reconstructed" not in cohort["tags"]


def test_current_active_force_cohorts_have_trainable_capability(campaign):
    planner = ProductionCampaignPlanner(campaign)
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


def test_named_house_command_staff_is_routed_for_future_development(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    planner._ensure_activity_routes()
    ref = "officer.house_tang.wei_guard.deputy"
    command_index = planner.read("state/cmd/command-personnel.json")
    assert ref in command_index["record_index"]
    runtime = planner.read("state/runtime.json")
    routed = {
        person_ref
        for host in runtime["hosts"].values()
        if isinstance(host, dict) and host.get("kind") == "person_activity"
        for person_ref in host.get("routed_person_refs", [])
    }
    assert ref in routed
    person = planner.read(planner.owner_path(ref))
    assert person["autonomous_activity_state"]["verified_hours_per_cycle"] > 0
