from __future__ import annotations

import copy

from sword_runtime.campaign_event_planner import CampaignEventPlayerGroupActionPlanner
from sword_runtime.causal_event_store import get_causal_event, read_causal_event_owner, write_causal_event_owner
from sword_runtime.world_arc_report_handoff import settle_player_safe_world_arc_report
from sword_runtime.world_arcs import _schedule_report_route


_TEST_ARC_REF = "arc_ryo_fui_northern_wei_campaign"


def _planner(campaign):
    planner = CampaignEventPlayerGroupActionPlanner(campaign)
    planner._reset()
    # The repository fixture copies the current campaign, which may already hold
    # delivered reports for this live arc. Each handoff test owns a disposable
    # clone, so remove only prior report-delivery projections for this arc while
    # preserving their exact source events and all unrelated campaign state.
    _path, owner0 = read_causal_event_owner(planner)
    owner = copy.deepcopy(owner0)
    causal = owner.get("causal_events", {})
    if isinstance(causal, dict):
        for event_ref, event in list(causal.items()):
            if (
                isinstance(event, dict)
                and event.get("kind") == "world_arc_report"
                and event.get("arc_ref") == _TEST_ARC_REF
            ):
                causal.pop(event_ref, None)
    write_causal_event_owner(planner, owner)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    runtime.pop("player_safe_world_arc_claims", None)
    planner.put("state/runtime.json", runtime)
    return planner


def _install_material_source(planner, event_ref: str, at: str, evidence: dict) -> None:
    _path, owner = read_causal_event_owner(planner)
    owner["causal_events"][event_ref] = {
        "event_ref": event_ref,
        "kind": "world_arc_activity",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "arc_ref": _TEST_ARC_REF,
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
        arc_ref=_TEST_ARC_REF,
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


def _operation_evidence(operation_ref: str, formation_ref: str) -> dict:
    return {
        "kind": "exact_operation_created",
        "operation_ref": operation_ref,
        "formation_ref": formation_ref,
        "formation_status_before": "ready",
        "formation_status_after": "mobilized",
        "evidence_stage": "domain_action",
    }


def test_exact_operation_evidence_becomes_clear_bounded_report(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    source_ref = "event_test_player_safe_operation"
    _install_material_source(
        planner,
        source_ref,
        at,
        _operation_evidence("operation_test_northern_wei", "formation_test_qin"),
    )
    host = _scheduled_host(planner, source_ref, at)

    notice = settle_player_safe_world_arc_report(planner, host, at)

    report = get_causal_event(planner, source_ref + ".report")
    assert report is not None
    assert "active military operation" in report["summary"]
    assert "preparation, intent" in report["summary"]
    assert "exact force, route, commander" in report["summary"]
    assert "material domain work that actually settled" not in report["summary"]
    assert "operation_test_northern_wei" not in report["summary"]
    assert "formation_test_qin" not in report["summary"]
    assert report["provenance"]["player_safe_evidence_kind"] == "exact_operation_created"
    assert "player_safe_delta" not in report["provenance"]
    # The acute direct shape is a campaign-event notice for the causal scheduler.
    # It is not itself a persistent decision wake.
    assert notice is not None
    assert notice["kind"] == "campaign_event"
    assert notice["reason"] == report["summary"]


def test_distinct_operation_creation_reports_additional_commitment_without_hidden_ids(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])

    first_ref = "event_test_player_safe_operation_first"
    _install_material_source(
        planner,
        first_ref,
        at,
        _operation_evidence("operation_hidden_first", "formation_hidden_first"),
    )
    first_host = _scheduled_host(planner, first_ref, at)
    assert settle_player_safe_world_arc_report(planner, first_host, at) is not None

    second_ref = "event_test_player_safe_operation_second"
    _install_material_source(
        planner,
        second_ref,
        at,
        _operation_evidence("operation_hidden_second", "formation_hidden_second"),
    )
    second_host = _scheduled_host(planner, second_ref, at)
    notice = settle_player_safe_world_arc_report(planner, second_host, at)

    report = get_causal_event(planner, second_ref + ".report")
    assert report is not None
    assert notice is not None
    assert "further military commitment" in report["summary"]
    assert "another active military operation" in report["summary"]
    assert "additional material action" in report["summary"]
    assert "operation_hidden_first" not in report["summary"]
    assert "operation_hidden_second" not in report["summary"]
    assert "formation_hidden_first" not in report["summary"]
    assert "formation_hidden_second" not in report["summary"]
    assert report["provenance"]["player_safe_evidence_kind"] == "exact_operation_created"
    assert "player_safe_delta" not in report["provenance"]


def test_repeat_of_same_exact_operation_claim_is_suppressed_without_deleting_source(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    evidence = _operation_evidence("operation_hidden_repeat", "formation_hidden_repeat")

    first_ref = "event_test_player_safe_repeat_first"
    _install_material_source(planner, first_ref, at, evidence)
    first_host = _scheduled_host(planner, first_ref, at)
    assert settle_player_safe_world_arc_report(planner, first_host, at) is not None
    assert get_causal_event(planner, first_ref + ".report") is not None

    duplicate_ref = "event_test_player_safe_repeat_second"
    _install_material_source(planner, duplicate_ref, at, evidence)
    duplicate_host = _scheduled_host(planner, duplicate_ref, at)
    assert settle_player_safe_world_arc_report(planner, duplicate_host, at) is None

    # Exact causal source history remains intact. Only redundant information
    # delivery is suppressed.
    assert get_causal_event(planner, duplicate_ref) is not None
    assert get_causal_event(planner, duplicate_ref + ".report") is None
    runtime_host = planner.read("state/runtime.json")["hosts"][duplicate_host["host_id"]]
    assert runtime_host["recurrence_seconds"] == 0

    claims = planner.read("state/runtime.json").get("player_safe_world_arc_claims", [])
    exact_claims = [row for row in claims if row.get("evidence_kind") == "exact_operation_created"]
    assert len(exact_claims) == 1
    assert "operation_hidden_repeat" not in str(exact_claims)
    assert "formation_hidden_repeat" not in str(exact_claims)


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

    notice = settle_player_safe_world_arc_report(planner, host, at)

    assert notice is None
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
