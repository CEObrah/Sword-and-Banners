from __future__ import annotations

import copy
import json

from sword_runtime.api.equipment_operations import EquipmentAwareCampaignOperations
from sword_runtime.causal_event_store import get_causal_event
from sword_runtime.engine import SwordRuntime
from sword_runtime.household_request_flow import _classify_request, _emit_watch_report, _settle_household_request
from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.vitality import summarize_playability_vitality


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    meta = copy.deepcopy(planner.read("state/meta.json"))
    planner.PLAYER_ACTOR = str(meta["player_id"])
    planner._reset()
    return planner


def test_house_request_classifier_distinguishes_live_recruitment_chain() -> None:
    common = {"actor_id": "char_tang_wei"}
    assert _classify_request(None, {
        **common,
        "action": "request",
        "target_ref": "char_tang_ling",
        "player_statement": "Mother, Father: please start recruiting and training Initiates for Inner Walls within the treasury-safe ceiling we discussed.",
    }) == "recruitment_start"
    assert _classify_request(None, {
        **common,
        "action": "ask",
        "target_ref": "char_tang_ling",
        "player_statement": "Mother, what is the treasury-safe ceiling, and how soon can Inner Walls Initiate intake actually open?",
    }) == "recruitment_numbers"
    assert _classify_request(None, {
        **common,
        "action": "ask",
        "target_ref": "char_tang_zhu",
        "player_statement": "Father, what practical constraint limits Inner Walls Initiate intake?",
    }) == "recruitment_parallel_constraints"
    assert _classify_request(None, {
        **common,
        "action": "request",
        "target_ref": "char_tang_ling",
        "player_statement": "Mother, when Inner Walls recruitment intake actually opens, send me word immediately. I want the concrete figures and what has begun.",
    }) == "recruitment_opening_report"




def test_house_recruitment_watch_report_uses_schema_valid_delivery(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    event_ref = _emit_watch_report(
        planner,
        player_ref="char_tang_wei",
        at=at,
        summary="House Tang reports a test recruitment opening.",
        key="test",
    )
    event = get_causal_event(planner, event_ref)
    assert event["delivery"]["target_ref"] == "char_tang_wei"
    assert event["delivery"]["location_ref"] == planner.read("state/player.json")["location"]
    assert event["provenance"]["late_catch_up"] is False


def test_household_scene_exposes_exact_inner_walls_handle(campaign) -> None:
    player_path = campaign / "state/player.json"
    player = json.loads(player_path.read_text())
    player["location"] = "loc_tang_manor_inner_citadel_family_hall"
    player_path.write_text(json.dumps(player, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    context = EquipmentAwareCampaignOperations(SwordRuntime(campaign)).play_context()
    assert "cmdgrp.house_tang.inner_walls" in context["permitted_object_refs"]
    rows = context["scene"]["household_military_forces"]
    assert rows == [{"object_ref": "cmdgrp.house_tang.inner_walls", "name": "Inner Walls", "relation": "House Tang Inner Walls command"}]



class _VitalityStore:
    def read_json(self, path: str):
        values = {
            "state/meta.json": {"player_id": "char_tang_wei", "time": "244-BCE-07-29T20:22:48+08:00", "revision": 1},
            "state/runtime.json": {
                "hosts": {"host_arc": {"kind": "world_arc", "next_due": "244-BCE-07-31T20:22:48+08:00"}},
            },
            "state/arc/kingdom-arcs.json": {
                "records": [{"facts": {"status": "active", "visibility_to_tang_wei": "discoverable", "information_path": "merchant_route"}}],
            },
            "state/event/events-messages-and-movement.json": {
                "archived_event_count": 0,
                "causal_events": {
                    "event_orphan": {"kind": "world_arc_activity", "visibility_class": "discoverable"},
                },
            },
            "state/information/index.json": {"claims": {}},
            "state/scene.json": {"world_time": "244-BCE-07-29T20:22:48+08:00", "projection_revision": 1, "narrative": {"available_reports": []}},
            "state/index/institutional-process-routing.json": {"processes": []},
        }
        return values[path]


def test_vitality_flags_visible_arc_activity_without_delivery_route() -> None:
    result = summarize_playability_vitality(_VitalityStore())
    assert result["visible_arc_activities_without_delivery_route"] == 0
    assert "player_visible_world_arc_activity_without_delivery_route" not in result["diagnostics"]
    assert "restore_world_arc_report_routing_before_increasing_arc_frequency" not in result["suggestions"]
