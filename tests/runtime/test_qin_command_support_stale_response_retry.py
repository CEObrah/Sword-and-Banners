from __future__ import annotations

import copy

import sword_runtime.qin_command_support_reconciliation as reconciliation
from sword_runtime.sim.calendar import CampaignTime


OP_REF = "operation_fixture_qin_stale_response"
OP_PATH = f"state/operations/{OP_REF}.json"
ORDER_REF = "operational_order_fixture_pending"
FORMATION_REF = "formation_fixture_qin"


class _Planner:
    def __init__(self):
        self.data = {
            "state/player.json": {
                "career_state": {
                    "appointments": [{
                        "kind": "qin_field_command",
                        "state_ref": "state_qin",
                        "status": "active",
                        "office": "field_command:fixture",
                        "operation_ref": OP_REF,
                        "formation_refs": [FORMATION_REF],
                    }]
                }
            },
            OP_PATH: {
                "operation_ref": OP_REF,
                "status": "active",
                "formation_refs": [FORMATION_REF],
                "last_operational_order_ref": ORDER_REF,
                "operational_orders": [{
                    "order_ref": ORDER_REF,
                    "issued_at": "244-BCE-11-19T20:22:48+08:00",
                    "status": "strategic_directive_pending_operational_briefing",
                    "actionability_status": "pending_operational_briefing",
                }],
            },
        }

    def read(self, path):
        if path not in self.data:
            raise FileNotFoundError(path)
        return copy.deepcopy(self.data[path])


def _exact_operation_record(planner, operation_ref):
    if operation_ref != OP_REF:
        return None
    return OP_PATH, planner.read(OP_PATH)


def _patch_routes(monkeypatch):
    monkeypatch.setattr(reconciliation, "exact_operation_record", _exact_operation_record)
    monkeypatch.setattr(
        reconciliation,
        "command_endpoint_location",
        lambda planner, ref: "loc_qin_bureau" if ref == "inst_qin_military_bureau" else None,
    )
    monkeypatch.setattr(reconciliation, "player_command_location", lambda planner: "loc_sanyou")
    monkeypatch.setattr(
        reconciliation,
        "command_message_route",
        lambda read, origin, destination, round_trip=False: {
            "origin_ref": origin,
            "destination_ref": destination,
            "travel_seconds": 23 * 3600,
            "one_way_seconds": 23 * 3600,
            "round_trip": round_trip,
            "path": [origin, destination],
            "route_refs": ["route_fixture_qin_support"],
            "modes": ["horse", "foot"],
        },
    )


def _runtime():
    return {
        "world_time": "244-BCE-12-21T12:00:00+08:00",
        "hosts": {},
        "events": [],
    }


def test_stale_auto_response_schedules_distinct_recovery_work(monkeypatch):
    planner = _Planner()
    _patch_routes(monkeypatch)
    original_work_ref = reconciliation._auto_briefing_work_ref(OP_REF, ORDER_REF)
    original_response_ref = reconciliation._response_ref(original_work_ref)
    monkeypatch.setattr(
        reconciliation,
        "get_causal_event",
        lambda planner, ref: {"event_ref": ref} if ref == original_response_ref else None,
    )
    runtime = _runtime()

    changed = reconciliation._ensure_missing_automatic_routes(
        planner,
        runtime,
        current=CampaignTime.parse(runtime["world_time"]),
        review_seconds=4 * 3600,
    )

    recovery_work_ref = reconciliation._recovery_briefing_work_ref(
        OP_REF, ORDER_REF, original_work_ref
    )
    recovery_host_ref, recovery_event_ref = reconciliation._review_ids(recovery_work_ref)
    assert changed == [recovery_work_ref]
    assert recovery_work_ref.startswith("recovery_qin_campaign_briefing_")
    host = runtime["hosts"][recovery_host_ref]
    assert host["work_ref"] == recovery_work_ref
    assert host["support_kind"] == "operational_briefing"
    assert host["operation_ref"] == OP_REF
    assert host["order_ref"] == ORDER_REF
    assert host["next_due"] == "244-BCE-12-21T12:00:01+08:00"
    assert runtime["events"] == [{
        "event_id": recovery_event_ref,
        "kind": "qin_command_support_review",
        "priority": 43,
        "target_host": recovery_host_ref,
        "due_at": "244-BCE-12-21T12:00:01+08:00",
    }]


def test_no_stale_response_uses_normal_automatic_work_ref(monkeypatch):
    planner = _Planner()
    _patch_routes(monkeypatch)
    monkeypatch.setattr(reconciliation, "get_causal_event", lambda planner, ref: None)
    runtime = _runtime()

    changed = reconciliation._ensure_missing_automatic_routes(
        planner,
        runtime,
        current=CampaignTime.parse(runtime["world_time"]),
        review_seconds=4 * 3600,
    )

    original_work_ref = reconciliation._auto_briefing_work_ref(OP_REF, ORDER_REF)
    assert changed == [original_work_ref]
    host_ref, _event_ref = reconciliation._review_ids(original_work_ref)
    assert runtime["hosts"][host_ref]["work_ref"] == original_work_ref


def test_existing_recovery_response_prevents_duplicate_retry(monkeypatch):
    planner = _Planner()
    _patch_routes(monkeypatch)
    original_work_ref = reconciliation._auto_briefing_work_ref(OP_REF, ORDER_REF)
    original_response_ref = reconciliation._response_ref(original_work_ref)
    recovery_work_ref = reconciliation._recovery_briefing_work_ref(
        OP_REF, ORDER_REF, original_work_ref
    )
    recovery_response_ref = reconciliation._response_ref(recovery_work_ref)
    monkeypatch.setattr(
        reconciliation,
        "get_causal_event",
        lambda planner, ref: {"event_ref": ref}
        if ref in {original_response_ref, recovery_response_ref}
        else None,
    )
    runtime = _runtime()

    assert reconciliation._ensure_missing_automatic_routes(
        planner,
        runtime,
        current=CampaignTime.parse(runtime["world_time"]),
        review_seconds=4 * 3600,
    ) == []
    assert runtime["hosts"] == {}
    assert runtime["events"] == []
