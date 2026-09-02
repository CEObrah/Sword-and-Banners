from __future__ import annotations

import copy

from sword_runtime.production_runtime_planner import ProductionCampaignPlanner
from sword_runtime.operation_routing import exact_operation_record


OP_REF = "operation_arc_131572c4e8a2892bbc"
ARC_REF = "arc_ryo_fui_northern_wei_campaign"
QIN_REFS = ["formation_high_guard_qin_a", "formation_high_guard_qin_b"] + [f"formation_black_banner_{i:02d}{half}" for i in range(1, 5) for half in ("a", "b")]


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
        "operational_orders": [],
        "last_operational_order_ref": None,
        "last_operational_order_at": None,
        "order_status": None,
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
    assert "planning_requirement" not in order


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


def test_equivalent_world_arc_directive_reaffirms_one_active_order(campaign):
    planner = _planner(campaign)
    op_path = _prepare_player_commanded_qin_operation(planner)
    now = str(planner.read("state/runtime.json")["world_time"])
    first = planner._priority_operation_evidence(
        actor_ref="state_qin", action_ref="action_equiv_1", arc_ref=ARC_REF,
        goal="open offensive operations against northern Wei", target_ref="state_wei",
        at=now, force_refs=["force_state_qin"], kind="state_world_arc_operation",
    )
    second = planner._priority_operation_evidence(
        actor_ref="state_qin", action_ref="action_equiv_2", arc_ref=ARC_REF,
        goal="open offensive operations against northern Wei", target_ref="char_ryo_fui",
        at=now, force_refs=["force_state_qin"], kind="state_world_arc_operation",
    )
    operation = planner.read(op_path)
    matching = [row for row in operation["operational_orders"] if row.get("arc_ref") == ARC_REF and row.get("objective") == first["objective"]]
    assert len(matching) == 1
    assert second["kind"] == "player_command_operational_order_reaffirmed"
    assert second["evidence_stage"] == "commitment"
    assert second["order_ref"] == first["order_ref"]
    assert matching[0]["target_ref"] == "char_ryo_fui"
    assert matching[0]["strategic_pressure_target_ref"] == "char_ryo_fui"
    assert "reaffirmation_count" not in matching[0]
    assert "last_reaffirmed_at" not in matching[0]
    assert "latest_target_ref" not in matching[0]


def test_equivalent_qin_directive_cannot_reopen_completed_staging(campaign):
    planner = _planner(campaign)
    resolved = exact_operation_record(planner, OP_REF)
    assert resolved is not None
    op_path, raw = resolved

    # Build the premise inside this disposable fixture.  The canonical campaign
    # may already have advanced beyond staging, so inheriting its phase makes
    # this regression chronology-dependent instead of testing the duplicate-order
    # guard.  Keep the arc before its active-operation wording so `goal` remains
    # the exact semantic objective used below.
    arc_doc = copy.deepcopy(planner.read("state/arc/kingdom-arcs.json"))
    arc_row = next(row for row in arc_doc["records"] if row.get("record_id") == ARC_REF)
    arc_row.setdefault("facts", {})["stage"] = "pressure"
    planner.put("state/arc/kingdom-arcs.json", arc_doc)

    completed_ref = "operational_order_fixture_completed_staging"
    before = copy.deepcopy(raw)
    before.update({
        "status": "active",
        "kind": "assigned_qin_field_detachment_operation",
        "objective": "protect core territory",
        "objective_refs": [ARC_REF, "state_wei"],
        "formation_refs": QIN_REFS,
        "administrative_authority": "char_tang_wei",
        "administrative_authorities": ["char_tang_wei"],
        "assignment_authority_ref": "char_tang_wei",
        "institutional_owner_ref": "state_qin",
        "source_force_ref": "force_state_qin",
        "command_group_ref": "cmdgrp.tang_wei.field_army",
        "autonomous": False,
        "campaign_phase": "awaiting_entry_authority",
        "order_status": "awaiting_entry_authority",
        "last_operational_order_ref": completed_ref,
        "operational_orders": [{
            "order_ref": completed_ref,
            "issued_at": str(planner.read("state/runtime.json")["world_time"]),
            "issuer_ref": "state_qin",
            "arc_ref": ARC_REF,
            "target_ref": "state_wei",
            "objective": "protect core territory",
            "status": "staged_awaiting_entry_authority",
            "actionability_status": "completed",
            "applies_to_formation_refs": sorted(QIN_REFS),
        }],
    })
    planner.put(op_path, before)

    now = str(planner.read("state/runtime.json")["world_time"])
    evidence = planner._priority_operation_evidence(
        actor_ref="state_qin",
        action_ref="action_reaffirm_completed_staging",
        arc_ref=ARC_REF,
        goal="protect core territory",
        target_ref="char_ryo_fui",
        at=now,
        force_refs=["force_state_qin"],
        kind="state_world_arc_operation",
    )

    after = planner.read(op_path)
    assert evidence is not None
    assert evidence["kind"] == "player_command_operational_order_reaffirmed"
    assert evidence["evidence_stage"] == "commitment"
    assert evidence["order_ref"] == completed_ref
    assert len(after["operational_orders"]) == 1
    assert after["last_operational_order_ref"] == completed_ref
    assert after["campaign_phase"] == "awaiting_entry_authority"
    assert after["order_status"] == "awaiting_entry_authority"
    assert after["operational_orders"][0]["status"] == "staged_awaiting_entry_authority"
    assert after["operational_orders"][0]["actionability_status"] == "completed"
