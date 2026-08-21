from __future__ import annotations

import copy

import pytest

from sword_runtime.recruitment_campaigns import cancel_campaign, finalize_campaign, start_campaign
from sword_runtime.sim.calendar import CampaignTime


def planner_for(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    return ProductionCampaignPlanner(campaign)


def test_private_and_candidate_recruitment_share_exact_local_population(campaign):
    planner = planner_for(campaign); planner._reset()
    pop_path = "state/population/qin.json"
    _pp, pop = planner._ensure_local_population_ledger("qin", copy.deepcopy(planner.read(pop_path)))
    _lp, _pop, site_ref = planner._local_population_site_for_location("qin", "loc_tang_manor_garrison_yard", pop, controller_ref="state_qin")
    row = pop["local_population"]["sites"][site_ref]
    before = int(row["civilian_strata"]["household_and_service"])
    moved = planner._consume_local_private_recruitment(
        pop, "qin", "loc_tang_manor_garrison_yard", 11,
        source_stratum="household_and_service", force_ref="force_house_tang", controller_ref="state_qin",
    )
    assert sum(x["personnel"] for x in moved) == 11
    row = pop["local_population"]["sites"][site_ref]
    assert int(row["civilian_strata"]["household_and_service"]) == before - 11
    assert int(row["service_allocations"]["force_house_tang"]["personnel"]) >= 11

    # Candidate campaigns reserve the same physical locality rather than a second pool.
    planner.put(pop_path, pop)
    result = start_campaign(planner, {
        "state": "qin", "campaign_ref": "campaign_v6_locality", "applicant_count": 8,
        "destination_force_ref": "force_tang_wei_personal", "role": "household_retainer",
        "location_ref": "loc_tang_manor_garrison_yard",
    }, evidence_ref="v6_locality_test")
    assert result["applicants"] == 8
    reserved_pop = planner.read(pop_path)
    reservations = sum(
        sum(int(v) for v in rec.get("source_strata", {}).values())
        for site in reserved_pop["local_population"]["sites"].values()
        for key, rec in site.get("candidate_reservations", {}).items()
        if key == "campaign_v6_locality"
    )
    assert reservations == 8
    finalized = finalize_campaign(planner, {"campaign_ref": "campaign_v6_locality"}, evidence_ref="v6_locality_accept")
    assert finalized["accepted"] == 8
    after = planner.read(pop_path)
    assert not any("campaign_v6_locality" in site.get("candidate_reservations", {}) for site in after["local_population"]["sites"].values())
    assert sum(
        int(site.get("service_allocations", {}).get("force_tang_wei_personal", {}).get("personnel", 0))
        for site in after["local_population"]["sites"].values()
    ) >= 8


def test_cancelled_candidate_campaign_returns_exact_local_reservations(campaign):
    planner = planner_for(campaign); planner._reset()
    pop_path = "state/population/qin.json"
    _pp, pop0 = planner._ensure_local_population_ledger("qin", copy.deepcopy(planner.read(pop_path))); planner.put(pop_path, pop0)
    before = sum(int(site.get("civilian_population", 0)) for site in pop0["local_population"]["sites"].values())
    start_campaign(planner, {
        "state": "qin", "campaign_ref": "campaign_v6_cancel", "applicant_count": 7,
        "destination_force_ref": "force_tang_wei_personal", "role": "household_retainer",
        "location_ref": "loc_tang_manor_garrison_yard",
    }, evidence_ref="v6_cancel_start")
    cancel_campaign(planner, {"campaign_ref": "campaign_v6_cancel"}, evidence_ref="v6_cancel")
    after = planner.read(pop_path)
    assert not any("campaign_v6_cancel" in site.get("candidate_reservations", {}) for site in after["local_population"]["sites"].values())
    assert sum(int(site.get("civilian_population", 0)) for site in after["local_population"]["sites"].values()) == before


def test_demographic_maturation_and_site_local_production_share_one_authority(campaign):
    planner = planner_for(campaign); planner._reset()
    host = copy.deepcopy(planner.read("state/runtime.json")["hosts"]["host_population_qin"])
    at = str(host["next_due"])
    planner._autonomy_population(host, 1, at)
    pop = planner.read("state/population/qin.json")
    age = pop["demography"]["age_cohorts"]
    assert sum(int(v) for v in age.values()) == int(pop["population_total"])
    assert pop["local_population"]["last_maturation"]["matured_to_working"] > 0
    assert sum(int(site["civilian_population"]) + int(site["service_population"]) + int(site.get("reserved_candidates", 0)) for site in pop["local_population"]["sites"].values()) == int(pop["population_total"])

    ep, eco_before = planner._private_economy("qin")
    regions_before = copy.deepcopy(eco_before["local_regions"]["regions"])
    planner._settle_private_production("qin", 1, at)
    eco = planner.read(ep)
    assert eco["local_regions"]["regions"]
    assert all(int(row["production_runtime"]["completed_monthly_closes"]) >= 1 for row in eco["local_regions"]["regions"].values())
    assert any(eco["local_regions"]["regions"][ref]["production_runtime"].get("last_labor_basis") for ref in regions_before)
    assert int(eco["cash_silver"]) == sum(int(row["cash_silver"]) for row in eco["local_regions"]["regions"].values())


def test_occupation_policy_governor_and_mobilization_are_consumed(campaign):
    planner = planner_for(campaign); planner._reset()
    harsh = {"occupation_policy": {"security_posture": {"value": "severe martial rule"}, "tax_posture": {"value": "heavy extraction"}, "recruitment_policy": {"value": "forced conscription"}}}
    conciliatory = {"occupation_policy": {"security_posture": {"value": "conciliatory restrained security"}, "tax_posture": {"value": "light relief taxation"}, "recruitment_policy": {"value": "voluntary recruitment"}, "relief_policy": {"value": "generous relief"}}}
    h = planner._occupation_policy_effects(harsh); c = planner._occupation_policy_effects(conciliatory)
    assert h["resistance_delta"] > c["resistance_delta"]
    assert h["recruitment_access_delta"] > c["recruitment_access_delta"]
    assert c["food_security_delta"] > h["food_security_delta"]

    polity = {"governors": {"loc_gyou": {"person_ref": "char_shou_bun_kun"}}}
    governor = planner._governor_effects(polity, "loc_gyou")
    assert governor["governor_ref"] == "char_shou_bun_kun"
    assert governor["administration_multiplier"] != 1.0 or governor["elite_delta"] != 0

    demobilized = planner._polity_mobilization_effects({"mobilization_policy": {"value": "demobilized"}})
    total_war = planner._polity_mobilization_effects({"mobilization_policy": {"value": "total_war"}})
    assert total_war["readiness_target"] > demobilized["readiness_target"]
    assert total_war["operation_capacity"] > demobilized["operation_capacity"]
    assert total_war["recruitment_factor"] > demobilized["recruitment_factor"]


def test_npc_war_intent_requires_material_interest_and_can_be_generated(campaign):
    planner = planner_for(campaign); planner._reset(); at = str(planner.read("state/runtime.json")["world_time"])
    path = "state/states/qin.json"; qin = copy.deepcopy(planner.read(path))
    qin["treasury_silver"] = max(100000, int(qin.get("treasury_silver", 0))); qin["mobilization_readiness"] = 85
    qin.setdefault("known_threats", {})["v6_zhao_threat"] = {"severity": 90, "source_ref": "state_zhao", "location_ref": "loc_gyou", "observed_at": at}
    qin.setdefault("strategic_goals", []).append("contest loc_gyou against Zhao")
    qin.setdefault("diplomacy", {})["state_zhao"] = {"status": "hostile", "tension": 80}
    planner.put(path, qin)
    intent = planner._generate_npc_war_intent("state_qin", at)
    assert intent is not None
    assert intent["status"] == "authorized" and intent["target_ref"] == "state_zhao"
    assert intent["authorization_basis"]["threat_score"] >= 45 or intent["authorization_basis"]["goal_interest"] > 0


def test_asymmetric_treaties_require_direction_and_diplomatic_people_require_authority(campaign):
    planner = planner_for(campaign); planner._reset(); at = str(planner.read("state/runtime.json")["world_time"])
    with pytest.raises(ValueError, match="explicit asymmetric"):
        planner._activate_diplomatic_treaty({"proposal_ref": "bad_tribute", "proposer_ref": "state_qin", "target_ref": "state_zhao", "kind": "tribute", "direction": "mutual", "terms": {"amount_silver": 5}}, at)
    with pytest.raises(PermissionError, match="hostage giver"):
        planner._activate_diplomatic_treaty({"proposal_ref": "bad_hostage", "proposer_ref": "state_zhao", "target_ref": "state_qin", "kind": "hostage_exchange", "direction": "proposer_to_target", "terms": {"hostage_person_ref": "char_hyou"}}, at)

    hostage_ref = planner._activate_diplomatic_treaty({"proposal_ref": "good_hostage", "proposer_ref": "state_qin", "target_ref": "state_zhao", "kind": "hostage_exchange", "direction": "proposer_to_target", "terms": {"hostage_person_ref": "char_hyou"}}, at)
    hyou = planner.read(planner.owner_path("char_hyou"))
    assert hyou["career_state"]["hostage_status"]["treaty_ref"] == hostage_ref

    marriage_ref = planner._activate_diplomatic_treaty({"proposal_ref": "marriage_test", "proposer_ref": "state_qin", "target_ref": "state_zhao", "kind": "marriage_alliance", "direction": "mutual", "terms": {"marriage_person_ref": "char_hyou", "marriage_partner_ref": "char_bananji"}}, at)
    treaty = planner.read("state/politics/treaties.json")["records"][marriage_ref]
    family = planner.read(planner.owner_path(treaty["terms"]["family_proposal_ref"]))
    assert family["status"] == "pending"
    assert treaty["terms"]["marriage_status"] == "pending_personal_consent"


def test_reparations_and_negotiated_land_exchange_are_material(campaign):
    planner = planner_for(campaign); planner._reset(); at = str(planner.read("state/runtime.json")["world_time"])
    qin_before = int(planner.read("state/states/qin.json")["treasury_silver"]); zhao_before = int(planner.read("state/states/zhao.json")["treasury_silver"])
    rep_ref = planner._activate_diplomatic_treaty({"proposal_ref": "rep_test", "proposer_ref": "state_qin", "target_ref": "state_zhao", "kind": "reparations", "direction": "proposer_to_target", "terms": {"amount_silver": 120, "duration_days": 360}}, at)
    planner._settle_treaty_obligations("state_qin", at, 1)
    assert int(planner.read("state/states/qin.json")["treasury_silver"]) < qin_before
    assert int(planner.read("state/states/zhao.json")["treasury_silver"]) > zhao_before
    assert planner.read("state/politics/treaties.json")["records"][rep_ref]["terms"]["reparations_remaining_silver"] < 120

    territory = planner.read("state/territory/control.json")
    qin_site = next(ref for ref, site in territory["sites"].items() if site.get("controller") == "state_qin")
    zhao_site = next(ref for ref, site in territory["sites"].items() if site.get("controller") == "state_zhao")
    ex_ref = planner._activate_diplomatic_treaty({"proposal_ref": "land_swap", "proposer_ref": "state_qin", "target_ref": "state_zhao", "kind": "territorial_exchange", "direction": "mutual", "terms": {"offer_location_refs": [qin_site], "request_location_refs": [zhao_site]}}, at)
    after = planner.read("state/territory/control.json")
    assert after["sites"][qin_site]["controller"] == "state_zhao"
    assert after["sites"][zhao_site]["controller"] == "state_qin"
    assert qin_site not in planner.read("state/states/qin.json")["territorial_control"]
    assert zhao_site in planner.read("state/states/qin.json")["territorial_control"]
    assert planner.read("state/politics/treaties.json")["records"][ex_ref]["terms"]["territorial_changes"]


def test_npc_sovereign_can_originate_multilateral_coalition_from_shared_threat(campaign):
    planner = planner_for(campaign); planner._reset(); at = str(planner.read("state/runtime.json")["world_time"])
    for ref, other in (("state_qin", "state_zhao"), ("state_zhao", "state_qin")):
        path, doc = planner._sovereign_owner(ref)
        doc.setdefault("known_threats", {})["shared_chu_threat"] = {"severity": 80, "source_ref": "state_chu", "location_ref": "loc_kankoku_pass", "observed_at": at}
        doc.setdefault("diplomacy", {})[other] = {"status": "allied", "tension": 10}
        planner.put(path, doc)
    proposal = planner._generate_npc_diplomatic_initiative("state_qin", at)
    assert proposal is not None
    assert proposal["kind"] == "coalition"
    assert proposal["terms"]["coalition_target_ref"] == "state_chu"


def test_state_ministries_act_with_exact_money_and_local_resources(campaign):
    planner = planner_for(campaign); planner._reset(); at = str(planner.read("state/runtime.json")["world_time"])
    fp, formation = planner._load_formation("formation_qin_wei_unit_01"); formation = copy.deepcopy(formation); formation["readiness"] = 30; formation["command_authority"] = "state_qin"; formation["commander_ref"] = None; planner.put(fp, formation)
    state_path = "state/states/qin.json"; state = copy.deepcopy(planner.read(state_path)); state["treasury_silver"] = max(10000, int(state.get("treasury_silver", 0))); before_treasury = int(state["treasury_silver"]); planner.put(state_path, state)
    planner._autonomy_institution({"owner_ref": "inst_qin_military_bureau"}, 1, at)
    trained = planner.read(fp); assert int(trained["readiness"]) > 30
    assert int(planner.read(state_path)["treasury_silver"]) < before_treasury
    assert "formation_qin_wei_unit_01" in planner.read(planner.owner_path("inst_qin_military_bureau"))["military_review"]["trained_formations"]

    # Give one unfortified Qin site a real need and sufficient local material/labor.
    territory = copy.deepcopy(planner.read("state/territory/control.json")); target = next(ref for ref, site in territory["sites"].items() if site.get("controller") == "state_qin")
    territory["sites"][target]["fortified"] = False; territory["sites"][target].setdefault("governance", {})["resistance"] = 60; planner.put("state/territory/control.json", territory)
    ep, eco = planner._private_economy("qin"); _site, region = planner._local_economy_region("qin", eco, target); region.setdefault("commodity_stock", {})["construction_material_units"] = max(1000, int(region.get("commodity_stock", {}).get("construction_material_units", 0))); planner._sync_local_economy_aggregate(eco); planner._write_private_economy(ep, eco)
    state = copy.deepcopy(planner.read(state_path)); state["treasury_silver"] = max(10000, int(state.get("treasury_silver", 0))); planner.put(state_path, state)
    planner._autonomy_institution({"owner_ref": "inst_qin_fortification_bureau"}, 1, at)
    review = planner.read(planner.owner_path("inst_qin_fortification_bureau"))["fortification_review"]
    assert review["project_started_ref"]


def test_interstate_theaters_allocate_multi_formation_campaign_groups(campaign):
    planner = planner_for(campaign); planner._reset()
    config = planner._interstate_theater_config(planner.read("game/data/world/autonomous-theaters.json"))
    qz = next(row for row in config["theaters"] if row["theater_ref"] == "qin_zhao_gyou")
    qin_refs = qz["formation_ref_lists"]["qin"]
    assert len(qin_refs) >= 2
    assert qz["army_groups"]["qin"]["primary_ref"] == qin_refs[0]
    assert qz["army_groups"]["qin"]["reserve_refs"] == qin_refs[1:]


def _install_overlay_tang_polity(planner, *, polity_ref: str = "polity_v6_test"):
    polity_path = f"state/politics/polities/{polity_ref}.json"
    polity = {
        "schema": "sword-polity", "owner_id": polity_ref, "polity_ref": polity_ref,
        "name": "V6 Test Polity", "sovereign_house_ref": "house_tang", "status": "recognized_state",
        "recognition_status": "recognized", "recognized_by": ["state_qin"],
        "treasury_ref": "treasury_house_tang", "military_force_refs": ["force_house_tang"],
        "military_authority_refs": ["house_tang"], "occupied_site_refs": ["loc_gyou"],
        "seat_claim_ref": "loc_gyou", "administrative_capacity": 80,
        "known_threats": {}, "diplomacy": {}, "court_case_refs": [], "market_access_refs": [],
    }
    planner.put(polity_path, polity); planner._register_owner(polity_ref, polity_path)
    territory = copy.deepcopy(planner.read("state/territory/control.json")); territory["sites"]["loc_gyou"]["controller"] = polity_ref; planner.put("state/territory/control.json", territory)
    treasury_path = planner.owner_path("treasury_house_tang"); treasury = copy.deepcopy(planner.read(treasury_path)); treasury["silver"] = max(50_000, int(treasury.get("silver", 0))); planner.put(treasury_path, treasury)
    return polity_ref, polity_path, treasury_path


def _polity_test_command(planner):
    from types import SimpleNamespace
    meta = planner.read("state/meta.json")
    return SimpleNamespace(actor_id=planner.PLAYER_ACTOR, expected_revision=int(meta["revision"]), command_type="polity_action", digest="v6-test", submitted_at=str(meta["time"]), mode="gameplay")


def test_capacity_derived_revolt_can_exceed_old_six_thousand_ceiling(campaign):
    planner = planner_for(campaign); planner._reset(); at = str(planner.read("state/runtime.json")["world_time"])
    pop_path = "state/population/chu.json"; _pp, pop = planner._ensure_local_population_ledger("chu", copy.deepcopy(planner.read(pop_path))); planner.put(pop_path, pop)
    row = pop["local_population"]["sites"]["loc_shintei"]
    rebels = planner._ensure_occupation_rebel_force(
        location_ref="loc_shintei", native_state="chu", controller_state="state_qin",
        local_population=int(row["civilian_population"]),
        governance={"resistance": 100, "elite_cooperation": 0, "displacement_pressure": 100}, at=at,
    )
    assert int(rebels["personnel"]) > 6000
    assert int(rebels["personnel"]) <= int(row["agricultural_available"])


def test_polity_can_found_exact_local_market_and_court_advances_without_auto_verdict(campaign):
    planner = planner_for(campaign); planner._reset(); polity_ref, polity_path, treasury_path = _install_overlay_tang_polity(planner)
    before = int(planner.read(treasury_path)["silver"])
    market_result = planner._dispatch_polity_action(_polity_test_command(planner), {
        "polity_ref": polity_ref, "action": "found_market", "location_ref": "loc_gyou",
        "investment_silver": 1000, "market_name": "Gyou Sovereign Market",
    })
    market = planner.read(planner.owner_path(market_result["market_ref"]))
    assert market["location_ref"] == "loc_gyou"
    assert market["regional_source_ref"] == "loc_gyou"
    assert int(planner.read(treasury_path)["silver"]) == before - 1000
    assert market_result["market_ref"] in planner.read(polity_path)["market_access_refs"]

    court_result = planner._dispatch_polity_action(_polity_test_command(planner), {
        "polity_ref": polity_ref, "action": "open_court_case", "case_kind": "corruption", "subject_ref": "char_hyou",
    })
    case_path = planner.owner_path(court_result["case_ref"]); case = planner.read(case_path)
    assert case["status"] == "open"
    for expected in ("investigating", "hearing", "decision_required"):
        due = str(case["next_review_at"])
        polity = copy.deepcopy(planner.read(polity_path)); planner._autonomy_polity_court(polity_ref, polity, due)
        case = planner.read(case_path); assert case["status"] == expected
    assert "decision" not in case


def test_nonadjacent_defensive_obligation_can_create_access_aware_expeditionary_theater(campaign):
    planner = planner_for(campaign); planner._reset(); at = str(planner.read("state/runtime.json")["world_time"])
    guarantee_ref = planner._activate_diplomatic_treaty({
        "proposal_ref": "v6_yan_han_guarantee", "proposer_ref": "state_yan", "target_ref": "state_han",
        "kind": "guarantee", "direction": "proposer_to_target", "terms": {"duration_days": 3650},
    }, at)
    # Grant the obligated Yan army lawful transit through the sovereigns that can
    # lie on its exact formation-capable route toward Chu.
    for state in ("han", "zhao", "qin", "wei", "qi"):
        planner._activate_diplomatic_treaty({
            "proposal_ref": f"v6_yan_access_{state}", "proposer_ref": f"state_{state}", "target_ref": "state_yan",
            "kind": "military_access", "direction": "proposer_to_target", "terms": {"duration_days": 3650},
        }, at)
    obligations = planner._propagate_defensive_treaty_obligations(
        attacker_ref="state_chu", defender_ref="state_han", location_ref="loc_han_capital", theater_ref="v6_chu_han", at=at,
    )
    assert any(row["treaty_ref"] == guarantee_ref and row["obligated_ref"] == "state_yan" for row in obligations)
    config = planner._interstate_theater_config(planner.read("game/data/world/autonomous-theaters.json"))
    expeditionary = next(row for row in config["theaters"] if row.get("expeditionary") and set(row["sides"]) == {"yan", "chu"})
    assert expeditionary["source_treaty_ref"] == guarantee_ref
    assert expeditionary["formation_ref_lists"]["yan"]
    locations = planner.read("game/data/world/locations.json")
    rows = locations.get("locations", []) if isinstance(locations, dict) else locations
    if isinstance(rows, dict):
        rows = list(rows.values())
    target = next(row for row in rows if isinstance(row, dict) and row.get("ref") == expeditionary["target_location_ref"])
    assert target.get("state") == "chu"


def test_every_explicit_civilian_population_owner_settles_births_deaths_and_grows(campaign):
    planner = planner_for(campaign); planner._reset()
    owner_refs = [
        "population_qin",
        "population_jo",
        "population_quanrong",
        "population_yotanwa_confederation",
        "population_northern_steppe",
        "population_tang_manor",
    ]
    for owner_ref in owner_refs:
        path = planner.owner_path(owner_ref)
        before = copy.deepcopy(planner.read(path))
        before_total = int(before["population_total"])
        planner._autonomy_population({"owner_ref": owner_ref}, 1, "244-BCE-12-04T07:22:48+08:00")
        after = planner.read(path)
        dem = after["demography"]
        assert int(dem["last_births"]) > 0
        assert int(dem["last_deaths"]) > 0
        assert int(after["population_total"]) == sum(int(v) for v in after["strata"].values())
        assert int(after["population_total"]) > before_total
        if isinstance(after.get("local_population"), dict) and isinstance(after["local_population"].get("sites"), dict):
            local_total = sum(
                int(row.get("civilian_population", 0))
                + int(row.get("service_population", 0))
                + int(row.get("candidates_reserved", 0))
                + int(row.get("displaced", 0))
                for row in after["local_population"]["sites"].values()
            )
            assert local_total == int(after["population_total"])


def test_demographic_balance_produces_long_run_population_growth_without_magic_multiplier(campaign):
    planner = planner_for(campaign); planner._reset()
    for owner_ref in ("population_qin", "population_tang_manor"):
        path = planner.owner_path(owner_ref)
        before = int(planner.read(path)["population_total"])
        planner._autonomy_population({"owner_ref": owner_ref}, 10, "235-BCE-08-18T18:22:48+08:00")
        after = planner.read(path)
        dem = after["demography"]
        assert int(dem["last_births"]) > int(dem["last_deaths"]) > 0
        assert int(after["population_total"]) > before
        # 25 births / 17 ordinary civilian deaths per thousand is modest growth,
        # not an explosive replacement multiplier.
        assert int(after["population_total"]) < int(before * 1.15)
