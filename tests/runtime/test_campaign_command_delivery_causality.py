from __future__ import annotations

import copy

import sword_runtime.campaign_command_delivery as delivery


OPERATION_REF = "operation.test.delivery"
CYCLE_REF = "campaign_command_cycle.test.delivery"
BASE_ORDER_REF = "operational_order.base"
NEW_ORDER_REF = "operational_order.follow_on"
ATTEMPT_REF = "interaction_attempt.follow_on.delivery"


class _FakePlanner:
    def __init__(self):
        self.data = {
            "state/runtime.json": {
                "world_time": "244-BCE-12-21T12:00:01+08:00",
                "hosts": {
                    "legacy_review": {
                        "host_id": "legacy_review",
                        "kind": "institutional_followup",
                        "route_domain": "campaign_command_follow_on_review",
                        "next_due": "244-BCE-12-23T10:00:01+08:00",
                    }
                },
                "events": [{
                    "event_id": "legacy_review_event",
                    "kind": "institutional_followup",
                    "target_host": "legacy_review",
                    "due_at": "244-BCE-12-23T10:00:01+08:00",
                }],
            },
            "state/player.json": {"location": "loc_sanyou"},
            "state/cmd/command-groups/cmdgrp.tang_wei.field_army.json": {
                "active_context_ref": OPERATION_REF,
            },
            "cycle.json": {
                "kind": "campaign_command_cycle",
                "cycle_ref": CYCLE_REF,
                "operation_ref": OPERATION_REF,
                "status": "campaign_command_active",
                "superior_command_ref": "char_mou_gou",
                "supreme_commander_ref": "char_mou_gou",
                "delivered_superior_order_refs": [BASE_ORDER_REF],
                "current_superior_order": {"order_ref": NEW_ORDER_REF},
                "campaign_command_decisions": [{
                    "decision_ref": "campaign_command_decision.test",
                    "decided_at": "244-BCE-12-21T12:00:01+08:00",
                    "order_ref": NEW_ORDER_REF,
                    "base_order_ref": BASE_ORDER_REF,
                    "follow_on_request_refs": [],
                }],
            },
            "operation.json": {
                "owner_id": OPERATION_REF,
                "status": "active",
                "location_ref": "loc_sanyou",
                "last_operational_order_ref": NEW_ORDER_REF,
                "order_status": "staff_briefed_awaiting_commander_execution",
                "campaign_phase": "contact_development",
                "operational_orders": [{
                    "order_ref": BASE_ORDER_REF,
                    "issued_at": "244-BCE-11-19T20:22:48+08:00",
                    "status": "phase_complete_awaiting_follow_on_direction",
                    "actionability_status": "completed",
                    "mission_packet": {
                        "mission_phase": "campaign_concentration_and_advance",
                        "phase_status": "completed",
                    },
                }, {
                    "order_ref": NEW_ORDER_REF,
                    "order_kind": "campaign_command_follow_on_mission",
                    "source_order_ref": BASE_ORDER_REF,
                    "issued_at": "244-BCE-12-21T12:00:01+08:00",
                    "superior_commander_ref": "char_mou_gou",
                    "status": "staff_briefed_awaiting_commander_execution",
                    "actionability_status": "actionable",
                    "mission_packet": {
                        "mission_phase": "contact_development",
                        "phase_status": "ready_for_commander_execution",
                    },
                }],
            },
            "state/char/char_mou_gou.json": {
                "person_id": "char_mou_gou",
                "current_location": "loc_qin_regional_01",
            },
            "game/data/mechanics/campaign-command.json": {
                "campaign_command_cycle": {
                    "superior_order_delivery_delay_minutes": 15,
                }
            },
        }
        self.paths = {
            CYCLE_REF: "cycle.json",
            OPERATION_REF: "operation.json",
            "char_mou_gou": "state/char/char_mou_gou.json",
        }

    def read(self, path):
        if path not in self.data:
            raise FileNotFoundError(path)
        return copy.deepcopy(self.data[path])

    def read_optional(self, path):
        value = self.data.get(path)
        return copy.deepcopy(value) if value is not None else None

    def put(self, path, value):
        self.data[path] = copy.deepcopy(value)

    def owner_path(self, ref):
        if ref not in self.paths:
            raise KeyError(ref)
        return self.paths[ref]


def _patch_owners(monkeypatch, planner):
    monkeypatch.setattr(
        delivery,
        "_read_cycle",
        lambda _planner, operation_ref: (
            "cycle.json", copy.deepcopy(planner.data["cycle.json"])
        ) if operation_ref == OPERATION_REF else None,
    )
    monkeypatch.setattr(
        delivery,
        "_load_operation",
        lambda _planner, operation_ref: (
            "operation.json", copy.deepcopy(planner.data["operation.json"])
        ) if operation_ref == OPERATION_REF else (_ for _ in ()).throw(ValueError(operation_ref)),
    )
    monkeypatch.setattr(
        delivery,
        "command_message_route",
        lambda _read, origin, destination, *, round_trip=False: {
            "origin_ref": origin,
            "destination_ref": destination,
            "route_refs": ["route.qin_capital_to_sanyou"],
            "path": [origin, destination],
            "one_way_seconds": 82800,
            "travel_seconds": 82800,
            "round_trip": round_trip,
            "modes": ["horse", "foot"],
        },
    )


def test_legacy_undelivered_decision_is_demoted_and_routed(monkeypatch) -> None:
    planner = _FakePlanner()
    _patch_owners(monkeypatch, planner)

    changed = delivery.reconcile_undelivered_campaign_decisions(planner)
    assert changed == [NEW_ORDER_REF]
    operation = planner.data["operation.json"]
    assert operation["last_operational_order_ref"] == BASE_ORDER_REF
    assert operation["order_status"] == "awaiting_follow_on_direction"
    assert operation["campaign_phase"] == "operational_area_arrival"
    pending = operation["operational_orders"][-1]
    assert pending["status"] == "issued_pending_delivery"
    assert pending["actionability_status"] == "pending_delivery"
    assert planner.data["cycle.json"]["current_superior_order"]["order_ref"] == BASE_ORDER_REF

    result = delivery.sync_campaign_decision_delivery_routes(planner)
    assert result["registered"] == 1
    assert result["retired_legacy_review_hosts"] == 1
    runtime = planner.data["state/runtime.json"]
    assert "legacy_review" not in runtime["hosts"]
    assert not any(event.get("target_host") == "legacy_review" for event in runtime["events"])
    host = next(
        host for host in runtime["hosts"].values()
        if host.get("kind") == "campaign_command_superior_order"
        and host.get("phase_instance_ref") == NEW_ORDER_REF
    )
    assert host["source_location_ref"] == "loc_qin_regional_01"
    assert host["target_location_ref"] == "loc_sanyou"
    assert host["communication_travel_seconds"] == 82800


def test_decision_order_cannot_activate_until_cycle_records_delivery(monkeypatch) -> None:
    planner = _FakePlanner()
    _patch_owners(monkeypatch, planner)
    delivery.reconcile_undelivered_campaign_decisions(planner)
    delivery.sync_campaign_decision_delivery_routes(planner)
    host = next(
        host for host in planner.data["state/runtime.json"]["hosts"].values()
        if host.get("kind") == "campaign_command_superior_order"
    )

    assert delivery.activate_delivered_campaign_decision(
        planner, host, "244-BCE-12-22T11:15:01+08:00"
    ) is False
    assert planner.data["operation.json"]["last_operational_order_ref"] == BASE_ORDER_REF

    planner.data["cycle.json"]["delivered_superior_order_refs"].append(NEW_ORDER_REF)
    assert delivery.activate_delivered_campaign_decision(
        planner, host, "244-BCE-12-22T11:15:01+08:00"
    ) is True
    operation = planner.data["operation.json"]
    assert operation["last_operational_order_ref"] == NEW_ORDER_REF
    assert operation["order_status"] == "staff_briefed_awaiting_commander_execution"
    assert operation["campaign_phase"] == "contact_development"
    order = operation["operational_orders"][-1]
    assert order["actionability_status"] == "actionable"
    assert order["delivered_at"] == "244-BCE-12-22T11:15:01+08:00"
    decision = planner.data["cycle.json"]["campaign_command_decisions"][0]
    assert decision["delivery_status"] == "delivered"


def test_delivered_decision_is_never_demoted(monkeypatch) -> None:
    planner = _FakePlanner()
    planner.data["cycle.json"]["delivered_superior_order_refs"].append(NEW_ORDER_REF)
    _patch_owners(monkeypatch, planner)

    assert delivery.reconcile_undelivered_campaign_decisions(planner) == []
    assert planner.data["operation.json"]["last_operational_order_ref"] == NEW_ORDER_REF
