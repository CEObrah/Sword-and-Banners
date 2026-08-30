from __future__ import annotations

import math
import time

import pytest

from sword_runtime.production_runtime_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime


class CountingProductionPlanner(ProductionCampaignPlanner):
    def __init__(self, root):
        super().__init__(root)
        self.causal_heap_calls: list[str] = []

    def _advance_causal_runtime(self, target_text: str):
        self.causal_heap_calls.append(target_text)
        return super()._advance_causal_runtime(target_text)


@pytest.mark.parametrize(("days", "threshold"), [(30, 12.0), (90, 30.0), (365, 75.0)])
def test_production_hosted_horizon_is_bounded_atomic_windows(campaign, days: int, threshold: float):
    """Guard real hosted chronology at 30/90/365 days.

    Long skips use seven-day in-memory causal heaps, matching the scheduler safety
    cadence, but remain one staged command transaction with no intermediate
    persistence. Thresholds detect the audited hosted regression without treating
    test-process teardown as simulation cost.
    """
    planner = CountingProductionPlanner(campaign)
    planner._reset()
    runtime = planner.read("state/runtime.json")
    start = CampaignTime.parse(str(runtime["world_time"]))
    disk_start = str(planner.store.read_json("state/runtime.json")["world_time"])
    target = start.add_seconds(days * 86400)
    planner._active_command_type = "advance_time"

    before = time.perf_counter()
    result = planner._advance_runtime(str(target))
    elapsed = time.perf_counter() - before

    after = planner.read("state/runtime.json")
    expected_windows = math.ceil(days / 7)
    assert len(planner.causal_heap_calls) == expected_windows
    assert planner.causal_heap_calls[-1] == str(target)
    assert after["world_time"] == str(target)
    assert after["scheduler"]["causal_settled_through"] == str(target)
    assert int(result["events_processed"]) > 0
    assert str(planner.store.read_json("state/runtime.json")["world_time"]) == disk_start
    assert elapsed < threshold, (days, elapsed)
