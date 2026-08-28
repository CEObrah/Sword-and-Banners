from __future__ import annotations

import json
from pathlib import Path

from sword_runtime.api.campaign_planning_operations import CampaignPlanningAwareOperations
from sword_runtime.api.command_discovery import compact_play_context
from sword_runtime.engine import SwordRuntime


_OPERATION_REF = "operation_arc_131572c4e8a2892bbc"
_BRIEFING_REF = "information.qin_campaign_briefing.a98b9575d13e9931a873"
_BRIEFING_PATH = f"state/information/{_BRIEFING_REF}.json"


def _operation(context: dict) -> dict:
    return next(
        row for row in context["controlled_operations"]
        if row.get("operation_ref") == _OPERATION_REF
    )


def _encoded_size(value) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def test_live_context_overlays_current_planning_without_rewriting_legacy_briefing(campaign):
    root = Path(campaign)
    briefing_path = root / _BRIEFING_PATH
    meta_path = root / "state/meta.json"
    briefing_before = briefing_path.read_bytes()
    meta_before = meta_path.read_bytes()

    operations = CampaignPlanningAwareOperations(SwordRuntime(campaign))
    context = operations.play_context()
    operation = _operation(context)

    # Historical information remains the snapshot that was actually issued.
    assert operation["briefing_information_ref"] == _BRIEFING_REF
    assert "march_planning" not in operation["campaign_context"]
    assert briefing_path.read_bytes() == briefing_before
    assert meta_path.read_bytes() == meta_before

    # Live command context receives the current read-only staff projection.
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
    assert "remain under the campaign supreme command" in hierarchy["subordination_rule"]
    assert "does not make it an independent campaign" in hierarchy["separation_rule"]

    overlay = campaign_command["march_planning_projection"]
    assert overlay["status"] == "current_read_only_projection"
    assert overlay["historical_briefing_unchanged"] is True
    assert "does not rewrite the historical briefing" in overlay["authority_rule"]
    assert "issue an order" in overlay["authority_rule"]
    assert "advance campaign time" in overlay["authority_rule"]


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
        row["command_ref"]
        for row in scheme["command_assignments"] + scheme["strategic_reserve_commands"]
    }
    assert set(scheme["command_hierarchy"]["subordinate_command_refs"]) == planned_command_refs


def test_compact_live_context_keeps_campaign_decisions_and_drops_redundant_bulk(campaign):
    operations = CampaignPlanningAwareOperations(SwordRuntime(campaign))
    full = operations.play_context()
    full_operation = _operation(full)
    assert full_operation["campaign_context"]["other_friendly_participants"]
    assert any(
        route.get("segments")
        for route in full_operation["campaign_command"]["march_planning"]["command_routes"]
    )

    compact = compact_play_context(full)
    encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    top_sizes = sorted(
        ((key, _encoded_size(value)) for key, value in compact.items()),
        key=lambda item: item[1],
        reverse=True,
    )[:12]
    operation_sizes = sorted(
        ((key, _encoded_size(value)) for key, value in _operation(compact).items()),
        key=lambda item: item[1],
        reverse=True,
    )[:12]
    command_sizes = sorted(
        ((key, _encoded_size(value)) for key, value in _operation(compact)["campaign_command"].items()),
        key=lambda item: item[1],
        reverse=True,
    )[:12]
    assert len(encoded) < 48_000, {
        "total": len(encoded),
        "top": top_sizes,
        "operation": operation_sizes,
        "campaign_command": command_sizes,
    }

    operation = _operation(compact)
    campaign_context = operation["campaign_context"]
    assert "other_friendly_participants" not in campaign_context
    assert campaign_context["other_friendly_participant_count"] >= 1

    planning = operation["campaign_command"]["march_planning"]
    scheme = planning["campaign_scheme"]
    assert scheme["objectives"]
    assert scheme["command_assignments"]
    assert "strategic_reserve_commands" in scheme
    assert scheme["command_hierarchy"]["kind"] == "supreme_campaign_field_army"
    assert scheme["command_hierarchy"]["subordinate_command_refs"]

    # Route paths and real shared bottlenecks remain visible, while verbose
    # per-segment geometry is demand-loaded rather than repeated every turn.
    assert planning["command_routes"]
    assert all("segments" not in route for route in planning["command_routes"])
    assert all("path_names" in route for route in planning["command_routes"])
    assert "shared_bottlenecks" in planning
