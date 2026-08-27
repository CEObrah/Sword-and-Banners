from __future__ import annotations

import copy
import json
import subprocess

from sword_runtime.causal_event_store import get_causal_event
from sword_runtime.production_runtime_planner import ProductionCampaignPlanner
from sword_runtime.qin_command_support_flow import QIN_COMMAND_SUPPORT_DELIVERY_INDEX, sync_qin_command_support
from sword_runtime.sim.calendar import CampaignTime
from conftest import execute_hosted_production


OPERATION_REF = "operation_arc_131572c4e8a2892bbc"
COMMAND_GROUP_REF = "cmdgrp.tang_wei.field_army"


def _flush_planner_fixture(campaign, planner, message: str) -> None:
    for rel, value in planner._writes.items():
        path = campaign / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for rel in planner._deletes:
        path = campaign / rel
        if path.exists():
            path.unlink()
    subprocess.run(["git", "-C", str(campaign), "add", "-A"], check=True)
    staged = subprocess.run(["git", "-C", str(campaign), "diff", "--cached", "--quiet"]).returncode
    if staged != 0:
        subprocess.run(["git", "-C", str(campaign), "commit", "--quiet", "-m", message], check=True)

QIN_FORMATION_REFS = [
    "formation_high_guard_qin_a", "formation_high_guard_qin_b",
    "formation_black_banner_01a", "formation_black_banner_01b",
    "formation_black_banner_02a", "formation_black_banner_02b",
    "formation_black_banner_03a", "formation_black_banner_03b",
    "formation_black_banner_04a", "formation_black_banner_04b",
]


def test_legacy_qin_appointment_routes_current_operation_from_command_group_context(campaign) -> None:
    planner = ProductionCampaignPlanner(campaign)
    planner.PLAYER_ACTOR = "char_tang_wei"
    planner._reset()

    player = copy.deepcopy(planner.read("state/player.json"))
    appointment = next(
        row for row in player.get("career_state", {}).get("appointments", [])
        if row.get("kind") == "qin_field_command" and row.get("status") == "active"
    )
    appointment.pop("operation_ref", None)
    appointment["command_group_ref"] = COMMAND_GROUP_REF
    appointment["formation_refs"] = list(QIN_FORMATION_REFS)
    planner.put("state/player.json", player)

    group_path = planner.owner_path(COMMAND_GROUP_REF)
    group = copy.deepcopy(planner.read(group_path))
    group["active_context_ref"] = OPERATION_REF
    planner.put(group_path, group)

    for ref in QIN_FORMATION_REFS:
        formation_path = planner.owner_path(ref)
        formation = copy.deepcopy(planner.read(formation_path))
        formation["administrative_owner"] = "state_qin"
        formation["command_authority"] = "char_tang_wei"
        planner.put(formation_path, formation)

    op_path = planner.read("state/operations/index.json")["operations"][OPERATION_REF]
    operation = copy.deepcopy(planner.read(op_path))
    order = copy.deepcopy(operation["operational_orders"][-1])
    order["order_ref"] = "operational_order_test_legacy_scope_auto_briefing"
    order["status"] = "strategic_directive_pending_operational_briefing"
    order["actionability_status"] = "pending_operational_briefing"
    order.pop("mission_packet", None)
    order.pop("staff_briefed_at", None)
    operation["operational_orders"].append(order)
    operation["last_operational_order_ref"] = order["order_ref"]
    operation["order_status"] = "awaiting_operational_briefing"
    planner.put(op_path, operation)

    planner.put(QIN_COMMAND_SUPPORT_DELIVERY_INDEX, {
        "schema": "generic-object", "authority": False, "by_operation": {}
    })
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    current = CampaignTime.parse(str(runtime["world_time"]))
    runtime["hosts"] = {}
    runtime["events"] = []
    runtime["scheduler"]["dirty"] = False
    runtime["scheduler"]["causal_settled_through"] = str(current)

    sync_qin_command_support(planner, runtime)
    hosts = [
        row for row in runtime["hosts"].values()
        if row.get("kind") == "qin_command_support_review"
        and row.get("support_kind") == "operational_briefing"
    ]
    assert len(hosts) == 1
    assert hosts[0]["operation_ref"] == OPERATION_REF
    planner.put("state/runtime.json", runtime)

    planner._active_command_type = "advance_time"
    result = planner._advance_causal_runtime(str(current.add_hours(1)))

    notices = result["campaign_event_notices"]
    assert len(notices) == 1
    response = get_causal_event(planner, notices[0]["campaign_event_ref"])
    assert response["process_kind"] == "qin_field_command_support"
    assert response["process_stage"] == "operational_briefing"

    operation = planner.read(op_path)
    assert operation["order_status"] == "staff_briefed_awaiting_commander_execution"
    assert operation["operational_orders"][-1]["actionability_status"] == "actionable"


def test_normal_advance_time_auto_briefs_legacy_qin_appointment(campaign) -> None:
    planner = ProductionCampaignPlanner(campaign)
    planner.PLAYER_ACTOR = "char_tang_wei"
    planner._reset()

    player = copy.deepcopy(planner.read("state/player.json"))
    appointment = next(
        row for row in player.get("career_state", {}).get("appointments", [])
        if row.get("kind") == "qin_field_command" and row.get("status") == "active"
    )
    appointment.pop("operation_ref", None)
    appointment["command_group_ref"] = COMMAND_GROUP_REF
    appointment["formation_refs"] = list(QIN_FORMATION_REFS)
    planner.put("state/player.json", player)

    group_path = planner.owner_path(COMMAND_GROUP_REF)
    group = copy.deepcopy(planner.read(group_path))
    group["active_context_ref"] = OPERATION_REF
    planner.put(group_path, group)

    for ref in QIN_FORMATION_REFS:
        formation_path = planner.owner_path(ref)
        formation = copy.deepcopy(planner.read(formation_path))
        formation["administrative_owner"] = "state_qin"
        formation["command_authority"] = "char_tang_wei"
        planner.put(formation_path, formation)

    op_path = planner.read("state/operations/index.json")["operations"][OPERATION_REF]
    operation = copy.deepcopy(planner.read(op_path))
    order = copy.deepcopy(operation["operational_orders"][-1])
    order["order_ref"] = "operational_order_test_legacy_scope_public_advance"
    order["status"] = "strategic_directive_pending_operational_briefing"
    order["actionability_status"] = "pending_operational_briefing"
    order.pop("mission_packet", None)
    order.pop("staff_briefed_at", None)
    operation["operational_orders"].append(order)
    operation["last_operational_order_ref"] = order["order_ref"]
    operation["order_status"] = "awaiting_operational_briefing"
    planner.put(op_path, operation)

    planner.put(QIN_COMMAND_SUPPORT_DELIVERY_INDEX, {
        "schema": "generic-object", "authority": False, "by_operation": {}
    })
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    runtime["hosts"] = {
        host_id: host for host_id, host in runtime.get("hosts", {}).items()
        if not (isinstance(host, dict) and host.get("kind") == "qin_command_support_review")
    }
    live_hosts = set(runtime["hosts"])
    runtime["events"] = [
        event for event in runtime.get("events", [])
        if not (
            isinstance(event, dict)
            and (event.get("kind") == "qin_command_support_review" or event.get("target_host") not in live_hosts)
        )
    ]
    planner.put("state/runtime.json", runtime)

    _flush_planner_fixture(
        campaign, planner, "test: legacy Qin appointment public advance fixture"
    )

    current = CampaignTime.parse(str(runtime["world_time"]))
    execute_hosted_production(
        campaign, "advance_time", {"target_time": str(current.add_hours(1))},
        request_id="legacy-qin-public-advance",
    )

    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    operation = planner.read(op_path)
    assert operation["order_status"] == "staff_briefed_awaiting_commander_execution"
    assert operation["operational_orders"][-1]["actionability_status"] == "actionable"
