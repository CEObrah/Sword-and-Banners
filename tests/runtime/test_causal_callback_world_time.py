from __future__ import annotations

import copy

import pytest

from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    meta = copy.deepcopy(planner.read("state/meta.json"))
    planner.PLAYER_ACTOR = str(meta["player_id"])
    planner._reset()
    return planner


def test_world_time_remains_strict_outside_callbacks_but_uses_due_cursor_inside(campaign) -> None:
    planner = _planner(campaign)
    meta_time = CampaignTime.parse(str(planner.read("state/meta.json")["time"]))
    due = meta_time.add_seconds(3600)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    runtime["world_time"] = str(due)
    planner.put("state/runtime.json", runtime)

    with pytest.raises(ValueError, match="campaign chronology authorities disagree"):
        planner._world_time()

    planner._active_event_id = "event_test_due_callback"
    planner._active_host_id = "host_test_due_callback"
    assert planner._world_time() == due

    planner._active_event_id = None
    planner._active_host_id = None
    with pytest.raises(ValueError, match="campaign chronology authorities disagree"):
        planner._world_time()


def test_great_bow_guard_pool_can_settle_at_scheduler_due_time_before_meta_close(campaign) -> None:
    planner = _planner(campaign)
    meta_time = CampaignTime.parse(str(planner.read("state/meta.json")["time"]))
    due = meta_time.add_seconds(3600)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    runtime["world_time"] = str(due)
    planner.put("state/runtime.json", runtime)
    planner._active_event_id = "event_house_gbg_pool_test"
    planner._active_host_id = "host_house_gbg_pool_test"

    planner._settle_great_bow_guard_candidate_pool(
        {"program_ref": "program_house_tang_great_bow_guard"},
        str(due),
    )

    great = planner.read("state/houses/house_tang.json")["administrative_programs"]["great_bow_guard"]
    assert great["candidate_campaign_ref"]
    assert great["applicants_registered"] == 1200
    assert great["screened_candidates"] == 0
    assert great["rejected_candidates"] == 0
