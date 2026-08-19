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


