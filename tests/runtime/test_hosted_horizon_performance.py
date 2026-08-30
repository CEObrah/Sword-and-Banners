from __future__ import annotations

import math
import time

import pytest

from sword_runtime.campaign_command_contact import CampaignCommandContactMixin
from sword_runtime.campaign_command_requests import CampaignCommandRequestMixin
from sword_runtime.campaign_follow_on_order import materialize_reconciled_campaign_follow_on_orders
from sword_runtime.message_reply_flow import MessageReplyFlowMixin
from sword_runtime.production_planner import ProductionCampaignPlanner as _BaseProductionCampaignPlanner
from sword_runtime.production_runtime_planner import ProductionCampaignPlanner
from sword_runtime.qin_command_support_flow import QinCommandSupportFlowMixin
from sword_runtime.qin_operational_order_guard import QinOperationalOrderGuardMixin
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.sovereign_campaign_authority_mixin import SovereignCampaignAuthorityMixin
from sword_runtime.time_integration import ProductionTimeIntegrationMixin


class CountingProductionPlanner(ProductionCampaignPlanner):
    def __init__(self, root):
        super().__init__(root)
        self.causal_heap_calls: list[str] = []

    def _advance_causal_runtime(self, target_text: str):
        self.causal_heap_calls.append(target_text)
        return super()._advance_causal_runtime(target_text)


class ProductionPlannerWithoutReconMixin(
    ProductionTimeIntegrationMixin,
    SovereignCampaignAuthorityMixin,
    QinCommandSupportFlowMixin,
    QinOperationalOrderGuardMixin,
    CampaignCommandRequestMixin,
    MessageReplyFlowMixin,
    CampaignCommandContactMixin,
    _BaseProductionCampaignPlanner,
):
    """Diagnostic mirror of hosted composition before the reconnaissance mixin."""

    def _prepare_scheduler_for_advance(self, target_text: str) -> None:
        refreshed = self._reconcile_campaign_entry_authority()
        materialize_reconciled_campaign_follow_on_orders(self, refreshed)
        super()._prepare_scheduler_for_advance(target_text)


@pytest.mark.parametrize(("days", "cpu_threshold"), [(30, 12.0), (90, 30.0)])
def test_production_hosted_horizon_is_bounded_atomic_windows(campaign, days: int, cpu_threshold: float):
    planner = CountingProductionPlanner(campaign)
    planner._reset()
    runtime = planner.read("state/runtime.json")
    start = CampaignTime.parse(str(runtime["world_time"]))
    disk_start = str(planner.store.read_json("state/runtime.json")["world_time"])
    target = start.add_seconds(days * 86400)
    planner._active_command_type = "advance_time"

    wall_before = time.perf_counter()
    cpu_before = time.process_time()
    result = planner._advance_runtime(str(target))
    cpu_elapsed = time.process_time() - cpu_before
    wall_elapsed = time.perf_counter() - wall_before

    after = planner.read("state/runtime.json")
    expected_windows = math.ceil(days / 7)
    assert len(planner.causal_heap_calls) == expected_windows
    assert planner.causal_heap_calls[-1] == str(target)
    assert after["world_time"] == str(target)
    assert after["scheduler"]["causal_settled_through"] == str(target)
    assert int(result["events_processed"]) > 0
    assert str(planner.store.read_json("state/runtime.json")["world_time"]) == disk_start
    assert cpu_elapsed < cpu_threshold, (days, cpu_elapsed, wall_elapsed)


def test_diagnostic_top_level_recon_mixin_cost(campaign):
    days = 90

    def run(planner_cls):
        planner = planner_cls(campaign)
        planner._reset()
        runtime = planner.read("state/runtime.json")
        start = CampaignTime.parse(str(runtime["world_time"]))
        target = start.add_seconds(days * 86400)
        planner._active_command_type = "advance_time"
        before = time.process_time()
        result = planner._advance_runtime(str(target))
        return time.process_time() - before, int(result["events_processed"])

    with_recon, with_events = run(ProductionCampaignPlanner)
    without_recon, without_events = run(ProductionPlannerWithoutReconMixin)
    assert False, {
        "with_recon_cpu": with_recon,
        "without_recon_cpu": without_recon,
        "with_events": with_events,
        "without_events": without_events,
        "ratio": with_recon / max(without_recon, 1e-9),
    }
