from __future__ import annotations

from collections.abc import Mapping

from sword_runtime.campaign_march_lifecycle import (
    CAMPAIGN_MARCH_HOST_KIND,
    sync_campaign_march_routes,
)
from sword_runtime.production_runtime_planner import ProductionCampaignPlanner


def _march_hosts(planner):
    runtime = planner.read("state/runtime.json")
    return [
        row for row in runtime.get("hosts", {}).values()
        if isinstance(row, Mapping) and row.get("kind") == CAMPAIGN_MARCH_HOST_KIND
    ]


def test_stuck_qin_campaign_registers_npc_marches_without_moving_tang_wei(campaign):
    planner = ProductionCampaignPlanner(campaign)

    registered = set(sync_campaign_march_routes(planner))

    assert "formation_qin_mou_gou_central" in registered
    assert "formation_qin_ousen_central" in registered
    assert "formation_qin_kanki_raider_host" in registered
    assert not any(ref.startswith("formation_black_banner_") for ref in registered)
    assert "formation_high_guard_qin_a" not in registered
    assert "formation_high_guard_qin_b" not in registered

    hosts = _march_hosts(planner)
    mou_gou = [row for row in hosts if row.get("operation_ref") == "operation_qin_mou_gou_northern_wei_campaign"]
    assert len(mou_gou) == 3
    assert {row.get("destination_ref") for row in mou_gou} == {"loc_sanyou"}
    assert all(row.get("travel_hours", 0) > 0 for row in mou_gou)

    operation = planner.read("state/operations/operation_qin_mou_gou_northern_wei_campaign.json")
    assignment = operation.get("campaign_march_assignment")
    assert isinstance(assignment, Mapping)
    assert assignment.get("status") == "ordered"
    assert assignment.get("destination_ref") == "loc_sanyou"
    assert assignment.get("issuer_ref") == "char_mou_gou"
    assert operation.get("status") == "advancing"


def test_campaign_march_scheduler_dispatch_moves_formation_only_at_registered_arrival(campaign):
    planner = ProductionCampaignPlanner(campaign)
    sync_campaign_march_routes(planner)
    host = next(
        row for row in _march_hosts(planner)
        if row.get("formation_ref") == "formation_qin_mou_gou_central"
    )

    before = planner.read(planner.owner_path("formation_qin_mou_gou_central"))
    assert before.get("location_ref") == "loc_qin_regional_01"
    assert before.get("status") == "marching"

    planner._run_due_host(host, str(host["next_due"]))

    after = planner.read(planner.owner_path("formation_qin_mou_gou_central"))
    assert after.get("location_ref") == "loc_sanyou"
    movement = after.get("operational_movement")
    assert isinstance(movement, Mapping)
    assert movement.get("movement_owner") == CAMPAIGN_MARCH_HOST_KIND
    assert movement.get("departed_at") == host.get("departed_at")
    assert movement.get("tail_arrived_at") == host.get("next_due")
    assert planner._pending_wake_created is None


def test_campaign_march_sync_is_idempotent(campaign):
    planner = ProductionCampaignPlanner(campaign)
    first = sync_campaign_march_routes(planner)
    first_hosts = _march_hosts(planner)
    second = sync_campaign_march_routes(planner)
    second_hosts = _march_hosts(planner)

    assert first
    assert second == []
    assert len(second_hosts) == len(first_hosts)
