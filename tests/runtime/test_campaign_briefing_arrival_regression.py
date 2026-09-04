from __future__ import annotations

import copy

from sword_runtime import campaign_briefing as briefing


class _Planner:
    def __init__(self, operation):
        self.operation = copy.deepcopy(operation)

    def put(self, path, value):
        assert path == "state/operations/test.json"
        self.operation = copy.deepcopy(value)


def _operation(*, phase="contact_development", existing_packet=None):
    order = {"order_ref": "order.test"}
    if existing_packet is not None:
        order.update(
            {
                "mission_packet": copy.deepcopy(existing_packet),
                "status": "staff_briefed_awaiting_commander_execution",
                "actionability_status": "actionable",
            }
        )
    return {
        "owner_id": "operation.test",
        "last_operational_order_ref": "order.test",
        "operational_orders": [order],
        "campaign_phase": phase,
        "location_ref": "loc_origin",
    }


def _dossier(*, own_location="loc_origin", destination="loc_target", authorized=True):
    return {
        "own": {"location_refs": [own_location], "strength": 9500, "echelon": {}},
        "other_friendly_participants": [],
        "coordination_authority_ref": "inst_qin_military_bureau",
        "operational_area": {
            "destination_ref": destination,
            "destination_name": "Sanyou" if destination == "loc_sanyou" else "Target",
            "strategic_target_ref": destination,
            "strategic_target_name": "Sanyou" if destination == "loc_sanyou" else "Target",
            "hostile_entry_authorized": authorized,
            "entry_status": "authorized" if authorized else "awaiting_war_or_entry_authority",
        },
        "enemy_intelligence": {
            "estimated_strength_low": 0,
            "estimated_strength_high": 0,
            "confidence_milli": 350,
            "contact_status": "no confirmed opposing field formation",
            "reported_formation_count": 0,
            "reported_field_body_count": 0,
            "reported_commanders": [],
        },
        "friendly_total_strength": 9500,
    }


def _patch_storage(monkeypatch, planner):
    monkeypatch.setattr(
        briefing,
        "_load_operation",
        lambda _planner, _operation_ref: ("state/operations/test.json", copy.deepcopy(planner.operation)),
    )
    monkeypatch.setattr(
        briefing,
        "_location_rows",
        lambda _planner: {
            "loc_origin": {"ref": "loc_origin", "name": "Origin"},
            "loc_target": {"ref": "loc_target", "name": "Target"},
            "loc_sanyou": {"ref": "loc_sanyou", "name": "Sanyou"},
        },
    )


def test_briefing_refresh_preserves_established_campaign_phase(monkeypatch):
    planner = _Planner(_operation(phase="contact_development"))
    _patch_storage(monkeypatch, planner)
    monkeypatch.setattr(briefing, "reconcile_campaign_arrival", lambda *args, **kwargs: None)

    packet = briefing.ensure_actionable_mission_packet(
        planner,
        "operation.test",
        _dossier(own_location="loc_origin", destination="loc_target", authorized=True),
        at="244-BCE-11-08T12:00:00+08:00",
    )

    assert packet["phase_status"] == "ready_for_commander_execution"
    assert packet["destination_ref"] == "loc_target"
    assert planner.operation["campaign_phase"] == "contact_development"
    assert planner.operation["order_status"] == "staff_briefed_awaiting_commander_execution"


def test_current_zero_distance_packet_reconciles_instead_of_reopening_march(monkeypatch):
    existing_packet = {
        "mission_phase": "campaign_concentration_and_advance",
        "phase_status": "ready_for_commander_execution",
        "destination_ref": "loc_sanyou",
        "destination_name": "Sanyou",
        "rendezvous_location_ref": "loc_sanyou",
        "rendezvous_name": "Sanyou",
        "strategic_target_ref": "loc_sanyou",
        "strategic_target_name": "Sanyou",
        "hostile_entry_authorized": True,
        "friendly_participant_operation_refs": [],
        "enemy_estimate": {
            "strength_low": 0,
            "strength_high": 0,
            "confidence_milli": 350,
            "contact_status": "no confirmed opposing field formation",
        },
    }
    planner = _Planner(_operation(phase="contact_development", existing_packet=existing_packet))
    _patch_storage(monkeypatch, planner)
    calls = []

    def _reconcile(_planner, operation_ref, *, destination_ref, at, unit_duties=None):
        calls.append((operation_ref, destination_ref, at))
        operation = copy.deepcopy(planner.operation)
        order = operation["operational_orders"][0]
        completed = copy.deepcopy(order["mission_packet"])
        completed["phase_status"] = "completed"
        completed["actual_arrival_ref"] = destination_ref
        completed["completed_at"] = at
        order["mission_packet"] = completed
        order["actionability_status"] = "completed"
        order["status"] = "phase_complete_awaiting_follow_on_direction"
        operation["campaign_phase"] = "operational_area_arrival"
        operation["order_status"] = "awaiting_follow_on_direction"
        planner.put("state/operations/test.json", operation)
        return {"operation_ref": operation_ref, "phase": "operational_area_arrival"}

    monkeypatch.setattr(briefing, "reconcile_campaign_arrival", _reconcile)

    packet = briefing.ensure_actionable_mission_packet(
        planner,
        "operation.test",
        _dossier(own_location="loc_sanyou", destination="loc_sanyou", authorized=True),
        at="244-BCE-11-08T12:00:00+08:00",
    )

    assert calls == [("operation.test", "loc_sanyou", "244-BCE-11-08T12:00:00+08:00")]
    assert packet["phase_status"] == "completed"
    assert packet["actual_arrival_ref"] == "loc_sanyou"
    assert planner.operation["campaign_phase"] == "operational_area_arrival"
    assert planner.operation["order_status"] == "awaiting_follow_on_direction"


def test_completed_authorized_briefing_never_orders_march_to_current_location(monkeypatch):
    planner = object()
    monkeypatch.setattr(
        briefing,
        "_location_rows",
        lambda _planner: {"loc_sanyou": {"ref": "loc_sanyou", "name": "Sanyou"}},
    )
    dossier = _dossier(own_location="loc_sanyou", destination="loc_sanyou", authorized=True)
    packet = {
        "mission_phase": "campaign_concentration_and_advance",
        "phase_status": "completed",
        "destination_ref": "loc_sanyou",
        "destination_name": "Sanyou",
        "rendezvous_location_ref": "loc_sanyou",
        "rendezvous_name": "Sanyou",
        "hostile_entry_authorized": True,
    }

    text = briefing.render_campaign_briefing(planner, dossier, packet)

    assert "march toward Sanyou" not in text
    assert "arrival and deployment at Sanyou as complete" in text
    assert "another march to the same location" in text
