from __future__ import annotations

import copy

from sword_runtime.api.stable_operations import StableCampaignOperations
from sword_runtime.causal_event_store import read_causal_event_owner, write_causal_event_owner
from sword_runtime.information_handoff import record_delivered_world_arc_report_information
from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime


def test_delivered_world_arc_report_becomes_player_known_information(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    now = str(planner.read("state/runtime.json")["world_time"])
    source_ref = "event_world_arc_information_handoff_source"
    report_ref = source_ref + ".report"
    _path, owner = read_causal_event_owner(planner)
    owner.setdefault("causal_events", {})[report_ref] = {
        "event_ref": report_ref,
        "kind": "world_arc_report",
        "status": "triggered",
        "due_at": now,
        "triggered_at": now,
        "arc_ref": "arc_ryo_fui_northern_wei_campaign",
        "source_event_ref": source_ref,
        "summary": "Reports establish that the campaign has produced an active military operation; tactical particulars remain unavailable.",
        "delivery": {
            "target_ref": "char_tang_wei",
            "location_ref": "loc_tang_manor_training_ground",
            "route": "military dispatches and merchant reports",
        },
        "provenance": {
            "kind": "world_arc_information_propagation",
            "exposure_roll": 10,
            "exposure_chance": 70,
            "player_safe_evidence_kind": "exact_operation_created",
        },
    }
    write_causal_event_owner(planner, owner)

    information_ref = record_delivered_world_arc_report_information(
        planner,
        {
            "kind": "world_arc_report",
            "arc_ref": "arc_ryo_fui_northern_wei_campaign",
            "source_event_ref": source_ref,
            "visibility": "discoverable",
        },
        now,
    )

    assert isinstance(information_ref, str)
    index = planner.read("state/information/index.json")
    assert information_ref in index["by_holder"]["char_tang_wei"]
    claim = planner.read(index["claims"][information_ref])
    assert claim["origin_authority"] == "runtime_established"
    assert claim["world_truth_authority"] is False
    assert claim["epistemic_kind"] == "report"
    assert claim["knowers"] == ["char_tang_wei"]
    assert claim["fact"] == owner["causal_events"][report_ref]["summary"]
    assert "material_evidence" not in claim
    # The causal report already owns the actual journey. Duplicating a partial
    # information delivery would either violate the information schema or invent
    # transport details that the report bridge does not know.
    assert "deliveries" not in claim

    subjects = planner.read("state/information/subject-index.json")["subjects"]
    assert information_ref in subjects[report_ref]
    assert information_ref in subjects["arc_ryo_fui_northern_wei_campaign"]


def test_unattested_report_does_not_create_new_player_knowledge(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    now = str(planner.read("state/runtime.json")["world_time"])
    source_ref = "event_world_arc_unattested_report"
    report_ref = source_ref + ".report"
    before_index = copy.deepcopy(planner.read("state/information/index.json"))
    _path, owner = read_causal_event_owner(planner)
    owner.setdefault("causal_events", {})[report_ref] = {
        "event_ref": report_ref,
        "kind": "world_arc_report",
        "status": "triggered",
        "due_at": now,
        "triggered_at": now,
        "arc_ref": "arc_ryo_fui_northern_wei_campaign",
        "source_event_ref": source_ref,
        "summary": "Generic material work settled.",
        "delivery": {
            "target_ref": "char_tang_wei",
            "location_ref": "loc_tang_manor_training_ground",
            "route": "military dispatches and merchant reports",
        },
        "provenance": {"kind": "world_arc_information_propagation"},
    }
    write_causal_event_owner(planner, owner)

    result = record_delivered_world_arc_report_information(
        planner,
        {
            "arc_ref": "arc_ryo_fui_northern_wei_campaign",
            "source_event_ref": source_ref,
            "visibility": "discoverable",
        },
        now,
    )

    assert result is None
    assert planner.read("state/information/index.json") == before_index


def test_latest_report_subject_points_to_accumulated_arc_dossier(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    now = str(planner.read("state/runtime.json")["world_time"])
    _path, owner = read_causal_event_owner(planner)
    arc_ref = "arc_ryo_fui_northern_wei_campaign"

    initial_subjects = planner.read("state/information/subject-index.json")["subjects"]
    prior_arc_refs = set(initial_subjects.get(arc_ref, []))

    refs = []
    for suffix in ("one", "two"):
        source_ref = f"event_world_arc_information_handoff_{suffix}"
        report_ref = source_ref + ".report"
        owner.setdefault("causal_events", {})[report_ref] = {
            "event_ref": report_ref,
            "kind": "world_arc_report",
            "status": "triggered",
            "due_at": now,
            "triggered_at": now,
            "arc_ref": arc_ref,
            "source_event_ref": source_ref,
            "summary": f"Delivered report {suffix}.",
            "delivery": {
                "target_ref": "char_tang_wei",
                "location_ref": "loc_tang_manor_training_ground",
                "route": "military dispatch",
            },
            "provenance": {
                "kind": "world_arc_information_propagation",
                "player_safe_evidence_kind": "exact_operation_created",
            },
        }
        write_causal_event_owner(planner, owner)
        ref = record_delivered_world_arc_report_information(
            planner,
            {"arc_ref": arc_ref, "source_event_ref": source_ref, "visibility": "direct"},
            now,
        )
        refs.append(ref)
        owner = copy.deepcopy(read_causal_event_owner(planner)[1])

    subjects = planner.read("state/information/subject-index.json")["subjects"]
    latest_report_ref = "event_world_arc_information_handoff_two.report"
    expected_dossier = prior_arc_refs | set(refs)
    assert set(subjects[latest_report_ref]) == expected_dossier
    assert set(subjects[arc_ref]) == expected_dossier


def test_known_information_exposes_age_freshness_and_supersession_without_deleting_history(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    now = CampaignTime.parse(str(planner.read("state/runtime.json")["world_time"]))
    arc_ref = "test_arc_information_freshness"
    times = [str(now.add_seconds(-45 * 86400)), str(now)]
    refs = []
    for i, at in enumerate(times, 1):
        source_ref = f"event_world_arc_freshness_{i}"
        report_ref = source_ref + ".report"
        _path, owner = read_causal_event_owner(planner)
        owner.setdefault("causal_events", {})[report_ref] = {
            "event_ref": report_ref, "kind": "world_arc_report", "status": "triggered",
            "due_at": at, "triggered_at": at, "arc_ref": arc_ref, "source_event_ref": source_ref,
            "summary": f"Campaign assessment {i}.",
            "delivery": {"target_ref": "char_tang_wei", "location_ref": "loc_tang_manor", "route": "military dispatch"},
            "provenance": {"kind": "world_arc_information_propagation", "player_safe_evidence_kind": "exact_operation_created"},
        }
        write_causal_event_owner(planner, owner)
        refs.append(record_delivered_world_arc_report_information(planner, {"arc_ref": arc_ref, "source_event_ref": source_ref, "visibility": "direct"}, at))

    class _Store:
        def read_json(self, path): return planner.read(path)
    class _Runtime:
        store = _Store()
    rows = {row["information_ref"]: row for row in StableCampaignOperations(_Runtime())._known_information("char_tang_wei")}
    older, newer = rows[refs[0]], rows[refs[1]]
    assert older["created_at"] == times[0] and older["learned_at"] == times[0]
    assert older["source_age_days"] >= 44.9
    assert older["freshness"] in {"aging", "stale"}
    assert older["assessment_status"] == "historical_superseded"
    assert older["superseded_by_ref"] == refs[1]
    assert newer["assessment_status"] == "current_assessment"
    assert newer["supersedes_ref"] == refs[0]
    assert newer["freshness"] == "fresh"
    assert refs[0] in planner.read("state/information/index.json")["claims"]


def test_hot_play_context_omits_superseded_information_but_paging_preserves_it(campaign, tmp_path):
    from sword_runtime.service_runtime import ProductionSwordRuntime
    from sword_runtime.api.stable_operations import StableCampaignOperations

    runtime = ProductionSwordRuntime(campaign, tmp_path / "runtime")
    operations = StableCampaignOperations(runtime)
    all_rows = operations._all_known_information("char_tang_wei")
    superseded = [row for row in all_rows if row.get("assessment_status") == "historical_superseded"]
    current = [row for row in all_rows if row.get("assessment_status") != "historical_superseded"]

    context = operations.play_context()
    assert all(row.get("assessment_status") != "historical_superseded" for row in context["known_information"])
    assert context["known_information_count"] == len(all_rows)
    assert context["known_information_current_count"] == len(current)
    assert context["known_information_historical_count"] == len(superseded)
    if superseded:
        assert context["known_information_truncated"] is True
        assert context["read_hints"]["known_information_page"]["next_cursor"] == "0"
        page = operations.list_known_information(limit=64)
        paged_refs = {row["information_ref"] for row in page["known_information"]}
        assert {row["information_ref"] for row in superseded} <= paged_refs
