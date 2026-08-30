from __future__ import annotations

import math
import time

import pytest

from sword_runtime.production_runtime_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime


class CountingProductionPlanner(ProductionCampaignPlanner):
    def __init__(self, root):
        self.causal_heap_calls: list[str] = []
        self.read_calls = 0
        self.put_calls = 0
        super().__init__(root)

    def read(self, *args, **kwargs):
        self.read_calls += 1
        return super().read(*args, **kwargs)

    def put(self, *args, **kwargs):
        self.put_calls += 1
        return super().put(*args, **kwargs)

    def _advance_causal_runtime(self, target_text: str):
        self.causal_heap_calls.append(target_text)
        return super()._advance_causal_runtime(target_text)


def test_diagnostic_hosted_horizon_work_budget(campaign):
    days = 365
    planner = CountingProductionPlanner(campaign)
    planner._reset()
    planner.read_calls = 0
    planner.put_calls = 0
    runtime = planner.read("state/runtime.json")
    start = CampaignTime.parse(str(runtime["world_time"]))
    disk_start = str(planner.store.read_json("state/runtime.json")["world_time"])
    target = start.add_seconds(days * 86400)
    planner._active_command_type = "advance_time"

    cpu_before = time.process_time()
    result = planner._advance_runtime(str(target))
    cpu_elapsed = time.process_time() - cpu_before

    after = planner.read("state/runtime.json")
    expected_windows = math.ceil(days / 7)
    assert len(planner.causal_heap_calls) == expected_windows
    assert planner.causal_heap_calls[-1] == str(target)
    assert after["world_time"] == str(target)
    assert after["scheduler"]["causal_settled_through"] == str(target)
    assert int(result["events_processed"]) > 0
    assert str(planner.store.read_json("state/runtime.json")["world_time"]) == disk_start
    raise AssertionError(
        f"WORK_BUDGET days={days} cpu={cpu_elapsed:.6f} "
        f"reads={planner.read_calls} puts={planner.put_calls} "
        f"windows={len(planner.causal_heap_calls)} events={int(result['events_processed'])}"
    )
