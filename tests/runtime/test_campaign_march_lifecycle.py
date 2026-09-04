from __future__ import annotations

import copy
from collections.abc import Mapping

from sword_runtime.campaign_march_lifecycle import (
    CAMPAIGN_MARCH_HOST_KIND,
    settle_campaign_march_host,
    sync_campaign_march_routes,
)
from sword_runtime.campaign_subordinate_orders import sync_campaign_subordinate_orders
from sword_runtime.production_runtime_planner import ProductionCampaignPlanner
from sword_runtime.time_integration import HOST_KIND_SPECS


_MOU_GOU_OPERATION = "operation_qin_mou_gou_northern_wei_campaign"
_MOU_BU_OPERATION = "operation_qin_mou_bu_northern_wei_campaign"
_EASTERN_RESERVE_OPERATION = "operation_qin_eastern_reserve_northern_wei_campaign"
_MOU_GOU_FORMATIONS = {
    "formation_qin_kanki_raider_host",
    "formation_qin_mou_gou_central",
    "formation_qin_ousen_central",
}


def _march_hosts(planner):
    runtime = planner.read("state/runtime.json")
    return [
        row for row in runtime.get("hosts", {}).values()
        if isinstance(row, Mapping) and row.get("kind") == CAMPAIGN_MARCH_HOST_KIND
    ]


def _operation(planner, operation_ref):
    return planner.read(f"state/operations/{operation_ref}.json")


def _latest_order(operation):
    ref = str(operation.get("last_operational_order_ref", ""))
    rows = operation.get("operational_orders", [])
    for row in reversed(rows if isinstance(rows, list) else []):
        if isinstance(row, Mapping) and (not ref or str(row.get("order_ref", "")) == ref):
            return row
    return None


def _strip_campaign_march_artifacts(planner):
    """Create an isolated pre-execution fixture from whatever live save was supplied.

    The release campaign may already contain lawful subordinate orders and march
    hosts.  Lifecycle tests must exercise creation/reconciliation rather than
    assume a historical starting location or an empty scheduler.  Remove only
    outputs owned by this lifecycle in the disposable test repository; leave
    staff planning, campaign authority, formation locations, and all unrelated
    campaign truth intact.
    """
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise AssertionError("test fixture runtime causal queue is invalid")
    removed_host_ids = {
        host_id for host_id, host in hosts.items()
        if isinstance(host_id, str)
        and isinstance(host, Mapping)
        and host.get("kind") == CAMPAIGN_MARCH_HOST_KIND
    }
    runtime["hosts"] = {
        host_id: host for host_id, host in hosts.items()
        if host_id not in removed_host_ids
    }
    runtime["events"] = [
        row for row in events
        if not (isinstance(row, Mapping) and row.get("target_host") in removed_host_ids)
    ]
    planner.put("state/runtime.json", runtime)

    for operation_ref in (
        _MOU_GOU_OPERATION,
        _MOU_BU_OPERATION,
        _EASTERN_RESERVE_OPERATION,
        "operation_qin_ouki_northern_wei_campaign",
        "operation_qin_mobile_reserve_northern_wei_campaign",
    ):
        operation = copy.deepcopy(_operation(planner, operation_ref))
        rows = operation.get("operational_orders")
        if not isinstance(rows, list):
            continue
        removed_order_refs = {
            str(row.get("order_ref"))
            for row in rows
            if isinstance(row, Mapping)
            and row.get("order_kind") == "campaign_subordinate_march_order"
            and isinstance(row.get("order_ref"), str)
        }
        kept = [
            copy.deepcopy(row) for row in rows
            if not (isinstance(row, Mapping) and row.get("order_kind") == "campaign_subordinate_march_order")
        ]
        if len(kept) == len(rows):
            continue
        operation["operational_orders"] = kept
        if str(operation.get("last_operational_order_ref", "")) in removed_order_refs:
            if kept and isinstance(kept[-1], Mapping) and isinstance(kept[-1].get("order_ref"), str):
                operation["last_operational_order_ref"] = kept[-1]["order_ref"]
            else:
                operation.pop("last_operational_order_ref", None)
                operation.pop("order_status", None)
        current = operation.get("current_operational_order")
        if isinstance(current, Mapping) and current.get("order_kind") == "campaign_subordinate_march_order":
            operation.pop("current_operational_order", None)
        planner.put(f"state/operations/{operation_ref}.json", operation)


def test_staff_projection_alone_is_not_executable_campaign_movement(campaign):
    planner = ProductionCampaignPlanner(campaign)
    _strip_campaign_march_artifacts(planner)
    formation_path = planner.owner_path("formation_qin_mou_gou_central")
    before = copy.deepcopy(planner.read(formation_path))
    operation_before = copy.deepcopy(_operation(planner, _MOU_GOU_OPERATION))

    registered = sync_campaign_march_routes(planner)

    assert registered == []
    assert _march_hosts(planner) == []
    after = planner.read(formation_path)
    assert after.get("location_ref") == before.get("location_ref")
    assert after.get("status") == before.get("status")
    assert _latest_order(operation_before) is None
    assert _latest_order(_operation(planner, _MOU_GOU_OPERATION)) is None


def test_campaign_command_adopts_exact_npc_orders_without_moving_formations(campaign):
    planner = ProductionCampaignPlanner(campaign)
    _strip_campaign_march_artifacts(planner)
    central_path = planner.owner_path("formation_qin_mou_gou_central")
    before_central = copy.deepcopy(planner.read(central_path))
    player_operation_before = copy.deepcopy(_operation(planner, "operation_arc_131572c4e8a2892bbc"))
    reserve_before = copy.deepcopy(_operation(planner, _EASTERN_RESERVE_OPERATION))

    created = sync_campaign_subordinate_orders(planner)

    assert created
    mou_gou = _operation(planner, _MOU_GOU_OPERATION)
    order = _latest_order(mou_gou)
    assert isinstance(order, Mapping)
    assert order.get("order_kind") == "campaign_subordinate_march_order"
    assert order.get("issuer_ref") == "state_qin"
    assert order.get("superior_commander_ref") == "char_mou_gou"
    assert order.get("actionability_status") == "actionable"
    assert set(order.get("applies_to_formation_refs", [])) == _MOU_GOU_FORMATIONS
    packet = order.get("mission_packet")
    assert isinstance(packet, Mapping)
    assert packet.get("destination_ref") == "loc_sanyou"
    assert packet.get("hostile_entry_authorized") is True
    assert packet.get("entry_status") == "authorized"

    # Command adoption writes an order, not a movement result.
    after_central = planner.read(central_path)
    assert after_central.get("location_ref") == before_central.get("location_ref")
    assert after_central.get("status") == before_central.get("status")

    # Tang Wei remains outside autonomous command adoption.
    player_operation_after = _operation(planner, "operation_arc_131572c4e8a2892bbc")
    assert player_operation_after.get("last_operational_order_ref") == player_operation_before.get("last_operational_order_ref")

    # The strategic reserve has no objective assignment and remains uncommitted.
    reserve_after = _operation(planner, _EASTERN_RESERVE_OPERATION)
    assert reserve_after.get("last_operational_order_ref") == reserve_before.get("last_operational_order_ref")
    assert not any(
        isinstance(row, Mapping) and row.get("order_kind") == "campaign_subordinate_march_order"
        for row in reserve_after.get("operational_orders", [])
    )


def test_exact_subordinate_orders_register_only_lawful_routes_without_pre_movement(campaign):
    planner = ProductionCampaignPlanner(campaign)
    _strip_campaign_march_artifacts(planner)
    central_path = planner.owner_path("formation_qin_mou_gou_central")
    before = copy.deepcopy(planner.read(central_path))
    sync_campaign_subordinate_orders(planner)

    registered = set(sync_campaign_march_routes(planner))

    # Exact current formation locations are authoritative.  Only Kanki's host
    # is still short of Sanyou in the supplied campaign; central formations and
    # the mobile reserve already there must not receive duplicate march hosts.
    assert "formation_qin_kanki_raider_host" in registered
    assert "formation_qin_mou_gou_central" not in registered
    assert "formation_qin_ousen_central" not in registered
    assert "formation_qin_ouki_vanguard" not in registered
    assert "formation_qin_tou_mobile_army" not in registered
    assert "formation_qin_mobile_reserve" not in registered
    assert "formation_qin_mou_bu_shock_army" not in registered
    assert "formation_qin_reserve_infantry_02" not in registered
    assert not any(ref.startswith("formation_black_banner_") for ref in registered)
    assert "formation_high_guard_qin_a" not in registered
    assert "formation_high_guard_qin_b" not in registered

    # Mou Bu's projected route crosses geography for which the canonical movement
    # authority has no lawful transit basis. The exact order therefore blocks
    # rather than letting staff planning create passage rights.
    mou_bu_order = _latest_order(_operation(planner, _MOU_BU_OPERATION))
    assert isinstance(mou_bu_order, Mapping)
    assert mou_bu_order.get("status") == "execution_blocked"
    assert mou_bu_order.get("actionability_status") == "blocked"
    assert mou_bu_order.get("mission_packet", {}).get("phase_status") == "blocked"

    after = planner.read(central_path)
    assert after.get("location_ref") == before.get("location_ref")
    assert after.get("status") == before.get("status")

    mou_gou_hosts = [row for row in _march_hosts(planner) if row.get("operation_ref") == _MOU_GOU_OPERATION]
    assert len(mou_gou_hosts) == 1
    assert mou_gou_hosts[0].get("formation_ref") == "formation_qin_kanki_raider_host"
    assert {row.get("destination_ref") for row in mou_gou_hosts} == {"loc_sanyou"}
    assert all(row.get("leg_origin_ref") for row in mou_gou_hosts)
    assert all(row.get("leg_destination_ref") for row in mou_gou_hosts)
    assert all(int(row.get("leg_hours", 0)) > 0 for row in mou_gou_hosts)
    assert all(row.get("next_due") != planner.read("state/runtime.json")["world_time"] for row in mou_gou_hosts)


def test_campaign_march_due_settlement_advances_exactly_one_canonical_leg(campaign):
    planner = ProductionCampaignPlanner(campaign)
    _strip_campaign_march_artifacts(planner)
    sync_campaign_subordinate_orders(planner)
    sync_campaign_march_routes(planner)
    host = next(
        row for row in _march_hosts(planner)
        if row.get("formation_ref") == "formation_qin_kanki_raider_host"
    )
    formation_path = planner.owner_path("formation_qin_kanki_raider_host")
    before = copy.deepcopy(planner.read(formation_path))

    assert host.get("leg_origin_ref") == before.get("location_ref")
    expected_next = str(host["leg_destination_ref"])
    result = settle_campaign_march_host(planner, host, str(host["next_due"]))

    assert result is not None
    after = planner.read(formation_path)
    assert after.get("location_ref") == expected_next
    assert after.get("last_march_leg", {}).get("from") == host.get("leg_origin_ref")
    assert after.get("last_march_leg", {}).get("to") == expected_next
    assert after.get("last_march_leg", {}).get("toward") == "loc_sanyou"
    assert int(after.get("last_march_leg", {}).get("hours", 0)) == int(host.get("leg_hours", 0))
    assert result.get("location_ref") == expected_next
    # The exact next leg may now be the final destination in a matured save;
    # the invariant is that only the host's already-planned canonical leg moves.


def test_normal_chronology_recovers_stuck_campaign_without_retroactive_movement(campaign):
    planner = ProductionCampaignPlanner(campaign)
    _strip_campaign_march_artifacts(planner)
    marching_path = planner.owner_path("formation_qin_kanki_raider_host")
    before = copy.deepcopy(planner.read(marching_path))
    world_time = str(planner.read("state/runtime.json")["world_time"])

    # Preparation performs command/routing reconciliation at the current frontier
    # but must not rewrite physical history or advance the clock.
    planner._prepare_scheduler_for_advance(world_time)
    after_prepare = planner.read(marching_path)
    assert after_prepare.get("location_ref") == before.get("location_ref")
    assert planner.read("state/runtime.json")["world_time"] == world_time

    host = next(
        row for row in _march_hosts(planner)
        if row.get("formation_ref") == "formation_qin_kanki_raider_host"
    )
    due = str(host["next_due"])
    metrics = planner._advance_runtime(due)

    after = planner.read(marching_path)
    assert after.get("location_ref") == host.get("leg_destination_ref")
    assert planner.read("state/runtime.json")["world_time"] == due
    assert int(metrics.get("events_processed", 0)) >= 1


def test_campaign_march_order_and_route_sync_are_idempotent_including_blocked_orders(campaign):
    planner = ProductionCampaignPlanner(campaign)
    _strip_campaign_march_artifacts(planner)
    first_orders = sync_campaign_subordinate_orders(planner)
    operation_after_first = copy.deepcopy(_operation(planner, _MOU_GOU_OPERATION))
    first_order_count = len(operation_after_first.get("operational_orders", []))
    first_routes = sync_campaign_march_routes(planner)
    first_host_count = len(_march_hosts(planner))
    mou_bu_after_first = copy.deepcopy(_operation(planner, _MOU_BU_OPERATION))
    mou_bu_order_count = len(mou_bu_after_first.get("operational_orders", []))

    second_orders = sync_campaign_subordinate_orders(planner)
    second_routes = sync_campaign_march_routes(planner)
    operation_after_second = _operation(planner, _MOU_GOU_OPERATION)
    mou_bu_after_second = _operation(planner, _MOU_BU_OPERATION)

    assert first_orders
    assert second_orders == []
    assert first_routes
    assert second_routes == []
    assert len(operation_after_second.get("operational_orders", [])) == first_order_count
    assert len(mou_bu_after_second.get("operational_orders", [])) == mou_bu_order_count
    assert _latest_order(mou_bu_after_second).get("actionability_status") == "blocked"
    assert len(_march_hosts(planner)) == first_host_count


def test_campaign_march_is_owned_by_central_chronology_not_an_mro_dispatch_mixin(campaign):
    planner = ProductionCampaignPlanner(campaign)

    assert HOST_KIND_SPECS[CAMPAIGN_MARCH_HOST_KIND] == {
        "owner": "campaign_march_lifecycle",
        "wake": "never",
    }
    assert all(cls.__name__ != "CampaignMarchLifecycleMixin" for cls in type(planner).__mro__)


def test_arrived_assignment_does_not_regenerate_mobile_reserve_march(campaign):
    planner = ProductionCampaignPlanner(campaign)
    _strip_campaign_march_artifacts(planner)
    reserve_formation = planner.read(planner.owner_path("formation_qin_mobile_reserve"))
    assert reserve_formation.get("location_ref") == "loc_sanyou"

    sync_campaign_subordinate_orders(planner)
    reserve_operation = _operation(planner, "operation_qin_mobile_reserve_northern_wei_campaign")
    assert not any(
        isinstance(row, Mapping) and row.get("order_kind") == "campaign_subordinate_march_order"
        for row in reserve_operation.get("operational_orders", [])
    )
    assert not any(
        row.get("formation_ref") == "formation_qin_mobile_reserve"
        for row in _march_hosts(planner)
    )
