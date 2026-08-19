from __future__ import annotations

import copy

from sword_runtime.campaign_event_planner import CampaignEventPlayerGroupActionPlanner
from sword_runtime.causal_event_store import get_causal_event, read_causal_event_owner, write_causal_event_owner
from sword_runtime.world_arc_report_handoff import settle_player_safe_world_arc_report
from sword_runtime.world_arcs import _schedule_report_route


def _planner(campaign):
    planner = CampaignEventPlayerGroupActionPlanner(campaign)
    planner._reset()
    return planner


def _install_material_source(planner, event_ref: str, at: str, evidence: dict) -> None:
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
        "result": "material_action_settled",
        "evidence_stage": "domain_action",
        "required_evidence_stage": "domain_action",
        "pressure_stage": "acute",
        "visibility_class": "direct",
        "summary": "Internal material arc settlement.",
        "provenance": {
            "kind": "world_arc_orchestration",
            "arc_owner_ref": "kingdom_arcs",
            "review_count": 1,
            "domain_status": "material_action_settled",
            "evidence_stage": "domain_action",
            "required_evidence_stage": "domain_action",
            "domain_action_ref": "state_qin",
            "material_evidence": copy.deepcopy(evidence),
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
        pressure_stage="acute",
        visibility="direct",
    )
    runtime = planner.read("state/runtime.json")
    rows = [
        row for row in runtime["hosts"].values()
        if row.get("kind") == "world_arc_report" and row.get("source_event_ref") == source_event_ref
    ]
    assert len(rows) == 1
    return copy.deepcopy(rows[0])


def test_exact_operation_evidence_becomes_clear_bounded_report(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    source_ref = "event_test_player_safe_operation"
    _install_material_source(
        planner,
        source_ref,
        at,
        {
            "kind": "exact_operation_created",
            "operation_ref": "operation_test_northern_wei",
            "formation_ref": "formation_test_qin",
            "formation_status_before": "ready",
            "formation_status_after": "mobilized",
            "evidence_stage": "domain_action",
        },
    )
    host = _scheduled_host(planner, source_ref, at)

    wake = settle_player_safe_world_arc_report(planner, host, at)

    report = get_causal_event(planner, source_ref + ".report")
    assert report is not None
    assert "active military operation" in report["summary"]
    assert "preparation, intent" in report["summary"]
    assert "exact force, route, commander" in report["summary"]
    assert "material domain work that actually settled" not in report["summary"]
    assert report["provenance"]["player_safe_evidence_kind"] == "exact_operation_created"
    assert wake is not None
    assert wake["reason"] == report["summary"]


def test_opaque_material_evidence_is_removed_before_player_handoff(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    source_ref = "event_test_opaque_material"
    _install_material_source(
        planner,
        source_ref,
        at,
        {
            "kind": "mobilization_readiness_changed",
            "before": 40,
            "after": 50,
            "evidence_stage": "domain_action",
        },
    )
    host = _scheduled_host(planner, source_ref, at)

    wake = settle_player_safe_world_arc_report(planner, host, at)

    assert wake is None
    assert get_causal_event(planner, source_ref + ".report") is None


def test_incomplete_operation_evidence_is_not_promoted_to_news(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    source_ref = "event_test_incomplete_operation"
    _install_material_source(
        planner,
        source_ref,
        at,
        {
            "kind": "exact_operation_created",
            "operation_ref": "operation_test_northern_wei",
            "evidence_stage": "domain_action",
        },
    )
    host = _scheduled_host(planner, source_ref, at)

    assert settle_player_safe_world_arc_report(planner, host, at) is None
    assert get_causal_event(planner, source_ref + ".report") is None
