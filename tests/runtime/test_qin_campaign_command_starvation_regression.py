from __future__ import annotations

import copy

from sword_runtime.causal_event_store import get_causal_event
from sword_runtime.production_runtime_planner import ProductionCampaignPlanner
from sword_runtime.qin_command_support_flow import (
    QIN_COMMAND_SUPPORT_DELIVERY_INDEX,
    settle_qin_command_support,
    sync_qin_command_support,
)
from sword_runtime.vitality import summarize_playability_vitality


OP_REF = "operation_arc_131572c4e8a2892bbc"
ARC_REF = "arc_ryo_fui_northern_wei_campaign"
QIN_REFS = [
    "formation_high_guard_qin_a",
    "formation_high_guard_qin_b",
] + [
    f"formation_black_banner_{i:02d}{half}"
    for i in range(1, 5)
    for half in ("a", "b")
]
PRIOR_ORDER_REF = "operational_order_fixture_existing_actionable"


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner.PLAYER_ACTOR = "char_tang_wei"
    planner._reset()
    return planner


def _prepare_actionable_scope(planner) -> str:
    now = str(planner.read("state/runtime.json")["world_time"])
    op_path = planner.read("state/operations/index.json")["operations"][OP_REF]
    operation = copy.deepcopy(planner.read(op_path))
    operation.update({
        "status": "active",
        "kind": "assigned_qin_field_detachment_operation",
        "objective": "maintain a reconnaissance screen and report material contact",
        "objective_refs": [ARC_REF, "state_wei"],
        "formation_refs": list(QIN_REFS),
        "administrative_authority": "char_tang_wei",
        "administrative_authorities": ["char_tang_wei"],
        "assignment_authority_ref": "char_tang_wei",
        "institutional_owner_ref": "state_qin",
        "source_force_ref": "force_state_qin",
        "command_group_ref": "cmdgrp.tang_wei.field_army",
        "autonomous": False,
        "location_ref": "loc_qin_eastern_depot",
        "operational_orders": [{
            "order_ref": PRIOR_ORDER_REF,
            "issued_at": now,
            "issuer_ref": "state_qin",
            "arc_ref": ARC_REF,
            "target_ref": "state_wei",
            "objective": "maintain a reconnaissance screen and report material contact",
            "status": "staff_briefed_awaiting_commander_execution",
            "actionability_status": "actionable",
            "applies_to_formation_refs": sorted(QIN_REFS),
            "mission_packet": {
                "mission_phase": "contact_development",
                "destination_ref": "loc_sanyou",
                "strategic_target_ref": "loc_sanyou",
                "hostile_entry_authorized": True,
                "entry_status": "authorized",
                "agency_rule": "Contact is not a general-attack order; Tang Wei retains local tactical discretion.",
            },
        }],
        "last_operational_order_ref": PRIOR_ORDER_REF,
        "last_operational_order_at": now,
        "order_status": "staff_briefed_awaiting_commander_execution",
    })
    planner.put(op_path, operation)

    player = copy.deepcopy(planner.read("state/player.json"))
    player.setdefault("career_state", {})["appointments"] = [{
        "kind": "qin_field_command",
        "office": "field_command:test_starvation_repair",
        "state_ref": "state_qin",
        "formation_ref": QIN_REFS[0],
        "formation_refs": list(QIN_REFS),
        "operation_ref": OP_REF,
        "command_group_ref": "cmdgrp.tang_wei.field_army",
        "status": "active",
    }]
    planner.put("state/player.json", player)

    for ref in QIN_REFS:
        path = planner.owner_path(ref)
        formation = copy.deepcopy(planner.read(path))
        formation["administrative_owner"] = "state_qin"
        formation["command_authority"] = "char_tang_wei"
        formation["location_ref"] = "loc_qin_eastern_depot"
        planner.put(path, formation)
    return op_path


def _issue_broad_directive(planner) -> dict:
    now = str(planner.read("state/runtime.json")["world_time"])
    evidence = planner._priority_operation_evidence(
        actor_ref="state_qin",
        action_ref="action_test_starvation_repair_directive",
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
    return evidence


def _auto_hosts(runtime):
    return [
        row for row in runtime["hosts"].values()
        if row.get("kind") == "qin_command_support_review"
        and row.get("support_kind") == "operational_briefing"
        and str(row.get("work_ref", "")).startswith("auto_qin_campaign_briefing_")
    ]


def test_broad_qin_directive_does_not_clobber_existing_actionable_mission(campaign):
    planner = _planner(campaign)
    op_path = _prepare_actionable_scope(planner)
    evidence = _issue_broad_directive(planner)

    operation = planner.read(op_path)
    assert operation["last_operational_order_ref"] == PRIOR_ORDER_REF
    assert operation["order_status"] == "staff_briefed_awaiting_commander_execution"
    pending = next(row for row in operation["operational_orders"] if row.get("order_ref") == evidence["order_ref"])
    assert pending["status"] == "strategic_directive_pending_operational_briefing"
    assert pending["actionability_status"] == "pending_operational_briefing"
    assert set(pending["applies_to_formation_refs"]) == set(QIN_REFS)
    assert set(pending["applies_to_formation_refs"]).isdisjoint(set(operation.get("auxiliary_formation_refs", [])))
    current = next(row for row in operation["operational_orders"] if row.get("order_ref") == PRIOR_ORDER_REF)
    assert current["actionability_status"] == "actionable"


def test_pending_directive_routes_exactly_one_support_review_while_prior_mission_remains_current(campaign):
    planner = _planner(campaign)
    op_path = _prepare_actionable_scope(planner)
    evidence = _issue_broad_directive(planner)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))

    sync_qin_command_support(planner, runtime)
    sync_qin_command_support(planner, runtime)

    hosts = _auto_hosts(runtime)
    assert len(hosts) == 1
    assert hosts[0]["operation_ref"] == OP_REF
    assert hosts[0]["order_ref"] == evidence["order_ref"]
    assert set(hosts[0]["formation_refs"]) == set(QIN_REFS)
    assert planner.read(op_path)["last_operational_order_ref"] == PRIOR_ORDER_REF


def test_exact_support_review_promotes_only_after_staff_packet_exists(campaign):
    planner = _planner(campaign)
    op_path = _prepare_actionable_scope(planner)
    evidence = _issue_broad_directive(planner)
    pending_ref = str(evidence["order_ref"])
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    sync_qin_command_support(planner, runtime)
    host = _auto_hosts(runtime)[0]

    assert planner.read(op_path)["last_operational_order_ref"] == PRIOR_ORDER_REF
    wake = settle_qin_command_support(planner, host, str(host["next_due"]))

    assert wake is not None
    operation = planner.read(op_path)
    assert operation["last_operational_order_ref"] == pending_ref
    promoted = next(row for row in operation["operational_orders"] if row.get("order_ref") == pending_ref)
    assert promoted["actionability_status"] == "actionable"
    assert promoted["status"] == "staff_briefed_awaiting_commander_execution"
    assert isinstance(promoted.get("mission_packet"), dict)
    prior = next(row for row in operation["operational_orders"] if row.get("order_ref") == PRIOR_ORDER_REF)
    assert prior["mission_packet"]["agency_rule"].startswith("Contact is not a general-attack order")
    response = get_causal_event(planner, wake["campaign_event_ref"])
    assert response["process_stage"] == "operational_briefing"
    delivery = planner.read(QIN_COMMAND_SUPPORT_DELIVERY_INDEX)
    assert delivery["by_order"][OP_REF]["order_ref"] == pending_ref


def test_vitality_flags_pending_briefing_without_route_and_clears_after_sync(campaign):
    planner = _planner(campaign)
    _prepare_actionable_scope(planner)
    _issue_broad_directive(planner)

    class _Store:
        def read_json(self, path):
            return planner.read(path)

    before = summarize_playability_vitality(_Store())
    assert before["blocked_pending_qin_operational_briefings"] == 1
    assert "pending_qin_operational_briefing_without_support_route" in before["diagnostics"]

    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    sync_qin_command_support(planner, runtime)
    planner.put("state/runtime.json", runtime)
    after = summarize_playability_vitality(_Store())
    assert after["blocked_pending_qin_operational_briefings"] == 0
    assert "pending_qin_operational_briefing_without_support_route" not in after["diagnostics"]
    assert after["scheduled_player_relevant_hosts"] >= 1
