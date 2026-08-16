from __future__ import annotations

import copy

from sword_runtime.causal_event_store import get_causal_event
from sword_runtime.cohort_personnel import role_count
from sword_runtime.great_bow_guard_personal_integrity import repair_great_bow_guard_personal_ownership
from sword_runtime.house_field_preparation_flow import settle_house_field_preparation
from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.qin_command_briefing_flow import settle_qin_command_briefing, sync_qin_command_briefings


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    meta = copy.deepcopy(planner.read("state/meta.json"))
    planner.PLAYER_ACTOR = str(meta["player_id"])
    planner._reset()
    return planner


def test_great_bow_guard_is_repaired_to_tang_wei_personal_force_with_training(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])

    assert role_count(planner.read("state/forces/house-tang.json"), "great_bow_guard") == 300
    assert role_count(planner.read("state/forces/tang-wei-personal.json"), "great_bow_guard") == 0

    result = repair_great_bow_guard_personal_ownership(planner, at=at)
    assert result is not None
    assert result["personnel"] == 300

    house_force = planner.read("state/forces/house-tang.json")
    personal_force = planner.read("state/forces/tang-wei-personal.json")
    assert role_count(house_force, "great_bow_guard") == 0
    assert role_count(personal_force, "great_bow_guard") == 300

    house = planner.read("state/houses/house_tang.json")
    program = house["administrative_programs"]["great_bow_guard"]
    assert program["force_ref"] == "force_tang_wei_personal"
    assert program["command_authority_ref"] == "char_tang_wei"
    assert program["administrative_sponsor_ref"] == "house_tang"

    registry = planner.read("state/recruitment/candidate-pools.json")
    campaign_ref = program["candidate_campaign_ref"]
    row = registry["campaigns"][campaign_ref]
    assert row["destination_force_ref"] == "force_tang_wei_personal"
    assert row["accepted_count"] == 300
    assert sum(int(item["personnel"]) for item in row["local_service_allocations"]) == 300
    assert {item["force_ref"] for item in row["local_service_allocations"]} == {"force_tang_wei_personal"}

    ledger = personal_force["cohort_ledger"]["cohorts"]
    accepted = [ledger[ref] for ref in row["cohort_refs"]]
    assert sum(
        sum(int(value) for value in cohort.get("reserve_by_location", {}).values())
        + sum(int(value) for value in cohort.get("allocated_by_formation", {}).values())
        for cohort in accepted
    ) == 300
    assert all(float(cohort["verified_training_hours_per_person"]) == 224.0 for cohort in accepted)
    assert all(len(cohort["training_history"]) == 4 for cohort in accepted)

    population = planner.read("state/population/qin.json")
    allocations = population["local_population"]["sites"]["loc_tang_manor_training_ground"]["service_allocations"]
    assert allocations["force_tang_wei_personal"]["personnel"] == 300
    assert "force_house_tang" not in allocations

    repair_great_bow_guard_personal_ownership(planner, at=at)
    assert role_count(planner.read("state/forces/tang-wei-personal.json"), "great_bow_guard") == 300
    assert role_count(planner.read("state/forces/house-tang.json"), "great_bow_guard") == 0


def test_existing_qin_briefing_request_gets_exact_pre_assumption_reply(campaign) -> None:
    planner = _planner(campaign)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    sync_qin_command_briefings(planner, runtime)

    hosts = [host for host in runtime["hosts"].values() if host.get("kind") == "qin_command_briefing_reply"]
    assert len(hosts) == 1
    host = hosts[0]
    assert host["formation_ref"] == "formation_qin_border_line"

    formation_before = copy.deepcopy(planner.read("state/formations/qin-border-line.json"))
    wake = settle_qin_command_briefing(planner, host, str(runtime["world_time"]))
    assert wake is not None
    assert "Strength: 8000" in wake["reason"]
    assert "line infantry 8000" in wake["reason"]
    assert "food 40000 kg" in wake["reason"]
    assert "fodder 0 kg" in wake["reason"]
    assert "war arrows 0" in wake["reason"]
    assert "no subordinate formation registry" in wake["reason"]

    formation_after = planner.read("state/formations/qin-border-line.json")
    assert formation_after["commander_ref"] == formation_before["commander_ref"] is None
    assert formation_after["command_authority"] == "state_qin"

    player = planner.read("state/player.json")
    appointment = next(row for row in player["career_state"]["appointments"] if row.get("formation_ref") == "formation_qin_border_line")
    assert appointment["status"] == "awaiting_assumption"
    assert appointment["command_structure_status"] == "subordinate_registry_absent_staffing_requested"
    assert appointment["staffing_request_status"] == "required_before_tactical_employment"
    assert appointment["briefed_logistics"] == {
        "food_kg": 40000,
        "fodder_kg": 0,
        "war_arrows": 0,
        "war_bolts": 0,
    }


def test_house_field_preparation_reports_exact_stock_and_keeps_kai_training_valid(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    repair_great_bow_guard_personal_ownership(planner, at=at)

    inventory_before = copy.deepcopy(planner.read("state/inv/inventories.json"))
    treasury_before = copy.deepcopy(planner.read("state/treasury/treasury-house-tang.json"))
    wake = settle_house_field_preparation(
        planner,
        {
            "response_event_ref": "event_test_house_field_preparation",
            "request_id": "test-house-field-preparation",
        },
        at,
    )
    assert wake is not None
    assert "Great Bow Guard" in wake["reason"]
    assert "Tang Armor 300" in wake["reason"]
    assert "Tang Helmets 300" in wake["reason"]
    assert "Tang Shields 300" in wake["reason"]
    assert "Great War Bows 300" in wake["reason"]
    assert "100 Tang heavy warhorses" in wake["reason"]
    assert "100 horse-armor sets" in wake["reason"]
    assert "food 45350528 kg" in wake["reason"]
    assert "fodder 17312000 kg" in wake["reason"]
    assert "does not contain a House-owned monthly Tang-armor manufacturing owner" in wake["reason"]

    kai = planner.read("state/char/tang-kai.json")
    assert kai["development_state"]["current_training_disposition"] == "tang_manor_age_appropriate_verified_training"
    assert any("No live weapons" in order for order in kai["goal_state"]["current_orders"])

    house = planner.read("state/houses/house_tang.json")
    prep = house["administrative_programs"]["wei_field_preparation"]
    assert prep["great_bow_guard_force_ref"] == "force_tang_wei_personal"
    assert prep["great_bow_guard_personnel"] == 300
    assert prep["champions_personnel"] == 100
    assert prep["equipment_issue_status"] == "not_yet_issued_or_reserved_by_this_report"
    assert prep["house_stock_snapshot"]["tang_armor_reserve"] == 300
    assert prep["house_stock_snapshot"]["tang_horse_armor_reserve"] == 100
    assert prep["house_stock_snapshot"]["war_arrows_strategic_reserve"] == 3549240
    assert prep["house_stock_snapshot"]["monthly_food_contract_kg"] == 600000
    assert prep["house_stock_snapshot"]["monthly_fodder_contract_kg"] == 100000

    assert planner.read("state/inv/inventories.json") == inventory_before
    assert planner.read("state/treasury/treasury-house-tang.json") == treasury_before
    assert get_causal_event(planner, "event_test_house_field_preparation") is not None
