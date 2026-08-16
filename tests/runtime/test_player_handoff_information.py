from __future__ import annotations

import copy

from sword_runtime.causal_event_store import read_causal_event_owner, write_causal_event_owner
from sword_runtime.information_handoff import record_delivered_world_arc_report_information
from sword_runtime.production_planner import ProductionCampaignPlanner


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
    assert set(subjects[latest_report_ref]) == set(refs)
    assert set(subjects[arc_ref]) == set(refs)
