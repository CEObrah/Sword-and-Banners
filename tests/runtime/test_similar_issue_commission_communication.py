from __future__ import annotations

import copy
from types import SimpleNamespace

from sword_runtime.campaign_depth import _commission_path, _commission_request_path
from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.time_integration import dispatch_due_host


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    return planner


def _cmd(planner, *, actor="char_tang_wei"):
    meta = planner.read("state/meta.json")
    return SimpleNamespace(actor_id=actor, expected_revision=int(meta["revision"]))


def _move_person(planner, person_ref: str, location_ref: str) -> None:
    path = planner.owner_path(person_ref)
    person = copy.deepcopy(planner.read(path))
    person["current_location"] = location_ref
    if "location_ref" in person:
        person["location_ref"] = location_ref
    planner.put(path, person)


def _move_player(planner, location_ref: str) -> None:
    player = copy.deepcopy(planner.read("state/player.json"))
    player["location"] = location_ref
    player["current_location"] = location_ref
    planner.put("state/player.json", player)


def _offer_and_accept_house_tang_commission(planner, request_ref: str):
    request = planner.read(_commission_request_path(request_ref))
    due = str(request["responds_at"])
    result = planner._autonomy_commission(
        {"request_ref": request_ref, "owner_ref": request_ref}, 1, due
    )
    assert result and result["commission_ref"].startswith("commission.")
    commission_ref = str(result["commission_ref"])
    planner._dispatch_commission(
        _cmd(planner), {"action": "accept", "commission_ref": commission_ref}
    )
    return commission_ref


def test_remote_commission_request_includes_physical_round_trip_before_response(campaign):
    planner = _planner(campaign)
    _move_player(planner, "loc_sanyou")
    _move_person(planner, "char_tang_zhu", "loc_tang_manor")
    start = planner._world_time()
    request_ref = "commission.request.test.remote_physical_route"

    result = planner._dispatch_commission(
        _cmd(planner),
        {"action": "request", "request_ref": request_ref, "issuer_ref": "house_tang", "category": None},
    )
    request = planner.read(_commission_request_path(request_ref))
    response = CampaignTime.parse(str(request["responds_at"]))

    assert request["source_location_ref"] == "loc_sanyou"
    assert request["issuer_location_ref"] == "loc_tang_manor"
    assert int(request["communication_travel_seconds"]) > 0
    assert start.seconds_until(response) == int(request["communication_travel_seconds"]) + 6 * 3600
    assert result["communication_travel_seconds"] == request["communication_travel_seconds"]
    assert planner._autonomy_commission(
        {"request_ref": request_ref, "owner_ref": request_ref}, 1, str(start.add_hours(6))
    ) is None
    assert planner.read(_commission_request_path(request_ref))["status"] == "pending"


def test_colocated_commission_request_uses_processing_time_without_fake_travel(campaign):
    planner = _planner(campaign)
    _move_player(planner, "loc_tang_manor")
    _move_person(planner, "char_tang_zhu", "loc_tang_manor")
    start = planner._world_time()
    request_ref = "commission.request.test.local_processing"

    planner._dispatch_commission(
        _cmd(planner),
        {"action": "request", "request_ref": request_ref, "issuer_ref": "house_tang", "category": None},
    )
    request = planner.read(_commission_request_path(request_ref))
    assert int(request["communication_travel_seconds"]) == 0
    assert str(request["responds_at"]) == str(start.add_hours(6))


def test_remote_commission_report_cannot_settle_before_courier_and_reply(campaign):
    planner = _planner(campaign)
    _move_player(planner, "loc_tang_manor")
    _move_person(planner, "char_tang_zhu", "loc_tang_manor")
    request_ref = "commission.request.test.report_delivery"
    planner._dispatch_commission(
        _cmd(planner),
        {"action": "request", "request_ref": request_ref, "issuer_ref": "house_tang", "category": None},
    )
    commission_ref = _offer_and_accept_house_tang_commission(planner, request_ref)

    _move_player(planner, "loc_sanyou")
    report_start = planner._world_time()
    planner._dispatch_commission(
        _cmd(planner),
        {"action": "report", "commission_ref": commission_ref, "report_ref": "report.test.remote", "evidence_refs": []},
    )
    commission = planner.read(_commission_path(commission_ref))
    response_due = CampaignTime.parse(str(commission["report_response_due_at"]))

    assert commission["status"] == "report_in_transit"
    assert int(commission["communication_travel_seconds"]) > 0
    assert report_start.seconds_until(response_due) == int(commission["communication_travel_seconds"]) + 3600
    assert planner._autonomy_commission_settlement(
        {"commission_ref": commission_ref, "owner_ref": commission_ref},
        str(CampaignTime.parse(str(commission["report_delivery_due_at"]))),
    ) is None
    assert planner.read(_commission_path(commission_ref))["status"] == "report_in_transit"

    result = planner._autonomy_commission_settlement(
        {"commission_ref": commission_ref, "owner_ref": commission_ref}, str(response_due)
    )
    assert result and result["status"] == "reported"
    settled = planner.read(_commission_path(commission_ref))
    assert settled["settlement_result"] == "insufficient_relevant_evidence"
    assert settled["report_delivered_at"] == commission["report_delivery_due_at"]


class _CommissionWakeProbe:
    def __init__(self):
        self._pending_wake_created = {"old": "sentinel"}
        self._active_host_id = "host.test"
        self._active_event_id = "event.test"
        self.offer_calls = 0
        self.review_calls = 0

    def _autonomy_commission(self, host, occurrences, due_text):
        self.offer_calls += 1
        return {"commission_ref": "commission.test", "event_id": "offer.test"}

    def _autonomy_commission_settlement(self, host, due_text):
        self.review_calls += 1
        return {"commission_ref": "commission.test", "status": "completed"}


def test_commission_offer_and_review_are_not_hard_scheduler_wakes():
    probe = _CommissionWakeProbe()
    dispatch_due_host(probe, {"kind": "commission", "request_ref": "commission.request.test"}, "244-BCE-10-20T12:00:00+08:00")
    assert probe.offer_calls == 1
    assert probe._pending_wake_created is None

    probe._pending_wake_created = {"old": "sentinel"}
    dispatch_due_host(probe, {"kind": "commission_settlement", "commission_ref": "commission.test"}, "244-BCE-10-20T13:00:00+08:00")
    assert probe.review_calls == 1
    assert probe._pending_wake_created is None
