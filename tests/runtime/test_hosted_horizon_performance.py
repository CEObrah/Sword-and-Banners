from __future__ import annotations

import math

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


@pytest.mark.parametrize("days", [30, 90, 365])
def test_production_hosted_horizon_is_bounded_atomic_windows(campaign, days: int):
    """Guard hosted chronology by causal work, not runner clock speed.

    Long skips use seven-day in-memory causal heaps but remain one staged command
    transaction with no intermediate persistence. The guard bounds three things
    that represent engine complexity directly: causal-window count, event density,
    and logical read/write fanout per settled event. A wall-clock assertion made
    the same deterministic work pass or fail depending on hosted-runner speed.
    """
    planner = CountingProductionPlanner(campaign)
    planner._reset()
    planner.read_calls = 0
    planner.put_calls = 0

    runtime = planner.read("state/runtime.json")
    start = CampaignTime.parse(str(runtime["world_time"]))
    disk_start = str(planner.store.read_json("state/runtime.json")["world_time"])
    target = start.add_seconds(days * 86400)
    planner._active_command_type = "advance_time"

    result = planner._advance_runtime(str(target))

    after = planner.read("state/runtime.json")
    expected_windows = math.ceil(days / 7)
    events_processed = int(result["events_processed"])

    assert len(planner.causal_heap_calls) == expected_windows
    assert planner.causal_heap_calls[-1] == str(target)
    assert after["world_time"] == str(target)
    assert after["scheduler"]["causal_settled_through"] == str(target)
    assert events_processed > 0
    assert str(planner.store.read_json("state/runtime.json")["world_time"]) == disk_start

    # Current 365-day hosted fixture settles 2,070 events in 53 windows with
    # 1,711,297 logical reads and 62,837 staged puts. These proportional budgets
    # retain substantial feature headroom while failing event explosions or
    # superlinear per-event repository fanout.
    assert events_processed <= (days * 8) + 50
    assert planner.read_calls <= (events_processed * 1_000) + 100_000
    assert planner.put_calls <= (events_processed * 40) + 10_000
