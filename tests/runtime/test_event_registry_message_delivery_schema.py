from __future__ import annotations

import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from sword_runtime.causal_event_store import get_causal_event, read_causal_event_owner
from sword_runtime.contact_request_flow import _settle_institutional_followup
from sword_runtime.player_story_flow import _dispatch_player_story_message, settle_player_story_message_delivery
from sword_runtime.production_planner import ProductionCampaignPlanner


ROOT = Path(__file__).resolve().parents[2]


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    meta = copy.deepcopy(planner.read("state/meta.json"))
    planner.PLAYER_ACTOR = str(meta["player_id"])
    planner._reset()
    return planner


def _validate_event_owner(planner) -> None:
    schema = json.loads((ROOT / "game" / "schemas" / "event-registry.schema.json").read_text())
    _path, owner = read_causal_event_owner(planner)
    Draft202012Validator(schema).validate(owner)


def test_player_story_message_delivery_validates_in_transit_and_delivered(campaign) -> None:
    planner = _planner(campaign)
    now = str(planner.read("state/runtime.json")["world_time"])
    event_ref = "event_player_story_message_delivery_schema_regression"

    # Exercise the courier envelope directly. Story-review eligibility is a
    # separate concern and can lawfully suppress a recurring family invitation
    # while Tang Wei is on exact active field duty.
    assert _dispatch_player_story_message(
        planner,
        event_ref=event_ref,
        at=now,
        actor_ref="char_tang_ling",
        source_owner_ref="char_tang_ling",
        event_kind="message",
        process_kind="family_initiative",
        transit_stage="invitation_in_transit",
        delivered_stage="invitation_delivered",
        delivered_summary="Tang Ling's household message reaches Tang Wei through the physical courier route.",
        route_label="House Tang household messenger",
    ) == event_ref
    _validate_event_owner(planner)

    event = get_causal_event(planner, event_ref)
    assert event is not None
    assert event["status"] == "in_transit"
    delivery = event["delivery"]
    assert delivery["status"] == "in_transit"
    assert delivery["source_location_ref"]
    assert delivery["courier_route"]["origin_ref"] == delivery["source_location_ref"]
    assert delivery["courier_route"]["destination_ref"] == delivery["location_ref"]

    runtime = planner.read("state/runtime.json")
    host = next(
        row
        for row in runtime.get("hosts", {}).values()
        if isinstance(row, dict)
        and row.get("kind") == "player_story_message_delivery"
        and row.get("story_event_ref") == event_ref
    )
    due = str(host["next_due"])
    assert settle_player_story_message_delivery(planner, host, due) == event_ref

    _validate_event_owner(planner)
    delivered = get_causal_event(planner, event_ref)
    assert delivered is not None
    assert delivered["status"] == "triggered"
    assert delivered["triggered_at"] == due
    assert delivered["delivery"]["status"] == "delivered"
    assert delivered["delivery"]["source_location_ref"]
    assert delivered["delivery"]["courier_route"]["origin_ref"] == delivered["delivery"]["source_location_ref"]


def test_message_reply_receipt_delivery_travel_metadata_validates(campaign) -> None:
    planner = _planner(campaign)
    now = str(planner.read("state/runtime.json")["world_time"])
    contact_ref = "interaction_attempt_schema_receipt_regression"
    host = {
        "contact_ref": contact_ref,
        "source_process_ref": "event_test_source_message",
        "source_owner_ref": "char_tang_wei",
        "response_summary": "Tang Wei's reply reaches its recipient through the physical courier route.",
        "delivery_route": "physical courier",
        "response_stage": "reply_received",
        "route_domain": "message_reply_receipt",
        "actor_ref": "char_tang_ling",
        "recipient_target_location_ref": "loc_tang_manor_inner_citadel_family_hall",
        "communication_travel_seconds": 104400,
    }

    event_ref = _settle_institutional_followup(planner, host, now)
    assert event_ref
    _validate_event_owner(planner)

    receipt = get_causal_event(planner, event_ref)
    assert receipt is not None
    assert receipt["kind"] == "message_receipt"
    assert receipt["target_ref"] == "char_tang_ling"
    assert receipt["delivery"]["location_ref"] == "loc_tang_manor_inner_citadel_family_hall"
    assert receipt["delivery"]["communication_travel_seconds"] == 104400
