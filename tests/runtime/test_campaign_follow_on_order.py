from __future__ import annotations

import json
from pathlib import Path

from sword_runtime.production_runtime_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime


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


def test_reconciled_entry_gets_new_deliverable_follow_on_order_without_moving_army(campaign: Path) -> None:
    root = Path(campaign)
    planner = _planner(root)
    operation_path = planner.read("state/operations/index.json")["operations"][OPERATION_REF]
    current_operation = planner.read(operation_path)

    # The live campaign has already advanced through this reconciliation and
    # currently stores the generated follow-on order.  Recreate the exact stale
    # pre-entry-authority shape inside this disposable fixture so this regression
    # continues to test the lifecycle transition rather than the mutable point in
    # the playthrough at which the test suite happens to run.
    current_latest = current_operation["operational_orders"][-1]
    if current_latest.get("order_kind") == "campaign_entry_follow_on_march_order":
        base_order_ref = str(current_latest["source_order_ref"])
        staged = json.loads(json.dumps(current_operation))
        staged["operational_orders"] = [
            row for row in staged["operational_orders"]
            if row.get("order_ref") != current_latest["order_ref"]
        ]
        staged["last_operational_order_ref"] = base_order_ref
        staged["campaign_phase"] = "awaiting_entry_authority"
        staged["order_status"] = "awaiting_entry_authority"
        base_order = next(row for row in staged["operational_orders"] if row.get("order_ref") == base_order_ref)
        base_order["status"] = "staged_awaiting_entry_authority"
        base_order["actionability_status"] = "blocked_awaiting_entry_authority"
        packet = base_order["mission_packet"]
        packet["hostile_entry_authorized"] = False
        packet["entry_status"] = "awaiting_war_or_entry_authority"
        packet["phase_status"] = "awaiting_entry_authority"
        planner.put(operation_path, staged)

        cycle_ref = staged["campaign_command_cycle_ref"]
        cycle_path = planner.owner_path(cycle_ref)
        cycle = json.loads(json.dumps(planner.read(cycle_path)))
        cycle["delivered_superior_order_refs"] = [
            ref for ref in cycle.get("delivered_superior_order_refs", [])
            if ref != current_latest["order_ref"]
        ]
        if base_order_ref not in cycle["delivered_superior_order_refs"]:
            cycle["delivered_superior_order_refs"].append(base_order_ref)
        cycle["current_superior_order"] = json.loads(json.dumps(base_order))
        planner.put(cycle_path, cycle)
    else:
        base_order_ref = str(current_operation["last_operational_order_ref"])
        cycle_ref = current_operation["campaign_command_cycle_ref"]
        cycle_path = planner.owner_path(cycle_ref)

    operation_before = planner.read(operation_path)
    locations_before = {
        ref: planner.read(planner.owner_path(ref)).get("location_ref")
        for ref in operation_before["formation_refs"]
    }
    qin_before = (root / "state/states/qin.json").read_bytes()

    cycle_before = planner.read(cycle_path)
    assert base_order_ref in cycle_before["delivered_superior_order_refs"]

    current = CampaignTime.parse(str(planner.read("state/runtime.json")["world_time"]))
    planner._prepare_scheduler_for_advance(str(current.add_seconds(3600)))

    operation_after = planner.read(operation_path)
    latest = operation_after["operational_orders"][-1]
    packet = latest["mission_packet"]

    assert latest["order_ref"] != base_order_ref
    assert latest["order_kind"] == "campaign_entry_follow_on_march_order"
    assert latest["source_order_ref"] == base_order_ref
    assert latest["superior_commander_ref"] == "char_mou_gou"
    assert latest["actionability_status"] == "actionable"
    assert packet["hostile_entry_authorized"] is True
    assert packet["phase_status"] == "ready_for_commander_execution"
    assert packet["destination_ref"] != "loc_kanyou"
    assert "does not assign a vanguard" in latest["follow_on_requirement"]

    runtime_after = planner.read("state/runtime.json")
    order_hosts = [
        row for row in runtime_after["hosts"].values()
        if isinstance(row, dict)
        and row.get("kind") == "campaign_command_superior_order"
        and row.get("operation_ref") == OPERATION_REF
        and row.get("phase_instance_ref") == latest["order_ref"]
    ]
    assert len(order_hosts) == 1

    # The preparation boundary stages command lifecycle only. No formation moves,
    # no diplomacy rewrite, and the historical delivered order ref remains intact.
    assert {
        ref: planner.read(planner.owner_path(ref)).get("location_ref")
        for ref in operation_before["formation_refs"]
    } == locations_before
    assert (root / "state/states/qin.json").read_bytes() == qin_before
    assert base_order_ref in planner.read(cycle_path)["delivered_superior_order_refs"]
