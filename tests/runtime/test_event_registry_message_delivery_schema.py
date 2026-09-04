from __future__ import annotations

import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from sword_runtime.causal_event_store import get_causal_event, read_causal_event_owner
from sword_runtime.player_story_flow import settle_player_story_message_delivery, settle_player_story_review
from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime


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
    review_at = str(CampaignTime.parse(now).add_seconds(35 * 86400))
    _path, owner_before = read_causal_event_owner(planner)
    before_refs = set(owner_before.get("causal_events", {}))

    settle_player_story_review(planner, {"kind": "player_story_review"}, review_at)
    _validate_event_owner(planner)

    _path, owner = read_causal_event_owner(planner)
    candidates = [
        (str(ref), row)
        for ref, row in owner.get("causal_events", {}).items()
        if ref not in before_refs
        and isinstance(row, dict)
        and row.get("process_kind") == "family_initiative"
        and row.get("status") == "in_transit"
    ]
    assert candidates
    event_ref, event = candidates[-1]
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
