from __future__ import annotations

import copy

from sword_runtime.great_bow_guard_flow import settle_great_bow_guard_due_reviews
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


def _set_started_at(planner, campaign_ref: str, started_at: str) -> None:
    registry = copy.deepcopy(planner.read(REGISTRY_PATH))
    registry["campaigns"][campaign_ref]["started_at"] = started_at
    planner.put(REGISTRY_PATH, registry)


def test_months_old_great_bow_guard_campaign_catches_up_earned_reviews(campaign) -> None:
    planner = _planner(campaign)
    now = CampaignTime.parse(str(planner.read("state/runtime.json")["world_time"]))
    campaign_ref = _campaign_ref(planner)
    _set_started_at(planner, campaign_ref, str(now.add_days(-42)))

    mass_wake = planner._great_bow_guard_mass_screening(
        {"kind": "house_gbg_mass_screening", "campaign_ref": campaign_ref},
        str(now),
    )
    assert mass_wake is not None
    food_before = int(planner.read("state/treasury/treasury-house-tang.json")["food_kg"])

    wake = settle_great_bow_guard_due_reviews(
        planner,
        {"kind": "house_gbg_lifecycle", "campaign_ref": campaign_ref},
        str(now),
    )
    assert wake is not None

    row = planner.read(REGISTRY_PATH)["campaigns"][campaign_ref]
    assert row["status"] == "accepted_equipment_pending"
    assert row["accepted_count"] == 300
    assert row["regional_application_count"] == 120000
    assert row["verified_training_hours_per_person"] == 224
    catchup = row["lifecycle_catchup_history"][-1]
    assert catchup["kind"] == "elapsed_review_catchup"
    assert catchup["eligible_reviews"] == 5
    assert catchup["completed_reviews_before"] == 0
    assert catchup["reviews_settled"] == 5

    food_after = int(planner.read("state/treasury/treasury-house-tang.json")["food_kg"])
    assert food_after < food_before


def test_new_great_bow_guard_campaign_does_not_receive_unearned_training(campaign) -> None:
    planner = _planner(campaign)
    now = CampaignTime.parse(str(planner.read("state/runtime.json")["world_time"]))
    campaign_ref = _campaign_ref(planner)
    _set_started_at(planner, campaign_ref, str(now))

    planner._great_bow_guard_mass_screening(
        {"kind": "house_gbg_mass_screening", "campaign_ref": campaign_ref},
        str(now),
    )
    settle_great_bow_guard_due_reviews(
        planner,
        {"kind": "house_gbg_lifecycle", "campaign_ref": campaign_ref},
        str(now),
    )

    row = planner.read(REGISTRY_PATH)["campaigns"][campaign_ref]
    assert row["status"] == "training_candidate"
    assert row["remaining_candidates"] == 300
    assert float(row.get("verified_training_hours_per_person", 0.0)) == 0.0
    assert not row.get("lifecycle_catchup_history")
