import copy

import sword_runtime.campaign_command_decision as decision
import sword_runtime.campaign_communications as communications
from sword_runtime.campaign_command_cycle import retain_campaign_command_decisions


class _FakePlanner:
    PLAYER_ACTOR = "char_tang_wei"

    def __init__(self, data):
        self.data = copy.deepcopy(data)
        self.puts = []

    def read(self, path):
        if path not in self.data:
            raise FileNotFoundError(path)
        return copy.deepcopy(self.data[path])

    def read_optional(self, path):
        value = self.data.get(path)
        return copy.deepcopy(value) if value is not None else None

    def put(self, path, value):
        self.data[path] = copy.deepcopy(value)
        self.puts.append(path)

    def owner_path(self, owner_ref):
        paths = {
            "char_mou_gou": "state/people/char_mou_gou.json",
            "campaign_command_cycle.test": "cycle.json",
        }
        if owner_ref not in paths:
            raise KeyError(owner_ref)
        return paths[owner_ref]


def _cycle():
    return {
        "kind": "campaign_command_cycle",
        "cycle_ref": "campaign_command_cycle.test",
        "operation_ref": "operation.test",
        "status": "campaign_command_active",
        "venue_ref": "loc_sanyou",
        "war_council": {"status": "held"},
        "supreme_commander_ref": "char_mou_gou",
        "superior_command_ref": "char_mou_gou",
        "coordination_authority_ref": "inst_qin_military_bureau",
        "upward_reports": [],
        "reported_command_information_refs": [],
        "reported_follow_on_request_refs": [],
        "campaign_command_decision_refs": [],
    }


def _operation():
    return {
        "owner_id": "operation.test",
        "status": "active",
        "location_ref": "loc_sanyou",
        "operational_area_ref": "loc_sanyou",
        "strategic_target_ref": "loc_sanyou",
        "institutional_owner_ref": "state_qin",
        "campaign_phase": "operational_area_arrival",
        "order_status": "awaiting_follow_on_direction",
        "last_operational_order_ref": "operational_order.base",
        "operational_orders": [{
            "order_ref": "operational_order.base",
            "issued_at": "244-BCE-09-17T22:22:48+08:00",
            "issuer_ref": "state_qin",
            "superior_commander_ref": "char_mou_gou",
            "status": "phase_complete_awaiting_follow_on_direction",
            "actionability_status": "completed",
            "objective": "Reach Sanyou and report on arrival.",
            "mission_packet": {
                "strategic_target_ref": "loc_sanyou",
                "strategic_target_name": "Sanyou",
                "destination_ref": "loc_sanyou",
                "destination_name": "Sanyou",
            },
            "applies_to_formation_refs": ["formation_qin_a", "formation_qin_b"],
            "excluded_non_state_formation_refs": ["formation_house_tang_a"],
        }],
    }


def test_bounded_campaign_command_history_never_evicts_live_delivery_work():
    decisions = [
        {"decision_ref": "pending.old", "order_ref": "order.pending.old", "delivery_status": "in_transit"}
    ] + [
        {"decision_ref": f"delivered.{i}", "order_ref": f"order.delivered.{i}", "delivery_status": "delivered"}
        for i in range(40)
    ]
    kept_decisions = retain_campaign_command_decisions(decisions)
    assert any(row["decision_ref"] == "pending.old" for row in kept_decisions)
    assert len([row for row in kept_decisions if row["delivery_status"] == "delivered"]) == 32

    reports = [
        {"report_ref": "report.pending.old", "delivery_status": "route_unresolved"}
    ] + [
        {"report_ref": f"report.delivered.{i}", "delivery_status": "delivered"}
        for i in range(60)
    ]
    kept_reports = communications.retain_upward_reports(reports)
    assert any(row["report_ref"] == "report.pending.old" for row in kept_reports)
    assert len([row for row in kept_reports if row["delivery_status"] == "delivered"]) == 48


def _base_data(*, with_intelligence=True, attempts=None, superior_location="loc_sanyou"):
    data = {
        "state/runtime.json": {
            "world_time": "244-BCE-09-29T18:00:00+08:00",
            "hosts": {},
            "events": [],
        },
        "state/player.json": {"location": "loc_sanyou"},
        "state/people/char_mou_gou.json": {
            "person_ref": "char_mou_gou",
            "current_location": superior_location,
        },
        "state/cmd/command-groups/cmdgrp.tang_wei.field_army.json": {
            "active_context_ref": "operation.test",
        },
        "state/information/index.json": {
            "claims": {},
            "by_holder": {"char_tang_wei": []},
        },
        "state/index/interaction-attempts.json": {"attempts": list(attempts or [])},
        "cycle.json": _cycle(),
        "operation.json": _operation(),
        "game/data/mechanics/campaign-command.json": {
            "campaign_command_cycle": {"superior_request_response_delay_minutes": 15}
        },
    }
    if with_intelligence:
        info_ref = "information.military_reconnaissance.test"
        info_path = "state/information/claims/test.json"
        data["state/information/index.json"] = {
            "claims": {info_ref: info_path},
            "by_holder": {"char_tang_wei": [info_ref]},
        }
        data[info_path] = {
            "information_ref": info_ref,
            "classification": "command_intelligence",
            "subject_ref": "military_reconnaissance:loc_wei_regional_02",
            "claim": "Eight enemy formations were observed in the assigned corridor.",
            "confidence_milli": 746,
            "provenance": "military_reconnaissance",
            "holder_states": {
                "char_tang_wei": {
                    "learned_at": "244-BCE-09-29T17:30:00+08:00",
                    "source_ref": "char_ren_qiao",
                }
            },
        }
    return data


def _patch_exact_owners(monkeypatch, planner):
    monkeypatch.setattr(
        decision,
        "_read_cycle",
        lambda _planner, operation_ref: (
            "cycle.json", copy.deepcopy(planner.data["cycle.json"])
        ) if operation_ref == "operation.test" else None,
    )
    monkeypatch.setattr(
        decision,
        "_load_operation",
        lambda _planner, operation_ref: (
            "operation.json", copy.deepcopy(planner.data["operation.json"])
        ) if operation_ref == "operation.test" else (_ for _ in ()).throw(KeyError(operation_ref)),
    )


def test_material_command_intelligence_creates_one_bounded_follow_on_order(monkeypatch):
    planner = _FakePlanner(_base_data())
    _patch_exact_owners(monkeypatch, planner)
    monkeypatch.setattr(
        communications,
        "command_message_route",
        lambda _read, origin, destination, **_kwargs: {
            "origin_ref": origin,
            "destination_ref": destination,
            "travel_seconds": 0,
        },
    )

    created = decision.sync_campaign_command_decisions(planner)
    assert len(created) == 1
    operation = planner.data["operation.json"]
    latest = operation["operational_orders"][-1]
    assert latest["order_ref"] == created[0]
    assert latest["order_kind"] == "campaign_command_follow_on_mission"
    assert latest["status"] == "issued_pending_delivery"
    assert latest["actionability_status"] == "pending_delivery"
    assert latest["mission_packet"]["mission_phase"] == "contact_development"
    assert latest["mission_packet"]["phase_status"] == "issued_pending_delivery"
    assert latest["mission_packet"]["source_information_refs"] == [
        "information.military_reconnaissance.test"
    ]
    assert latest["applies_to_formation_refs"] == ["formation_qin_a", "formation_qin_b"]
    assert latest["excluded_non_state_formation_refs"] == ["formation_house_tang_a"]
    assert "formation_refs" not in latest["mission_packet"]
    # Superior issuance is not field receipt. The exact current operation remains
    # on its previously delivered order until the courier delivery owner activates it.
    assert operation["last_operational_order_ref"] == "operational_order.base"
    assert operation["campaign_phase"] == "operational_area_arrival"
    assert operation["order_status"] == "awaiting_follow_on_direction"

    cycle = planner.data["cycle.json"]
    assert cycle["reported_command_information_refs"] == ["information.military_reconnaissance.test"]
    assert cycle["upward_reports"][-1]["phase"] == "material_intelligence"
    assert len(cycle["campaign_command_decisions"]) == 1
    assert cycle["campaign_command_decisions"][0]["delivery_status"] == "pending_delivery"
    assert cycle.get("current_superior_order") is None

    assert decision.sync_campaign_command_decisions(planner) == []
    assert len(planner.data["operation.json"]["operational_orders"]) == 2



def test_remote_material_intelligence_cannot_drive_superior_order_before_courier_delivery(monkeypatch):
    planner = _FakePlanner(_base_data(superior_location="loc_qin_eastern_depot"))
    _patch_exact_owners(monkeypatch, planner)
    monkeypatch.setattr(
        communications,
        "command_message_route",
        lambda _read, origin, destination, **_kwargs: {
            "origin_ref": origin,
            "destination_ref": destination,
            "route_refs": ["route.sanyou_to_depot"],
            "path": [origin, destination],
            "one_way_seconds": 3600,
            "travel_seconds": 3600,
            "round_trip": False,
            "modes": ["horse"],
        },
    )

    assert decision.sync_campaign_command_decisions(planner) == []
    cycle = planner.data["cycle.json"]
    assert cycle["reported_command_information_refs"] == []
    report = cycle["upward_reports"][-1]
    assert report["phase"] == "material_intelligence"
    assert report["delivery_status"] == "in_transit"
    assert report["communication_travel_seconds"] == 3600
    assert report["delivery_due_at"] == "244-BCE-09-29T19:00:00+08:00"
    runtime = planner.data["state/runtime.json"]
    host = next(iter(runtime["hosts"].values()))
    assert host["kind"] == "campaign_command_report_delivery"
    assert len(planner.data["operation.json"]["operational_orders"]) == 1

    communications.settle_upward_report_delivery(
        planner, host, "244-BCE-09-29T19:00:00+08:00"
    )
    planner.data["state/runtime.json"]["world_time"] = "244-BCE-09-29T19:00:00+08:00"
    created = decision.sync_campaign_command_decisions(planner)
    assert len(created) == 1
    assert planner.data["cycle.json"]["reported_command_information_refs"] == [
        "information.military_reconnaissance.test"
    ]
    assert planner.data["cycle.json"]["upward_reports"][-1]["delivery_status"] == "delivered"



def test_compact_upward_report_projection_exposes_delivery_state_not_just_preparation_time():
    from sword_runtime.api.command_discovery import _compact_upward_reports

    rows, count = _compact_upward_reports([{
        "report_ref": "campaign_command_report.test",
        "phase": "material_intelligence",
        "prepared_at": "244-BCE-09-29T18:00:00+08:00",
        "reported_at": "244-BCE-09-29T18:00:00+08:00",
        "delivery_status": "in_transit",
        "delivery_due_at": "244-BCE-09-29T19:00:00+08:00",
        "source_location_ref": "loc_sanyou",
        "target_location_ref": "loc_qin_eastern_depot",
        "communication_travel_seconds": 3600,
        "information_refs": ["information.military_reconnaissance.test"],
    }])
    assert count == 1
    assert rows[0]["prepared_at"] == "244-BCE-09-29T18:00:00+08:00"
    assert rows[0]["delivery_status"] == "in_transit"
    assert rows[0]["delivery_due_at"] == "244-BCE-09-29T19:00:00+08:00"
    assert rows[0]["communication_travel_seconds"] == 3600




def test_upward_report_chases_superior_who_moves_before_delivery(monkeypatch):
    planner = _FakePlanner(_base_data(superior_location="loc_qin_eastern_depot"))
    _patch_exact_owners(monkeypatch, planner)

    def route(_read, origin, destination, **_kwargs):
        seconds = 3600 if (origin, destination) == ("loc_sanyou", "loc_qin_eastern_depot") else 7200
        return {
            "origin_ref": origin,
            "destination_ref": destination,
            "route_refs": [f"route.{origin}.{destination}"],
            "path": [origin, destination],
            "one_way_seconds": seconds,
            "travel_seconds": seconds,
            "round_trip": False,
            "modes": ["horse"],
        }

    monkeypatch.setattr(communications, "command_message_route", route)
    assert decision.sync_campaign_command_decisions(planner) == []
    cycle = planner.data["cycle.json"]
    report = cycle["upward_reports"][-1]
    runtime = planner.data["state/runtime.json"]
    host_id, host = next(iter(runtime["hosts"].items()))
    planner._active_host_id = host_id

    # The courier reaches the original post, but Mou Gou has moved. Receipt must
    # stay false and the same host must chase the named superior.
    planner.data["state/people/char_mou_gou.json"]["current_location"] = "loc_kanyou"
    assert communications.settle_upward_report_delivery(
        planner, host, "244-BCE-09-29T19:00:00+08:00"
    ) is None
    cycle = planner.data["cycle.json"]
    report = cycle["upward_reports"][-1]
    assert report["delivery_status"] == "in_transit"
    assert report["target_location_ref"] == "loc_kanyou"
    assert report["courier_reroutes"][-1]["destination_ref"] == "loc_kanyou"
    assert cycle["reported_command_information_refs"] == []
    active = planner.data["state/runtime.json"]["hosts"][host_id]
    assert active["target_location_ref"] == "loc_kanyou"
    assert active["recurrence_seconds"] == 7200

    # Once the rerouted courier reaches Mou Gou's current post, the report becomes
    # usable by superior command exactly once.
    delivered = communications.settle_upward_report_delivery(
        planner, active, "244-BCE-09-29T21:00:00+08:00"
    )
    assert delivered is not None
    assert delivered["delivery_status"] == "delivered"
    assert planner.data["cycle.json"]["reported_command_information_refs"] == [
        "information.military_reconnaissance.test"
    ]
