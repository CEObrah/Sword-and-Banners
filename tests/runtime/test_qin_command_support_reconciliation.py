from __future__ import annotations

import copy

import sword_runtime.qin_command_support_reconciliation as reconciliation


OP_REF = "operation_fixture_qin_legacy_scope"
OP_PATH = f"state/operations/{OP_REF}.json"
GROUP_REF = "cmdgrp.tang_wei.field_army"
GROUP_PATH = f"state/cmd/command-groups/{GROUP_REF}.json"
PRIOR_REF = "operational_order_fixture_actionable"
PENDING_REF = "operational_order_fixture_pending"
PRIOR_ISSUED = "244-BCE-11-15T08:22:48+08:00"
PENDING_ISSUED = "244-BCE-11-19T20:22:48+08:00"
RUNTIME_PATH = "state/runtime.json"
LOGISTICS_PATH = "game/data/mechanics/logistics.json"
EVENT_OWNER_PATH = "state/event/events-messages-and-movement.json"
AUTO_WORK_REF = reconciliation._auto_briefing_work_ref(OP_REF, PENDING_REF)
AUTO_HOST_REF, AUTO_EVENT_REF = reconciliation._review_ids(AUTO_WORK_REF)


class _Planner:
    def __init__(
        self,
        *,
        current_ref=PENDING_REF,
        prior_actionability="actionable",
        prior_status="staff_briefed_awaiting_commander_execution",
    ):
        self.writes = []
        order_status = (
            "awaiting_operational_briefing"
            if current_ref == PENDING_REF
            else prior_status
        )
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
                        "issued_at": PRIOR_ISSUED,
                        "status": prior_status,
                        "actionability_status": prior_actionability,
                        "applies_to_formation_refs": ["formation_qin_a"],
                        "excluded_non_state_formation_refs": ["formation_house_private"],
                    },
                    {
                        "order_ref": PENDING_REF,
                        "issued_at": PENDING_ISSUED,
                        "status": "strategic_directive_pending_operational_briefing",
                        "actionability_status": "pending_operational_briefing",
                        "applies_to_formation_refs": ["formation_qin_a"],
                        "excluded_non_state_formation_refs": ["formation_house_private"],
                    },
                ],
                "last_operational_order_ref": current_ref,
                "order_status": order_status,
            },
            LOGISTICS_PATH: {
                "military_supply_policy": {"qin_support_review_delay_hours": 4}
            },
            EVENT_OWNER_PATH: {
                "schema": "event-registry",
                "owner_id": "events_messages_and_movement",
                "causal_events": {},
                "archives": [],
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


def _seed_auto_route(planner, *, world_time, next_due, travel_seconds=23 * 3600, work_ref=AUTO_WORK_REF):
    planner.data[RUNTIME_PATH] = {
        "world_time": world_time,
        "hosts": {
            AUTO_HOST_REF: {
                "host_id": AUTO_HOST_REF,
                "kind": "qin_command_support_review",
                "work_ref": work_ref,
                "support_kind": "operational_briefing",
                "operation_ref": OP_REF,
                "order_ref": PENDING_REF,
                "communication_travel_seconds": travel_seconds,
                "next_due": next_due,
                "resolved_through": world_time,
                "safe_through": world_time,
            }
        },
        "events": [{
            "event_id": AUTO_EVENT_REF,
            "kind": "qin_command_support_review",
            "priority": 43,
            "target_host": AUTO_HOST_REF,
            "due_at": next_due,
        }],
    }


def _seed_empty_runtime(planner, *, world_time="244-BCE-12-21T12:00:00+08:00"):
    planner.data[RUNTIME_PATH] = {
        "world_time": world_time,
        "hosts": {},
        "events": [],
    }


def _patch_route(monkeypatch):
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


def test_legacy_qin_appointment_is_normalized_without_rolling_back_newer_pending_order(monkeypatch):
    planner = _Planner()
    monkeypatch.setattr(reconciliation, "exact_operation_record", _exact_operation_record)

    repaired = reconciliation.reconcile_legacy_qin_command_support_state(planner)

    appointment = planner.data["state/player.json"]["career_state"]["appointments"][0]
    operation = planner.data[OP_PATH]
    assert appointment["operation_ref"] == OP_REF
    assert repaired == []
    assert operation["last_operational_order_ref"] == PENDING_REF
    assert operation["order_status"] == "awaiting_operational_briefing"

    planner.writes.clear()
    assert reconciliation.reconcile_legacy_qin_command_support_state(planner) == []
    assert planner.writes == []


def test_reconciliation_heals_regressed_pointer_to_newer_pending_order(monkeypatch):
    planner = _Planner(current_ref=PRIOR_REF)
    monkeypatch.setattr(reconciliation, "exact_operation_record", _exact_operation_record)

    repaired = reconciliation.reconcile_legacy_qin_command_support_state(planner)

    operation = planner.data[OP_PATH]
    assert repaired == [OP_REF]
    assert operation["last_operational_order_ref"] == PENDING_REF
    assert operation["order_status"] == "awaiting_operational_briefing"
    assert operation["operational_orders"][0]["order_ref"] == PRIOR_REF
    assert operation["operational_orders"][1]["order_ref"] == PENDING_REF

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

    operation = planner.data[OP_PATH]
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


def test_pending_order_selection_uses_issued_at_not_list_position(monkeypatch):
    planner = _Planner()
    monkeypatch.setattr(reconciliation, "exact_operation_record", _exact_operation_record)
    orders = planner.data[OP_PATH]["operational_orders"]
    planner.data[OP_PATH]["operational_orders"] = [orders[1], orders[0]]

    assert reconciliation._latest_pending_order_ref(planner, OP_REF) == PENDING_REF


def test_newer_actionable_order_suppresses_older_pending_by_issued_at(monkeypatch):
    planner = _Planner()
    monkeypatch.setattr(reconciliation, "exact_operation_record", _exact_operation_record)
    planner.data[OP_PATH]["operational_orders"][0]["issued_at"] = "244-BCE-11-21T08:22:48+08:00"

    assert reconciliation._latest_pending_order_ref(planner, OP_REF) == ""


def test_missing_automatic_briefing_host_is_created_from_qin_scope(monkeypatch):
    planner = _Planner()
    monkeypatch.setattr(reconciliation, "exact_operation_record", _exact_operation_record)
    _patch_route(monkeypatch)
    orders = planner.data[OP_PATH]["operational_orders"]
    planner.data[OP_PATH]["operational_orders"] = [orders[1], orders[0]]
    _seed_empty_runtime(planner)

    changed = reconciliation.reconcile_overdue_qin_command_support_routes(planner)

    assert changed == [AUTO_WORK_REF]
    host = planner.data[RUNTIME_PATH]["hosts"][AUTO_HOST_REF]
    assert host["support_kind"] == "operational_briefing"
    assert host["operation_ref"] == OP_REF
    assert host["order_ref"] == PENDING_REF
    assert host["formation_refs"] == ["formation_qin_a"]
    assert host["next_due"] == "244-BCE-12-21T12:00:01+08:00"
    assert host["communication_travel_seconds"] == 23 * 3600
    events = planner.data[RUNTIME_PATH]["events"]
    assert len(events) == 1
    assert events[0]["event_id"] == AUTO_EVENT_REF
    assert events[0]["target_host"] == AUTO_HOST_REF
    assert events[0]["due_at"] == "244-BCE-12-21T12:00:01+08:00"

    planner.writes.clear()
    assert reconciliation.reconcile_overdue_qin_command_support_routes(planner) == []
    assert planner.writes == []
    assert len(planner.data[RUNTIME_PATH]["events"]) == 1


def test_overdue_automatic_briefing_is_due_at_next_scheduler_tick(monkeypatch):
    planner = _Planner()
    monkeypatch.setattr(reconciliation, "exact_operation_record", _exact_operation_record)
    _seed_auto_route(
        planner,
        world_time="244-BCE-12-21T12:00:00+08:00",
        next_due="244-BCE-12-22T15:00:00+08:00",
    )

    changed = reconciliation.reconcile_overdue_qin_command_support_routes(planner)

    assert changed == [AUTO_WORK_REF]
    host = planner.data[RUNTIME_PATH]["hosts"][AUTO_HOST_REF]
    event = planner.data[RUNTIME_PATH]["events"][0]
    assert host["next_due"] == "244-BCE-12-21T12:00:01+08:00"
    assert event["due_at"] == "244-BCE-12-21T12:00:01+08:00"


def test_fresh_automatic_briefing_uses_original_issue_time(monkeypatch):
    planner = _Planner()
    monkeypatch.setattr(reconciliation, "exact_operation_record", _exact_operation_record)
    planner.data[OP_PATH]["operational_orders"][1]["issued_at"] = "244-BCE-12-21T11:00:00+08:00"
    _seed_auto_route(
        planner,
        world_time="244-BCE-12-21T12:00:00+08:00",
        next_due="244-BCE-12-22T15:00:00+08:00",
    )

    changed = reconciliation.reconcile_overdue_qin_command_support_routes(planner)

    assert changed == [AUTO_WORK_REF]
    assert planner.data[RUNTIME_PATH]["hosts"][AUTO_HOST_REF]["next_due"] == "244-BCE-12-22T14:00:00+08:00"
    assert planner.data[RUNTIME_PATH]["events"][0]["due_at"] == "244-BCE-12-22T14:00:00+08:00"


def test_exhausted_automatic_briefing_host_is_reactivated(monkeypatch):
    planner = _Planner()
    monkeypatch.setattr(reconciliation, "exact_operation_record", _exact_operation_record)
    _seed_auto_route(
        planner,
        world_time="244-BCE-12-21T12:00:00+08:00",
        next_due=None,
    )
    planner.data[RUNTIME_PATH]["events"][0]["suspended"] = True

    changed = reconciliation.reconcile_overdue_qin_command_support_routes(planner)

    assert changed == [AUTO_WORK_REF]
    host = planner.data[RUNTIME_PATH]["hosts"][AUTO_HOST_REF]
    assert host["next_due"] == "244-BCE-12-21T12:00:01+08:00"
    events = planner.data[RUNTIME_PATH]["events"]
    assert len(events) == 1
    assert events[0]["target_host"] == AUTO_HOST_REF
    assert events[0]["due_at"] == "244-BCE-12-21T12:00:01+08:00"
    assert events[0].get("suspended") is not True


def test_missing_scheduler_event_for_live_automatic_briefing_is_rebuilt(monkeypatch):
    planner = _Planner()
    monkeypatch.setattr(reconciliation, "exact_operation_record", _exact_operation_record)
    planner.data[OP_PATH]["operational_orders"][1]["issued_at"] = "244-BCE-12-21T11:00:00+08:00"
    due = "244-BCE-12-22T14:00:00+08:00"
    _seed_auto_route(
        planner,
        world_time="244-BCE-12-21T12:00:00+08:00",
        next_due=due,
    )
    planner.data[RUNTIME_PATH]["events"] = []

    changed = reconciliation.reconcile_overdue_qin_command_support_routes(planner)

    assert changed == [AUTO_WORK_REF]
    assert planner.data[RUNTIME_PATH]["hosts"][AUTO_HOST_REF]["next_due"] == due
    events = planner.data[RUNTIME_PATH]["events"]
    assert len(events) == 1
    assert events[0]["target_host"] == AUTO_HOST_REF
    assert events[0]["due_at"] == due


def test_exhausted_host_for_resolved_briefing_is_not_reactivated(monkeypatch):
    planner = _Planner()
    monkeypatch.setattr(reconciliation, "exact_operation_record", _exact_operation_record)
    pending = planner.data[OP_PATH]["operational_orders"][1]
    pending["status"] = "staff_briefed_awaiting_commander_execution"
    pending["actionability_status"] = "actionable"
    _seed_auto_route(
        planner,
        world_time="244-BCE-12-21T12:00:00+08:00",
        next_due=None,
    )

    assert reconciliation.reconcile_overdue_qin_command_support_routes(planner) == []
    assert planner.data[RUNTIME_PATH]["hosts"][AUTO_HOST_REF]["next_due"] is None


def test_existing_institutional_response_prevents_route_reactivation(monkeypatch):
    planner = _Planner()
    monkeypatch.setattr(reconciliation, "exact_operation_record", _exact_operation_record)
    _seed_auto_route(
        planner,
        world_time="244-BCE-12-21T12:00:00+08:00",
        next_due=None,
    )
    response_ref = reconciliation._response_ref(AUTO_WORK_REF)
    planner.data[EVENT_OWNER_PATH]["causal_events"][response_ref] = {
        "event_ref": response_ref,
        "kind": "institutional_response",
        "status": "triggered",
    }

    assert reconciliation.reconcile_overdue_qin_command_support_routes(planner) == []
    assert planner.data[RUNTIME_PATH]["hosts"][AUTO_HOST_REF]["next_due"] is None


def test_explicit_support_request_timing_is_untouched(monkeypatch):
    planner = _Planner()
    monkeypatch.setattr(reconciliation, "exact_operation_record", _exact_operation_record)
    original_due = "244-BCE-12-22T15:00:00+08:00"
    _seed_auto_route(
        planner,
        world_time="244-BCE-12-21T12:00:00+08:00",
        next_due=original_due,
        work_ref="interaction_attempt_fixture",
    )

    assert reconciliation.reconcile_overdue_qin_command_support_routes(planner) == []
    assert planner.data[RUNTIME_PATH]["hosts"][AUTO_HOST_REF]["next_due"] == original_due
    assert planner.data[RUNTIME_PATH]["events"][0]["due_at"] == original_due
