from __future__ import annotations

import copy
from collections.abc import Mapping

from sword_runtime.campaign_march_lifecycle import (
    CAMPAIGN_MARCH_HOST_KIND,
    settle_campaign_march_host,
    sync_campaign_march_routes,
)
from sword_runtime.production_runtime_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime


def _march_hosts(planner):
    runtime = planner.read("state/runtime.json")
    return [
        row for row in runtime.get("hosts", {}).values()
        if isinstance(row, Mapping) and row.get("kind") == CAMPAIGN_MARCH_HOST_KIND
    ]


def test_stuck_qin_campaign_registers_npc_routes_without_pre_moving_any_formation(campaign):
    planner = ProductionCampaignPlanner(campaign)
    formation_path = planner.owner_path("formation_qin_mou_gou_central")
    before = copy.deepcopy(planner.read(formation_path))

    registered = set(sync_campaign_march_routes(planner))

    assert "formation_qin_mou_gou_central" in registered
    assert "formation_qin_ousen_central" in registered
    assert "formation_qin_kanki_raider_host" in registered
    assert not any(ref.startswith("formation_black_banner_") for ref in registered)
    assert "formation_high_guard_qin_a" not in registered
    assert "formation_high_guard_qin_b" not in registered

    # Route registration is bookkeeping. Physical movement remains owned by the
    # canonical formation movement resolver when the causal host actually settles.
    after_sync = planner.read(formation_path)
    assert after_sync.get("location_ref") == before.get("location_ref") == "loc_qin_regional_01"
    assert after_sync.get("status") == before.get("status") == "ready"

    hosts = _march_hosts(planner)
    mou_gou = [row for row in hosts if row.get("operation_ref") == "operation_qin_mou_gou_northern_wei_campaign"]
    assert len(mou_gou) == 3
    assert {row.get("destination_ref") for row in mou_gou} == {"loc_sanyou"}
    assert all(row.get("next_due") == planner.read("state/runtime.json")["world_time"] for row in mou_gou)

    operation = planner.read("state/operations/operation_qin_mou_gou_northern_wei_campaign.json")
    assignment = operation.get("campaign_march_assignment")
    assert isinstance(assignment, Mapping)
    assert assignment.get("status") == "ordered"
    assert assignment.get("destination_ref") == "loc_sanyou"
    assert assignment.get("issuer_ref") == "char_mou_gou"
    assert assignment.get("source_kind") in {"autonomous_supreme_command_assignment", "exact_operation_order"}
    # Materializing an NPC order does not claim that the troops have already moved.
    assert operation.get("status") == "mobilizing"


def test_campaign_march_settlement_uses_exactly_one_canonical_route_leg(campaign):
    planner = ProductionCampaignPlanner(campaign)
    sync_campaign_march_routes(planner)
    host = next(
        row for row in _march_hosts(planner)
        if row.get("formation_ref") == "formation_qin_mou_gou_central"
    )

    formation_path = planner.owner_path("formation_qin_mou_gou_central")
    before = copy.deepcopy(planner.read(formation_path))
    origin = str(before["location_ref"])
    destination = str(host["destination_ref"])
    expected_next, _base_hours = planner._formation_route_next(
        origin,
        destination,
        formation=before,
        at=str(host["next_due"]),
    )

    result = settle_campaign_march_host(planner, host, str(host["next_due"]))

    assert result is not None
    after = planner.read(formation_path)
    assert after.get("location_ref") == expected_next
    assert after.get("last_march_leg", {}).get("from") == origin
    assert after.get("last_march_leg", {}).get("to") == expected_next
    assert after.get("last_march_leg", {}).get("toward") == destination
    assert result.get("location_ref") == expected_next
    assert int(result.get("leg_hours", 0)) > 0

    live_host = next(
        row for row in _march_hosts(planner)
        if row.get("formation_ref") == "formation_qin_mou_gou_central"
    )
    if expected_next == destination:
        assert live_host.get("retire_after_settlement") is True
        assert int(live_host.get("recurrence_seconds", 1)) == 0
    else:
        assert live_host.get("retire_after_settlement") is False
        assert int(live_host.get("recurrence_seconds", 0)) >= 3600


def test_hosted_scheduler_consumes_campaign_march_route_during_normal_chronology(campaign):
    planner = ProductionCampaignPlanner(campaign)
    formation_path = planner.owner_path("formation_qin_mou_gou_central")
    before = copy.deepcopy(planner.read(formation_path))
    origin = str(before["location_ref"])
    runtime_before = planner.read("state/runtime.json")
    current = CampaignTime.parse(str(runtime_before["world_time"]))
    target = current.add_seconds(3600)

    metrics = planner._advance_runtime(str(target))

    after = planner.read(formation_path)
    assert after.get("location_ref") != origin
    assert after.get("last_march_leg", {}).get("from") == origin
    assert after.get("last_march_leg", {}).get("toward") == "loc_sanyou"
    runtime_after = planner.read("state/runtime.json")
    assert runtime_after.get("world_time") == str(target)
    assert runtime_after.get("scheduler", {}).get("causal_settled_through") == str(target)
    assert int(metrics.get("events_processed", 0)) >= 1


def test_campaign_march_sync_is_idempotent_and_preserves_player_agency(campaign):
    planner = ProductionCampaignPlanner(campaign)
    first = sync_campaign_march_routes(planner)
    first_hosts = _march_hosts(planner)
    second = sync_campaign_march_routes(planner)
    second_hosts = _march_hosts(planner)

    assert first
    assert second == []
    assert len(second_hosts) == len(first_hosts)
    assert all(row.get("formation_ref") not in {
        "formation_black_banner_01a",
        "formation_high_guard_qin_a",
        "formation_red_lance_a",
    } for row in second_hosts)


def test_terminal_participant_operation_prunes_its_march_routes(campaign):
    planner = ProductionCampaignPlanner(campaign)
    sync_campaign_march_routes(planner)
    operation_path = "state/operations/operation_qin_mou_gou_northern_wei_campaign.json"
    operation = copy.deepcopy(planner.read(operation_path))
    operation["status"] = "completed"
    planner.put(operation_path, operation)

    sync_campaign_march_routes(planner)

    assert not any(
        row.get("operation_ref") == "operation_qin_mou_gou_northern_wei_campaign"
        for row in _march_hosts(planner)
    )
