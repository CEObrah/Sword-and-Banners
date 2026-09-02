from __future__ import annotations

import copy
import hashlib
import json

from sword_runtime.api.interaction_surface import INTERACTION_ATTEMPT_PREFIX, record_interaction_attempt
from sword_runtime.campaign_command_contact import _campaign_cycle_for_attempt
from sword_runtime.campaign_command_cycle import _put_cycle
from sword_runtime.causal_event_store import get_causal_event_from_reader
from sword_runtime.contact_request_flow import _response_ref, _settle_contact_request
from sword_runtime.production_runtime_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime


CYCLE_REF = "campaign_command_cycle.test_superior_contact"


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    meta = copy.deepcopy(planner.read("state/meta.json"))
    planner.PLAYER_ACTOR = str(meta["player_id"])
    planner._reset()
    player = copy.deepcopy(planner.read("state/player.json"))
    player["location"] = "loc_kanyou"
    planner.put("state/player.json", player)
    _put_cycle(planner, {
        "schema": "generic-object",
        "authority": True,
        "owner_id": CYCLE_REF,
        "cycle_ref": CYCLE_REF,
        "kind": "campaign_command_cycle",
        "operation_ref": "operation_test_superior_contact",
        "campaign_arc_ref": "arc_ryo_fui_northern_wei_campaign",
        "state_ref": "state_qin",
        "coordination_authority_ref": "inst_qin_military_bureau",
        "supreme_commander_ref": "char_mou_gou",
        "superior_command_ref": "char_mou_gou",
        "venue_ref": "loc_kanyou",
        "participant_operation_refs": [],
        "participant_commander_refs": ["char_tang_wei", "char_mou_gou"],
        "status": "campaign_command_active",
        "war_council": {"status": "held"},
        "daily_cycle": {"status": "active"},
        "delivered_superior_order_refs": [],
        "created_at": str(planner.read("state/runtime.json")["world_time"]),
        "updated_at": str(planner.read("state/runtime.json")["world_time"]),
    })
    return planner


def _attempt(label: str) -> dict:
    return {
        "schema": "sword-interaction-attempt.v1",
        "surface_digest": hashlib.sha256(label.encode("utf-8")).hexdigest(),
        "actor_id": "char_tang_wei",
        "target_ref": "loc_kanyou",
        "action": "seek_contact",
        "process_ref": CYCLE_REF,
        "player_statement": "I want my exact march orders and a ruling through the lawful campaign command channel.",
        "formation_refs": [],
        "posture": "Insistent but within the campaign chain of command.",
        "world_response_status": "not_established_by_attempt",
    }


def _record(planner, label: str, at: str) -> str:
    attempt = _attempt(label)
    ref = record_interaction_attempt(
        planner,
        INTERACTION_ATTEMPT_PREFIX + json.dumps(attempt, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        at=at,
    )
    assert isinstance(ref, str)
    return ref


def test_campaign_command_seek_contact_resolves_exact_cycle_without_fake_presence(campaign) -> None:
    planner = _planner(campaign)
    cycle = _campaign_cycle_for_attempt(planner, _attempt("route"))
    assert cycle is not None
    assert cycle["cycle_ref"] == CYCLE_REF
    assert cycle["coordination_authority_ref"] == "inst_qin_military_bureau"
    assert cycle["superior_command_ref"] == "char_mou_gou"


def test_campaign_command_contact_schedules_one_bounded_headquarters_callback(campaign) -> None:
    planner = _planner(campaign)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    at = str(runtime["world_time"])
    first_ref = _record(planner, "first-press", at)
    _record(planner, "second-press", at)

    planner._sync_contact_request_routes(runtime)
    hosts = [
        row for row in runtime["hosts"].values()
        if row.get("kind") == "contact_request"
        and row.get("route_domain") == "campaign_command_contact"
        and row.get("campaign_command_cycle_ref") == CYCLE_REF
    ]
    assert len(hosts) == 1
    host = hosts[0]
    assert host["institution_ref"] == "inst_qin_military_bureau"
    assert host["superior_command_ref"] == "char_mou_gou"
    assert CampaignTime.parse(host["next_due"]) == CampaignTime.parse(at).add_seconds(15 * 60)
    assert get_causal_event_from_reader(planner, _response_ref(str(host["contact_ref"]))) is None
    # Which same-instant press is retained is deliberately not player-significant;
    # the invariant is one unresolved headquarters callback, not duplicate replies.
    assert isinstance(first_ref, str)


def test_campaign_command_contact_settlement_is_receipt_access_not_a_ruling(campaign) -> None:
    planner = _planner(campaign)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    at = str(runtime["world_time"])
    _record(planner, "settlement-press", at)
    planner._sync_contact_request_routes(runtime)
    host = next(
        row for row in runtime["hosts"].values()
        if row.get("route_domain") == "campaign_command_contact"
    )
    due = str(host["next_due"])
    event_ref = _settle_contact_request(planner, host, due)
    event = get_causal_event_from_reader(planner, event_ref)
    assert event is not None
    assert event["kind"] == "audience_response"
    assert event["route_domain"] == "campaign_command_contact"
    assert event["actor_ref"] == "inst_qin_military_bureau"
    assert event["process_stage"] == "audience_ready"
    assert "headquarters receipt/access only" in event["summary"]
    assert "does not establish face-to-face access" in event["summary"]
    assert "a vanguard ruling" in event["summary"]
    assert "a new operational order" in event["summary"]
