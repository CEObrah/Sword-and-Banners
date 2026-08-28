from __future__ import annotations

import json
from pathlib import Path

from sword_runtime.production_runtime_planner import ProductionCampaignPlanner
from sword_runtime.sovereign_campaign_authority import (
    hostile_entry_authorized,
    projected_campaign_entry_authorities,
)


OPERATION_REF = "operation_arc_131572c4e8a2892bbc"


def _planner(campaign: Path) -> ProductionCampaignPlanner:
    planner = ProductionCampaignPlanner(campaign)
    planner.PLAYER_ACTOR = "char_tang_wei"
    planner._reset()
    return planner


def _raw_operation(root: Path) -> dict:
    index = json.loads((root / "state/operations/index.json").read_text(encoding="utf-8"))
    return json.loads((root / index["operations"][OPERATION_REF]).read_text(encoding="utf-8"))


def _formation_locations(root: Path, operation: dict) -> dict[str, str | None]:
    owners = json.loads((root / "state/index/owner-index.json").read_text(encoding="utf-8"))["owners"]
    return {
        ref: json.loads((root / owners[ref]).read_text(encoding="utf-8")).get("location_ref")
        for ref in operation["formation_refs"]
    }


def test_live_records_arc_shape_projects_exact_qin_campaign_entry_authority(campaign: Path) -> None:
    root = Path(campaign)
    planner = _planner(root)
    qin_path = root / "state/states/qin.json"
    qin_before = qin_path.read_bytes()
    raw_qin = json.loads(qin_before)

    assert raw_qin["diplomacy"]["state_wei"]["status"] == "neutral"
    assert raw_qin.get("war_intents", []) == []

    authorities = projected_campaign_entry_authorities(planner, "state_qin")
    authority = next(row for row in authorities if row["operation_ref"] == OPERATION_REF)
    assert authority["target_ref"] == "state_wei"
    assert authority["order_ref"] == "operational_order_669dd21e8390d23c6b"
    assert authority["arc_ref"] == "arc_ryo_fui_northern_wei_campaign"
    assert authority["kind"] == "exact_state_campaign_order_entry_authority"
    assert authority["projection_only"] is True
    assert hostile_entry_authorized(planner, "state_qin", "state_wei") is True

    projected_qin = planner.read("state/states/qin.json")
    derived = [
        row for row in projected_qin["war_intents"]
        if row.get("kind") == "exact_state_campaign_order_entry_authority"
    ]
    assert len(derived) == 1
    assert derived[0]["target_ref"] == "state_wei"
    assert projected_qin["diplomacy"]["state_wei"]["status"] == "neutral"
    assert qin_path.read_bytes() == qin_before


def test_reconciliation_reopens_completed_staging_without_moving_army_or_rewriting_diplomacy(campaign: Path) -> None:
    root = Path(campaign)
    planner = _planner(root)
    qin_path = root / "state/states/qin.json"
    qin_before = qin_path.read_bytes()
    operation_before = _raw_operation(root)
    locations_before = _formation_locations(root, operation_before)

    assert operation_before["campaign_phase"] == "awaiting_entry_authority"
    assert operation_before["operational_orders"][-1]["status"] == "staged_awaiting_entry_authority"
    assert operation_before["operational_orders"][-1]["mission_packet"]["hostile_entry_authorized"] is False

    refreshed = planner._reconcile_campaign_entry_authority()
    assert refreshed == [OPERATION_REF]

    operation_after = _raw_operation(root)
    latest = operation_after["operational_orders"][-1]
    packet = latest["mission_packet"]
    assert operation_after["campaign_phase"] == "campaign_concentration"
    assert operation_after["order_status"] == "staff_briefed_awaiting_commander_execution"
    assert latest["status"] == "staff_briefed_awaiting_commander_execution"
    assert latest["actionability_status"] == "actionable"
    assert packet["phase_status"] == "ready_for_commander_execution"
    assert packet["hostile_entry_authorized"] is True
    assert packet["entry_status"] == "authorized"
    assert packet["destination_ref"] != "loc_kanyou"

    assert _formation_locations(root, operation_after) == locations_before
    assert qin_path.read_bytes() == qin_before
    raw_qin_after = json.loads(qin_path.read_text(encoding="utf-8"))
    assert raw_qin_after["diplomacy"]["state_wei"]["status"] == "neutral"
    assert raw_qin_after.get("war_intents", []) == []
