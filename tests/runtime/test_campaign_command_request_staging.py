from __future__ import annotations

import copy
import hashlib
import json

from sword_runtime.api.interaction_surface import INTERACTION_ATTEMPT_PREFIX, record_interaction_attempt
from sword_runtime.campaign_command_requests import _cycle_for_attempt
from sword_runtime.campaign_follow_on_order import materialize_reconciled_campaign_follow_on_orders
from sword_runtime.causal_event_store import get_causal_event_from_reader
from sword_runtime.contact_request_flow import _settle_contact_request
from sword_runtime.production_runtime_planner import ProductionCampaignPlanner


PLAYER = "char_tang_wei"
LEDGER = "state/index/interaction-attempts.json"


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner.PLAYER_ACTOR = PLAYER
    planner._reset()
    ledger = copy.deepcopy(planner.read(LEDGER))
    ledger["attempts"] = []
    planner.put(LEDGER, ledger)
    return planner


def _cycle(planner):
    operation = planner.read("state/operations/operation_arc_131572c4e8a2892bbc.json")
    cycle_ref = operation["campaign_command_cycle_ref"]
    return cycle_ref, planner.read(planner.owner_path(cycle_ref))


def _record(planner, label: str, *, action: str, target_ref: str, process_ref: str, statement: str) -> str:
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
        "posture": "test campaign command staging",
        "world_response_status": "not_established_by_attempt",
    }
    ref = record_interaction_attempt(
        planner,
        INTERACTION_ATTEMPT_PREFIX + json.dumps(
            attempt, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
        at=at,
    )
    assert isinstance(ref, str)
    return ref


def test_substantive_headquarters_request_requires_scene_or_settled_receiving_channel(campaign) -> None:
    planner = _planner(campaign)
    cycle_ref, cycle = _cycle(planner)
    venue_ref = str(cycle["venue_ref"])
    coordination_ref = str(cycle["coordination_authority_ref"])

    bare_request = {
        "actor_id": PLAYER,
        "target_ref": venue_ref,
        "action": "request",
        "process_ref": cycle_ref,
        "player_statement": "Give me my exact march orders and a vanguard ruling.",
        "posture": "formal request",
    }
    assert _cycle_for_attempt(planner, bare_request) is None

    in_scene = dict(bare_request)
    in_scene["scene_session_ref"] = "scene_session_test_campaign_hq"
    assert _cycle_for_attempt(planner, in_scene)["cycle_ref"] == cycle_ref

    # A staff receiving channel is not direct personal access to the named superior.
    person_request = dict(bare_request)
    person_request["target_ref"] = str(cycle["superior_command_ref"])
    assert _cycle_for_attempt(planner, person_request) is None
    assert coordination_ref


def test_settled_campaign_contact_can_carry_later_substantive_request_without_face_to_face_access(campaign) -> None:
    planner = _planner(campaign)
    cycle_ref, cycle = _cycle(planner)
    venue_ref = str(cycle["venue_ref"])
    coordination_ref = str(cycle["coordination_authority_ref"])

    player = copy.deepcopy(planner.read("state/player.json"))
    player["location"] = venue_ref
    planner.put("state/player.json", player)

    _record(
        planner,
        "staged-contact",
        action="seek_contact",
        target_ref=venue_ref,
        process_ref=cycle_ref,
        statement="I seek the lawful campaign headquarters receiving channel.",
    )
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    planner._sync_contact_request_routes(runtime)
    contact_host = next(
        row for row in runtime["hosts"].values()
        if row.get("kind") == "contact_request"
        and row.get("route_domain") == "campaign_command_contact"
        and row.get("campaign_command_cycle_ref") == cycle_ref
    )
    contact_response_ref = _settle_contact_request(planner, contact_host, str(contact_host["next_due"]))
    contact_response = get_causal_event_from_reader(planner, contact_response_ref)
    assert contact_response is not None
    assert contact_response["route_domain"] == "campaign_command_contact"
    assert contact_response["source_event_ref"] == cycle_ref

    request_ref = _record(
        planner,
        "staged-substantive-request",
        action="request",
        target_ref=coordination_ref,
        process_ref=contact_response_ref,
        statement="Give me my exact march orders for Sanyou and a ruling on my request to lead the vanguard.",
    )

    refreshed = planner._reconcile_campaign_entry_authority()
    materialize_reconciled_campaign_follow_on_orders(planner, refreshed)
    runtime2 = copy.deepcopy(planner.read("state/runtime.json"))
    planner._sync_contact_request_routes(runtime2)
    request_host = next(
        row for row in runtime2["hosts"].values()
        if row.get("kind") == "institutional_followup"
        and row.get("route_domain") == "campaign_command_request"
        and row.get("contact_ref") == request_ref
    )
    assert request_host["campaign_command_cycle_ref"] == cycle_ref
    assert request_host["actor_ref"] == cycle["superior_command_ref"]
    assert request_host["request_topics"] == ["march_orders", "vanguard"]
    assert "does not grant" in request_host["response_summary"].lower()

    staff_channel_attempt = {
        "actor_id": PLAYER,
        "target_ref": coordination_ref,
        "action": "request",
        "process_ref": contact_response_ref,
        "player_statement": "Give me my march orders.",
        "posture": "formal request",
    }
    assert _cycle_for_attempt(planner, staff_channel_attempt)["cycle_ref"] == cycle_ref

    # The same staff receipt still does not authorize direct speech to Mou Gou.
    direct_person = dict(staff_channel_attempt)
    direct_person["target_ref"] = str(cycle["superior_command_ref"])
    assert _cycle_for_attempt(planner, direct_person) is None
