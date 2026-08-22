from __future__ import annotations

import copy

from sword_runtime.production_runtime_planner import ProductionCampaignPlanner


OP_REF = "operation_arc_131572c4e8a2892bbc"
ARC_REF = "arc_ryo_fui_northern_wei_campaign"
QIN_REFS = [f"formation_qin_wei_unit_{i:02d}" for i in range(1, 5)]


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    meta = planner.read("state/meta.json")
    planner.PLAYER_ACTOR = str(meta["player_id"])
    planner._reset()
    return planner


def _prepare_player_commanded_qin_operation(planner) -> str:
    op_path = planner.read("state/operations/index.json")["operations"][OP_REF]
    operation = copy.deepcopy(planner.read(op_path))
    operation.update({
        "status": "active",
        "kind": "assigned_qin_field_detachment_operation",
        "objective": "maintain military readiness",
        "objective_refs": [ARC_REF, "state_wei"],
        "formation_refs": QIN_REFS,
        "administrative_authority": "char_tang_wei",
        "administrative_authorities": ["char_tang_wei"],
        "assignment_authority_ref": "char_tang_wei",
        "institutional_owner_ref": "state_qin",
        "source_force_ref": "force_state_qin",
        "command_group_ref": "cmdgrp.tang_wei.field_army",
        "autonomous": False,
    })
    planner.put(op_path, operation)
    return op_path


def test_world_arc_qin_directive_waits_for_operational_briefing(campaign):
    planner = _planner(campaign)
    op_path = _prepare_player_commanded_qin_operation(planner)
    now = str(planner.read("state/runtime.json")["world_time"])

    evidence = planner._priority_operation_evidence(
        actor_ref="state_qin",
        action_ref="action_test_qin_strategic_directive",
        arc_ref=ARC_REF,
        goal="open offensive operations against northern Wei",
        target_ref="state_wei",
        at=now,
        force_refs=["force_state_qin"],
        kind="state_world_arc_operation",
    )

    assert evidence is not None
    assert evidence["kind"] == "player_command_operational_order_issued"
    assert evidence["actionability_status"] == "pending_operational_briefing"
    assert evidence["order_status"] == "awaiting_operational_briefing"
    assert evidence["movement_committed"] is False
    assert evidence["tactical_decision_committed"] is False

    operation = planner.read(op_path)
    assert operation["order_status"] == "awaiting_operational_briefing"
    order = operation["operational_orders"][-1]
    assert order["status"] == "strategic_directive_pending_operational_briefing"
    assert order["actionability_status"] == "pending_operational_briefing"
    assert order["strategic_pressure_target_ref"] == "state_wei"
    assert "Strategic pressure metadata is not a battlefield target" in order["planning_requirement"]


def test_world_arc_person_target_never_becomes_battlefield_target_by_inference(campaign):
    planner = _planner(campaign)
    op_path = _prepare_player_commanded_qin_operation(planner)
    now = str(planner.read("state/runtime.json")["world_time"])

    evidence = planner._priority_operation_evidence(
        actor_ref="state_qin",
        action_ref="action_test_qin_arc_driver_target",
        arc_ref=ARC_REF,
        goal="maintain campaign pressure",
        target_ref="char_ryo_fui",
        at=now,
        force_refs=["force_state_qin"],
        kind="state_world_arc_operation",
    )

    assert evidence is not None
    assert evidence["actionability_status"] == "pending_operational_briefing"
    assert evidence["strategic_pressure_target_ref"] == "char_ryo_fui"
    order = planner.read(op_path)["operational_orders"][-1]
    assert order["strategic_pressure_target_ref"] == "char_ryo_fui"
    assert order["status"] == "strategic_directive_pending_operational_briefing"
