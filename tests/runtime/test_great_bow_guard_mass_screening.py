from __future__ import annotations

import copy

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


def test_mass_screening_host_precedes_residential_lifecycle(campaign) -> None:
    planner = _planner(campaign)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    now = str(runtime["world_time"])
    sync_great_bow_guard_flow(planner, runtime)
    planner._sync_great_bow_guard_mass_screening(runtime)

    mass_events = [
        row for row in runtime["events"]
        if row.get("kind") == "house_gbg_mass_screening"
    ]
    lifecycle_events = [
        row for row in runtime["events"]
        if row.get("kind") == "house_gbg_lifecycle"
    ]
    assert len(mass_events) == 1
    assert len(lifecycle_events) == 1
    assert mass_events[0]["due_at"] == now
    assert lifecycle_events[0]["due_at"] == now
    assert int(mass_events[0]["priority"]) < int(lifecycle_events[0]["priority"])


def test_mass_screening_examines_120000_records_without_reserving_120000_bodies(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    campaign_ref = _campaign_ref(planner)
    before_pop = copy.deepcopy(planner.read("state/population/qin.json"))
    before_reserved = int(before_pop["strata"]["recruitment_candidates_reserved"])
    before_treasury = int(planner.read("state/treasury/treasury-house-tang.json")["silver"])

    wake = planner._great_bow_guard_mass_screening(
        {"kind": "house_gbg_mass_screening", "campaign_ref": campaign_ref},
        at,
    )
    assert wake is not None

    registry = planner.read(REGISTRY_PATH)
    row = registry["campaigns"][campaign_ref]
    assert row["status"] == "screening"
    assert row["mass_screening_complete"] is True
    assert row["regional_application_count"] == 120000
    assert row["regional_application_records_nonresident"] == 118800
    assert row["regional_shortlist_count"] == 1200
    assert row["remaining_candidates"] == 1200
    assert row["stage_history"][-1]["kind"] == "regional_mass_screening"
    assert row["stage_history"][-1]["before"] == 120000
    assert row["stage_history"][-1]["after"] == 1200
    assert row["stage_history"][-1]["application_records_only"] is True

    after_pop = planner.read("state/population/qin.json")
    assert int(after_pop["strata"]["recruitment_candidates_reserved"]) == before_reserved
    assert after_pop["strata"] == before_pop["strata"]

    house = planner.read("state/houses/house_tang.json")
    program = house["administrative_programs"]["great_bow_guard"]
    assert program["applicants_registered"] == 120000
    assert program["regional_applicants_screened"] == 120000
    assert program["regional_screening_rejected"] == 118800
    assert program["residential_trial_candidates"] == 1200
    assert program["recruitment_phase"] == "residential_archery_trials"

    after_treasury = int(planner.read("state/treasury/treasury-house-tang.json")["silver"])
    mass_costs = [
        int(item.get("silver", 0))
        for item in row["economic_history"]
        if item.get("kind") in {"regional_application_contact", "regional_candidate_screening"}
    ]
    assert before_treasury - after_treasury == sum(mass_costs)
    assert sum(mass_costs) > 0


def test_completed_mass_host_is_retained_while_its_player_wake_is_pending(campaign) -> None:
    planner = _planner(campaign)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    campaign_ref = _campaign_ref(planner)
    planner._sync_great_bow_guard_mass_screening(runtime)
    host_id, event_id = planner._gbg_mass_ids(campaign_ref)
    assert host_id in runtime["hosts"]
    assert any(row.get("event_id") == event_id for row in runtime["events"])

    planner._great_bow_guard_mass_screening(
        {"kind": "house_gbg_mass_screening", "campaign_ref": campaign_ref},
        str(runtime["world_time"]),
    )
    runtime["pending_wake"] = {
        "wake_ref": "wake.test.mass",
        "kind": "campaign_event",
        "target_host": host_id,
        "event_id": event_id,
    }
    planner._sync_great_bow_guard_mass_screening(runtime)
    assert host_id in runtime["hosts"]
    assert any(row.get("event_id") == event_id for row in runtime["events"])


def test_mass_funnel_then_final_trial_selects_300_and_preserves_mass_history(campaign) -> None:
    planner = _planner(campaign)
    start = CampaignTime.parse(str(planner.read("state/runtime.json")["world_time"]))
    campaign_ref = _campaign_ref(planner)

    mass_wake = planner._great_bow_guard_mass_screening(
        {"kind": "house_gbg_mass_screening", "campaign_ref": campaign_ref},
        str(start),
    )
    assert mass_wake is not None
    final_trial_wake = settle_great_bow_guard_review(
        planner,
        {"kind": "house_gbg_lifecycle"},
        str(start),
    )
    assert final_trial_wake is not None

    registry = planner.read(REGISTRY_PATH)
    row = registry["campaigns"][campaign_ref]
    assert row["status"] == "training_candidate"
    assert row["remaining_candidates"] == 300
    assert row["mass_screening_complete"] is True
    assert row["regional_application_count"] == 120000
    assert any(item.get("kind") == "regional_mass_screening" for item in row["stage_history"])

    house = planner.read("state/houses/house_tang.json")
    program = house["administrative_programs"]["great_bow_guard"]
    assert program["applicants_registered"] == 120000
    assert program["regional_applicants_screened"] == 120000
    assert program["regional_screening_rejected"] == 118800
    assert program["rejected_candidates"] == 119700
    assert program["shortlisted_candidates"] == 300
    assert program["recruitment_phase"] == "candidate_training"

    final_wake = None
    for week in range(1, 5):
        final_wake = settle_great_bow_guard_review(
            planner,
            {"kind": "house_gbg_lifecycle"},
            str(start.add_seconds(week * 7 * 86400)),
        )
    assert final_wake is not None
    row = planner.read(REGISTRY_PATH)["campaigns"][campaign_ref]
    assert row["status"] == "accepted_equipment_pending"
    assert row["accepted_count"] == 300
    assert row["regional_application_count"] == 120000
