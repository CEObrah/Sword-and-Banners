from __future__ import annotations

import copy

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
    assert _classify_request({
        **common,
        "action": "request",
        "target_ref": "char_tang_ling",
        "player_statement": "Mother, Father: please start the Great Bow Guard recruitment as soon as possible within the treasury-safe ceiling we discussed. Also begin recruiting and training Initiates for Sword Manor.",
    }) == "recruitment_start"
    assert _classify_request({
        **common,
        "action": "ask",
        "target_ref": "char_tang_ling",
        "player_statement": "Mother, what is the treasury-safe ceiling, and how soon can the Great Bow Guard recruitment and Sword Manor Initiate intake actually open?",
    }) == "recruitment_numbers"
    assert _classify_request({
        **common,
        "action": "ask",
        "target_ref": "char_tang_zhu",
        "player_statement": "Father, what practical constraint prevents us from running the Great Bow Guard recruitment and Sword Manor Initiate intake in parallel?",
    }) == "recruitment_parallel_constraints"
    assert _classify_request({
        **common,
        "action": "request",
        "target_ref": "char_tang_ling",
        "player_statement": "Mother, when either recruitment intake actually opens, send me word immediately. I want the concrete figures and what has begun.",
    }) == "recruitment_opening_report"


def test_house_recruitment_review_opens_great_bow_intake_without_creating_fighters(campaign) -> None:
    planner = _planner(campaign)
    house = copy.deepcopy(planner.read("state/houses/house_tang.json"))
    house.setdefault("administrative_requests", {})["test-house-recruitment-start"] = {
        "request_id": "test-house-recruitment-start",
        "kind": "recruitment_start",
        "status": "queued",
        "requested_at": str(planner.read("state/runtime.json")["world_time"]),
    }
    planner.put("state/houses/house_tang.json", house)
    before_house_force = int(planner.read("state/forces/house-tang.json")["headcount"])
    before_sword = int(planner.read("state/forces/sword-manor.json")["headcount"])
    at = str(planner.read("state/runtime.json")["world_time"])

    _settle_household_request(planner, {"request_id": "test-house-recruitment-start"}, at)

    after_house = planner.read("state/houses/house_tang.json")
    program = after_house["administrative_programs"]["great_bow_guard"]
    assert program["status"] == "recruiting"
    assert program["fighting_establishment_max"] == 300
    assert program["headcount_created_by_opening"] == 0
    assert program["spending_committed_by_opening_silver"] == 0
    assert int(planner.read("state/forces/house-tang.json")["headcount"]) == before_house_force
    # The release fixture is already at its Sword Manor trainee authorization,
    # so the request must not manufacture an extra intake beyond capacity.
    assert int(planner.read("state/forces/sword-manor.json")["headcount"]) == before_sword
    request = after_house["administrative_requests"]["test-house-recruitment-start"]
    assert request["status"] == "settled"
    assert request["result"]["great_bow_guard"]["status"] == "recruiting"
    event = get_causal_event(planner, request["response_event_ref"])
    assert event["kind"] == "institutional_response"
    assert event["process_stage"] == "completed"
    assert event["provenance"]["late_catch_up"] is False
    assert "result" not in event
    assert "source_interaction_request_id" not in event


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


def test_household_scene_exposes_exact_sword_manor_handle(campaign) -> None:
    context = EquipmentAwareCampaignOperations(SwordRuntime(campaign)).play_context()
    assert "institution_sword_manor" in context["permitted_object_refs"]
    rows = context["scene"]["household_institutions"]
    assert rows == [{"object_ref": "institution_sword_manor", "name": "Sword Manor", "relation": "House Tang institution"}]


class _VitalityStore:
    def read_json(self, path: str):
        values = {
            "state/meta.json": {"player_id": "char_tang_wei", "time": "245-BCE-01-01T00:00:00+08:00", "revision": 1},
            "state/runtime.json": {
                "hosts": {"host_arc": {"kind": "world_arc", "next_due": "245-BCE-01-03T00:00:00+08:00"}},
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
            "state/scene.json": {"world_time": "245-BCE-01-01T00:00:00+08:00", "projection_revision": 1, "narrative": {"available_reports": []}},
            "state/index/institutional-process-routing.json": {"processes": []},
        }
        return values[path]


def test_vitality_flags_visible_arc_activity_without_delivery_route() -> None:
    result = summarize_playability_vitality(_VitalityStore())
    assert result["visible_arc_activities_without_delivery_route"] == 1
    assert "player_visible_world_arc_activity_without_delivery_route" in result["diagnostics"]
    assert "repair_world_arc_report_routing_before_increasing_arc_frequency" in result["suggestions"]
