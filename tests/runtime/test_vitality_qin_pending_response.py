from __future__ import annotations

import copy

from sword_runtime.qin_command_support_reconciliation import (
    _auto_briefing_work_ref,
    _response_ref,
)
from sword_runtime.vitality import _pending_qin_briefing_responses_without_actionability


OP_REF = "operation_fixture_qin_pending_response"
OP_PATH = f"state/operations/{OP_REF}.json"
ORDER_REF = "operational_order_fixture_pending_response"
EVENT_OWNER_PATH = "state/event/events-messages-and-movement.json"


class _Store:
    def __init__(self, *, with_response: bool):
        work_ref = _auto_briefing_work_ref(OP_REF, ORDER_REF)
        response_ref = _response_ref(work_ref)
        causal_events = {
            response_ref: {
                "event_ref": response_ref,
                "kind": "institutional_response",
                "status": "triggered",
                "process_kind": "qin_field_command_support",
                "process_stage": "operational_briefing",
            }
        } if with_response else {}
        self.data = {
            "state/operations/index.json": {"operations": {OP_REF: OP_PATH}},
            OP_PATH: {
                "operation_ref": OP_REF,
                "status": "active",
                "institutional_owner_ref": "state_qin",
                "administrative_authority": "char_tang_wei",
                "last_operational_order_ref": ORDER_REF,
                "operational_orders": [{
                    "order_ref": ORDER_REF,
                    "issued_at": "244-BCE-11-19T20:22:48+08:00",
                    "status": "strategic_directive_pending_operational_briefing",
                    "actionability_status": "pending_operational_briefing",
                }],
            },
            EVENT_OWNER_PATH: {
                "schema": "event-registry",
                "owner_id": "events_messages_and_movement",
                "causal_events": causal_events,
                "archives": [],
                "archived_event_count": 0,
                "archive_segment_count": 0,
                "next_archive_seq": 1,
            },
        }

    def read_json(self, path):
        if path not in self.data:
            raise FileNotFoundError(path)
        return copy.deepcopy(self.data[path])


def test_pending_qin_briefing_with_exact_response_is_inconsistent():
    assert _pending_qin_briefing_responses_without_actionability(
        _Store(with_response=True)
    ) == 1


def test_pending_qin_briefing_without_response_is_not_this_failure_mode():
    assert _pending_qin_briefing_responses_without_actionability(
        _Store(with_response=False)
    ) == 0
