from __future__ import annotations

import copy

import sword_runtime.qin_command_support_reconciliation as reconciliation


OP_REF = "operation_fixture_qin_legacy_scope"
OP_PATH = f"state/operations/{OP_REF}.json"
GROUP_REF = "cmdgrp.tang_wei.field_army"
GROUP_PATH = f"state/cmd/command-groups/{GROUP_REF}.json"
PRIOR_REF = "operational_order_fixture_actionable"
PENDING_REF = "operational_order_fixture_pending"


class _Planner:
    def __init__(self, *, prior_actionability="actionable", prior_status="staff_briefed_awaiting_commander_execution"):
        self.writes = []
        self.data = {
            "state/player.json": {
                "career_state": {
                    "appointments": [{
                        "kind": "qin_field_command",
                        "state_ref": "state_qin",
                        "status": "active",
                        "office": "field_command:legacy",
                        "command_group_ref": GROUP_REF,
                        "formation_refs": ["formation_qin_a"],
                    }]
                }
            },
            GROUP_PATH: {
                "command_group_ref": GROUP_REF,
                "active_context_ref": OP_REF,
            },
            OP_PATH: {
                "schema": "sword-operation",
                "owner_id": OP_REF,
                "operation_ref": OP_REF,
                "status": "active",
                "command_group_ref": GROUP_REF,
                "formation_refs": ["formation_qin_a", "formation_house_private"],
                "auxiliary_formation_refs": ["formation_house_private"],
                "operational_orders": [
                    {
                        "order_ref": PRIOR_REF,
                        "status": prior_status,
                        "actionability_status": prior_actionability,
                        "applies_to_formation_refs": ["formation_qin_a"],
                        "excluded_non_state_formation_refs": ["formation_house_private"],
                    },
                    {
                        "order_ref": PENDING_REF,
                        "status": "strategic_directive_pending_operational_briefing",
                        "actionability_status": "pending_operational_briefing",
                        "applies_to_formation_refs": ["formation_qin_a"],
                        "excluded_non_state_formation_refs": ["formation_house_private"],
                    },
                ],
                "last_operational_order_ref": PENDING_REF,
                "order_status": "awaiting_operational_briefing",
            },
        }

    def read(self, path):
        if path not in self.data:
            raise FileNotFoundError(path)
        return copy.deepcopy(self.data[path])

    def put(self, path, value):
        self.data[path] = copy.deepcopy(value)
        self.writes.append(path)


def _exact_operation_record(planner, operation_ref):
    if operation_ref != OP_REF:
        return None
    return OP_PATH, planner.read(OP_PATH)


def test_legacy_qin_appointment_is_normalized_and_displaced_mission_restored(monkeypatch):
    planner = _Planner()
    monkeypatch.setattr(reconciliation, "exact_operation_record", _exact_operation_record)

    repaired = reconciliation.reconcile_legacy_qin_command_support_state(planner)

    appointment = planner.data["state/player.json"]["career_state"]["appointments"][0]
    operation = planner.data[OP_PATH]
    assert appointment["operation_ref"] == OP_REF
    assert repaired == [OP_REF]
    assert operation["last_operational_order_ref"] == PRIOR_REF
    assert operation["order_status"] == "staff_briefed_awaiting_commander_execution"
    pending = operation["operational_orders"][1]
    assert pending["order_ref"] == PENDING_REF
    assert pending["actionability_status"] == "pending_operational_briefing"
    assert pending["excluded_non_state_formation_refs"] == ["formation_house_private"]

    planner.writes.clear()
    assert reconciliation.reconcile_legacy_qin_command_support_state(planner) == []
    assert planner.writes == []


def test_reconciliation_does_not_revive_past_completed_phase(monkeypatch):
    planner = _Planner(
        prior_actionability="completed",
        prior_status="phase_complete_awaiting_follow_on_direction",
    )
    monkeypatch.setattr(reconciliation, "exact_operation_record", _exact_operation_record)

    repaired = reconciliation.reconcile_legacy_qin_command_support_state(planner)

    appointment = planner.data["state/player.json"]["career_state"]["appointments"][0]
    operation = planner.data[OP_PATH]
    assert appointment["operation_ref"] == OP_REF
    assert repaired == []
    assert operation["last_operational_order_ref"] == PENDING_REF
    assert operation["order_status"] == "awaiting_operational_briefing"


def test_legacy_group_mismatch_fails_closed(monkeypatch):
    planner = _Planner()
    planner.data[GROUP_PATH]["command_group_ref"] = "cmdgrp.someone_else.field_army"
    monkeypatch.setattr(reconciliation, "exact_operation_record", _exact_operation_record)

    assert reconciliation.reconcile_legacy_qin_command_support_state(planner) == []
    appointment = planner.data["state/player.json"]["career_state"]["appointments"][0]
    assert "operation_ref" not in appointment
    assert planner.data[OP_PATH]["last_operational_order_ref"] == PENDING_REF
    assert planner.writes == []
