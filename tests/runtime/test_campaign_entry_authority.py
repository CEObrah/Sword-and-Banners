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


def _current_order(operation: dict) -> dict:
    order_ref = str(operation.get("last_operational_order_ref", ""))
    return next(
        row
        for row in reversed(operation.get("operational_orders", []))
        if isinstance(row, dict) and (not order_ref or str(row.get("order_ref", "")) == order_ref)
    )


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
    diplomacy_before = json.loads(json.dumps(raw_qin["diplomacy"]["state_wei"]))

    # The maintained campaign fixture may lawfully move between non-war diplomatic
    # states as play advances. Entry-authority projection must not depend on one
    # historical label and must never rewrite the saved diplomatic relation.
    assert diplomacy_before["status"] != "war"
    assert not any(row.get("projection_only") is True for row in raw_qin.get("war_intents", []) if isinstance(row, dict))

    authorities = projected_campaign_entry_authorities(planner, "state_qin")
    authority = next(row for row in authorities if row["operation_ref"] == OPERATION_REF)
    operation = _raw_operation(root)
    current = _current_order(operation)
    assert authority["target_ref"] == "state_wei"
    # Current-save tests must follow the exact active order named by the
    # operation rather than assuming list tail equals current order.
    assert authority["order_ref"] == current["order_ref"]
    expected_arc_ref = current.get("arc_ref") or operation.get("campaign_arc_ref") or next(
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
    assert projected_qin["diplomacy"]["state_wei"] == diplomacy_before
    assert qin_path.read_bytes() == qin_before


def test_reconciliation_reopens_completed_staging_without_moving_army_or_rewriting_diplomacy(campaign: Path) -> None:
    root = Path(campaign)
    qin_path = root / "state/states/qin.json"
    qin_before = qin_path.read_bytes()
    raw_qin_before = json.loads(qin_before)
    diplomacy_before = json.loads(json.dumps(raw_qin_before["diplomacy"]["state_wei"]))
    operation_index = json.loads((root / "state/operations/index.json").read_text(encoding="utf-8"))
    operation_path = root / operation_index["operations"][OPERATION_REF]
    canonical_operation = _raw_operation(root)

    # The canonical save has already been reconciled. Recreate only the stale
    # pre-authority projection this test is about inside the disposable fixture,
    # preserving the exact current order identity and every physical formation.
    staged = json.loads(json.dumps(canonical_operation))
    staged["campaign_phase"] = "awaiting_entry_authority"
    staged["order_status"] = "awaiting_entry_authority"
    current_staged = _current_order(staged)
    current_staged["status"] = "staged_awaiting_entry_authority"
    current_staged["actionability_status"] = "blocked_awaiting_entry_authority"
    packet_staged = current_staged["mission_packet"]
    packet_staged["hostile_entry_authorized"] = False
    packet_staged["entry_status"] = "awaiting_war_or_entry_authority"
    packet_staged["phase_status"] = "awaiting_entry_authority"
    operation_path.write_text(json.dumps(staged, separators=(",", ":")) + "\n", encoding="utf-8")

    planner = _planner(root)
    operation_before = _raw_operation(root)
    locations_before = _formation_locations(root, operation_before)

    assert operation_before["campaign_phase"] == "awaiting_entry_authority"
    current_before = _current_order(operation_before)
    assert current_before["status"] == "staged_awaiting_entry_authority"
    assert current_before["mission_packet"]["hostile_entry_authorized"] is False

    refreshed = planner._reconcile_campaign_entry_authority()
    assert refreshed == [OPERATION_REF]

    operation_path = planner.read("state/operations/index.json")["operations"][OPERATION_REF]
    operation_after = planner.read(operation_path)
    current = _current_order(operation_after)
    packet = current["mission_packet"]
    # Entry reconciliation owns the stale authority gate only. Later campaign
    # phases are separate owners, so this regression asserts that the gate is
    # cleared rather than asking entry reconciliation to reconstruct later play.
    assert operation_after["campaign_phase"] != "awaiting_entry_authority"
    assert operation_after["order_status"] != "awaiting_entry_authority"
    assert current["status"] != "staged_awaiting_entry_authority"
    assert current["actionability_status"] != "blocked_awaiting_entry_authority"
    assert packet["phase_status"] != "awaiting_entry_authority"
    assert packet["hostile_entry_authorized"] is True
    assert packet["entry_status"] == "authorized"
    assert packet["destination_ref"] != "loc_kanyou"

    # Reconciliation stages only the corrected campaign packet. It does not move
    # formations or persist a synthetic declaration/war intent by itself.
    assert _formation_locations(root, operation_before) == locations_before
    assert qin_path.read_bytes() == qin_before
    raw_qin_after = json.loads(qin_path.read_text(encoding="utf-8"))
    assert raw_qin_after["diplomacy"]["state_wei"] == diplomacy_before
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
