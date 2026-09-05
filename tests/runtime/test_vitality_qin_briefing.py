from __future__ import annotations

import copy

from sword_runtime.vitality import _pending_qin_briefings_without_support_path


OP_REF = "operation_fixture_qin_vitality"
OP_PATH = f"state/operations/{OP_REF}.json"
CURRENT_PENDING = "operational_order_current_pending"
HISTORICAL_PENDING = "operational_order_historical_pending"


class _Store:
    def __init__(self, operation):
        self.data = {
            "state/operations/index.json": {"operations": {OP_REF: OP_PATH}},
            OP_PATH: copy.deepcopy(operation),
        }

    def read_json(self, path):
        if path not in self.data:
            raise FileNotFoundError(path)
        return copy.deepcopy(self.data[path])


def _operation():
    return {
        "operation_ref": OP_REF,
        "status": "active",
        "institutional_owner_ref": "state_qin",
        "administrative_authority": "char_tang_wei",
        "last_operational_order_ref": CURRENT_PENDING,
        "operational_orders": [
            {
                "order_ref": CURRENT_PENDING,
                "issued_at": "244-BCE-11-19T20:22:48+08:00",
                "status": "strategic_directive_pending_operational_briefing",
                "actionability_status": "pending_operational_briefing",
            },
            {
                "order_ref": HISTORICAL_PENDING,
                "issued_at": "244-BCE-11-16T07:37:48+08:00",
                "status": "strategic_directive_pending_operational_briefing",
                "actionability_status": "pending_operational_briefing",
            },
        ],
    }


def _host(order_ref):
    return {
        "kind": "qin_command_support_review",
        "support_kind": "operational_briefing",
        "operation_ref": OP_REF,
        "order_ref": order_ref,
        "next_due": "244-BCE-12-21T12:00:01+08:00",
    }


def test_vitality_checks_newest_pending_by_issued_at_not_list_tail():
    operation = _operation()
    store = _Store(operation)
    hosts = {"host_current": _host(CURRENT_PENDING)}

    assert _pending_qin_briefings_without_support_path(store, hosts) == 0


def test_vitality_still_blocks_when_newest_pending_has_no_route():
    operation = _operation()
    store = _Store(operation)
    hosts = {"host_historical": _host(HISTORICAL_PENDING)}

    assert _pending_qin_briefings_without_support_path(store, hosts) == 1


def test_newer_actionable_order_suppresses_older_pending_pressure():
    operation = _operation()
    operation["operational_orders"].insert(0, {
        "order_ref": "operational_order_newer_actionable",
        "issued_at": "244-BCE-11-20T06:00:00+08:00",
        "status": "staff_briefed_awaiting_commander_execution",
        "actionability_status": "actionable",
    })
    store = _Store(operation)

    assert _pending_qin_briefings_without_support_path(store, {}) == 0
