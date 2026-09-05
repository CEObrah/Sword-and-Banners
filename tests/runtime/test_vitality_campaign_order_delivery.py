from __future__ import annotations

import copy

from sword_runtime.campaign_command_cycle import _cycle_ref
from sword_runtime.vitality import _campaign_decision_orders_exposed_before_delivery


OP_REF = "operation_fixture_campaign_delivery_vitality"
OP_PATH = f"state/operations/{OP_REF}.json"
CYCLE_REF = _cycle_ref(OP_REF)
CYCLE_PATH = "state/campaign-command/cycle-fixture-delivery-vitality.json"
BASE_ORDER = "operational_order_fixture_delivered_base"
DECISION_ORDER = "operational_order_fixture_pending_decision"


class _Store:
    def __init__(
        self,
        *,
        decision_current: bool,
        decision_actionable: bool,
        decision_delivered: bool,
    ):
        decision_status = (
            "staff_briefed_awaiting_commander_execution"
            if decision_actionable
            else "issued_pending_delivery"
        )
        decision_actionability = "actionable" if decision_actionable else "pending_delivery"
        delivered_refs = [BASE_ORDER]
        delivery_status = "in_transit"
        delivered_at = None
        if decision_delivered:
            delivered_refs.append(DECISION_ORDER)
            delivery_status = "delivered"
            delivered_at = "244-BCE-12-22T11:15:01+08:00"
        decision_order = {
            "order_ref": DECISION_ORDER,
            "order_kind": "campaign_command_follow_on_mission",
            "source_order_ref": BASE_ORDER,
            "status": decision_status,
            "actionability_status": decision_actionability,
        }
        if delivered_at is not None:
            decision_order["delivered_at"] = delivered_at

        self.data = {
            "state/operations/index.json": {"operations": {OP_REF: OP_PATH}},
            "state/index/owner-index.json": {
                "owners": {
                    OP_REF: OP_PATH,
                    CYCLE_REF: CYCLE_PATH,
                }
            },
            OP_PATH: {
                "operation_ref": OP_REF,
                "status": "active",
                "last_operational_order_ref": DECISION_ORDER if decision_current else BASE_ORDER,
                "operational_orders": [
                    {
                        "order_ref": BASE_ORDER,
                        "status": "phase_complete_awaiting_follow_on_direction",
                        "actionability_status": "completed",
                    },
                    decision_order,
                ],
            },
            CYCLE_PATH: {
                "kind": "campaign_command_cycle",
                "cycle_ref": CYCLE_REF,
                "operation_ref": OP_REF,
                "delivered_superior_order_refs": delivered_refs,
                "current_superior_order": {
                    "order_ref": DECISION_ORDER if decision_current else BASE_ORDER,
                },
                "campaign_command_decisions": [
                    {
                        "decision_ref": "campaign_command_decision.fixture",
                        "order_ref": DECISION_ORDER,
                        "base_order_ref": BASE_ORDER,
                        "delivery_status": delivery_status,
                    }
                ],
            },
        }

    def read_json(self, path):
        if path not in self.data:
            raise FileNotFoundError(path)
        return copy.deepcopy(self.data[path])


def test_current_undelivered_campaign_decision_is_vitality_failure():
    store = _Store(
        decision_current=True,
        decision_actionable=True,
        decision_delivered=False,
    )
    assert _campaign_decision_orders_exposed_before_delivery(store) == 1


def test_pending_noncurrent_campaign_decision_is_healthy():
    store = _Store(
        decision_current=False,
        decision_actionable=False,
        decision_delivered=False,
    )
    assert _campaign_decision_orders_exposed_before_delivery(store) == 0


def test_undelivered_noncurrent_but_actionable_decision_is_still_detected():
    store = _Store(
        decision_current=False,
        decision_actionable=True,
        decision_delivered=False,
    )
    assert _campaign_decision_orders_exposed_before_delivery(store) == 1


def test_delivered_current_campaign_decision_is_healthy():
    store = _Store(
        decision_current=True,
        decision_actionable=True,
        decision_delivered=True,
    )
    assert _campaign_decision_orders_exposed_before_delivery(store) == 0
