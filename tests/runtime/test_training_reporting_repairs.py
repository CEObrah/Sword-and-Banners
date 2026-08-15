from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from sword_runtime.causal_event_store import read_causal_event_owner
from sword_runtime.development import age_years
from sword_runtime.household_request_flow import (
    _ensure_report_watch,
    _settle_recruitment_watch,
    _watch_ids,
)
from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.training_rates import verified_activity_hours_per_cycle


def test_house_tang_adult_cycle_uses_canonical_max_sustainable_rate(campaign):
    profiles = json.loads(
        (Path(campaign) / "game/data/mil/recruitment-cohort-profiles.json").read_text()
    )
    person = {
        "affiliation": "House Tang",
        "autonomous_activity_state": {"verified_hours_per_cycle": 48.0},
    }
    contract = {"mode": "standing_role_training"}

    hours = verified_activity_hours_per_cycle(
        person,
        contract,
        profiles,
        30 * 86400,
    )

    assert hours == 240.0


def test_child_household_contract_never_receives_adult_cycle_hours(campaign):
    profiles = json.loads(
        (Path(campaign) / "game/data/mil/recruitment-cohort-profiles.json").read_text()
    )
    kai = json.loads((Path(campaign) / "state/char/tang-kai.json").read_text())

    hours = verified_activity_hours_per_cycle(
        kai,
        kai["activity_contract"],
        profiles,
        30 * 86400,
    )

    assert hours == 0.0


def test_household_downtime_overrides_stale_48_hour_cache(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    start = CampaignTime.parse(str(planner.read("state/runtime.json")["world_time"]))
    end = start.add_hours(24)
    person_path, ling = planner._exact_person("char_tang_ling", active=False)
    ling = deepcopy(ling)
    activity = ling.setdefault("autonomous_activity_state", {})
    activity["cadence_seconds"] = 30 * 86400
    activity["verified_hours_per_cycle"] = 48.0
    activity["next_due"] = str(start.add_seconds(30 * 86400))
    activity.pop("interim_cycle_started_at", None)
    activity.pop("interim_verified_activity_hours", None)
    planner.put(person_path, ling)

    result = planner._accrue_household_person_activity(
        "char_tang_ling",
        start,
        end,
        "test-house-tang-max-sustainable",
    )
    _path, after = planner._exact_person("char_tang_ling", active=False)

    assert result["verified_activity_hours_in_current_cycle"] == 8.0
    assert after["autonomous_activity_state"]["verified_hours_per_cycle"] == 240.0


def test_named_person_activity_host_settles_house_tang_cycle_at_240_hours(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    start = CampaignTime.parse(str(planner.read("state/runtime.json")["world_time"]))
    due = start.add_seconds(30 * 86400)
    person_path, ling = planner._exact_person("char_tang_ling", active=False)
    ling = deepcopy(ling)
    ling["affiliation"] = "House Tang"
    ling.setdefault("activity_contract", {})["mode"] = "standing_role_training"
    ling["activity_contract"]["focus"] = "Governance"
    activity = ling.setdefault("autonomous_activity_state", {})
    activity["cadence_seconds"] = 30 * 86400
    activity["verified_hours_per_cycle"] = 48.0
    activity["next_due"] = str(due)
    activity["focus_cursor"] = 0
    planner.put(person_path, ling)

    planner._settle_activity_host(
        {"routed_person_refs": ["char_tang_ling"]},
        str(due),
    )
    _path, after = planner._exact_person("char_tang_ling", active=False)

    assert after["autonomous_activity_state"]["verified_hours_per_cycle"] == 240.0
    assert after["autonomous_development_history"][-1]["hours"] == 240.0
    assert after["autonomous_development_history"][-1]["verification_basis"] == "structured_causal_activity_cycle_v2"


def _clear_existing_recruitment_watch(planner: ProductionCampaignPlanner) -> tuple[dict, str, str]:
    house = deepcopy(planner.read("state/houses/house_tang.json"))
    reporting = house.setdefault("recruitment_reporting", {})
    reporting.pop("char_tang_wei", None)
    planner.put("state/houses/house_tang.json", house)

    host_id, event_id = _watch_ids("char_tang_wei")
    runtime = deepcopy(planner.read("state/runtime.json"))
    runtime.get("hosts", {}).pop(host_id, None)
    runtime["events"] = [
        row
        for row in runtime.get("events", [])
        if not isinstance(row, dict) or row.get("event_id") != event_id
    ]
    planner.put("state/runtime.json", runtime)
    return house, host_id, event_id


def test_reporting_subscription_baselines_already_disclosed_great_bow_opening(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    house, _host_id, _event_id = _clear_existing_recruitment_watch(planner)
    at = str(planner.read("state/runtime.json")["world_time"])
    opened_at = "245-BCE-12-07T19:22:48+08:00"
    house.setdefault("administrative_programs", {})["great_bow_guard"] = {
        "status": "recruiting",
        "opened_at": opened_at,
    }

    _ensure_report_watch(planner, at=at, house=house, player_ref="char_tang_wei")

    subscription = house["recruitment_reporting"]["char_tang_wei"]
    assert subscription["reported_great_bow_guard_opened_at"] == opened_at


def test_reporting_subscription_emits_future_great_bow_opening_exactly_once(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    house, host_id, _event_id = _clear_existing_recruitment_watch(planner)
    start = CampaignTime.parse(str(planner.read("state/runtime.json")["world_time"]))
    house.setdefault("administrative_programs", {})["great_bow_guard"] = {"status": "not_open"}
    _ensure_report_watch(planner, at=str(start), house=house, player_ref="char_tang_wei")
    planner.put("state/houses/house_tang.json", house)

    manor = deepcopy(planner.read("state/population/tang-manor.json"))
    recruitment_runtime = manor.setdefault("recruitment_runtime", {})
    recruitment_runtime["last_house_requested_intake"] = 0
    recruitment_runtime["last_sword_manor_intake"] = 0
    planner.put("state/population/tang-manor.json", manor)

    opened = start.add_hours(1)
    house = deepcopy(planner.read("state/houses/house_tang.json"))
    house.setdefault("administrative_programs", {})["great_bow_guard"] = {
        "status": "recruiting",
        "opened_at": str(opened),
    }
    planner.put("state/houses/house_tang.json", house)
    host = deepcopy(planner.read("state/runtime.json")["hosts"][host_id])
    before = set(read_causal_event_owner(planner)[1]["causal_events"])

    first_review = start.add_hours(12)
    _settle_recruitment_watch(planner, host, str(first_review))
    after_first = set(read_causal_event_owner(planner)[1]["causal_events"])
    created = after_first - before
    assert len(created) == 1
    created_event = read_causal_event_owner(planner)[1]["causal_events"][next(iter(created))]
    assert "Great Bow Guard applicant intake is open" in created_event["summary"]

    _settle_recruitment_watch(planner, host, str(first_review.add_hours(12)))
    after_second = set(read_causal_event_owner(planner)[1]["causal_events"])
    assert after_second == after_first


def test_player_default_is_56_hours_and_kai_is_five(campaign):
    player = json.loads((Path(campaign) / "state/player.json").read_text())
    kai = json.loads((Path(campaign) / "state/char/tang-kai.json").read_text())
    runtime = json.loads((Path(campaign) / "state/runtime.json").read_text())

    assert player["activity_contract"]["verified_hours_per_7d"] == 56
    assert "up to 56 hours per 7 days" in player["activity_contract"]["planned_opportunity"]
    assert age_years(kai, CampaignTime.parse(runtime["world_time"])) == 5
    assert "age-five supervised play" in kai["activity_contract"]["planned_opportunity"]
    assert kai["activity_contract"]["mode"] == "age_appropriate_household_training"
    assert "no live weapons" in kai["activity_contract"]["planned_opportunity"]
