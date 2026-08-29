from __future__ import annotations

import copy
import hashlib
import json

from fastapi.testclient import TestClient

from sword_runtime.api.app import create_app
from sword_runtime.api.interaction_surface import INTERACTION_ATTEMPT_PREFIX, record_interaction_attempt
from sword_runtime.campaign_follow_on_order import materialize_reconciled_campaign_follow_on_orders
from sword_runtime.causal_event_store import (
    get_causal_event_from_reader,
    read_causal_event_owner,
    write_causal_event_owner,
)
from sword_runtime.contact_request_flow import _settle_contact_request, _settle_institutional_followup
from sword_runtime.interaction_routing_health import summarize_interaction_routing
from sword_runtime.production_runtime_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime


PLAYER = "char_tang_wei"


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner.PLAYER_ACTOR = PLAYER
    planner._reset()
    return planner


def _record(
    planner,
    label: str,
    *,
    action: str,
    target_ref: str,
    process_ref: str | None,
    statement: str,
) -> str:
    at = str(planner.read("state/runtime.json")["world_time"])
    attempt = {
        "schema": "sword-interaction-attempt.v1",
        "surface_digest": hashlib.sha256(label.encode("utf-8")).hexdigest(),
        "actor_id": PLAYER,
        "target_ref": target_ref,
        "action": action,
        "process_ref": process_ref,
        "player_statement": statement,
        "formation_refs": [],
        "posture": "test route",
        "world_response_status": "not_established_by_attempt",
    }
    ref = record_interaction_attempt(
        planner,
        INTERACTION_ATTEMPT_PREFIX
        + json.dumps(attempt, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        at=at,
    )
    assert isinstance(ref, str)
    return ref


def _campaign_cycle(planner):
    operation = planner.read("state/operations/operation_arc_131572c4e8a2892bbc.json")
    cycle_ref = operation.get("campaign_command_cycle_ref")
    assert isinstance(cycle_ref, str) and cycle_ref
    cycle = planner.read(planner.owner_path(cycle_ref))
    return cycle_ref, cycle


def test_direct_person_request_requires_established_access_but_seek_contact_remains_legal(campaign) -> None:
    token = "a" * 48
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(create_app(campaign, token)) as client:
        context = client.get("/v1/play/context", headers=headers).json()
        assert "char_mou_gou" in context["permitted_person_ids"]
        present = {
            row["person_id"]
            for row in context["scene"]["scene_cast"]["present_people"]
            if isinstance(row, dict) and isinstance(row.get("person_id"), str)
        }
        assert "char_mou_gou" not in present
        cycle_ref = context["controlled_operations"][0]["campaign_command"]["cycle_ref"]
        base = context["campaign"]

        direct = {
            "campaign_id": base["campaign_id"],
            "request_id": "absent-direct-request",
            "actor_id": base["player_id"],
            "command_type": "interaction_action",
            "expected_revision": base["revision"],
            "submitted_at": base["world_time"],
            "payload": {
                "target_ref": "char_mou_gou",
                "process_ref": cycle_ref,
                "action": "request",
                "player_statement": "Give me my march orders.",
            },
            "mode": "gameplay",
        }
        rejected = client.post("/v1/commands/preview", headers=headers, json=direct)
        assert rejected.status_code == 409
        assert rejected.json()["detail"]["code"] == "interaction_person_access_not_established"

        seek = copy.deepcopy(direct)
        seek["request_id"] = "legal-seek-contact"
        seek["payload"] = {
            "target_ref": "char_mou_gou",
            "process_ref": cycle_ref,
            "action": "seek_contact",
            "player_statement": "I seek the lawful campaign command channel.",
        }
        allowed = client.post("/v1/commands/preview", headers=headers, json=seek)
        assert allowed.status_code == 200
        assert allowed.json()["world_response_status"] == "not_established_by_attempt"


def test_campaign_contact_then_substantive_request_produces_one_later_superior_reply(campaign) -> None:
    planner = _planner(campaign)
    cycle_ref, cycle = _campaign_cycle(planner)
    player = copy.deepcopy(planner.read("state/player.json"))
    player["location"] = str(cycle["venue_ref"])
    planner.put("state/player.json", player)
    at = str(planner.read("state/runtime.json")["world_time"])

    first_ref = _record(
        planner,
        "campaign-request-first",
        action="seek_contact",
        target_ref=str(cycle["venue_ref"]),
        process_ref=cycle_ref,
        statement="I want my march orders for Sanyou.",
    )
    second_ref = _record(
        planner,
        "campaign-request-second",
        action="seek_contact",
        target_ref=str(cycle["venue_ref"]),
        process_ref=cycle_ref,
        statement="I want my exact march orders for Sanyou and a ruling on my request to lead the vanguard.",
    )
    assert first_ref != second_ref

    refreshed = planner._reconcile_campaign_entry_authority()
    materialize_reconciled_campaign_follow_on_orders(planner, refreshed)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    planner._sync_contact_request_routes(runtime)

    contact_hosts = [
        row for row in runtime["hosts"].values()
        if row.get("kind") == "contact_request"
        and row.get("route_domain") == "campaign_command_contact"
        and row.get("campaign_command_cycle_ref") == cycle_ref
    ]
    request_hosts = [
        row for row in runtime["hosts"].values()
        if row.get("kind") == "institutional_followup"
        and row.get("route_domain") == "campaign_command_request"
        and row.get("campaign_command_cycle_ref") == cycle_ref
    ]
    assert len(contact_hosts) == 1
    assert len(request_hosts) == 1
    request_host = request_hosts[0]
    assert request_host["contact_ref"] == second_ref
    assert request_host["request_topics"] == ["march_orders", "vanguard"]
    assert request_host["request_dispositions"]["vanguard"] == "unresolved_no_exact_ruling"
    assert CampaignTime.parse(request_host["next_due"]) >= CampaignTime.parse(contact_hosts[0]["next_due"]).add_seconds(15 * 60)
    assert get_causal_event_from_reader(planner, request_host["contact_ref"]) is None

    _settle_contact_request(planner, contact_hosts[0], str(contact_hosts[0]["next_due"]))
    response_ref = _settle_institutional_followup(planner, request_host, str(request_host["next_due"]))
    response = get_causal_event_from_reader(planner, response_ref)
    assert response is not None
    assert response["kind"] == "institutional_response"
    assert response["actor_ref"] == "char_mou_gou"
    assert response["process_stage"] == "campaign_command_request_answered"
    assert "vanguard" in response["summary"].lower()
    assert "remains unresolved" in response["summary"].lower()
    assert "not a denial" in response["summary"].lower()
    assert "does not grant" not in response["summary"].lower()
    assert "march" in response["summary"].lower()
    assert "move Tang Wei's army" in request_host["response_summary"] or "march order" in request_host["response_summary"]


def _seed_message(planner, event_ref: str = "event_test_family_message") -> str:
    at = str(planner.read("state/runtime.json")["world_time"])
    _path, owner = read_causal_event_owner(planner)
    owner["causal_events"][event_ref] = {
        "event_ref": event_ref,
        "kind": "message",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "actor_ref": "char_tang_kai",
        "target_ref": PLAYER,
        "process_kind": "family_initiative",
        "process_stage": "invitation_delivered",
        "summary": "Tang Kai asks when his brother will visit.",
        "delivery": {"target_ref": PLAYER, "location_ref": "loc_kanyou", "route": "household messenger"},
        "provenance": {"kind": "causal_runtime_settlement", "source_owner_ref": "char_tang_kai", "work_ref": event_ref, "late_catch_up": False},
    }
    write_causal_event_owner(planner, owner)
    return event_ref


def test_reply_to_exact_message_has_receipt_route_without_inventing_requested_travel(campaign) -> None:
    planner = _planner(campaign)
    message_ref = _seed_message(planner)
    attempt_ref = _record(
        planner,
        "family-message-reply",
        action="request",
        target_ref=message_ref,
        process_ref=message_ref,
        statement="Tell Kai and my parents to come to Kanyou so I can say goodbye.",
    )

    before = summarize_interaction_routing(planner)
    assert before["routable_on_next_scheduler_reconcile"] >= 1
    assert attempt_ref not in before["unrouted_attempt_refs"]

    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    planner._sync_contact_request_routes(runtime)
    host = next(
        row for row in runtime["hosts"].values()
        if row.get("route_domain") == "message_reply_receipt" and row.get("contact_ref") == attempt_ref
    )
    assert host["actor_ref"] == "char_tang_kai"
    assert "does not by itself move the sender" in host["response_summary"]
    response_ref = _settle_institutional_followup(planner, host, str(host["next_due"]))
    response = get_causal_event_from_reader(planner, response_ref)
    assert response is not None
    assert response["actor_ref"] == "char_tang_kai"
    assert "requested travel" in response["summary"]


def test_routing_health_flags_legacy_direct_person_orphans_separately(campaign) -> None:
    planner = _planner(campaign)
    cycle_ref, _cycle = _campaign_cycle(planner)
    orphan_ref = _record(
        planner,
        "legacy-absent-person-request",
        action="request",
        target_ref="char_mou_gou",
        process_ref=cycle_ref,
        statement="Give me a ruling.",
    )

    routing = summarize_interaction_routing(planner)

    assert routing["legacy_invalid_access_attempts"] >= 1
    assert orphan_ref in routing["legacy_invalid_access_attempt_refs"]
    assert "legacy_person_interaction_lacked_established_access" in routing["diagnostics"]
