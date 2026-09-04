from __future__ import annotations

import json
from pathlib import Path

from sword_runtime.api.campaign_planning_operations import CampaignPlanningAwareOperations
from sword_runtime.api.command_discovery import compact_play_context
from sword_runtime.engine import SwordRuntime


_OPERATION_REF = "operation_arc_131572c4e8a2892bbc"
def _operation(context: dict) -> dict:
    return next(row for row in context["controlled_operations"] if row.get("operation_ref") == _OPERATION_REF)


def _encoded_size(value) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def test_live_context_overlays_current_planning_without_rewriting_legacy_briefing(campaign):
    root = Path(campaign)
    operation_state = json.loads((root / f"state/operations/{_OPERATION_REF}.json").read_text())
    briefing_ref = operation_state["briefing_information_ref"]
    briefing_path = root / "state/information" / f"{briefing_ref}.json"
    meta_path = root / "state/meta.json"
    briefing_before = briefing_path.read_bytes()
    meta_before = meta_path.read_bytes()

    operations = CampaignPlanningAwareOperations(SwordRuntime(campaign))
    context = operations.play_context()
    operation = _operation(context)

    assert operation["briefing_information_ref"] == briefing_ref
    assert operation["campaign_context"]["march_planning"]["strategic_target_ref"] == "loc_sanyou"
    assert briefing_path.read_bytes() == briefing_before
    assert meta_path.read_bytes() == meta_before

    campaign_command = operation["campaign_command"]
    planning = campaign_command["march_planning"]
    assert planning["kind"] == "staff_route_capacity_baseline"
    scheme = planning["campaign_scheme"]
    assert scheme["kind"] == "pre_entry_campaign_staff_scheme"
    assert scheme["strategic_anchor_ref"] == "loc_sanyou"
    assert scheme["objective_count"] >= 2
    assert scheme["command_assignments"]

    hierarchy = scheme["command_hierarchy"]
    assert hierarchy["kind"] == "supreme_campaign_field_army"
    assert hierarchy["root_role"] == "supreme_campaign_command"
    assert hierarchy["subordinate_command_refs"]
    assert "beneath campaign supreme command" in hierarchy["subordination_rule"]
    assert "does not make it an independent campaign" in hierarchy["separation_rule"]

    overlay = campaign_command["march_planning_projection"]
    assert overlay["status"] == "current_read_only_projection"
    assert overlay["historical_briefing_unchanged"] is True
    assert "does not rewrite the historical briefing" in overlay["authority_rule"]
    assert "issue an order" in overlay["authority_rule"]
    assert "advance campaign time" in overlay["authority_rule"]


def test_live_planning_overlay_counts_recursive_house_subordinates_without_reowning_them(campaign):
    operations = CampaignPlanningAwareOperations(SwordRuntime(campaign))
    operation = _operation(operations.play_context())
    planning = operation["campaign_command"]["march_planning"]
    scheme = planning["campaign_scheme"]
    assignments = {row["commander_name"]: row for row in scheme["command_assignments"]}

    mou_gou = assignments["Mou Gou"]
    assert mou_gou["state_owned_personnel"] == 73200
    assert mou_gou["non_state_subordinate_personnel"] == 21991
    assert mou_gou["personnel"] == 95191

    ouki = assignments["Ouki"]
    assert ouki["state_owned_personnel"] == 46100
    assert ouki["non_state_subordinate_personnel"] == 13994
    assert ouki["personnel"] == 60094

    tang_wei = assignments["Tang Wei"]
    assert tang_wei["state_owned_personnel"] == 5000
    assert tang_wei["non_state_subordinate_personnel"] == 4500
    assert tang_wei["personnel"] == 9500

    assert scheme["state_owned_planned_strength"] == 172300
    assert scheme["non_state_subordinate_strength"] == 40485
    assert scheme["command_span_planned_strength"] == 212785
    assert scheme["excluded_non_state_strength"] == 40485
    assert operation["campaign_context"]["friendly_total_strength"] == 212785
    assert scheme["command_hierarchy"]["state_owned_strength"] == 172300
    assert scheme["command_hierarchy"]["command_span_strength"] == 212785
    assert "does not transfer ownership" in scheme["ownership_rule"]

    sanyou = next(row for row in scheme["objectives"] if row["objective_ref"] == "loc_sanyou")
    assert sanyou["assigned_strength"] == 109691
    keiyou = next(row for row in scheme["objectives"] if row["objective_ref"] == "loc_keiyou")
    assert keiyou["assigned_strength"] == 60094

    route_strengths = {
        (row["command_ref"], row["origin_ref"]): row["strength"]
        for row in planning["command_routes"]
    }
    tang_wei_group = next(
        row for row in operations.play_context()["controlled_command_groups"]
        if row.get("command_group_ref") == "cmdgrp.tang_wei.field_army"
    )
    assert route_strengths[("cmdgrp.tang_wei.field_army", tang_wei_group["location_ref"])] == 9500
    assert any(load["combined_strength"] > 83200 for load in planning["shared_bottlenecks"])


def test_live_planning_overlay_preserves_staff_plan_authority_boundaries(campaign):
    operations = CampaignPlanningAwareOperations(SwordRuntime(campaign))
    operation = _operation(operations.play_context())
    planning = operation["campaign_command"]["march_planning"]
    scheme = planning["campaign_scheme"]

    assert "does not issue an order" in scheme["authority_rule"]
    assert "authorize hostile entry" in scheme["authority_rule"]
    assert "transfer troop ownership" in scheme["authority_rule"]
    assert "does not assign a route" in planning["authority_rule"]

    planned_command_refs = {
        row["command_ref"] for row in scheme["command_assignments"] + scheme["strategic_reserve_commands"]
    }
    assert set(scheme["command_hierarchy"]["subordinate_command_refs"]) == planned_command_refs


def test_compact_live_context_keeps_campaign_decisions_and_drops_redundant_bulk(campaign):
    operations = CampaignPlanningAwareOperations(SwordRuntime(campaign))
    full = operations.play_context()
    full_operation = _operation(full)
    assert full_operation["campaign_context"]["other_friendly_participants"]
    assert any(route.get("segments") for route in full_operation["campaign_command"]["march_planning"]["command_routes"])

    compact = compact_play_context(full)
    encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    diagnostics = {
        "total": len(encoded),
        "top": sorted(((key, _encoded_size(value)) for key, value in compact.items()), key=lambda item: item[1], reverse=True)[:16],
        "operation": sorted(((key, _encoded_size(value)) for key, value in _operation(compact).items()), key=lambda item: item[1], reverse=True)[:16],
        "campaign_command": sorted(((key, _encoded_size(value)) for key, value in _operation(compact)["campaign_command"].items()), key=lambda item: item[1], reverse=True)[:16],
    }
    if len(encoded) >= 48_000:
        print("COMPACT_SIZE_DIAGNOSTICS=" + json.dumps(diagnostics, separators=(",", ":")))
    assert len(encoded) < 48_000

    operation = _operation(compact)
    campaign_context = operation["campaign_context"]
    assert "other_friendly_participants" not in campaign_context
    assert campaign_context["other_friendly_participant_count"] >= 1
    assert campaign_context["friendly_total_strength"] == 212785

    planning = operation["campaign_command"]["march_planning"]
    scheme = planning["campaign_scheme"]
    assert scheme["objectives"]
    assert scheme["strategic_anchor_ref"] == "loc_sanyou"
    assert scheme["campaign_scope_kind"] == "regional_campaign"
    assert scheme["command_hierarchy"]["kind"] == "supreme_campaign_field_army"
    assert scheme["command_hierarchy"]["subordinate_command_count"] >= 1
    assert scheme["command_assignment_count"] >= 1
    assert scheme["strategic_reserve_command_count"] >= 1
    assert planning["command_route_count"] >= 1
    assert planning["shared_bottleneck_count"] >= 1
    assert planning["detail_rule"] == "demand_load_exact_operation_for_route_assignment_or_bottleneck_detail"
    assert "command_assignments" not in scheme
    assert "command_routes" not in planning
    assert "shared_bottlenecks" not in planning

    deep = compact["gm_scene_context"]["deep_reads"]
    assert "permitted_person_refs" not in deep
    assert "permitted_object_refs" not in deep
    assert "read_hints" not in deep
    assert deep["permitted_person_refs_source"] == "play_context.permitted_person_ids"
    assert deep["permitted_object_refs_source"] == "play_context.permitted_object_refs"
    assert deep["read_hints_source"] == "play_context.read_hints"
