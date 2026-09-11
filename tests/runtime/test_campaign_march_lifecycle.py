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


_PLAYER_OPERATION = "operation_arc_131572c4e8a2892bbc"
_MOU_GOU_OPERATION = "operation_qin_mou_gou_northern_wei_campaign"
_MOU_BU_OPERATION = "operation_qin_mou_bu_northern_wei_campaign"
_EASTERN_RESERVE_OPERATION = "operation_qin_eastern_reserve_northern_wei_campaign"
_CAMPAIGN_OPERATIONS = (
    _MOU_GOU_OPERATION,
    _MOU_BU_OPERATION,
    _EASTERN_RESERVE_OPERATION,
    "operation_qin_ouki_northern_wei_campaign",
    "operation_qin_mobile_reserve_northern_wei_campaign",
)


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


def _all_campaign_formation_locations(planner):
    refs: set[str] = set()
    for operation_ref in (_PLAYER_OPERATION, *_CAMPAIGN_OPERATIONS):
        operation = _operation(planner, operation_ref)
        refs.update(
            str(ref) for ref in operation.get("formation_refs", [])
            if isinstance(ref, str) and ref
        )
    return {
        ref: planner.read(planner.owner_path(ref)).get("location_ref")
        for ref in sorted(refs)
    }


def _orders_by_ref(planner, refs):
    wanted = {str(ref) for ref in refs}
    found = {}
    for operation_ref in _CAMPAIGN_OPERATIONS:
        operation = _operation(planner, operation_ref)
        for row in operation.get("operational_orders", []):
            if not isinstance(row, Mapping):
                continue
            order_ref = str(row.get("order_ref", ""))
            if order_ref in wanted:
                found[order_ref] = row
    return found


def _strip_campaign_march_artifacts(planner):
    """Create an isolated pre-execution fixture from whatever campaign save is supplied.

    The maintained release fixture may already contain lawful subordinate orders and
    march hosts, and its formations continue to move as the campaign matures. These
    lifecycle tests exercise creation/reconciliation, not one historical deployment.
    Remove only outputs owned by this lifecycle in the disposable test repository;
    leave staff planning, campaign authority, physical locations, and unrelated truth.
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

    for operation_ref in _CAMPAIGN_OPERATIONS:
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
    before_locations = _all_campaign_formation_locations(planner)
    player_operation_before = copy.deepcopy(_operation(planner, _PLAYER_OPERATION))
    reserve_before = copy.deepcopy(_operation(planner, _EASTERN_RESERVE_OPERATION))

    created = sync_campaign_subordinate_orders(planner)

    assert created
    created_orders = _orders_by_ref(planner, created)
    assert set(created_orders) == set(created)
    for order in created_orders.values():
        assert order.get("order_kind") == "campaign_subordinate_march_order"
        assert order.get("issuer_ref") == "state_qin"
        assert order.get("superior_commander_ref") == "char_mou_gou"
        assert order.get("actionability_status") == "actionable"
        applies = [str(ref) for ref in order.get("applies_to_formation_refs", [])]
        assert applies
        packet = order.get("mission_packet")
        assert isinstance(packet, Mapping)
        destination = str(packet.get("destination_ref", ""))
        assert destination
        assert packet.get("hostile_entry_authorized") is True
        assert packet.get("entry_status") == "authorized"
        # At least one surviving assigned formation must still need the movement;
        # otherwise the synchronizer should have treated the assignment as satisfied.
        assert any(before_locations.get(ref) != destination for ref in applies)

    # Command adoption writes orders, never physical movement.
    assert _all_campaign_formation_locations(planner) == before_locations

    # Tang Wei remains outside autonomous command adoption.
    player_operation_after = _operation(planner, _PLAYER_OPERATION)
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
    before_locations = _all_campaign_formation_locations(planner)
    created = sync_campaign_subordinate_orders(planner)
    created_orders = _orders_by_ref(planner, created)

    registered = set(sync_campaign_march_routes(planner))
    hosts = _march_hosts(planner)

    assert created
    assert registered
    assert {str(row.get("formation_ref")) for row in hosts} == registered
    assert len(hosts) == len(registered)
    for host in hosts:
        formation_ref = str(host.get("formation_ref", ""))
        assert formation_ref
        assert before_locations[formation_ref] == host.get("leg_origin_ref")
        assert host.get("leg_destination_ref") != host.get("leg_origin_ref")
        assert int(host.get("leg_hours", 0)) > 0
        assert host.get("next_due") != planner.read("state/runtime.json")["world_time"]
        # Autonomous campaign routing must never absorb Tang Wei-owned formations.
        assert not formation_ref.startswith("formation_black_banner_")
        assert formation_ref not in {"formation_high_guard_qin_a", "formation_high_guard_qin_b"}

    # A formation already at its exact assigned destination must not receive a
    # duplicate march host merely because staff planning still names that objective.
    for order in created_orders.values():
        packet = order.get("mission_packet") if isinstance(order.get("mission_packet"), Mapping) else {}
        destination = str(packet.get("destination_ref", ""))
        for formation_ref in order.get("applies_to_formation_refs", []):
            if before_locations.get(str(formation_ref)) == destination:
                assert str(formation_ref) not in registered

    # Route registration also does not move anything before a due host settles.
    assert _all_campaign_formation_locations(planner) == before_locations


def test_campaign_march_due_settlement_advances_exactly_one_canonical_leg(campaign):
    planner = ProductionCampaignPlanner(campaign)
    _strip_campaign_march_artifacts(planner)
    sync_campaign_subordinate_orders(planner)
    sync_campaign_march_routes(planner)
    hosts = _march_hosts(planner)
    assert hosts
    host = hosts[0]
    formation_ref = str(host["formation_ref"])
    formation_path = planner.owner_path(formation_ref)
    before = copy.deepcopy(planner.read(formation_path))

    assert host.get("leg_origin_ref") == before.get("location_ref")
    expected_next = str(host["leg_destination_ref"])
    result = settle_campaign_march_host(planner, host, str(host["next_due"]))

    assert result is not None
    after = planner.read(formation_path)
    assert after.get("location_ref") == expected_next
    assert after.get("last_march_leg", {}).get("from") == host.get("leg_origin_ref")
    assert after.get("last_march_leg", {}).get("to") == expected_next
    assert after.get("last_march_leg", {}).get("toward") == host.get("destination_ref")
    assert int(after.get("last_march_leg", {}).get("hours", 0)) == int(host.get("leg_hours", 0))
    assert result.get("location_ref") == expected_next


def test_normal_chronology_recovers_stuck_campaign_without_retroactive_movement(campaign):
    planner = ProductionCampaignPlanner(campaign)
    _strip_campaign_march_artifacts(planner)
    before_locations = _all_campaign_formation_locations(planner)
    world_time = str(planner.read("state/runtime.json")["world_time"])

    # Preparation performs command/routing reconciliation at the current frontier
    # but must not rewrite physical history or advance the clock.
    planner._prepare_scheduler_for_advance(world_time)
    assert _all_campaign_formation_locations(planner) == before_locations
    assert planner.read("state/runtime.json")["world_time"] == world_time

    hosts = _march_hosts(planner)
    assert hosts
    host = hosts[0]
    formation_ref = str(host["formation_ref"])
    due = str(host["next_due"])
    metrics = planner._advance_runtime(due)

    after = planner.read(planner.owner_path(formation_ref))
    assert after.get("location_ref") == host.get("leg_destination_ref")
    assert planner.read("state/runtime.json")["world_time"] == due
    assert int(metrics.get("events_processed", 0)) >= 1


def test_campaign_march_order_and_route_sync_are_idempotent(campaign):
    planner = ProductionCampaignPlanner(campaign)
    _strip_campaign_march_artifacts(planner)
    first_orders = sync_campaign_subordinate_orders(planner)
    order_counts_after_first = {
        operation_ref: len(_operation(planner, operation_ref).get("operational_orders", []))
        for operation_ref in _CAMPAIGN_OPERATIONS
    }
    first_routes = sync_campaign_march_routes(planner)
    first_host_count = len(_march_hosts(planner))

    second_orders = sync_campaign_subordinate_orders(planner)
    second_routes = sync_campaign_march_routes(planner)

    assert first_orders
    assert second_orders == []
    assert first_routes
    assert second_routes == []
    assert {
        operation_ref: len(_operation(planner, operation_ref).get("operational_orders", []))
        for operation_ref in _CAMPAIGN_OPERATIONS
    } == order_counts_after_first
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
