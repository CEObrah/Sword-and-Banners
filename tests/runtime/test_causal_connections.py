from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import execute_production, execute_production_internal
from sword_runtime.causal_event_store import (
    EVENT_HEAD_LIMIT,
    EVENT_RECENT_ARCHIVE_METADATA_LIMIT,
    get_causal_event,
    read_causal_event_owner,
    write_causal_event_owner,
)
from sword_runtime.api.interaction_surface import triggered_interaction_page
from sword_runtime.recruitment_campaigns import start_campaign
from sword_runtime.sim.calendar import CampaignTime


def planner_for(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    return ProductionCampaignPlanner(campaign)


def _state_host(planner, state: str):
    return copy.deepcopy(planner.read("state/runtime.json")["hosts"][f"host_state_{state}"])


def _test_time(planner):
    """Use the current fixture clock instead of embedding a campaign-era date."""
    return str(planner.read("state/runtime.json")["world_time"])


def _free_qin_mobile_reserve_for_state_response(planner):
    """Give the disposable fixture non-player Qin capacity for state response tests."""
    index = planner.read("state/operations/index.json").get("operations", {})
    for operation_ref, operation_path in index.items():
        operation = copy.deepcopy(planner.read(operation_path))
        refs = set(str(ref) for ref in operation.get("formation_refs", []) if isinstance(ref, str))
        if not refs.intersection({"formation_qin_mobile_reserve", "formation_qin_siege_train"}):
            continue
        if str(operation.get("status", "")) not in {"planned", "mobilizing", "active", "engaged", "occupied"}:
            continue
        operation["status"] = "cancelled"
        operation["updated_at"] = _test_time(planner)
        planner.put(operation_path, operation)



def test_conquered_site_tax_is_paid_to_current_controller_from_native_economy(campaign):
    planner = planner_for(campaign); planner._reset()
    at = _test_time(planner)
    planner._occupation_initialize("loc_gyou", "state_qin", "state_zhao", at, "test_capture")
    territory = copy.deepcopy(planner.read("state/territory/control.json"))
    territory["sites"]["loc_gyou"]["controller"] = "state_qin"
    gov = territory["sites"]["loc_gyou"]["governance"]
    gov.update({"tax_compliance": 60, "recruitment_access": 0, "resistance": 20})
    planner.put("state/territory/control.json", territory)
    planner._settle_private_production("zhao", 1, at)
    zhao_cash_before = int(planner.read("state/economy/private/zhao.json")["cash_silver"])

    planner._autonomy_state(_state_host(planner, "qin"), 1, at)

    qin = planner.read("state/states/qin.json")
    row = next(row for row in qin["civil_finance"]["revenue_sources"] if row["location_ref"] == "loc_gyou")
    assert row["native_state"] == "zhao"
    assert row["controller_state"] == "qin"
    assert row["collected_silver"] > 0
    assert int(planner.read("state/economy/private/zhao.json")["cash_silver"]) == zhao_cash_before - row["collected_silver"]
    zhao = planner.read("state/states/zhao.json")
    assert "loc_gyou" not in zhao.get("territorial_control", [])


def test_occupation_recruitment_consumes_native_population_and_pays_origin_economy(campaign):
    planner = planner_for(campaign); planner._reset()
    at = _test_time(planner)
    planner._occupation_initialize("loc_gyou", "state_qin", "state_zhao", at, "test_capture")
    territory = copy.deepcopy(planner.read("state/territory/control.json"))
    territory["sites"]["loc_gyou"]["controller"] = "state_qin"
    gov = territory["sites"]["loc_gyou"]["governance"]
    gov.update({
        "status": "integrating", "administration": 90, "elite_cooperation": 90,
        "civilian_loyalty": 90, "resistance": 0, "tax_compliance": 0,
        "recruitment_access": 100,
    })
    planner.put("state/territory/control.json", territory)

    force_path = "state/forces/state-qin.json"
    force = copy.deepcopy(planner.read(force_path))
    force["authorized_strength"] = int(force["headcount"]) + 1000
    planner.put(force_path, force)

    # Disable native Qin replacement intake without changing total population.
    qin_pop_path = "state/population/qin.json"
    qin_pop = copy.deepcopy(planner.read(qin_pop_path))
    moved = int(qin_pop["strata"]["agricultural"])
    qin_pop["strata"]["agricultural"] = 0
    qin_pop["strata"]["household_and_service"] += moved
    planner.put(qin_pop_path, qin_pop)

    zhao_pop_before = copy.deepcopy(planner.read("state/population/zhao.json"))
    zhao_cash_before = int(planner.read("state/economy/private/zhao.json")["cash_silver"])
    qin_head_before = int(force["headcount"])
    planner._autonomy_state(_state_host(planner, "qin"), 1, at)

    qin_state = planner.read("state/states/qin.json")
    recruited = int(qin_state["civil_finance"]["occupied_recruits"])
    assert recruited > 0
    qin_force = planner.read(force_path)
    assert int(qin_force["headcount"]) == qin_head_before + recruited
    zhao_pop_after = planner.read("state/population/zhao.json")
    assert int(zhao_pop_before["strata"]["agricultural"]) - int(zhao_pop_after["strata"]["agricultural"]) == recruited
    assert int(zhao_pop_after["strata"].get("foreign_military_service", 0)) - int(zhao_pop_before["strata"].get("foreign_military_service", 0)) == recruited
    assert sum(int(v) for v in zhao_pop_before["strata"].values()) == sum(int(v) for v in zhao_pop_after["strata"].values())
    payment = int(qin_state["civil_finance"]["occupied_recruitment"][0]["payment_silver"])
    assert int(planner.read("state/economy/private/zhao.json")["cash_silver"]) == zhao_cash_before + payment


def test_low_liquidity_state_cannot_recruit_against_uncollected_macro_revenue(campaign):
    planner = planner_for(campaign); planner._reset()
    at = _test_time(planner)
    state_path = "state/states/qin.json"
    state = copy.deepcopy(planner.read(state_path)); state["treasury_silver"] = 0; planner.put(state_path, state)
    eco_path = "state/economy/private/qin.json"
    eco = copy.deepcopy(planner.read(eco_path)); eco["cash_silver"] = 0; planner.put(eco_path, eco)
    force_path = "state/forces/state-qin.json"
    force = copy.deepcopy(planner.read(force_path)); force["authorized_strength"] = int(force["headcount"]) + 1000; planner.put(force_path, force)
    pop_before = int(planner.read("state/population/qin.json")["strata"]["active_military"])
    head_before = int(force["headcount"])

    planner._autonomy_state(_state_host(planner, "qin"), 1, at)

    after_state = planner.read(state_path)
    finance = after_state["civil_finance"]
    collected = int(finance["revenue_collected_silver"])
    recruits = int(finance["native_recruits"])
    unit_cost = int(planner.read("game/data/mechanics/economy.json")["military_finance"]["recruitment_and_basic_issue_cost_silver_per_person"])
    assert int(finance["native_recruitment_payments_silver"]) == recruits * unit_cost
    assert recruits * unit_cost <= collected
    assert int(planner.read(force_path)["headcount"]) == head_before + recruits
    assert int(planner.read("state/population/qin.json")["strata"]["active_military"]) == pop_before + recruits


def test_undergarrisoned_unfunded_occupation_can_revolt_and_becomes_state_threat(campaign):
    planner = planner_for(campaign); planner._reset()
    at = _test_time(planner)
    planner._occupation_initialize("loc_gyou", "state_qin", "state_zhao", at, "test_capture")
    territory = copy.deepcopy(planner.read("state/territory/control.json"))
    territory["sites"]["loc_gyou"]["controller"] = "state_qin"
    gov = territory["sites"]["loc_gyou"]["governance"]
    gov.update({"resistance": 98, "food_security": 20, "elite_cooperation": 5})
    planner.put("state/territory/control.json", territory)
    state_path = "state/states/qin.json"
    state = copy.deepcopy(planner.read(state_path)); state["treasury_silver"] = 0; planner.put(state_path, state)

    planner._settle_occupation_administration("qin", 1, at)
    gov = planner.read("state/territory/control.json")["sites"]["loc_gyou"]["governance"]
    assert gov["status"] == "open_revolt"
    assert gov["tax_compliance"] == 0
    assert gov["recruitment_access"] == 0
    threat = planner.read(state_path)["known_threats"]["occupation_revolt:loc_gyou"]
    assert threat["kind"] == "occupation_revolt"
    assert threat["location_ref"] == "loc_gyou"
    assert threat["force_ref"].startswith("force_occupation_revolt_")
    assert threat["formation_refs"]
    rebel_force = planner.read(planner.owner_path(threat["force_ref"]))
    rebel_formation = planner.read(planner.owner_path(threat["formation_refs"][0]))
    rebel_faction = planner.read(planner.owner_path(threat["faction_ref"]))
    assert int(rebel_force["headcount"]) > 0
    assert int(rebel_formation["personnel"]) == int(rebel_force["headcount"])
    assert rebel_formation["location_ref"] == "loc_gyou"
    leader_ref = rebel_formation["commander_ref"]
    assert leader_ref in rebel_force["materialized_people"]
    assert leader_ref in rebel_faction["representative_refs"]
    leader = planner.read(planner.owner_path(leader_ref))
    assert leader["schema"] == "sword-materialized-person"
    assert leader["population_provenance"]["population_ref"] == "population_zhao"
    assert leader["population_provenance"]["principle"].startswith("this exact leader reclassifies")
    assert sum(int(x["count"]) for x in rebel_formation["cohort_composition"]) + 1 == int(rebel_formation["personnel"])
    planner._validate_person_location_for_formation(leader_ref, rebel_formation)
    assert rebel_faction["status"] == "active_revolt"
    assert planner.read("state/population/zhao.json")["strata"]["rebel_military"] == int(rebel_force["headcount"])
    assert planner.read(planner.owner_path(threat["operation_ref"]))["status"] == "active"

    # The state response consumes the saved threat while the revolt remains a real
    # opposing faction/force/formation rather than a scalar-only obstacle. The live
    # baseline already commits Qin's standing formations elsewhere, so this disposable
    # fixture releases the mobile reserve from that unrelated operation first.
    _free_qin_mobile_reserve_for_state_response(planner)
    planner._autonomy_state(_state_host(planner, "qin"), 1, at)
    index = planner.read("state/operations/index.json")["operations"]
    op_ref = next(ref for ref in index if ref.startswith("operation_auto_qin_"))
    operation = planner.read(index[op_ref])
    assert operation["target_location_ref"] == "loc_gyou"
    assert "occupation_revolt:loc_gyou" in operation["objective_refs"]

    # The same force is combat-capable and autonomous losses are charged back to
    # the exact Zhao rebel-military stratum rather than disappearing from population.
    pop_before = copy.deepcopy(planner.read("state/population/zhao.json"))
    force_before = int(planner.read(planner.owner_path(threat["force_ref"]))["headcount"])
    loss_result = planner._autonomy_apply_battle_losses(
        threat["formation_refs"][0], 10, at,
        losing_side=True, opponent_state="qin", seed_material="test_revolt_battle_loss",
    )
    assert loss_result["loss"] == 10
    assert loss_result["rebel_population_loss"]["personnel"] == 10
    pop_after = planner.read("state/population/zhao.json")
    assert int(pop_before["strata"]["rebel_military"]) - int(pop_after["strata"]["rebel_military"]) == 10
    assert int(pop_before["population_total"]) - int(pop_after["population_total"]) == 10
    assert int(planner.read(planner.owner_path(threat["force_ref"]))["headcount"]) == force_before - 10


def test_route_disruption_reduces_market_delivery_and_raises_insecurity(campaign):
    planner = planner_for(campaign); planner._reset()
    baseline = planner._market_transport_conditions("qin", "loc_kanyou")
    territory = copy.deepcopy(planner.read("state/territory/control.json"))
    territory["sites"]["loc_kankoku_pass"]["controller"] = "state_zhao"
    planner.put("state/territory/control.json", territory)
    disrupted = planner._market_transport_conditions("qin", "loc_kanyou")
    assert disrupted["disrupted_routes"] > baseline["disrupted_routes"]
    assert disrupted["route_factor"] < baseline["route_factor"]

    market_path = "state/markets/kanyou.json"
    market = copy.deepcopy(planner.read(market_path))
    for key in market["stock"]:
        market["stock"][key] = 0
    planner.put(market_path, market)
    eco_path = "state/economy/private/qin.json"
    eco = copy.deepcopy(planner.read(eco_path))
    for key in market["stock"]:
        eco.setdefault("finished_goods", {})[key] = 1_000_000
    planner.put(eco_path, eco)
    planner._restock_capital_market("qin", _test_time(planner))
    after = planner.read(market_path)
    assert after["transport_state"]["disrupted_routes"] > 0
    assert after["transport_state"]["delivery_factor"] < 1.0
    assert float(after["insecurity_hoarding_factor"]) > 1.0


def test_project_workers_are_reserved_from_craft_production_until_release(campaign):
    planner = planner_for(campaign); planner._reset()
    eco_path = "state/economy/private/qin.json"
    eco = copy.deepcopy(planner.read(eco_path)); eco["commodity_stock"]["construction_material_units"] = 1_000_000; planner.put(eco_path, eco)
    meta = planner.read("state/meta.json")
    command = SimpleNamespace(command_type="institution_project", digest="labor1234567890", actor_id="internal:sword-autonomy", expected_revision=int(meta["revision"]), submitted_at=str(meta["time"]))
    planner._start_funded_institution_project(command, {
        "institution_ref": "inst_qin_fortification_bureau", "project_ref": "project_labor_reservation",
        "duration_hours": 24, "kind": "construction", "magnitude": 100,
    })
    reserved = int(planner.read(eco_path)["labor_allocation"]["projects"]["project_labor_reservation"]["workers"])
    assert reserved > 0
    planner._settle_private_production("qin", 1, str(meta["time"]))
    runtime = planner.read(eco_path)["production_runtime"]["last_labor_basis"]
    assert runtime["construction_workers_reserved"] == reserved
    assert runtime["craft_and_industry_available_for_production"] == runtime["craft_and_industry_total"] - reserved


def test_recruitment_campaign_spending_is_paid_into_regional_private_economy(campaign):
    planner = planner_for(campaign); planner._reset()
    eco_before = int(planner.read("state/economy/private/qin.json")["cash_silver"])
    treasury_path = planner.owner_path("treasury_house_tang")
    treasury_before = int(planner.read(treasury_path)["silver"])
    result = start_campaign(planner, {
        "state": "qin", "campaign_ref": "campaign_payment_conservation", "applicant_count": 100,
        "destination_force_ref": "force_tang_wei_personal", "role": "household_retainer",
        "location_ref": "loc_tang_manor_garrison_yard",
    }, evidence_ref="test_recruitment_payment")
    spent = int(result["silver_spent"])
    assert spent > 0
    assert int(planner.read(treasury_path)["silver"]) == treasury_before - spent
    assert int(planner.read("state/economy/private/qin.json")["cash_silver"]) == eco_before + spent


def test_exact_information_wakes_reactive_faction_and_governs_action(campaign):
    before = planner_for(campaign).read("state/runtime.json")["hosts"]["host_faction_zhao_defense_council"]["next_due"]
    execute_production_internal(campaign, "information_create", {
        "information_ref": "information_riboku_reactive_test",
        "claim": "A verified Qin concentration is reported near the Zhao frontier.",
        "knowers": ["char_riboku"], "confidence": "0.9", "provenance": "frontier scout report",
    }, request_id="faction-info-wake")
    planner = planner_for(campaign); planner._reset()
    faction = planner.read("state/factions/faction_zhao_defense_council.json")
    assert "information_riboku_reactive_test" in faction["knowledge"]
    assert "information_riboku_reactive_test" in faction["pending_information_refs"]
    after_due = planner.read("state/runtime.json")["hosts"]["host_faction_zhao_defense_council"]["next_due"]
    assert after_due != before

    planner._autonomy_faction({"owner_ref": "faction_zhao_defense_council"}, 3, str(planner.read("state/runtime.json")["world_time"]))
    faction = planner.read("state/factions/faction_zhao_defense_council.json")
    commitment = faction["last_action"]
    assert commitment["action"] == "frontier_readiness"
    assert "information_riboku_reactive_test" in commitment["knowledge_refs_used"]
    assert faction["relationships"]["faction_zhao_court_conservatives"]["sentiment"] < 0


def test_causal_event_store_archives_hot_overflow_and_rehydrates_exact_old_ref(campaign):
    planner = planner_for(campaign); planner._reset()
    _path, owner = read_causal_event_owner(planner)
    now = str(planner.read("state/runtime.json")["world_time"])
    first_ref = "event_archive_test_0000"
    for i in range(EVENT_HEAD_LIMIT + 32):
        ref = f"event_archive_test_{i:04d}"
        owner["causal_events"][ref] = {
            "event_ref": ref, "kind": "test_event", "status": "triggered",
            "due_at": now, "triggered_at": now, "summary": f"archive test {i}",
        }
    write_causal_event_owner(planner, owner)
    hot = planner.read("state/event/events-messages-and-movement.json")
    assert len(hot["causal_events"]) <= EVENT_HEAD_LIMIT
    assert int(hot["archived_event_count"]) > 0
    restored = get_causal_event(planner, first_ref)
    assert restored is not None
    assert restored["event_ref"] == first_ref
    assert any(path.startswith("state/event/archive/segment_") for path in planner._writes)
    assert any(path.startswith("state/event/index/route_") for path in planner._writes)


def test_foreign_service_casualties_are_charged_to_origin_population(campaign):
    planner = planner_for(campaign); planner._reset()
    at = _test_time(planner)
    planner._occupation_initialize("loc_gyou", "state_qin", "state_zhao", at, "test_capture")
    territory = copy.deepcopy(planner.read("state/territory/control.json"))
    territory["sites"]["loc_gyou"]["controller"] = "state_qin"
    gov = territory["sites"]["loc_gyou"]["governance"]
    gov.update({"status": "integrating", "administration": 90, "elite_cooperation": 90, "civilian_loyalty": 90, "resistance": 0, "tax_compliance": 0, "recruitment_access": 100})
    planner.put("state/territory/control.json", territory)
    force_path = "state/forces/state-qin.json"
    force = copy.deepcopy(planner.read(force_path)); force["authorized_strength"] = int(force["headcount"]) + 100; planner.put(force_path, force)
    qin_pop_path = "state/population/qin.json"
    qin_pop = copy.deepcopy(planner.read(qin_pop_path)); moved = int(qin_pop["strata"]["agricultural"]); qin_pop["strata"]["agricultural"] = 0; qin_pop["strata"]["household_and_service"] += moved; planner.put(qin_pop_path, qin_pop)
    planner._autonomy_state(_state_host(planner, "qin"), 1, at)

    force = planner.read(force_path)
    cohort_id = next(cid for cid, row in force["cohort_ledger"]["cohorts"].items() if row.get("origin", {}).get("population_ref") == "population_zhao")
    qin_before = copy.deepcopy(planner.read(qin_pop_path))
    zhao_before = copy.deepcopy(planner.read("state/population/zhao.json"))
    loss = 10
    # Reproduce the base battle reducer's owner-state population debit before exact provenance reconciliation.
    qin_debited = copy.deepcopy(qin_before)
    qin_debited["strata"]["active_military"] -= loss
    qin_debited["population_total"] -= loss
    planner.put(qin_pop_path, qin_debited)

    reconciled = planner._reconcile_foreign_service_casualties(
        "force_state_qin", {cohort_id: loss}, at=at, evidence_ref="battle_foreign_service_test"
    )
    assert reconciled == {"population_zhao": loss}
    qin_after = planner.read(qin_pop_path)
    zhao_after = planner.read("state/population/zhao.json")
    assert int(qin_after["strata"]["active_military"]) == int(qin_before["strata"]["active_military"])
    assert int(qin_after["population_total"]) == int(qin_before["population_total"])
    assert int(zhao_before["strata"]["foreign_military_service"]) - int(zhao_after["strata"]["foreign_military_service"]) == loss
    assert int(zhao_before["population_total"]) - int(zhao_after["population_total"]) == loss


def test_house_can_proclaim_proto_state_and_take_territory_with_exact_occupation(campaign):
    planner = planner_for(campaign); planner._reset()
    formation_ref = "formation_tang_champions_first"
    formation_path = planner.owner_path(formation_ref)
    formation = copy.deepcopy(planner.read(formation_path))
    formation["location_ref"] = "loc_gyou"
    planner.put(formation_path, formation)
    planner._index_formation_location(formation_ref, "loc_kanyou", "loc_gyou")

    operation_ref = "operation_test_house_sovereignty"
    operation_path = f"state/operations/{operation_ref}.json"
    operation = {
        "schema": "sword-operation", "owner_id": operation_ref, "operation_ref": operation_ref,
        "status": "occupied", "location_ref": "loc_gyou", "formation_refs": [formation_ref],
        "administrative_authority": "house_tang", "administrative_authorities": ["house_tang"],
        "objective": "occupy Gyou for House Tang", "created_at": str(planner._world_time()),
    }
    planner.put(operation_path, operation)
    index = copy.deepcopy(planner.read("state/operations/index.json")); index.setdefault("operations", {})[operation_ref] = operation_path; planner.put("state/operations/index.json", index); planner._register_owner(operation_ref, operation_path)

    meta = planner.read("state/meta.json")
    proclaim = SimpleNamespace(command_type="house_action", digest="sovereignty123456", request_id="sovereignty-proclaim", actor_id="char_tang_wei", expected_revision=int(meta["revision"]), submitted_at=str(meta["time"]))
    result = planner._proclaim_house_territorial_authority(proclaim, {"house_ref": "house_tang", "action": "proclaim_territorial_authority", "location_ref": "loc_gyou", "operation_ref": operation_ref, "polity_name": "Tang Territorial Authority"})
    assert result["polity_ref"] == "polity_tang"
    polity = planner.read(planner.owner_path("polity_tang"))
    assert polity["status"] == "territorial_authority"
    assert polity["sovereign_house_ref"] == "house_tang"
    assert planner.read(planner.owner_path("house_tang"))["sovereignty_ref"] == "polity_tang"

    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    for event in runtime.get("events", []):
        if isinstance(event, dict):
            event["suspended"] = True
    planner.put("state/runtime.json", runtime)
    transfer = SimpleNamespace(command_type="territorial_consequence", digest="sovereignty654321", request_id="sovereignty-transfer", actor_id="internal:sword-autonomy", expected_revision=int(planner.read("state/meta.json")["revision"]), submitted_at=str(planner.read("state/meta.json")["time"]))
    transfer_result = planner._dispatch(transfer, {"location_ref": "loc_gyou", "controller": "polity_tang", "operation_ref": operation_ref})
    assert transfer_result["controller"] == "polity_tang"
    assert planner.read("state/territory/control.json")["sites"]["loc_gyou"]["controller"] == "polity_tang"
    polity = planner.read(planner.owner_path("polity_tang"))
    assert polity["status"] == "proto_state"
    assert "loc_gyou" in polity["occupied_site_refs"]

    # Recognition is a separate state-owned act; two exact state recognitions elevate
    # the proto-state without rewriting House identity into an existing kingdom.
    for state in ("qin", "wei"):
        recognize = SimpleNamespace(command_type="state_action", digest=f"recognize{state}1234", request_id=f"recognize-{state}", actor_id="internal:sword-autonomy", expected_revision=int(planner.read("state/meta.json")["revision"]), submitted_at=str(planner.read("state/meta.json")["time"]))
        planner._recognize_polity(recognize, {"state": state, "action": "recognize_polity", "polity_ref": "polity_tang"})
    polity = planner.read(planner.owner_path("polity_tang"))
    assert polity["status"] == "recognized_state"
    assert polity["recognition_status"] == "recognized"
    assert {"state_qin", "state_wei"}.issubset(set(polity["recognized_by"]))
    assert set(polity.get("institution_refs", {})) == {"regional_administration", "military_bureau", "recruitment_office", "granary_depot_office", "fortification_bureau", "horse_administration"}


def test_project_cancellation_releases_workers_and_refunds_unused_inputs(campaign):
    planner = planner_for(campaign); planner._reset()
    eco_path = "state/economy/private/qin.json"
    eco = copy.deepcopy(planner.read(eco_path)); eco["commodity_stock"]["construction_material_units"] = 10000; planner.put(eco_path, eco)
    state_before = int(planner.read("state/states/qin.json")["treasury_silver"])
    material_before = int(eco["commodity_stock"]["construction_material_units"])
    meta = planner.read("state/meta.json")
    start = SimpleNamespace(command_type="institution_project", digest="cancelproject1234", request_id="cancel-project-start", actor_id="internal:sword-autonomy", expected_revision=int(meta["revision"]), submitted_at=str(meta["time"]))
    planner._start_funded_institution_project(start, {"institution_ref": "inst_qin_fortification_bureau", "project_ref": "project_cancel_test", "duration_hours": 96, "kind": "construction", "magnitude": 10})
    assert "project_cancel_test" in planner.read(eco_path)["labor_allocation"]["projects"]
    after_start_state = int(planner.read("state/states/qin.json")["treasury_silver"])
    assert after_start_state < state_before

    cancel = SimpleNamespace(command_type="project_cancel", digest="cancelproject5678", request_id="cancel-project-do", actor_id="internal:sword-autonomy", expected_revision=int(planner.read("state/meta.json")["revision"]), submitted_at=str(planner.read("state/meta.json")["time"]))
    result = planner._cancel_funded_project(cancel, {"institution_ref": "inst_qin_fortification_bureau", "project_ref": "project_cancel_test"})
    assert result["status"] == "cancelled"
    assert result["refunds"]["construction_workers_released"] > 0
    assert result["refunds"]["silver_refunded"] > 0
    assert result["refunds"]["construction_material_units"] > 0
    after_eco = planner.read(eco_path)
    assert "project_cancel_test" not in after_eco["labor_allocation"]["projects"]
    assert int(after_eco["commodity_stock"]["construction_material_units"]) > material_before - 200
    project = next(row for row in planner.read(planner.owner_path("inst_qin_fortification_bureau"))["projects"] if row["project_ref"] == "project_cancel_test")
    assert project["status"] == "cancelled"
    assert 0 <= float(project["progress_at_cancellation"]) < 1



def test_weighted_local_baselines_preserve_state_totals_and_site_differences(campaign):
    planner = planner_for(campaign); planner._reset()
    baselines = planner._ensure_local_site_baselines("zhao")
    population_total = int(planner.read("state/population/zhao.json")["population_total"])
    monthly_revenue = int(planner.read("state/states/zhao.json")["normal_monthly_revenue_silver"])
    assert sum(int(row["population_allocation"]) for row in baselines.values()) == population_total
    assert sum(int(row["monthly_tax_base_silver"]) for row in baselines.values()) == monthly_revenue
    assert int(baselines["loc_kantan"]["population_allocation"]) > int(baselines["loc_zhao_border_fort"]["population_allocation"])
    assert int(baselines["loc_gyou"]["monthly_tax_base_silver"]) > int(baselines["loc_zhao_border_fort"]["monthly_tax_base_silver"])
    saved = planner.read("state/territory/control.json")["sites"]["loc_gyou"]["local_baseline"]
    assert saved["authority"] is False


def test_hostile_interdiction_operation_disrupts_market_route_without_territorial_capture(campaign):
    planner = planner_for(campaign); planner._reset()
    baseline = planner._market_transport_conditions("qin", "loc_kanyou")
    operation_ref = "operation_test_zhao_interdict_kankoku"
    operation_path = f"state/operations/{operation_ref}.json"
    planner.put(operation_path, {
        "schema": "sword-operation", "owner_id": operation_ref, "operation_ref": operation_ref,
        "status": "active", "kind": "raid", "objective": "interdict Qin road and harass supply line",
        "location_ref": "loc_kankoku_pass", "route_refs": ["route_kanyou_kankoku"],
        "formation_refs": [], "administrative_authority": "state_zhao",
        "administrative_authorities": ["state_zhao"], "created_at": str(planner._world_time()),
    })
    index = copy.deepcopy(planner.read("state/operations/index.json"))
    index.setdefault("operations", {})[operation_ref] = operation_path
    planner.put("state/operations/index.json", index)
    disrupted = planner._market_transport_conditions("qin", "loc_kanyou")
    assert operation_ref in disrupted["operation_disruption_refs"]
    assert disrupted["disrupted_routes"] > baseline["disrupted_routes"]
    assert disrupted["route_factor"] < baseline["route_factor"]
    assert planner.read("state/territory/control.json")["sites"]["loc_kankoku_pass"]["controller"] == "state_qin"



def test_archived_player_facing_report_remains_discoverable_without_exact_id(campaign):
    planner = planner_for(campaign); planner._reset()
    _path, owner = read_causal_event_owner(planner)
    now = str(planner.read("state/runtime.json")["world_time"])
    old_ref = "event_archived_unread_world_report"
    owner["causal_events"][old_ref] = {
        "event_ref": old_ref, "kind": "world_arc_report", "status": "triggered",
        "due_at": now, "triggered_at": now, "arc_ref": "arc_archive_discovery_test",
        "source_event_ref": "event_archive_discovery_source", "summary": "Unread report that must survive hot-head eviction.",
        "delivery": {"target_ref": "char_tang_wei", "location_ref": "loc_kanyou", "route": "staff courier"},
        "provenance": {"kind": "world_arc_information_propagation"},
    }
    for i in range(EVENT_HEAD_LIMIT + 48):
        ref = f"event_archive_noise_{i:04d}"
        owner["causal_events"][ref] = {
            "event_ref": ref, "kind": "test_event", "status": "triggered",
            "due_at": f"{now}|{i:04d}", "triggered_at": f"{now}|{i:04d}", "summary": "archive noise",
        }
    write_causal_event_owner(planner, owner)
    assert old_ref not in planner.read("state/event/events-messages-and-movement.json")["causal_events"]
    page = triggered_interaction_page(planner, limit=20)
    assert page["count"] >= 1
    assert old_ref in {row["interaction_ref"] for row in page["interaction_handles"]}


def test_causal_archive_metadata_and_new_route_shards_remain_bounded(campaign, monkeypatch):
    import sword_runtime.causal_event_store as causal_store
    metadata_limit = 2
    monkeypatch.setattr(causal_store, "EVENT_RECENT_ARCHIVE_METADATA_LIMIT", metadata_limit)
    planner = planner_for(campaign); planner._reset()
    _path, owner = read_causal_event_owner(planner)
    now = str(planner.read("state/runtime.json")["world_time"])
    # A small patched metadata window exercises the same bounded behavior without
    # making the regression itself a multi-minute synthetic archive benchmark.
    for i in range(EVENT_HEAD_LIMIT + 256 * (metadata_limit + 2)):
        ref = f"event_archive_scale_{i:06d}"
        owner["causal_events"][ref] = {
            "event_ref": ref, "kind": "test_event", "status": "triggered",
            "due_at": now, "triggered_at": now, "summary": "archive scale test",
        }
    write_causal_event_owner(planner, owner)
    hot = planner.read("state/event/events-messages-and-movement.json")
    assert len(hot.get("archives", [])) <= metadata_limit
    route_paths = sorted(path for path in planner._writes if path.startswith("state/event/index/route_"))
    assert route_paths
    # New route shards use four hex characters, not the older two-hex bucket.
    assert all(len(Path(path).stem.removeprefix("route_")) == 4 for path in route_paths)
    assert get_causal_event(planner, "event_archive_scale_000000") is not None


def test_house_sovereignty_rejects_state_owned_force_with_only_player_command(campaign):
    import pytest
    planner = planner_for(campaign); planner._reset()
    formation_ref = "formation_qin_wei_unit_01"
    formation_path = planner.owner_path(formation_ref)
    formation = copy.deepcopy(planner.read(formation_path))
    formation["location_ref"] = "loc_gyou"
    formation["command_authority"] = "char_tang_wei"
    assert formation["administrative_owner"] == "state_qin"
    assert formation["owner_force_ref"] == "force_state_qin"
    planner.put(formation_path, formation)
    operation_ref = "operation_test_qin_conquest_under_wei_command"
    operation_path = f"state/operations/{operation_ref}.json"
    planner.put(operation_path, {
        "schema": "sword-operation", "owner_id": operation_ref, "operation_ref": operation_ref,
        "status": "occupied", "location_ref": "loc_gyou", "formation_refs": [formation_ref],
        "administrative_authority": "state_qin", "administrative_authorities": ["state_qin"],
        "objective": "occupy Gyou for Qin", "created_at": str(planner._world_time()),
    })
    index = copy.deepcopy(planner.read("state/operations/index.json")); index.setdefault("operations", {})[operation_ref] = operation_path; planner.put("state/operations/index.json", index); planner._register_owner(operation_ref, operation_path)
    meta = planner.read("state/meta.json")
    command = SimpleNamespace(command_type="house_action", digest="rejectcommandsovereignty", request_id="reject-command-sovereignty", actor_id="char_tang_wei", expected_revision=int(meta["revision"]), submitted_at=str(meta["time"]))
    with pytest.raises(PermissionError, match="command authority alone is insufficient"):
        planner._proclaim_house_territorial_authority(command, {"house_ref": "house_tang", "action": "proclaim_territorial_authority", "location_ref": "loc_gyou", "operation_ref": operation_ref, "polity_name": "Stolen Qin Conquest"})
    assert "polity_tang" not in planner.read("state/index/owner-index.json").get("owners", {})


def test_polity_tax_uses_elapsed_months_not_house_review_count(campaign):
    planner = planner_for(campaign); planner._reset()
    at = _test_time(planner)
    house_path = planner.owner_path("house_tang"); house = copy.deepcopy(planner.read(house_path)); house["sovereignty_ref"] = "polity_tang"; planner.put(house_path, house)
    polity_path = "state/politics/polities/polity_tang.json"
    planner.put(polity_path, {"schema": "sword-polity", "owner_id": "polity_tang", "polity_ref": "polity_tang", "name": "Tang Authority", "sovereign_house_ref": "house_tang", "status": "proto_state", "recognition_status": "unrecognized", "recognized_by": [], "treasury_ref": "treasury_house_tang", "military_force_refs": ["force_house_tang"], "military_authority_refs": ["house_tang"], "occupied_site_refs": ["loc_gyou"], "administrative_capacity": 80, "known_threats": {}}); planner._register_owner("polity_tang", polity_path)
    territory = copy.deepcopy(planner.read("state/territory/control.json")); territory["sites"]["loc_gyou"]["controller"] = "polity_tang"; territory["sites"]["loc_gyou"]["governance"] = {"status": "integrating", "administration": 90, "elite_cooperation": 90, "civilian_loyalty": 90, "resistance": 0, "tax_compliance": 80, "recruitment_access": 0, "food_security": 90}; planner.put("state/territory/control.json", territory)
    eco_path = "state/economy/private/zhao.json"; eco = copy.deepcopy(planner.read(eco_path)); eco["cash_silver"] = max(int(eco.get("cash_silver", 0)), 10**9); planner.put(eco_path, eco)
    planner._settle_house_polity("house_tang", 1, at, months=4)
    polity = planner.read(polity_path); row = next(row for row in polity["civil_finance"]["revenue_sources"] if row["location_ref"] == "loc_gyou")
    baseline = planner.read("state/territory/control.json")["sites"]["loc_gyou"]["local_baseline"]["monthly_tax_base_silver"]
    expected = int(round(int(baseline) * (int(row["tax_compliance"]) / 100.0) * 0.85 * 4))
    assert row["due_silver"] == expected
    assert row["collected_silver"] == expected


def test_active_revolt_gets_dynamic_scheduler_and_autonomous_irregular_campaign(campaign):
    from sword_runtime.civil_world import sync_faction_routes
    planner = planner_for(campaign); planner._reset(); at = _test_time(planner)
    planner._occupation_initialize("loc_gyou", "state_qin", "state_zhao", at, "test_capture")
    territory = copy.deepcopy(planner.read("state/territory/control.json")); territory["sites"]["loc_gyou"]["controller"] = "state_qin"; gov = territory["sites"]["loc_gyou"]["governance"]; gov.update({"resistance": 98, "food_security": 20, "elite_cooperation": 5}); planner.put("state/territory/control.json", territory)
    state = copy.deepcopy(planner.read("state/states/qin.json")); state["treasury_silver"] = 0; planner.put("state/states/qin.json", state)
    planner._settle_occupation_administration("qin", 1, at)
    revolt = planner.read("state/territory/control.json")["sites"]["loc_gyou"]["governance"]["revolt"]
    faction_ref = revolt["faction_ref"]; operation_ref = revolt["operation_ref"]
    runtime = copy.deepcopy(planner.read("state/runtime.json")); sync_faction_routes(planner, runtime); planner.put("state/runtime.json", runtime)
    host = next(h for h in runtime["hosts"].values() if isinstance(h, dict) and h.get("dynamic_revolt_route") is True and h.get("owner_ref") == faction_ref)
    assert host["recurrence_seconds"] == 7 * 86400
    before_actions = int(planner.read(planner.owner_path(faction_ref)).get("action_count", 0) or 0)
    planner._autonomy_faction(host, 1, at)
    faction = planner.read(planner.owner_path(faction_ref)); operation = planner.read(planner.owner_path(operation_ref))
    assert int(faction.get("action_count", 0) or 0) == before_actions + 1
    assert faction["last_action"]["action"] == "irregular_campaign"
    assert operation["last_autonomous_action"]["kind"] in {"raid", "raid_and_recruit"}
    assert operation["route_refs"]
    assert operation["kind"] == "local_insurgency_raid"


def test_house_polity_gets_monthly_causal_host_and_state_like_threat_response(campaign):
    from sword_runtime.civil_world import sync_polity_routes
    planner = planner_for(campaign); planner._reset(); at = str(planner.read("state/runtime.json")["world_time"])
    house_path = planner.owner_path("house_tang"); house = copy.deepcopy(planner.read(house_path)); house["sovereignty_ref"] = "polity_tang"; planner.put(house_path, house)
    polity_path = "state/politics/polities/polity_tang.json"
    planner.put(polity_path, {"schema": "sword-polity", "owner_id": "polity_tang", "polity_ref": "polity_tang", "name": "Tang State", "sovereign_house_ref": "house_tang", "status": "recognized_state", "recognition_status": "recognized", "recognized_by": ["state_qin", "state_wei"], "treasury_ref": "treasury_house_tang", "military_force_refs": ["force_house_tang"], "military_authority_refs": ["house_tang"], "occupied_site_refs": ["loc_kanyou"], "administrative_capacity": 80, "known_threats": {"test_local_threat": {"severity": 80, "location_ref": "loc_kanyou", "kind": "security_threat"}}}); planner._register_owner("polity_tang", polity_path)
    territory = copy.deepcopy(planner.read("state/territory/control.json")); territory["sites"]["loc_kanyou"]["controller"] = "polity_tang"; territory["sites"]["loc_kanyou"]["governance"] = {"status": "integrating", "administration": 80, "elite_cooperation": 80, "civilian_loyalty": 80, "resistance": 5, "tax_compliance": 70, "recruitment_access": 0, "food_security": 90}; planner.put("state/territory/control.json", territory)
    formation_path = planner.owner_path("formation_tang_champions_first"); formation = copy.deepcopy(planner.read(formation_path)); formation["commander_ref"] = None; formation["command_authority"] = "house_tang"; planner.put(formation_path, formation)
    runtime = copy.deepcopy(planner.read("state/runtime.json")); sync_polity_routes(planner, runtime); planner.put("state/runtime.json", runtime)
    host = runtime["hosts"]["host_polity_tang"]
    assert host["kind"] == "polity" and host["recurrence_seconds"] == 30 * 86400
    planner._autonomy_polity(host, 1, at)
    polity = planner.read(polity_path)
    assert polity["state_integration"]["monthly_autonomy"] is True
    assert polity["state_integration"]["threat_response_operations"] is True
    ops = planner.read("state/operations/index.json")["operations"]
    response_refs = [ref for ref in ops if ref.startswith("operation_tang_response_")]
    assert response_refs
    response = planner.read(ops[response_refs[0]])
    assert response["administrative_authority"] == "polity_tang"
    assert "test_local_threat" in response["objective_refs"]


def test_recognized_polity_participates_in_shared_interstate_front_and_diplomacy(campaign):
    planner = planner_for(campaign); planner._reset()
    house_path = planner.owner_path("house_tang"); house = copy.deepcopy(planner.read(house_path)); house["sovereignty_ref"] = "polity_tang"; planner.put(house_path, house)
    polity_path = "state/politics/polities/polity_tang.json"
    planner.put(polity_path, {
        "schema": "sword-polity", "owner_id": "polity_tang", "polity_ref": "polity_tang", "name": "Tang State",
        "sovereign_house_ref": "house_tang", "status": "recognized_state", "recognition_status": "recognized",
        "recognized_by": ["state_qin", "state_wei"], "treasury_ref": "treasury_house_tang",
        "military_force_refs": ["force_house_tang"], "military_authority_refs": ["house_tang"],
        "occupied_site_refs": ["loc_gyou"], "seat_claim_ref": "loc_gyou", "administrative_capacity": 80, "known_threats": {},
        "mobilization_readiness": 70,
        "war_intents": [{"intent_ref": "war_intent_tang_zhao_test", "status": "authorized", "target_ref": "state_zhao", "location_ref": "loc_zhao_regional_01", "kind": "territorial_control", "objective": "secure the adjacent Zhao frontier"}],
    }); planner._register_owner("polity_tang", polity_path)
    formation_path = planner.owner_path("formation_tang_champions_first"); formation = copy.deepcopy(planner.read(formation_path)); formation["location_ref"] = "loc_gyou"; formation["commander_ref"] = None; formation["command_authority"] = "house_tang"; planner.put(formation_path, formation)
    territory = copy.deepcopy(planner.read("state/territory/control.json")); territory["sites"]["loc_gyou"]["controller"] = "polity_tang"; planner.put("state/territory/control.json", territory)

    config = planner._interstate_theater_config(planner.read("game/data/world/autonomous-theaters.json"))
    dynamic = next(row for row in config["theaters"] if set(row.get("sides", [])) == {"polity_tang", "zhao"})
    assert dynamic["dynamic"] is True
    assert "formation_tang_champions_first" in dynamic["formation_refs"].values()
    polity = copy.deepcopy(planner.read(polity_path)); polity["war_intents"][0]["location_ref"] = dynamic["target_location_ref"]; planner.put(polity_path, polity)

    world_path = planner.owner_path("interstate_warring_states"); world = copy.deepcopy(planner.read(world_path))
    world.setdefault("theaters", {})[dynamic["theater_ref"]] = {"phase": "peace", "cycle": 0, "pressure": 99, "cooldown_reviews": 0, "history": []}
    planner.put(world_path, world)
    host = copy.deepcopy(planner.read("state/runtime.json")["hosts"]["host_interstate_wars"]); at = str(host["next_due"])
    planner._autonomy_interstate(host, 1, at)

    polity = planner.read(polity_path); zhao = planner.read("state/states/zhao.json")
    assert polity["diplomacy"]["state_zhao"]["status"] == "war"
    assert zhao["diplomacy"]["polity_tang"]["status"] == "war"
    record = planner.read(world_path)["theaters"][dynamic["theater_ref"]]
    assert {record["attacker_state"], record["defender_state"]} == {"polity_tang", "zhao"}
    assert record["phase"] == "mobilizing"


def test_explicit_territorial_grant_does_not_transfer_granting_state_force_to_house_polity(campaign):
    planner = planner_for(campaign); planner._reset()
    formation_ref = "formation_qin_wei_unit_01"
    formation_path = planner.owner_path(formation_ref)
    formation = copy.deepcopy(planner.read(formation_path))
    formation["location_ref"] = "loc_gyou"
    formation["command_authority"] = "char_tang_wei"
    planner.put(formation_path, formation)
    operation_ref = "operation_test_qin_granted_house_seat"
    operation_path = f"state/operations/{operation_ref}.json"
    planner.put(operation_path, {
        "schema": "sword-operation", "owner_id": operation_ref, "operation_ref": operation_ref,
        "status": "occupied", "location_ref": "loc_gyou", "formation_refs": [formation_ref],
        "administrative_authority": "state_qin", "administrative_authorities": ["state_qin"],
        "territorial_grants": ["house_tang"], "objective": "occupy Gyou under a Qin grant to House Tang",
        "created_at": str(planner._world_time()),
    })
    index = copy.deepcopy(planner.read("state/operations/index.json")); index.setdefault("operations", {})[operation_ref] = operation_path; planner.put("state/operations/index.json", index); planner._register_owner(operation_ref, operation_path)
    meta = planner.read("state/meta.json")
    command = SimpleNamespace(command_type="house_action", digest="grantsovereignty", request_id="grant-sovereignty", actor_id="char_tang_wei", expected_revision=int(meta["revision"]), submitted_at=str(meta["time"]))
    result = planner._proclaim_house_territorial_authority(command, {"house_ref": "house_tang", "action": "proclaim_territorial_authority", "location_ref": "loc_gyou", "operation_ref": operation_ref, "polity_name": "Tang Granted Authority"})
    assert result["polity_ref"] == "polity_tang"
    polity = planner.read(planner.owner_path("polity_tang"))
    assert "force_state_qin" not in polity["military_force_refs"]
    assert "state_qin" not in polity.get("military_authority_refs", [])
    assert "force_house_tang" in polity["military_force_refs"]


def test_polity_garrison_does_not_count_state_force_from_personal_command_authority(campaign):
    planner = planner_for(campaign); planner._reset()
    formation_ref = "formation_qin_wei_unit_01"
    formation_path = planner.owner_path(formation_ref)
    formation = copy.deepcopy(planner.read(formation_path))
    formation["location_ref"] = "loc_gyou"
    formation["command_authority"] = "house_tang"
    assert formation["administrative_owner"] == "state_qin"
    assert formation["owner_force_ref"] == "force_state_qin"
    planner.put(formation_path, formation)
    polity = {
        "schema": "sword-polity", "owner_id": "polity_tang", "polity_ref": "polity_tang",
        "sovereign_house_ref": "house_tang", "status": "proto_state", "recognition_status": "unrecognized",
        "treasury_ref": "treasury_house_tang", "military_force_refs": ["force_house_tang"],
        "military_authority_refs": ["house_tang"], "occupied_site_refs": ["loc_gyou"],
    }
    assert planner._polity_garrison_strength(polity, "loc_gyou") == 0


def test_recognized_polity_materializes_exact_institutions_with_polity_funding_and_routes(campaign):
    from sword_runtime.civil_world import sync_polity_routes
    planner = planner_for(campaign); planner._reset()
    at = str(planner.read("state/runtime.json")["world_time"])
    house_path = planner.owner_path("house_tang"); house = copy.deepcopy(planner.read(house_path)); house["sovereignty_ref"] = "polity_tang"; planner.put(house_path, house)
    polity_path = "state/politics/polities/polity_tang.json"
    polity = {
        "schema": "sword-polity", "owner_id": "polity_tang", "polity_ref": "polity_tang", "name": "Tang State",
        "sovereign_house_ref": "house_tang", "status": "recognized_state", "recognition_status": "recognized",
        "recognized_by": ["state_qin", "state_wei"], "treasury_ref": "treasury_house_tang",
        "military_force_refs": ["force_house_tang"], "military_authority_refs": ["house_tang"],
        "occupied_site_refs": ["loc_gyou"], "seat_claim_ref": "loc_gyou", "administrative_capacity": 40,
        "known_threats": {},
    }
    planner.put(polity_path, polity); planner._register_owner("polity_tang", polity_path)
    polity = copy.deepcopy(planner.read(polity_path)); refs = planner._ensure_polity_institutions("polity_tang", polity, at); planner.put(polity_path, polity)
    assert set(refs) == {"regional_administration", "military_bureau", "recruitment_office", "granary_depot_office", "fortification_bureau", "horse_administration"}
    for kind, ref in refs.items():
        inst = planner.read(planner.owner_path(ref))
        assert inst["state"] == "polity_tang"
        assert inst["sovereign_polity_ref"] == "polity_tang"
        assert inst["kind"] == kind
        assert inst["location_ref"] == "loc_gyou"
    funding_path, _funding, physical_state = planner._project_funding_source(planner.read(planner.owner_path(refs["regional_administration"])))
    assert funding_path == planner.owner_path("treasury_house_tang")
    assert physical_state == "zhao"
    runtime = copy.deepcopy(planner.read("state/runtime.json")); sync_polity_routes(planner, runtime); planner.put("state/runtime.json", runtime)
    institution_hosts = [h for h in runtime["hosts"].values() if isinstance(h, dict) and h.get("dynamic_polity_institution_route") is True]
    assert len(institution_hosts) == 6
    regional_host = next(h for h in institution_hosts if h.get("owner_ref") == refs["regional_administration"])
    planner._autonomy_institution(regional_host, 1, at)
    regional = planner.read(planner.owner_path(refs["regional_administration"]))
    review = regional["administration_review"]
    assert review["governed_site_count"] == 0
    assert review["governed_sites"] == []
    assert "rule" not in review


def test_local_population_ledger_conserves_regional_bodies_and_blocks_native_recruitment_from_lost_site(campaign):
    planner = planner_for(campaign); planner._reset()
    at = _test_time(planner)
    pop_path = "state/population/zhao.json"
    _path, pop = planner._ensure_local_population_ledger("zhao", copy.deepcopy(planner.read(pop_path)))
    sites = pop["local_population"]["sites"]
    assert sum(planner._local_origin_living(row) for row in sites.values()) == int(pop["population_total"])

    # Make Gyou the only locally agricultural Zhao source while leaving the global
    # agricultural stratum untouched.  Once Qin controls Gyou, Zhao must not be able
    # to recruit those anonymous statewide bodies through another site.
    for row in sites.values():
        row.setdefault("civilian_strata", {})["agricultural"] = 0
        planner._sync_local_population_row(row)
    gyou_available = min(500, int(sites["loc_gyou"]["civilian_population"]))
    assert gyou_available > 0
    sites["loc_gyou"].setdefault("civilian_strata", {})["agricultural"] = gyou_available
    planner._sync_local_population_row(sites["loc_gyou"])
    planner.put(pop_path, pop)

    territory = copy.deepcopy(planner.read("state/territory/control.json"))
    territory["sites"]["loc_gyou"]["controller"] = "state_qin"
    planner.put("state/territory/control.json", territory)

    force_path = "state/forces/state-zhao.json"
    force = copy.deepcopy(planner.read(force_path))
    force["authorized_strength"] = int(force["headcount"]) + 100
    planner.put(force_path, force)
    state_path = "state/states/zhao.json"
    state = copy.deepcopy(planner.read(state_path)); state["treasury_silver"] = max(100_000, int(state.get("treasury_silver", 0))); planner.put(state_path, state)

    global_ag_before = int(planner.read(pop_path)["strata"]["agricultural"])
    head_before = int(force["headcount"])
    planner._autonomy_state(_state_host(planner, "zhao"), 1, at)

    assert int(planner.read(force_path)["headcount"]) == head_before
    assert int(planner.read(pop_path)["strata"]["agricultural"]) == global_ag_before
    after = planner.read(pop_path)
    assert int(after["local_population"]["sites"]["loc_gyou"]["agricultural_available"]) == gyou_available


def test_local_population_service_transfers_share_one_site_capacity(campaign):
    planner = planner_for(campaign); planner._reset()
    pop_path = "state/population/zhao.json"
    _path, pop = planner._ensure_local_population_ledger("zhao", copy.deepcopy(planner.read(pop_path)))
    row = pop["local_population"]["sites"]["loc_gyou"]
    row["civilian_strata"] = {key: 0 for key in row.get("civilian_strata", {})}
    row["civilian_strata"]["agricultural"] = 15
    row["service_allocations"] = {}
    row["candidate_reservations"] = {}
    planner._sync_local_population_row(row)

    foreign = planner._consume_local_recruitment(pop, "zhao", "loc_gyou", 10, service_key="serving_foreign_military")
    rebels = planner._consume_local_recruitment(pop, "zhao", "loc_gyou", 10, service_key="rebel_military")
    assert foreign == 10
    assert rebels == 5
    row = pop["local_population"]["sites"]["loc_gyou"]
    assert row["civilian_population"] == 0
    assert row["agricultural_available"] == 0
    assert row["serving_foreign_military"] == 10
    assert row["rebel_military"] == 5


def test_occupation_recruitment_updates_exact_local_origin_ledger(campaign):
    planner = planner_for(campaign); planner._reset()
    at = _test_time(planner)
    planner._occupation_initialize("loc_gyou", "state_qin", "state_zhao", at, "test_capture")
    territory = copy.deepcopy(planner.read("state/territory/control.json"))
    territory["sites"]["loc_gyou"]["controller"] = "state_qin"
    territory["sites"]["loc_gyou"]["governance"].update({
        "status": "integrating", "administration": 95, "elite_cooperation": 95,
        "civilian_loyalty": 95, "resistance": 0, "tax_compliance": 0,
        "recruitment_access": 100,
    })
    planner.put("state/territory/control.json", territory)

    zhao_path = "state/population/zhao.json"
    _lp, zhao = planner._ensure_local_population_ledger("zhao", copy.deepcopy(planner.read(zhao_path)))
    planner.put(zhao_path, zhao)
    before = copy.deepcopy(zhao["local_population"]["sites"]["loc_gyou"])

    qin_force_path = "state/forces/state-qin.json"
    qin_force = copy.deepcopy(planner.read(qin_force_path)); qin_force["authorized_strength"] = int(qin_force["headcount"]) + 500; planner.put(qin_force_path, qin_force)
    # Keep this assertion about occupied recruitment isolated from native Qin intake.
    qin_path = "state/population/qin.json"
    _qp, qin = planner._ensure_local_population_ledger("qin", copy.deepcopy(planner.read(qin_path)))
    for row in qin["local_population"]["sites"].values():
        row.setdefault("civilian_strata", {})["agricultural"] = 0
        planner._sync_local_population_row(row)
    planner.put(qin_path, qin)

    planner._autonomy_state(_state_host(planner, "qin"), 1, at)
    qin_state = planner.read("state/states/qin.json")
    recruited = int(qin_state["civil_finance"]["occupied_recruits"])
    assert recruited > 0
    after = planner.read(zhao_path)["local_population"]["sites"]["loc_gyou"]
    assert int(before["civilian_population"]) - int(after["civilian_population"]) == recruited
    assert int(before["agricultural_available"]) - int(after["agricultural_available"]) == recruited
    assert int(after["serving_foreign_military"]) - int(before["serving_foreign_military"]) == recruited
    assert planner._local_origin_living(after) == planner._local_origin_living(before)


def test_local_population_loss_reduces_site_tax_and_garrison_scale(campaign):
    planner = planner_for(campaign); planner._reset()
    at = _test_time(planner)
    planner._occupation_initialize("loc_gyou", "state_qin", "state_zhao", at, "test_capture")
    territory = copy.deepcopy(planner.read("state/territory/control.json"))
    territory["sites"]["loc_gyou"]["controller"] = "state_qin"
    territory["sites"]["loc_gyou"]["governance"].update({"tax_compliance": 100, "resistance": 0})
    planner.put("state/territory/control.json", territory)

    pop_path = "state/population/zhao.json"
    _path, pop = planner._ensure_local_population_ledger("zhao", copy.deepcopy(planner.read(pop_path)))
    planner.put(pop_path, pop)
    planner._settle_private_production("zhao", 1, at)
    before_due = next(row for row in planner._territorial_revenue_plan("qin", 1) if row["location_ref"] == "loc_gyou")["due_silver"]
    _native, before_garrison_population = planner._occupation_population_estimate("loc_gyou")

    pop = copy.deepcopy(planner.read(pop_path)); row = pop["local_population"]["sites"]["loc_gyou"]
    remove = max(1, int(row["civilian_population"]) // 2)
    remaining = remove
    for key in ("dependents_children_elderly", "household_and_service", "agricultural", "craft_and_industry", "merchant_and_transport", "administration_and_education", "camp_medical_support"):
        have = max(0, int(row.get("civilian_strata", {}).get(key, 0)))
        take = min(have, remaining)
        if take:
            row["civilian_strata"][key] = have - take
            pop["strata"][key] = max(0, int(pop["strata"].get(key, 0)) - take)
            remaining -= take
        if remaining <= 0:
            break
    assert remaining == 0
    row["deaths_cumulative"] = int(row.get("deaths_cumulative", 0)) + remove
    planner._sync_local_population_row(row)
    pop["population_total"] -= remove
    planner.put(pop_path, pop)
    planner._settle_private_production("zhao", 1, str(CampaignTime.parse(at).add_days(30)))

    after_due = next(row for row in planner._territorial_revenue_plan("qin", 1) if row["location_ref"] == "loc_gyou")["due_silver"]
    _native, after_garrison_population = planner._occupation_population_estimate("loc_gyou")
    assert after_due < before_due
    assert after_garrison_population < before_garrison_population


def test_adjacent_sovereigns_do_not_drift_into_war_from_elapsed_pressure_alone(campaign):
    planner = planner_for(campaign); planner._reset()
    path = planner.owner_path("interstate_warring_states")
    world = copy.deepcopy(planner.read(path))
    theater = world["theaters"]["qin_zhao_gyou"]
    theater.update({"phase": "peace", "pressure": 99, "cooldown_reviews": 0, "history": []})
    planner.put(path, world)
    host = copy.deepcopy(planner.read("state/runtime.json")["hosts"]["host_interstate_wars"])
    at = CampaignTime.parse(str(host["next_due"]))
    # Many peace reviews cannot manufacture willingness or a casus belli.
    for _ in range(12):
        host["next_due"] = str(at)
        planner._autonomy_interstate(host, 1, str(at))
        at = at.add_seconds(int(host["recurrence_seconds"]))
    after = planner.read(path)["theaters"]["qin_zhao_gyou"]
    assert after["phase"] == "peace"
    assert int(after.get("cycle", 0)) == 0
    assert after["last_peace_review"]["authorized"] is False
    assert planner.read("state/states/qin.json").get("diplomacy", {}).get("zhao", {}).get("status") != "war"


def test_explicit_war_intent_authorizes_interstate_theater_without_pressure_countdown(campaign):
    planner = planner_for(campaign); planner._reset()
    qin_path = "state/states/qin.json"
    qin = copy.deepcopy(planner.read(qin_path))
    qin["mobilization_readiness"] = 70
    qin.setdefault("war_intents", []).append({
        "intent_ref": "war_intent_qin_gyou_test", "status": "authorized",
        "target_ref": "state_zhao", "location_ref": "loc_gyou",
        "kind": "territorial_control", "objective": "compel a settlement over Gyou",
    })
    planner.put(qin_path, qin)
    path = planner.owner_path("interstate_warring_states")
    world = copy.deepcopy(planner.read(path)); world["theaters"]["qin_zhao_gyou"].update({"phase": "peace", "pressure": 0, "cooldown_reviews": 0, "history": []}); planner.put(path, world)
    host = copy.deepcopy(planner.read("state/runtime.json")["hosts"]["host_interstate_wars"]); at = str(host["next_due"])
    planner._autonomy_interstate(host, 1, at)
    record = planner.read(path)["theaters"]["qin_zhao_gyou"]
    assert record["phase"] == "mobilizing"
    assert record["casus_belli"]["kind"] == "authorized_war_intent"
    assert record["casus_belli"]["intent_ref"] == "war_intent_qin_gyou_test"
    qin_after = planner.read(qin_path)
    intent = next(row for row in qin_after["war_intents"] if row["intent_ref"] == "war_intent_qin_gyou_test")
    assert intent["status"] == "activated"


def test_autonomous_counterinsurgency_settles_real_contact_and_conserved_losses(campaign):
    planner = planner_for(campaign); planner._reset(); at = _test_time(planner)
    planner._occupation_initialize("loc_gyou", "state_qin", "state_zhao", at, "counterinsurgency_capture")
    territory = copy.deepcopy(planner.read("state/territory/control.json")); territory["sites"]["loc_gyou"]["controller"] = "state_qin"; gov = territory["sites"]["loc_gyou"]["governance"]; gov.update({"resistance": 98, "food_security": 20, "elite_cooperation": 5}); planner.put("state/territory/control.json", territory)
    state = copy.deepcopy(planner.read("state/states/qin.json")); state["treasury_silver"] = 0; planner.put("state/states/qin.json", state)
    planner._settle_occupation_administration("qin", 1, at)
    revolt = planner.read("state/territory/control.json")["sites"]["loc_gyou"]["governance"]["revolt"]
    faction_ref = revolt["faction_ref"]; rebel_ref = revolt["formation_refs"][0]
    _free_qin_mobile_reserve_for_state_response(planner)
    planner._autonomy_state(_state_host(planner, "qin"), 1, at)
    index = planner.read("state/operations/index.json")["operations"]
    response_ref = next(ref for ref in index if ref.startswith("operation_auto_qin_") and "occupation_revolt:loc_gyou" in planner.read(index[ref]).get("objective_refs", []))
    response = planner.read(index[response_ref]); government_ref = response["formation_refs"][0]
    gp, government = planner._load_formation(government_ref); government = copy.deepcopy(government)
    old_loc = str(government.get("location_ref", "")); government["location_ref"] = "loc_gyou"; government["mobilized"] = True; government["status"] = "deployed"; government.setdefault("logistics", {})["food_kg"] = max(100000, int(government["logistics"].get("food_kg", 0))); planner.put(gp, government); planner._index_formation_location(government_ref, old_loc, "loc_gyou")
    rebel_before = int(planner.read(planner.owner_path(revolt["force_ref"]))["headcount"])
    gov_before = int(government["personnel"])
    planner._autonomy_faction({"owner_ref": faction_ref}, 1, at)
    rebel_after = int(planner.read(planner.owner_path(revolt["force_ref"]))["headcount"])
    gov_after = int(planner.read(gp)["personnel"])
    faction = planner.read(planner.owner_path(faction_ref))
    assert faction["counterinsurgency_history"][-1]["status"] in {"battle_settled", "revolt_contained"}
    assert rebel_after < rebel_before or gov_after < gov_before
    recent = planner.read("state/history/events/index.json").get("events", [])
    assert any(row.get("kind") == "counterinsurgency_battle" for row in recent)


def test_player_commanded_counterinsurgency_force_is_never_auto_fought(campaign):
    planner = planner_for(campaign); planner._reset(); at = _test_time(planner)
    planner._occupation_initialize("loc_gyou", "state_qin", "state_zhao", at, "player_counterinsurgency_capture")
    territory = copy.deepcopy(planner.read("state/territory/control.json")); territory["sites"]["loc_gyou"]["controller"] = "state_qin"; gov = territory["sites"]["loc_gyou"]["governance"]; gov.update({"resistance": 98, "food_security": 20, "elite_cooperation": 5}); planner.put("state/territory/control.json", territory)
    state = copy.deepcopy(planner.read("state/states/qin.json")); state["treasury_silver"] = 0; planner.put("state/states/qin.json", state)
    planner._settle_occupation_administration("qin", 1, at); revolt = planner.read("state/territory/control.json")["sites"]["loc_gyou"]["governance"]["revolt"]; faction_ref = revolt["faction_ref"]
    _free_qin_mobile_reserve_for_state_response(planner)
    planner._autonomy_state(_state_host(planner, "qin"), 1, at)
    index = planner.read("state/operations/index.json")["operations"]; response_ref = next(ref for ref in index if ref.startswith("operation_auto_qin_") and "occupation_revolt:loc_gyou" in planner.read(index[ref]).get("objective_refs", [])); response = copy.deepcopy(planner.read(index[response_ref])); government_ref = response["formation_refs"][0]
    gp, government = planner._load_formation(government_ref); government = copy.deepcopy(government); government["command_authority"] = planner.PLAYER_ACTOR; before = int(government["personnel"]); planner.put(gp, government)
    planner._autonomy_faction({"owner_ref": faction_ref}, 1, at)
    assert int(planner.read(gp)["personnel"]) == before
    response_after = planner.read(index[response_ref])
    assert response_after["player_decision_required"]["formation_ref"] == government_ref


def _commit_test_planner_writes(campaign, planner, message):
    import json, subprocess
    for rel, value in planner._writes.items():
        path = campaign / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    for rel in planner._deletes:
        path = campaign / rel
        if path.exists():
            path.unlink()
    subprocess.run(["git", "-C", str(campaign), "add", "state"], check=True)
    staged = subprocess.run(["git", "-C", str(campaign), "diff", "--cached", "--quiet"])
    if staged.returncode != 0:
        subprocess.run(["git", "-C", str(campaign), "commit", "--quiet", "-m", message], check=True)


def _install_test_tang_polity(campaign):
    import json
    polity_ref = "polity_tang"
    polity_path = campaign / "state/politics/polities/polity_tang.json"
    polity_path.parent.mkdir(parents=True, exist_ok=True)
    polity = {
        "schema": "sword-polity", "owner_id": polity_ref, "polity_ref": polity_ref,
        "name": "Tang State", "sovereign_house_ref": "house_tang", "status": "recognized_state",
        "recognition_status": "recognized", "recognized_by": ["state_qin", "state_wei"],
        "treasury_ref": "treasury_house_tang", "military_force_refs": ["force_house_tang"],
        "military_authority_refs": ["house_tang"], "occupied_site_refs": ["loc_gyou"],
        "seat_claim_ref": "loc_gyou", "administrative_capacity": 80, "known_threats": {}, "diplomacy": {},
    }
    polity_path.write_text(json.dumps(polity, indent=2) + "\n")
    idx_path = campaign / "state/index/owner-index.json"; idx = json.loads(idx_path.read_text()); idx["owners"][polity_ref] = "state/politics/polities/polity_tang.json"; idx_path.write_text(json.dumps(idx, indent=2) + "\n")
    house_path = campaign / idx["owners"]["house_tang"]; house = json.loads(house_path.read_text()); house["sovereignty_ref"] = polity_ref; house_path.write_text(json.dumps(house, indent=2) + "\n")
    terr_path = campaign / "state/territory/control.json"; terr = json.loads(terr_path.read_text()); terr["sites"]["loc_gyou"]["controller"] = polity_ref; terr["sites"]["loc_gyou"]["governance"] = {"status":"integrating","administration":80,"elite_cooperation":75,"civilian_loyalty":60,"resistance":20,"tax_compliance":60,"recruitment_access":40,"food_security":80}; terr_path.write_text(json.dumps(terr, indent=2) + "\n")
    import subprocess
    subprocess.run(["git", "-C", str(campaign), "add", "state"], check=True)
    subprocess.run(["git", "-C", str(campaign), "commit", "--quiet", "-m", "test fixture sovereign polity"], check=True)
    return polity_ref


def test_polity_action_is_first_class_sovereign_command_and_authorizes_war_intent(campaign):
    polity_ref = _install_test_tang_polity(campaign)
    result = execute_production(campaign, "polity_action", {"polity_ref": polity_ref, "action": "authorize_war", "target_ref": "state_zhao", "location_ref": "loc_gyou", "war_goal": "secure Tang sovereignty around Gyou"}, request_id="polity-war-intent").receipt.result
    assert result["action"] == "authorize_war"
    planner = planner_for(campaign); polity = planner.read(planner.owner_path(polity_ref)); intent = polity["war_intents"][-1]
    assert intent["status"] == "authorized" and intent["target_ref"] == "state_zhao"
    assert intent["authorized_by"] == planner.PLAYER_ACTOR


def test_polity_action_security_policy_requires_current_territorial_control(campaign):
    polity_ref = _install_test_tang_polity(campaign)
    execute_production(campaign, "polity_action", {"polity_ref": polity_ref, "action": "set_occupation_policy", "location_ref": "loc_gyou", "policy_key": "security_posture", "policy_value": "measured garrison and patrol posture"}, request_id="polity-occupation-policy")
    planner = planner_for(campaign); policy = planner.read("state/territory/control.json")["sites"]["loc_gyou"]["governance"]["occupation_policy"]["security_posture"]
    assert policy["set_by"] == planner.PLAYER_ACTOR


def test_diplomatic_proposal_arrives_then_target_sovereign_decides_and_activates_treaty(campaign):
    polity_ref = _install_test_tang_polity(campaign)
    result = execute_production(campaign, "polity_action", {"polity_ref": polity_ref, "action": "propose_treaty", "target_ref": "state_qin", "treaty_kind": "nonaggression", "direction": "mutual", "duration_days": 720}, request_id="polity-nag-proposal").receipt.result
    planner = planner_for(campaign); proposal_ref = result["proposal_ref"]; proposal = planner.read(planner.owner_path(proposal_ref)); assert proposal["status"] == "in_transit"
    target_path = planner.owner_path("state_qin"); target = copy.deepcopy(planner.read(target_path)); after_arrival = str(CampaignTime.parse(proposal["arrives_at"]).add_seconds(3600))
    planner._settle_diplomatic_routes("state_qin", target, after_arrival)
    proposal = planner.read(planner.owner_path(proposal_ref)); assert proposal["status"] == "accepted"
    treaty = planner.read("state/politics/treaties.json")["records"][proposal["treaty_ref"]]
    assert treaty["kind"] == "nonaggression" and treaty["terms"]["nonaggression_until"]
    assert {polity_ref, "state_qin"} == set(treaty["parties"])


def test_exact_treaty_registry_prevents_duplicate_standing_agreements_when_summary_status_changes(campaign):
    planner = planner_for(campaign); planner._reset(); at = _test_time(planner)
    alliance_ref = planner._activate_diplomatic_treaty({
        "proposal_ref": "diplomatic_proposal_qin_wei_alliance_registry_test",
        "proposer_ref": "state_qin", "target_ref": "state_wei",
        "kind": "alliance", "direction": "mutual", "terms": {"duration_days": 720},
    }, at)
    access_ref = planner._activate_diplomatic_treaty({
        "proposal_ref": "diplomatic_proposal_wei_qin_access_registry_test",
        "proposer_ref": "state_wei", "target_ref": "state_qin",
        "kind": "military_access", "direction": "proposer_to_target", "terms": {"duration_days": 365},
    }, str(CampaignTime.parse(at).add_days(1)))
    # The convenience bilateral status now describes the most recent agreement,
    # but the alliance remains an exact active treaty and must not be forgotten.
    assert planner.read("state/states/qin.json")["diplomacy"]["state_wei"]["status"] == "access_agreement"
    pair = planner._active_treaties_between("state_qin", "state_wei", str(CampaignTime.parse(at).add_days(2)))
    assert {row["kind"] for row in pair} == {"alliance", "military_access"}

    renewed_ref = planner._activate_diplomatic_treaty({
        "proposal_ref": "diplomatic_proposal_qin_wei_duplicate_alliance_registry_test",
        "proposer_ref": "state_qin", "target_ref": "state_wei",
        "kind": "alliance", "direction": "mutual", "terms": {"duration_days": 1080},
    }, str(CampaignTime.parse(at).add_days(30)))
    assert renewed_ref == alliance_ref
    treaties = planner.read("state/politics/treaties.json")["records"]
    assert access_ref in treaties
    assert sum(1 for row in treaties.values() if row.get("kind") == "alliance" and {"state_qin", "state_wei"}.issubset(set(row.get("parties", [])))) == 1
    assert treaties[alliance_ref]["renewal_count"] == 1
    assert CampaignTime.parse(treaties[alliance_ref]["terms"]["expires_at"]) > CampaignTime.parse(str(CampaignTime.parse(at).add_days(720)))


def test_autonomous_formal_diplomacy_uses_bounded_capacity_with_urgent_threat_shortening(campaign):
    planner = planner_for(campaign); planner._reset(); at = _test_time(planner)
    proposal = planner._create_diplomatic_proposal(
        "state_qin", "state_zhao", "nonaggression", "mutual", at,
        terms={"duration_days": 365},
        provenance={"kind": "npc_sovereign_initiative", "decision_score": 70},
    )
    proposal_path = planner.owner_path(proposal["proposal_ref"]); stored = copy.deepcopy(planner.read(proposal_path)); stored["status"] = "rejected"; planner.put(proposal_path, stored)
    qin = planner.read("state/states/qin.json")
    assert planner._autonomous_diplomatic_initiative_cooldown_seconds(qin, str(CampaignTime.parse(at).add_days(89)), threat_severity=0) > 0
    assert planner._autonomous_diplomatic_initiative_cooldown_seconds(qin, str(CampaignTime.parse(at).add_days(90)), threat_severity=0) == 0
    assert planner._autonomous_diplomatic_initiative_cooldown_seconds(qin, str(CampaignTime.parse(at).add_days(29)), threat_severity=65) > 0
    assert planner._autonomous_diplomatic_initiative_cooldown_seconds(qin, str(CampaignTime.parse(at).add_days(30)), threat_severity=65) == 0


def test_tribute_treaty_moves_conserved_silver_between_exact_sovereign_treasuries(campaign):
    polity_ref = _install_test_tang_polity(campaign)
    result = execute_production(campaign, "polity_action", {"polity_ref": polity_ref, "action": "propose_treaty", "target_ref": "state_qin", "treaty_kind": "tribute", "direction": "proposer_to_target", "duration_days": 365, "amount_silver": 100}, request_id="polity-tribute-proposal").receipt.result
    planner = planner_for(campaign); proposal = planner.read(planner.owner_path(result["proposal_ref"])); at = str(CampaignTime.parse(proposal["arrives_at"]).add_seconds(3600)); planner._settle_diplomatic_routes("state_qin", copy.deepcopy(planner.read(planner.owner_path("state_qin"))), at)
    proposal = planner.read(planner.owner_path(result["proposal_ref"])); assert proposal["status"] == "accepted"
    tang_treasury_path = planner.owner_path("treasury_house_tang"); tang_before = int(planner.read(tang_treasury_path)["silver"]); qin_before = int(planner.read("state/states/qin.json")["treasury_silver"])
    planner._settle_treaty_obligations(polity_ref, at, 1)
    assert int(planner.read(tang_treasury_path)["silver"]) == tang_before - 100
    assert int(planner.read("state/states/qin.json")["treasury_silver"]) == qin_before + 100


def test_recognized_polity_can_extend_sovereign_recognition_to_another_polity(campaign):
    polity_ref = _install_test_tang_polity(campaign)
    import json, subprocess
    target_ref = "polity_minor_test"
    target_path = campaign / "state/politics/polities/polity_minor_test.json"
    target = {
        "schema": "sword-polity", "owner_id": target_ref, "polity_ref": target_ref,
        "name": "Minor Test Polity", "sovereign_house_ref": "house_tang", "status": "proto_state",
        "recognition_status": "partially_recognized", "recognized_by": ["state_qin"],
        "treasury_ref": "treasury_house_tang", "military_force_refs": [], "military_authority_refs": ["house_tang"],
        "occupied_site_refs": ["loc_gyou"], "seat_claim_ref": "loc_gyou", "administrative_capacity": 30,
        "known_threats": {}, "diplomacy": {},
    }
    target_path.write_text(json.dumps(target, indent=2) + "\n")
    idx_path = campaign / "state/index/owner-index.json"; idx = json.loads(idx_path.read_text()); idx["owners"][target_ref] = "state/politics/polities/polity_minor_test.json"; idx_path.write_text(json.dumps(idx, indent=2) + "\n")
    subprocess.run(["git", "-C", str(campaign), "add", "state"], check=True)
    subprocess.run(["git", "-C", str(campaign), "commit", "--quiet", "-m", "test fixture recognition target"], check=True)
    result = execute_production(campaign, "polity_action", {"polity_ref": polity_ref, "action": "recognize_polity", "target_ref": target_ref}, request_id="polity-recognize-polity").receipt.result
    planner = planner_for(campaign); recognized = planner.read(planner.owner_path(target_ref))
    assert result["action"] == "recognize_polity"
    assert polity_ref in recognized["recognized_by"]
    assert recognized["recognition_status"] == "recognized"
    assert recognized["status"] == "recognized_state"


def test_defensive_alliance_creates_exact_third_party_war_obligation_when_ally_is_attacked(campaign):
    planner = planner_for(campaign); planner._reset()
    at = str(planner.read("state/runtime.json")["hosts"]["host_interstate_wars"]["next_due"])
    treaty_ref = planner._activate_diplomatic_treaty({
        "proposal_ref": "diplomatic_proposal_wei_zhao_alliance_test",
        "proposer_ref": "state_wei",
        "target_ref": "state_zhao",
        "kind": "alliance",
        "direction": "mutual",
        "terms": {"duration_days": 3650},
    }, at)
    qin_path = "state/states/qin.json"
    qin = copy.deepcopy(planner.read(qin_path)); qin["mobilization_readiness"] = 70
    qin.setdefault("war_intents", []).append({
        "intent_ref": "war_intent_qin_gyou_alliance_test", "status": "authorized",
        "target_ref": "state_zhao", "location_ref": "loc_gyou",
        "kind": "territorial_control", "objective": "attack Zhao at Gyou",
    })
    planner.put(qin_path, qin)
    world_path = planner.owner_path("interstate_warring_states")
    world = copy.deepcopy(planner.read(world_path)); world["theaters"]["qin_zhao_gyou"].update({"phase": "peace", "pressure": 0, "cooldown_reviews": 0, "history": []}); planner.put(world_path, world)
    host = copy.deepcopy(planner.read("state/runtime.json")["hosts"]["host_interstate_wars"])
    planner._autonomy_interstate(host, 1, at)
    wei = planner.read("state/states/wei.json")
    obligation = next(row for row in wei.get("war_intents", []) if row.get("treaty_ref") == treaty_ref and row.get("target_ref") == "state_qin")
    assert obligation["kind"] == "treaty_defense"
    assert obligation["status"] == "authorized"
    assert obligation["defended_sovereign_ref"] == "state_zhao"
    assert any(row.get("kind") == "treaty_defense_obligation" and row.get("treaty_ref") == treaty_ref for row in wei.get("known_threats", {}).values())
    treaty = planner.read("state/politics/treaties.json")["records"][treaty_ref]
    assert treaty["defense_invocations"][-1]["obligated_ref"] == "state_wei"


def test_military_access_treaty_is_consumed_by_exact_formation_transit_validation(campaign):
    planner = planner_for(campaign); planner._reset(); at = str(planner.read("state/runtime.json")["world_time"])
    formation = {"formation_ref": "formation_transit_test", "administrative_owner": "state_qin"}
    with pytest.raises(PermissionError, match="military access"):
        planner._validate_formation_transit(formation, "loc_gyou", at)
    treaty_ref = planner._activate_diplomatic_treaty({
        "proposal_ref": "diplomatic_proposal_zhao_qin_access_test",
        "proposer_ref": "state_zhao",
        "target_ref": "state_qin",
        "kind": "military_access",
        "direction": "proposer_to_target",
        "terms": {"duration_days": 365},
    }, at)
    planner._validate_formation_transit(formation, "loc_gyou", at)
    treaty = planner.read("state/politics/treaties.json")["records"][treaty_ref]
    assert treaty["terms"]["military_access_grantor_ref"] == "state_zhao"
    assert treaty["terms"]["military_access_beneficiary_ref"] == "state_qin"


def test_incoming_treaty_to_player_polity_waits_for_explicit_player_decision(campaign):
    polity_ref = _install_test_tang_polity(campaign)
    planner = planner_for(campaign); planner._reset(); now = CampaignTime.parse(str(planner.read("state/runtime.json")["world_time"])); arrived = str(now.add_seconds(-3600)); expires = str(now.add_seconds(30 * 86400))
    proposal_ref = "diplomatic_proposal_qin_tang_player_decision"
    proposal_path = f"state/politics/diplomatic-proposals/{proposal_ref}.json"
    proposal = {
        "schema": "sword-diplomatic-proposal", "owner_id": proposal_ref, "proposal_ref": proposal_ref,
        "proposer_ref": "state_qin", "target_ref": polity_ref, "kind": "nonaggression", "direction": "mutual",
        "status": "in_transit", "proposed_at": arrived, "arrives_at": arrived, "expires_at": expires,
        "terms": {"duration_days": 365}, "provenance": {"kind": "test_incoming_sovereign_proposal"},
    }
    planner.put(proposal_path, proposal); planner._register_owner(proposal_ref, proposal_path)
    polity_path = planner.owner_path(polity_ref); polity = copy.deepcopy(planner.read(polity_path)); polity.setdefault("diplomatic_route_refs", []).append(proposal_ref); planner.put(polity_path, polity)
    _commit_test_planner_writes(campaign, planner, "test incoming treaty")
    planner = planner_for(campaign); planner._reset(); planner._settle_diplomatic_routes(polity_ref, copy.deepcopy(planner.read(planner.owner_path(polity_ref))), str(now))
    pending = planner.read(planner.owner_path(proposal_ref)); assert pending["status"] == "pending_response"; assert pending["response_basis"]["kind"] == "pending_player_sovereign_decision"
    assert proposal_ref in planner.read(planner.owner_path(polity_ref))["diplomatic_route_refs"]
    _commit_test_planner_writes(campaign, planner, "test treaty arrived")
    result = execute_production(campaign, "polity_action", {"polity_ref": polity_ref, "action": "accept_treaty", "proposal_ref": proposal_ref}, request_id="polity-accept-incoming-treaty").receipt.result
    assert result["proposal_status"] == "accepted" and result["treaty_ref"].startswith("treaty_")
    planner = planner_for(campaign); accepted = planner.read(planner.owner_path(proposal_ref)); assert accepted["response_basis"]["kind"] == "player_sovereign_decision"
    assert proposal_ref not in planner.read(planner.owner_path(polity_ref)).get("diplomatic_route_refs", [])


def test_break_treaty_persists_hostile_bilateral_diplomacy_for_player_polity(campaign):
    polity_ref = _install_test_tang_polity(campaign)
    planner = planner_for(campaign); planner._reset(); at = str(planner.read("state/runtime.json")["world_time"])
    treaty_ref = planner._activate_diplomatic_treaty({
        "proposal_ref": "diplomatic_proposal_tang_qin_break_test", "proposer_ref": polity_ref, "target_ref": "state_qin",
        "kind": "nonaggression", "direction": "mutual", "terms": {"duration_days": 365},
    }, at)
    _commit_test_planner_writes(campaign, planner, "test treaty before break")
    execute_production(campaign, "polity_action", {"polity_ref": polity_ref, "action": "break_treaty", "treaty_ref": treaty_ref}, request_id="polity-break-treaty").receipt.result
    planner = planner_for(campaign)
    tang = planner.read(planner.owner_path(polity_ref)); qin = planner.read("state/states/qin.json")
    assert tang["diplomacy"]["state_qin"]["status"] == "hostile"
    assert qin["diplomacy"][polity_ref]["status"] == "hostile"
    assert planner.read("state/politics/treaties.json")["records"][treaty_ref]["status"] == "broken"
