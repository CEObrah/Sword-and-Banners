from __future__ import annotations

import copy

from sword_runtime.production_runtime_planner import ProductionCampaignPlanner


OPERATION_REF = "operation_arc_131572c4e8a2892bbc"
DESTINATION = "loc_kanyou"


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner.PLAYER_ACTOR = "char_tang_wei"
    planner._reset()
    return planner


def _seed_actionable_arrival(planner):
    op_path = planner.read("state/operations/index.json")["operations"][OPERATION_REF]
    operation = copy.deepcopy(planner.read(op_path))
    operation["location_ref"] = "loc_qin_eastern_depot"
    operation["order_status"] = "staff_briefed_awaiting_commander_execution"
    order = copy.deepcopy(operation["operational_orders"][-1])
    order["status"] = "staff_briefed_awaiting_commander_execution"
    order["actionability_status"] = "actionable"
    packet = copy.deepcopy(order["mission_packet"])
    packet["destination_ref"] = DESTINATION
    packet["destination_name"] = "Kanyou"
    packet["mission_phase"] = "campaign_muster_and_staging"
    packet["phase_status"] = "ready_for_commander_execution"
    packet["hostile_entry_authorized"] = False
    packet["entry_status"] = "awaiting_war_or_entry_authority"
    order["mission_packet"] = packet
    operation["operational_orders"][-1] = order
    planner.put(op_path, operation)
    opposing = set(operation.get("opposing_formation_refs", []))
    participants = [str(ref) for ref in operation.get("formation_refs", []) if ref not in opposing]
    return op_path, participants


def test_movement_reconciliation_delivers_arrival_report_when_last_participant_is_present(campaign):
    planner = _planner(campaign)
    op_path, participants = _seed_actionable_arrival(planner)
    straggler = participants[-1]
    for ref in participants:
        path = planner.owner_path(ref)
        formation = copy.deepcopy(planner.read(path))
        formation["location_ref"] = "loc_qin_eastern_depot" if ref == straggler else DESTINATION
        planner.put(path, formation)

    assert planner._reconcile_campaign_arrivals_after_movement([straggler], DESTINATION) == []

    path = planner.owner_path(straggler)
    formation = copy.deepcopy(planner.read(path))
    formation["location_ref"] = DESTINATION
    planner.put(path, formation)

    reports = planner._reconcile_campaign_arrivals_after_movement([straggler], DESTINATION)
    assert len(reports) == 1
    assert reports[0]["operation_ref"] == OPERATION_REF
    assert reports[0]["phase"] == "awaiting_entry_authority"
    assert reports[0]["information_ref"].startswith("information.campaign_phase.")

    operation = planner.read(op_path)
    assert operation["location_ref"] == DESTINATION
    assert operation["order_status"] == "awaiting_entry_authority"
    assert operation["campaign_phase"] == "awaiting_entry_authority"
    assert operation["last_phase_information_ref"] == reports[0]["information_ref"]
    order = operation["operational_orders"][-1]
    assert order["actionability_status"] == "completed"
    assert order["status"] == "staged_awaiting_entry_authority"
    assert order["mission_packet"]["phase_status"] == "completed"


def test_movement_reconciliation_ignores_unrelated_or_partial_operations(campaign):
    planner = _planner(campaign)
    op_path, participants = _seed_actionable_arrival(planner)
    straggler = participants[-1]
    for ref in participants:
        path = planner.owner_path(ref)
        formation = copy.deepcopy(planner.read(path))
        formation["location_ref"] = "loc_qin_eastern_depot" if ref == straggler else DESTINATION
        planner.put(path, formation)

    before = copy.deepcopy(planner.read(op_path))
    assert planner._reconcile_campaign_arrivals_after_movement(["formation_not_in_operation"], DESTINATION) == []
    assert planner.read(op_path) == before
    assert planner._reconcile_campaign_arrivals_after_movement([straggler], DESTINATION) == []
    assert planner.read(op_path) == before
