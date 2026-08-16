from __future__ import annotations

import copy

from sword_runtime.campaign_event_planner import CampaignEventPlayerGroupActionPlanner
from sword_runtime.causal_event_store import get_causal_event, read_causal_event_owner, write_causal_event_owner
from sword_runtime.world_arcs import _schedule_report_route, settle_world_arc_report


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


def test_concrete_blocked_arc_attempt_remains_reportable(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    source_ref = "event_test_arc_work_blocked"
    _install_source(planner, source_ref, at, "work_blocked")
    host = _scheduled_host(planner, source_ref, at)

    assert settle_world_arc_report(planner, host, at) is None
    report = get_causal_event(planner, source_ref + ".report")
    assert report is not None
    assert "blocked by material, informational, or institutional constraints" in report["summary"]
