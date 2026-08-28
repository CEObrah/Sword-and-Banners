from __future__ import annotations

import copy
from pathlib import Path

from sword_runtime.api.interaction_surface import INTERACTION_ATTEMPT_LEDGER_PATH
from sword_runtime.campaign_command_contact_flow import (
    _campaign_command_route_for_attempt,
    _request_ids,
)
from sword_runtime.causal_event_store import get_causal_event_from_reader
from sword_runtime.contact_request_flow import _response_ref, _settle_contact_request
from sword_runtime.production_runtime_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime


CYCLE_REF = "campaign_command_cycle.885d1dbce1823cdb2495"
MOU_GOU_REF = "char_mou_gou"


def _planner(campaign: Path) -> ProductionCampaignPlanner:
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    return planner


def _record_seek_attempt(planner: ProductionCampaignPlanner, *, event_id: str, target_ref: str = MOU_GOU_REF) -> dict:
    runtime = planner.read("state/runtime.json")
    now = str(runtime["world_time"])
    attempt = {
        "event_id": event_id,
        "at": now,
        "surface_digest": f"digest-{event_id}",
        "actor_id": "char_tang_wei",
        "target_ref": target_ref,
        "action": "seek_contact",
        "process_ref": CYCLE_REF,
        "player_statement": None,
        "formation_refs": [],
        "posture": None,
        "topic": None,
        "scopes": [],
        "world_response_status": "not_established_by_attempt",
        "scene_session_ref": None,
        "thread_status": "not_applicable",
        "resolved_at": None,
        "response_ref": None,
    }
    ledger = copy.deepcopy(planner.read(INTERACTION_ATTEMPT_LEDGER_PATH))
    rows = ledger.setdefault("attempts", [])
    assert isinstance(rows, list)
    rows.append(attempt)
    ledger["total_recorded"] = int(ledger.get("total_recorded", 0)) + 1
    planner.put(INTERACTION_ATTEMPT_LEDGER_PATH, ledger)
    return attempt


def test_named_superior_seek_routes_through_active_campaign_command_staff(campaign: Path) -> None:
    planner = _planner(campaign)
    attempt = {
        "event_id": "interaction_attempt_test_mou_gou_route",
        "at": str(planner.read("state/runtime.json")["world_time"]),
        "actor_id": "char_tang_wei",
        "target_ref": MOU_GOU_REF,
        "action": "seek_contact",
        "process_ref": CYCLE_REF,
    }

    route = _campaign_command_route_for_attempt(planner, attempt)

    assert route is not None
    assert route["campaign_command_cycle_ref"] == CYCLE_REF
    assert route["institution_ref"] == "inst_qin_military_bureau"
    assert route["target_person_ref"] == MOU_GOU_REF
    assert route["target_person_name"] == "Mou Gou"
    assert route["route_domain"] == "campaign_command_contact"
    assert route["delay_seconds"] == 30 * 60
    assert "receiving staff only" in route["audience_summary"]
    assert "has not yet received Tang Wei in person or answered him" in route["audience_summary"]


def test_named_campaign_contact_fails_closed_for_non_superior_participant(campaign: Path) -> None:
    planner = _planner(campaign)
    attempt = {
        "event_id": "interaction_attempt_test_ouki_route",
        "at": str(planner.read("state/runtime.json")["world_time"]),
        "actor_id": "char_tang_wei",
        "target_ref": "char_ouki",
        "action": "seek_contact",
        "process_ref": CYCLE_REF,
    }

    assert _campaign_command_route_for_attempt(planner, attempt) is None


def test_prepare_registers_existing_seek_attempt_without_waiting_for_global_reconcile(campaign: Path) -> None:
    planner = _planner(campaign)
    event_id = "interaction_attempt_test_campaign_command_prepare"
    attempt = _record_seek_attempt(planner, event_id=event_id)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    runtime["scheduler"]["dirty"] = False
    runtime["scheduler"]["dirty_reasons"] = []
    planner.put("state/runtime.json", runtime)
    current = CampaignTime.parse(str(runtime["world_time"]))

    planner._prepare_scheduler_for_advance(str(current.add_hours(1)))

    after = planner.read("state/runtime.json")
    host_id, scheduler_event_id = _request_ids(event_id)
    host = after["hosts"].get(host_id)
    assert isinstance(host, dict)
    assert host["kind"] == "contact_request"
    assert host["owner_ref"] == "inst_qin_military_bureau"
    assert host["source_event_id"] == event_id
    assert host["source_process_ref"] == CYCLE_REF
    assert host["route_domain"] == "campaign_command_contact"
    assert host["requested_person_ref"] == MOU_GOU_REF
    assert host["next_due"] == str(current.add_seconds(30 * 60))
    assert any(
        row.get("event_id") == scheduler_event_id and row.get("target_host") == host_id
        for row in after["events"]
        if isinstance(row, dict)
    )
    assert get_causal_event_from_reader(planner, _response_ref(event_id)) is None
    assert attempt["world_response_status"] == "not_established_by_attempt"


def test_campaign_command_contact_settlement_is_staff_reception_not_mou_gou_reply(campaign: Path) -> None:
    planner = _planner(campaign)
    event_id = "interaction_attempt_test_campaign_command_settlement"
    _record_seek_attempt(planner, event_id=event_id)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    assert planner._sync_campaign_command_contact_routes(runtime) >= 1
    host_id, _scheduler_event_id = _request_ids(event_id)
    host = runtime["hosts"][host_id]
    planner.put("state/runtime.json", runtime)

    response_ref = _settle_contact_request(planner, host, str(host["next_due"]))
    response = get_causal_event_from_reader(planner, response_ref)

    assert isinstance(response, dict)
    assert response["kind"] == "audience_response"
    assert response["actor_ref"] == "inst_qin_military_bureau"
    assert response["route_domain"] == "campaign_command_contact"
    assert "Mou Gou has not yet received Tang Wei in person or answered him" in response["summary"]
    assert "present_person_refs" not in response
    assert response.get("actor_ref") != MOU_GOU_REF
