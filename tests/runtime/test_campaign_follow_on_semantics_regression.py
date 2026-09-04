from __future__ import annotations

import copy

from sword_runtime import campaign_follow_on_semantics as semantics


class _Planner:
    def __init__(self, operation):
        self.operation = copy.deepcopy(operation)
        self.docs = {
            "state/cmd/command-groups/cmdgrp.tang_wei.field_army.json": {
                "active_context_ref": "operation.test"
            }
        }
        self.puts = []

    def read(self, path):
        if path in self.docs:
            return copy.deepcopy(self.docs[path])
        raise KeyError(path)

    def put(self, path, row):
        self.puts.append((path, copy.deepcopy(row)))
        if path == "state/operations/test.json":
            self.operation = copy.deepcopy(row)


def _operation(*, order_kind="campaign_command_follow_on_mission", phase="contact_development", actionability="actionable"):
    return {
        "schema": "sword-operation",
        "owner_id": "operation.test",
        "operation_ref": "operation.test",
        "status": "active",
        "location_ref": "loc_sanyou",
        "operational_area_ref": "loc_sanyou",
        "strategic_target_ref": "loc_sanyou",
        "last_operational_order_ref": "order.new",
        "operational_orders": [
            {
                "order_ref": "order.new",
                "order_kind": order_kind,
                "issued_at": "244-BCE-11-15T08:22:48+08:00",
                "actionability_status": actionability,
                "mission_packet": {
                    "mission_phase": phase,
                    "phase_status": "ready_for_commander_execution",
                    "issued_at": "244-BCE-11-08T08:22:48+08:00",
                    "strategic_target_ref": "loc_sanyou",
                    "strategic_target_name": "Sanyou",
                    "field_command_anchor_ref": "loc_sanyou",
                    "destination_ref": "loc_sanyou",
                    "destination_name": "Sanyou",
                    "rendezvous_location_ref": "loc_sanyou",
                    "rendezvous_name": "Sanyou",
                    "completed_at": "244-BCE-11-15T08:22:48+08:00",
                    "actual_arrival_ref": "loc_sanyou",
                    "next_phase_trigger": "Arrival at the destination causes a field-command situation report.",
                    "success_condition": "the current field command physically reaches the authorized operational area and completes deployment",
                },
            }
        ],
    }


def _route(monkeypatch, planner):
    monkeypatch.setattr(
        semantics,
        "exact_operation_record",
        lambda _planner, operation_ref: (
            "state/operations/test.json",
            copy.deepcopy(planner.operation),
        ) if operation_ref == "operation.test" else None,
    )


def test_contact_follow_on_drops_completed_arrival_metadata(monkeypatch):
    planner = _Planner(_operation())
    _route(monkeypatch, planner)

    assert semantics.normalize_current_contact_development_order(planner) is True

    packet = planner.operation["operational_orders"][0]["mission_packet"]
    for key in {
        "actual_arrival_ref",
        "completed_at",
        "destination_name",
        "destination_ref",
        "rendezvous_location_ref",
        "rendezvous_name",
    }:
        assert key not in packet
    assert packet["issued_at"] == "244-BCE-11-15T08:22:48+08:00"
    assert packet["field_command_anchor_ref"] == "loc_sanyou"
    assert packet["field_command_anchor_name"] == "Sanyou"
    assert "enemy dispositions" in packet["success_condition"]
    assert "does not authorize" in packet["next_phase_trigger"]


def test_contact_follow_on_normalization_is_idempotent(monkeypatch):
    planner = _Planner(_operation())
    _route(monkeypatch, planner)

    assert semantics.normalize_current_contact_development_order(planner) is True
    first = copy.deepcopy(planner.operation)
    assert semantics.normalize_current_contact_development_order(planner) is False
    assert planner.operation == first


def test_contact_follow_on_normalizer_fails_closed_for_other_orders(monkeypatch):
    for operation in (
        _operation(order_kind="other_order"),
        _operation(phase="campaign_concentration_and_advance"),
        _operation(actionability="completed"),
    ):
        planner = _Planner(operation)
        _route(monkeypatch, planner)
        assert semantics.normalize_current_contact_development_order(planner) is False
        assert planner.puts == []
