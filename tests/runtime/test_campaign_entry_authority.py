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
    assert not any(row.get("projection_only") is True for row in raw_qin.get("war_intents", []) if isinstance(row, dict))

    authorities = projected_campaign_entry_authorities(planner, "state_qin")
    authority = next(row for row in authorities if row["operation_ref"] == OPERATION_REF)
    operation = _raw_operation(root)
    latest = operation["operational_orders"][-1]
    assert authority["target_ref"] == "state_wei"
    # Current-save tests must follow the exact active order rather than pinning
    # a superseded order ID from an earlier campaign revision.
    assert authority["order_ref"] == latest["order_ref"]
    expected_arc_ref = latest.get("arc_ref") or operation.get("campaign_arc_ref") or next(
        ref for ref in operation.get("objective_refs", [])
        if isinstance(ref, str) and ref.startswith("arc_")
    )
    assert authority["arc_ref"] == expected_arc_ref
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
    qin_path = root / "state/states/qin.json"
    qin_before = qin_path.read_bytes()
    operation_index = json.loads((root / "state/operations/index.json").read_text(encoding="utf-8"))
    operation_path = root / operation_index["operations"][OPERATION_REF]
    operation_before = _raw_operation(root)

    # The canonical save has already been reconciled. Recreate only the stale
    # pre-authority projection this test is about inside the disposable fixture,
    # preserving the exact current order identity and every physical formation.
    staged = json.loads(json.dumps(operation_before))
    staged["campaign_phase"] = "awaiting_entry_authority"
    staged["order_status"] = "awaiting_entry_authority"
    latest_staged = staged["operational_orders"][-1]
    latest_staged["status"] = "staged_awaiting_entry_authority"
    latest_staged["actionability_status"] = "blocked_awaiting_entry_authority"
    packet_staged = latest_staged["mission_packet"]
    packet_staged["hostile_entry_authorized"] = False
    packet_staged["entry_status"] = "awaiting_war_or_entry_authority"
    packet_staged["phase_status"] = "awaiting_entry_authority"
    operation_path.write_text(json.dumps(staged, separators=(",", ":")) + "\n", encoding="utf-8")

    planner = _planner(root)
    operation_before = _raw_operation(root)
    locations_before = _formation_locations(root, operation_before)

    assert operation_before["campaign_phase"] == "awaiting_entry_authority"
    assert operation_before["operational_orders"][-1]["status"] == "staged_awaiting_entry_authority"
    assert operation_before["operational_orders"][-1]["mission_packet"]["hostile_entry_authorized"] is False

    refreshed = planner._reconcile_campaign_entry_authority()
    assert refreshed == [OPERATION_REF]

    operation_path = planner.read("state/operations/index.json")["operations"][OPERATION_REF]
    operation_after = planner.read(operation_path)
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

    # Reconciliation stages only the corrected campaign packet. It does not move
    # formations or persist a synthetic declaration/war intent by itself.
    assert _formation_locations(root, operation_before) == locations_before
    assert qin_path.read_bytes() == qin_before
    raw_qin_after = json.loads(qin_path.read_text(encoding="utf-8"))
    assert raw_qin_after["diplomacy"]["state_wei"]["status"] == "neutral"
    assert not any(row.get("projection_only") is True for row in raw_qin_after.get("war_intents", []) if isinstance(row, dict))


def test_projected_campaign_entry_authority_cannot_be_serialized_by_read_modify_write(campaign: Path) -> None:
    planner = _planner(Path(campaign))
    projected = planner.read("state/states/qin.json")
    assert any(
        isinstance(row, dict)
        and row.get("kind") == "exact_state_campaign_order_entry_authority"
        and row.get("projection_only") is True
        for row in projected.get("war_intents", [])
    )

    # Simulate an unrelated sovereign update that starts from the public read view.
    rewritten = json.loads(json.dumps(projected))
    rewritten["projection_persistence_regression_probe"] = True
    planner.put("state/states/qin.json", rewritten)

    staged = planner._writes["state/states/qin.json"]
    assert staged["projection_persistence_regression_probe"] is True
    assert not any(
        isinstance(row, dict) and row.get("projection_only") is True
        for row in staged.get("war_intents", [])
    )
