from __future__ import annotations

import copy

from sword_runtime.cohort_personnel import role_count
from sword_runtime.great_bow_guard_flow import settle_great_bow_guard_review, sync_great_bow_guard_flow
from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.recruitment_campaigns import REGISTRY_PATH
from sword_runtime.sim.calendar import CampaignTime


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    meta = copy.deepcopy(planner.read("state/meta.json"))
    planner.PLAYER_ACTOR = str(meta["player_id"])
    planner._reset()
    return planner


def _campaign_ref(planner) -> str:
    house = planner.read("state/houses/house_tang.json")
    return str(house["administrative_programs"]["great_bow_guard"]["candidate_campaign_ref"])


def test_existing_great_bow_guard_pool_gets_a_lifecycle_host(campaign) -> None:
    planner = _planner(campaign)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    now = str(runtime["world_time"])
    sync_great_bow_guard_flow(planner, runtime)
    host = runtime["hosts"]["host_house_great_bow_guard_lifecycle"]
    assert host["kind"] == "house_gbg_lifecycle"
    assert host["next_due"] == now
    assert host["campaign_ref"] == _campaign_ref(planner)


def test_great_bow_guard_screens_real_applicants_to_registered_establishment(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    campaign_ref = _campaign_ref(planner)
    before_pop = copy.deepcopy(planner.read("state/population/qin.json"))
    before_reserved = int(before_pop["strata"]["recruitment_candidates_reserved"])

    wake = settle_great_bow_guard_review(planner, {"kind": "house_gbg_lifecycle"}, at)
    assert wake is not None
    registry = planner.read(REGISTRY_PATH)
    row = registry["campaigns"][campaign_ref]
    assert row["status"] == "training_candidate"
    assert row["remaining_candidates"] == 300
    assert row["destination_force_ref"] == "force_house_tang"
    assert row["role"] == "great_bow_guard"

    house = planner.read("state/houses/house_tang.json")
    program = house["administrative_programs"]["great_bow_guard"]
    assert program["screened_candidates"] == 1200
    assert program["rejected_candidates"] == 900
    assert program["shortlisted_candidates"] == 300
    assert program["recruitment_phase"] == "candidate_training"

    after_pop = planner.read("state/population/qin.json")
    assert int(after_pop["strata"]["recruitment_candidates_reserved"]) == before_reserved - 900


def test_great_bow_guard_four_week_training_accepts_conserved_fighters_without_equipment_fiction(campaign) -> None:
    planner = _planner(campaign)
    start = CampaignTime.parse(str(planner.read("state/runtime.json")["world_time"]))
    campaign_ref = _campaign_ref(planner)
    settle_great_bow_guard_review(planner, {"kind": "house_gbg_lifecycle"}, str(start))

    before_private = int(planner.read("state/population/qin.json")["strata"]["private_household_military"])
    final_wake = None
    for week in range(1, 5):
        final_wake = settle_great_bow_guard_review(
            planner,
            {"kind": "house_gbg_lifecycle"},
            str(start.add_seconds(week * 7 * 86400)),
        )
    assert final_wake is not None

    registry = planner.read(REGISTRY_PATH)
    row = registry["campaigns"][campaign_ref]
    assert row["status"] == "accepted_equipment_pending"
    assert row["accepted_count"] == 300
    assert float(row["verified_training_hours_per_person"]) == 224.0

    house = planner.read("state/houses/house_tang.json")
    program = house["administrative_programs"]["great_bow_guard"]
    assert program["accepted_fighters"] == 300
    assert program["status"] == "forming"
    assert program["recruitment_phase"] == "equipment_and_formation_pending"
    assert float(program["verified_training_hours_per_candidate"]) == 224.0

    force = planner.read("state/forces/house-tang.json")
    assert role_count(force, "great_bow_guard") == 300
    assert force["authorized_by_role"]["great_bow_guard"] == 300
    assert force["available_equipment_units_by_role"]["great_bow_guard"] == 0
    assert "formation_tang_great_bow_guard_first" not in planner.read("state/index/owner-index.json").get("owners", {})

    pop = planner.read("state/population/qin.json")
    assert int(pop["strata"]["private_household_military"]) == before_private + 300
