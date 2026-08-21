from __future__ import annotations

import json

import pytest
from copy import deepcopy
from pathlib import Path

from sword_runtime.development import age_years
from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.training_rates import verified_activity_hours_per_cycle


def test_house_tang_adult_cycle_uses_canonical_max_sustainable_rate(campaign):
    profiles = json.loads(
        (Path(campaign) / "game/data/mil/recruitment-cohort-profiles.json").read_text()
    )
    person = {"affiliation": "House Tang"}
    contract = {"mode": "standing_role_training", "training_regimen_ref": "house_tang_max_sustainable"}

    hours = verified_activity_hours_per_cycle(person, contract, profiles, 30 * 86400)
    assert hours == pytest.approx(205.714286)


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


def test_named_house_tang_activity_host_settles_canonical_monthly_hours(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    start = CampaignTime.parse(str(planner.read("state/runtime.json")["world_time"]))
    due = start.add_seconds(30 * 86400)
    person_path, ling = planner._exact_person("char_tang_ling", active=False)
    ling = deepcopy(ling)
    ling["affiliation"] = "House Tang"
    ling.setdefault("activity_contract", {})["mode"] = "standing_role_training"
    activity = ling.setdefault("autonomous_activity_state", {})
    activity["cadence_seconds"] = 30 * 86400
    activity["verified_hours_per_cycle"] = 205.714286
    activity["next_due"] = str(due)
    activity["focus_cursor"] = 0
    planner.put(person_path, ling)

    planner._settle_activity_host({"routed_person_refs": ["char_tang_ling"]}, str(due))
    _path, after = planner._exact_person("char_tang_ling", active=False)

    assert after["autonomous_activity_state"]["verified_hours_per_cycle"] == pytest.approx(205.714286)
    last = after["autonomous_activity_state"]["last_training"]
    assert last["hours"] == 206
    assert last["program_ref"] == after["activity_contract"]["training_program_ref"]
    assert "autonomous_development_history" not in after
    assert after["autonomous_activity_state"]["fractional_training_hour_credit"] == pytest.approx(0.428572, abs=1e-6)


def test_player_and_child_current_training_policies_match_age_and_role(campaign):
    player = json.loads((Path(campaign) / "state/player.json").read_text())
    kai = json.loads((Path(campaign) / "state/char/tang-kai.json").read_text())
    runtime = json.loads((Path(campaign) / "state/runtime.json").read_text())

    assert player["activity_contract"]["verified_hours_per_7d"] == 48
    assert age_years(kai, CampaignTime.parse(runtime["world_time"])) == 5
    assert kai["activity_contract"]["mode"] == "age_appropriate_household_training"
    assert kai["activity_contract"]["training_program_ref"] == "program.tang_heir_child"
    assert kai["activity_contract"]["adult_regimen_prohibited"] is True
    assert "planned_opportunity" not in kai["activity_contract"]
