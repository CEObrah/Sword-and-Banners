from __future__ import annotations

import copy

from sword_runtime import campaign_arrival_lifecycle as arrival_lifecycle
from sword_runtime import production_runtime_planner as production


class _Planner:
    def __init__(self, operation):
        self.operation = copy.deepcopy(operation)
        self.docs = {
            "state/player.json": {
                "career_state": {
                    "appointments": [
                        {
                            "status": "active",
                            "kind": "qin_field_command",
                            "operation_ref": "operation.test",
                        }
                    ]
                }
            },
            "state/runtime.json": {"world_time": "244-BCE-11-15T08:22:48+08:00"},
        }

    def read(self, path):
        if path in self.docs:
            return copy.deepcopy(self.docs[path])
        raise KeyError(path)


def _operation(
    *,
    phase_status="ready_for_commander_execution",
    actionability_status="actionable",
    order_status="staff_briefed_awaiting_commander_execution",
    formation_refs=None,
    applies_to_formation_refs=None,
):
    if formation_refs is None:
        formation_refs = ["formation.test"]
    if applies_to_formation_refs is None:
        applies_to_formation_refs = ["formation.test"]
    return {
        "schema": "sword-operation",
        "operation_ref": "operation.test",
        "owner_id": "operation.test",
        "status": "active",
        "campaign_phase": "campaign_concentration",
        "formation_refs": list(formation_refs),
        "last_operational_order_ref": "order.test",
        "operational_orders": [
            {
                "order_ref": "order.test",
                "status": order_status,
                "actionability_status": actionability_status,
                "applies_to_formation_refs": list(applies_to_formation_refs),
                "mission_packet": {
                    "mission_phase": "campaign_concentration_and_advance",
                    "phase_status": phase_status,
                    "destination_ref": "loc_sanyou",
                    "hostile_entry_authorized": True,
                },
            }
        ],
    }


def _route_operation(monkeypatch, planner):
    monkeypatch.setattr(
        arrival_lifecycle,
        "exact_operation_record",
        lambda _planner, operation_ref: (
            "state/operations/test.json",
            copy.deepcopy(planner.operation),
        ) if operation_ref == "operation.test" else None,
    )


def test_prechronology_lifecycle_reconciles_current_open_arrival(monkeypatch):
    planner = _Planner(_operation())
    _route_operation(monkeypatch, planner)
    calls = []

    def _reconcile(_planner, operation_ref, *, destination_ref, at, unit_duties=None):
        calls.append((operation_ref, destination_ref, at))
        return {"operation_ref": operation_ref, "phase": "operational_area_arrival"}

    monkeypatch.setattr(arrival_lifecycle, "reconcile_campaign_arrival", _reconcile)

    reconciled = arrival_lifecycle.reconcile_satisfied_player_campaign_arrivals(planner)

    assert reconciled == ["operation.test"]
    assert calls == [
        ("operation.test", "loc_sanyou", "244-BCE-11-15T08:22:48+08:00")
    ]


def test_prechronology_lifecycle_accepts_executing_arrival(monkeypatch):
    planner = _Planner(
        _operation(
            phase_status="executing",
            actionability_status="executing",
            order_status="executing",
        )
    )
    _route_operation(monkeypatch, planner)
    calls = []

    def _reconcile(_planner, operation_ref, *, destination_ref, at, unit_duties=None):
        calls.append((operation_ref, destination_ref, at))
        return {"operation_ref": operation_ref, "phase": "operational_area_arrival"}

    monkeypatch.setattr(arrival_lifecycle, "reconcile_campaign_arrival", _reconcile)

    reconciled = arrival_lifecycle.reconcile_satisfied_player_campaign_arrivals(planner)

    assert reconciled == ["operation.test"]
    assert len(calls) == 1


def test_prechronology_lifecycle_does_not_claim_remote_arrival(monkeypatch):
    planner = _Planner(_operation())
    _route_operation(monkeypatch, planner)
    calls = []

    def _not_arrived(_planner, operation_ref, *, destination_ref, at, unit_duties=None):
        calls.append((operation_ref, destination_ref, at))
        return None

    monkeypatch.setattr(arrival_lifecycle, "reconcile_campaign_arrival", _not_arrived)

    reconciled = arrival_lifecycle.reconcile_satisfied_player_campaign_arrivals(planner)

    assert reconciled == []
    assert calls == [
        ("operation.test", "loc_sanyou", "244-BCE-11-15T08:22:48+08:00")
    ]


def test_prechronology_lifecycle_skips_terminal_order(monkeypatch):
    planner = _Planner(
        _operation(
            actionability_status="actionable",
            order_status="cancelled",
        )
    )
    _route_operation(monkeypatch, planner)

    def _unexpected(*args, **kwargs):
        raise AssertionError("terminal order must not reach arrival authority")

    monkeypatch.setattr(arrival_lifecycle, "reconcile_campaign_arrival", _unexpected)

    assert arrival_lifecycle.reconcile_satisfied_player_campaign_arrivals(planner) == []


def test_prechronology_lifecycle_skips_nonexecutable_packet_state(monkeypatch):
    planner = _Planner(
        _operation(
            phase_status="blocked",
            actionability_status="blocked",
            order_status="execution_blocked",
        )
    )
    _route_operation(monkeypatch, planner)

    def _unexpected(*args, **kwargs):
        raise AssertionError("blocked packet must not be silently promoted")

    monkeypatch.setattr(arrival_lifecycle, "reconcile_campaign_arrival", _unexpected)

    assert arrival_lifecycle.reconcile_satisfied_player_campaign_arrivals(planner) == []


def test_prechronology_lifecycle_skips_empty_formation_scope(monkeypatch):
    planner = _Planner(
        _operation(
            formation_refs=[],
            applies_to_formation_refs=[],
        )
    )
    _route_operation(monkeypatch, planner)

    def _unexpected(*args, **kwargs):
        raise AssertionError("empty formation scope must fail closed")

    monkeypatch.setattr(arrival_lifecycle, "reconcile_campaign_arrival", _unexpected)

    assert arrival_lifecycle.reconcile_satisfied_player_campaign_arrivals(planner) == []


def test_production_pre_advance_reconciles_arrival_before_follow_on(monkeypatch):
    calls = []
    planner = object.__new__(production.ProductionCampaignPlanner)

    monkeypatch.setattr(
        production.ProductionCampaignPlanner,
        "_reconcile_campaign_entry_authority",
        lambda self: calls.append("entry_authority") or ["operation.test"],
        raising=False,
    )
    monkeypatch.setattr(
        production,
        "reconcile_satisfied_player_campaign_arrivals",
        lambda self: calls.append("arrival") or ["operation.test"],
    )
    monkeypatch.setattr(
        production,
        "materialize_reconciled_campaign_follow_on_orders",
        lambda self, refs: calls.append(("follow_on", list(refs))) or [],
    )
    monkeypatch.setattr(
        production.ProductionCampaignPlanner,
        "_sync_campaign_command_decisions",
        lambda self: calls.append("command_decisions"),
        raising=False,
    )
    monkeypatch.setattr(
        production.ProductionTimeIntegrationMixin,
        "_prepare_scheduler_for_advance",
        lambda self, target_text: calls.append(("scheduler", target_text)),
    )

    planner._prepare_scheduler_for_advance("244-BCE-11-15T08:22:48+08:00")

    assert calls == [
        "entry_authority",
        "arrival",
        ("follow_on", ["operation.test"]),
        "command_decisions",
        ("scheduler", "244-BCE-11-15T08:22:48+08:00"),
    ]
