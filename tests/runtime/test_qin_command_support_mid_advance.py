from __future__ import annotations

import copy

from sword_runtime.causal_event_store import get_causal_event
from sword_runtime.production_runtime_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime


FORMATION_REF = "formation_black_banner_01a"
OPERATION_REF = "operation_arc_131572c4e8a2892bbc"
OFFICE = "field_command:test_qin_mid_advance_support"


class DirectiveDuringStatePlanner(ProductionCampaignPlanner):
    """Create a pending Qin directive only when the state host actually settles."""

    def _settle_operational_battlefields(self, start: CampaignTime, end: CampaignTime):
        return {"player_interrupt": False, "delivered_reports": [], "reviews": []}

    def _settle_core_due_host(self, host, due_text: str) -> None:
        if str(host.get("kind", "")) != "state":
            return super()._settle_core_due_host(host, due_text)

        op_path = self.read("state/operations/index.json")["operations"][OPERATION_REF]
        operation = copy.deepcopy(self.read(op_path))
        order = copy.deepcopy(operation["operational_orders"][-1])
        order["order_ref"] = "operational_order_test_mid_advance_auto_briefing"
        order["issued_at"] = due_text
        # Make the new directive semantically distinct from the deployment
        # baseline briefing so delivery de-duplication cannot correctly collapse
        # it as an unchanged dossier.
        order["objective"] = "test revised Qin directive requiring a fresh operational briefing"
        order["status"] = "strategic_directive_pending_operational_briefing"
        order["actionability_status"] = "pending_operational_briefing"
        order.pop("mission_packet", None)
        order.pop("staff_briefed_at", None)
        operation["operational_orders"].append(order)
        operation["last_operational_order_ref"] = order["order_ref"]
        operation["order_status"] = "awaiting_operational_briefing"
        self.put(op_path, operation)
        self._pending_wake_created = None


def _seed_active_qin_scope(planner: ProductionCampaignPlanner) -> None:
    player = copy.deepcopy(planner.read("state/player.json"))
    player.setdefault("career_state", {})["appointments"] = [{
        "kind": "qin_field_command",
        "office": OFFICE,
        "state_ref": "state_qin",
        "formation_ref": FORMATION_REF,
        "formation_refs": [FORMATION_REF],
        "operation_ref": OPERATION_REF,
        "status": "active",
    }]
    planner.put("state/player.json", player)

    formation_path = planner.owner_path(FORMATION_REF)
    formation = copy.deepcopy(planner.read(formation_path))
    formation["administrative_owner"] = "state_qin"
    formation["command_authority"] = "char_tang_wei"
    planner.put(formation_path, formation)


def test_state_directive_routes_and_delivers_qin_briefing_inside_same_advance(campaign) -> None:
    planner = DirectiveDuringStatePlanner(campaign)
    planner.PLAYER_ACTOR = "char_tang_wei"
    planner._reset()
    _seed_active_qin_scope(planner)

    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    current = CampaignTime.parse(str(runtime["world_time"]))
    due = current.add_hours(1)
    host_id = "host_test_qin_mid_advance_state"
    event_id = "event_test_qin_mid_advance_state"
    runtime["hosts"] = {
        host_id: {
            "host_id": host_id,
            "kind": "state",
            "owner_ref": "state_qin",
            "event_id": event_id,
            "recurrence_seconds": 0,
            "resolved_through": str(current),
            "next_due": str(due),
            "safe_through": str(due.add_seconds(-1)),
        }
    }
    runtime["events"] = [{
        "event_id": event_id,
        "kind": "state",
        "priority": 40,
        "target_host": host_id,
        "due_at": str(due),
    }]
    runtime["scheduler"]["dirty"] = False
    runtime["scheduler"]["causal_settled_through"] = str(current)
    planner.put("state/runtime.json", runtime)

    planner._active_command_type = "advance_time"
    target = current.add_hours(4)
    result = planner._advance_causal_runtime(str(target))

    # The state directive exists after the first hour, but the staff packet still
    # has to be reviewed and physically couriered to Tang Wei. A four-hour
    # advance must not teleport that briefing if geography says it is still in
    # transit.
    assert result["campaign_event_notices"] == []
    runtime_after = planner.read("state/runtime.json")
    support_host = next(
        row for row in runtime_after["hosts"].values()
        if row.get("kind") == "qin_command_support_review"
        and row.get("support_kind") == "operational_briefing"
    )
    support_due = CampaignTime.parse(str(support_host["next_due"]))
    assert support_due > target
    assert int(support_host["communication_travel_seconds"]) > 0

    delivered = planner._advance_causal_runtime(str(support_due))
    notices = delivered["campaign_event_notices"]
    assert len(notices) == 1
    notice = notices[0]
    response = get_causal_event(planner, notice["campaign_event_ref"])
    assert response["process_kind"] == "qin_field_command_support"
    assert response["process_stage"] == "operational_briefing"

    op_path = planner.read("state/operations/index.json")["operations"][OPERATION_REF]
    operation = planner.read(op_path)
    assert operation["order_status"] == "staff_briefed_awaiting_commander_execution"
    assert operation["operational_orders"][-1]["actionability_status"] == "actionable"
    assert planner.read("state/runtime.json")["world_time"] == str(support_due)
