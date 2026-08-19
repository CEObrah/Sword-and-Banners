from __future__ import annotations

import json
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
    contract = {"mode": "standing_role_training"}

    hours = verified_activity_hours_per_cycle(person, contract, profiles, 30 * 86400)
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


def test_named_house_tang_activity_host_settles_canonical_monthly_hours(campaign):
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
    activity["verified_hours_per_cycle"] = 240.0
    activity["next_due"] = str(due)
    activity["focus_cursor"] = 0
    planner.put(person_path, ling)

    planner._settle_activity_host({"routed_person_refs": ["char_tang_ling"]}, str(due))
    _path, after = planner._exact_person("char_tang_ling", active=False)

    assert after["autonomous_activity_state"]["verified_hours_per_cycle"] == 240.0
    assert after["autonomous_development_history"][-1]["hours"] == 240.0


def test_player_and_child_current_training_policies_match_age_and_role(campaign):
    player = json.loads((Path(campaign) / "state/player.json").read_text())
    kai = json.loads((Path(campaign) / "state/char/tang-kai.json").read_text())
    runtime = json.loads((Path(campaign) / "state/runtime.json").read_text())

    assert player["activity_contract"]["verified_hours_per_7d"] == 56
    assert age_years(kai, CampaignTime.parse(runtime["world_time"])) == 5
    assert kai["activity_contract"]["mode"] == "age_appropriate_household_training"
    assert "no live weapons" in kai["activity_contract"]["planned_opportunity"]
