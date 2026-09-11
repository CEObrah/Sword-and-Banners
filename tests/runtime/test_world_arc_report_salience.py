from __future__ import annotations

import copy

from sword_runtime.campaign_event_planner import CampaignEventPlayerGroupActionPlanner
from sword_runtime.causal_event_store import get_causal_event, read_causal_event_owner, write_causal_event_owner
from sword_runtime.world_arcs import _player_controlled_arc_operation, _schedule_report_route, settle_world_arc_report, settle_world_arc_review
from sword_runtime.world_arc_report_handoff import settle_player_safe_world_arc_report


def _planner(campaign):
    planner = CampaignEventPlayerGroupActionPlanner(campaign)
    planner._reset()
    return planner


def _install_source(planner, event_ref: str, at: str, result: str) -> None:
    _path, owner = read_causal_event_owner(planner)
    owner["causal_events"][event_ref] = {
        "event_ref": event_ref,
        "kind": "world_arc_activity",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "arc_ref": "arc_ryo_fui_northern_wei_campaign",
        "actor_ref": "state_qin",
        "basis_goal": "prepare a northern operation",
        "result": result,
        "evidence_stage": "domain_action" if result == "material_action_settled" else "intent",
        "required_evidence_stage": "domain_action",
        "pressure_stage": "material",
        "visibility_class": "direct",
        "summary": f"Test arc activity with result {result}.",
        "provenance": {
            "kind": "world_arc_orchestration",
            "arc_owner_ref": "kingdom_arcs",
            "review_count": 1,
            "domain_status": result,
            "evidence_stage": "domain_action" if result == "material_action_settled" else "intent",
            "required_evidence_stage": "domain_action",
            "domain_action_ref": "state_qin",
        },
    }
    write_causal_event_owner(planner, owner)


def _scheduled_host(planner, source_event_ref: str, at: str) -> dict:
    _schedule_report_route(
        planner,
        arc_ref="arc_ryo_fui_northern_wei_campaign",
        source_event_ref=source_event_ref,
        at=at,
        route="House Tang direct report",
        origin_state="qin",
        pressure_stage="material",
        visibility="direct",
    )
    runtime = planner.read("state/runtime.json")
    rows = [
        row for row in runtime["hosts"].values()
        if row.get("kind") == "world_arc_report" and row.get("source_event_ref") == source_event_ref
    ]
    assert len(rows) == 1
    return copy.deepcopy(rows[0])


def test_preexisting_queued_arc_report_route_terminates_without_player_report(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    source_ref = "event_test_arc_work_queued"
    _install_source(planner, source_ref, at, "work_queued")
    host = _scheduled_host(planner, source_ref, at)

    assert settle_world_arc_report(planner, host, at) is None
    runtime_host = planner.read("state/runtime.json")["hosts"][host["host_id"]]
    assert runtime_host["recurrence_seconds"] == 0
    assert get_causal_event(planner, source_ref + ".report") is None


def test_material_arc_activity_still_propagates_player_report(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    source_ref = "event_test_arc_material_settlement"
    _install_source(planner, source_ref, at, "material_action_settled")
    host = _scheduled_host(planner, source_ref, at)

    assert settle_world_arc_report(planner, host, at) is None
    report = get_causal_event(planner, source_ref + ".report")
    assert report is not None
    assert report["kind"] == "world_arc_report"
    assert report["delivery"]["target_ref"] == "char_tang_wei"
    assert "material domain work that actually settled" in report["summary"]


def test_blocked_arc_attempt_route_terminates_without_player_report(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    source_ref = "event_test_arc_work_blocked"
    _install_source(planner, source_ref, at, "work_blocked")
    host = _scheduled_host(planner, source_ref, at)

    assert settle_world_arc_report(planner, host, at) is None
    runtime_host = planner.read("state/runtime.json")["hosts"][host["host_id"]]
    assert runtime_host["recurrence_seconds"] == 0
    assert get_causal_event(planner, source_ref + ".report") is None



def test_northern_wei_controlled_operation_block_reports_truthfully_without_spam(campaign) -> None:
    from sword_runtime.production_planner import ProductionCampaignPlanner

    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    arc_ref = "arc_ryo_fui_northern_wei_campaign"
    operation_ref = "operation_arc_131572c4e8a2892bbc"
    now = str(planner.read("state/runtime.json")["world_time"])

    evidence = _player_controlled_arc_operation(
        planner,
        arc_ref,
        actor_ref="state_qin",
        outcome={"status": "work_blocked", "reason": "test exact supply constraint"},
    )
    assert evidence is not None
    assert evidence["operation_ref"] == operation_ref
    assert evidence["command_group_ref"] == "cmdgrp.tang_wei.field_army"

    # An opposing Wei failure on the same broad arc must never masquerade as
    # Tang Wei's field-army stall merely because both operations share the arc.
    assert _player_controlled_arc_operation(
        planner,
        arc_ref,
        actor_ref="state_wei",
        outcome={"status": "work_blocked", "reason": "opposing constraint"},
    ) is None

    planner._world_arc_completed_priority = lambda actor_ref, arc_ref: ({
        "status": "work_blocked",
        "reason": "test exact supply constraint",
        "operation_ref": operation_ref,
        "effect": {"goal": "advance the controlled Qin operation", "target_ref": "state_wei"},
    } if actor_ref == "state_qin" else None)
    planner._world_arc_domain_action = lambda actor_ref, target_ref, goal, at, arc_ref: {
        "status": "work_blocked",
        "reason": "test exact supply constraint",
        "operation_ref": operation_ref,
    }
    host = {"kind": "world_arc", "owner_ref": "kingdom_arcs", "arc_ref": arc_ref}
    settle_world_arc_review(planner, host, now)

    arcs = planner.read("state/arc/kingdom-arcs.json")
    record = next(row for row in arcs["records"] if row.get("record_id") == arc_ref)
    source_ref = record["runtime"]["last_initiative_ref"]
    source = get_causal_event(planner, source_ref)
    assert source is not None
    assert source["result"] == "work_blocked"
    controlled = source["provenance"].get("controlled_operation_evidence")
    assert controlled["operation_ref"] == operation_ref

    runtime = planner.read("state/runtime.json")
    report_hosts = [
        copy.deepcopy(row) for row in runtime["hosts"].values()
        if row.get("kind") == "world_arc_report" and row.get("source_event_ref") == source_ref
    ]
    assert len(report_hosts) == 1
    report_host = report_hosts[0]
    assert report_host["route"] == "Field Army military dispatches"
    assert report_host["visibility"] == "direct"

    # Military dispatches remain a lawful explicit information channel, but
    # Wei is now authoritatively at Kanyou after completed staging rather than
    # co-present at the eastern depot. The report must persist without becoming
    # a hard wake; only an acute/direct delivery is required to return a handoff.
    due = report_host["next_due"]
    handoff = settle_player_safe_world_arc_report(planner, report_host, due)
    if handoff is not None:
        assert handoff["kind"] == "campaign_event"
    assert planner.read("state/runtime.json").get("pending_wake") in (None, {})
    report = get_causal_event(planner, source_ref + ".report")
    assert report is not None
    assert report["delivery"]["target_ref"] == "char_tang_wei"
    assert report["delivery"]["route"] == "Field Army military dispatches"
    assert "blocked by material, informational, or institutional constraints" in report["summary"]
    assert operation_ref not in report["summary"]

    # Same reason inside the seven-day suppression interval remains causal
    # history but must not schedule a second player-facing stall report.
    later = str(__import__("sword_runtime.sim.calendar", fromlist=["CampaignTime"]).CampaignTime.parse(now).add_seconds(86400))
    settle_world_arc_review(planner, host, later)
    arcs2 = planner.read("state/arc/kingdom-arcs.json")
    record2 = next(row for row in arcs2["records"] if row.get("record_id") == arc_ref)
    source_ref2 = record2["runtime"]["last_initiative_ref"]
    assert source_ref2 != source_ref
    runtime2 = planner.read("state/runtime.json")
    second_hosts = [
        row for row in runtime2["hosts"].values()
        if row.get("kind") == "world_arc_report" and row.get("source_event_ref") == source_ref2
    ]
    assert second_hosts == []
