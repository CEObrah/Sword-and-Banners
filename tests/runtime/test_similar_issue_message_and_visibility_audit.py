from __future__ import annotations

import copy
import hashlib
import json
import subprocess

import pytest

from sword_runtime.api.interaction_surface import (
    INTERACTION_ATTEMPT_PREFIX,
    record_interaction_attempt,
    recent_interaction_attempts,
)
from sword_runtime.causal_event_store import get_causal_event, read_causal_event_owner, write_causal_event_owner
from sword_runtime.campaign_communications import (
    command_endpoint_location,
    command_message_route,
    ensure_player_message_delivery,
)
from sword_runtime.combat_tactics import build_team_plan, known_tactical_candidates
from sword_runtime.house_field_preparation_gate import sync_explicit_house_field_preparation
from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.qin_command_briefing_flow import sync_qin_command_briefings
from sword_runtime.qin_command_support_flow import sync_qin_command_support
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.world_arcs import _schedule_report_route
from conftest import execute_production


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner.PLAYER_ACTOR = "char_tang_wei"
    planner._reset()
    return planner


def _record(planner, *, request_id: str, target_ref: str, action: str = "request", statement: str = "request", process_ref=None, formation_refs=None):
    at = str(planner.read("state/runtime.json")["world_time"])
    attempt = {
        "schema": "sword-interaction-attempt.v1",
        "surface_digest": hashlib.sha256(request_id.encode("utf-8")).hexdigest(),
        "actor_id": "char_tang_wei",
        "target_ref": target_ref,
        "action": action,
        "process_ref": process_ref,
        "player_statement": statement,
        "formation_refs": list(formation_refs or []),
        "posture": "test physical message routing",
        "world_response_status": "not_established_by_attempt",
    }
    ref = record_interaction_attempt(
        planner,
        INTERACTION_ATTEMPT_PREFIX + json.dumps(attempt, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        at=at,
    )
    assert ref
    return at, ref


def test_interaction_attempt_snapshots_physical_origin(campaign):
    planner = _planner(campaign)
    player = copy.deepcopy(planner.read("state/player.json"))
    player["location"] = "loc_sanyou"
    planner.put("state/player.json", player)
    _record(planner, request_id="origin-snapshot", target_ref="char_tang_ling", statement="Please send me a report.")
    attempts, _ = recent_interaction_attempts(planner, "char_tang_wei", limit=8)
    row = next(row for row in attempts if str(row.get("player_statement")) == "Please send me a report.")
    assert row["origin_location_ref"] == "loc_sanyou"


def test_qin_briefing_request_uses_round_trip_geography_plus_processing(campaign):
    planner = _planner(campaign)
    player = copy.deepcopy(planner.read("state/player.json"))
    player["location"] = "loc_sanyou"
    appointment = next(
        row for row in player.get("career_state", {}).get("appointments", [])
        if row.get("kind") == "qin_field_command"
    )
    appointment["status"] = "awaiting_assumption"
    office = str(appointment["office"])
    planner.put("state/player.json", player)
    at, _ = _record(
        planner,
        request_id="remote-qin-briefing",
        target_ref="inst_qin_military_bureau",
        action="ask",
        process_ref=office,
        statement="Send me the exact pre-assumption order of battle and logistics briefing.",
    )
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    runtime["hosts"] = {}
    runtime["events"] = []
    sync_qin_command_briefings(planner, runtime)
    host = next(row for row in runtime["hosts"].values() if row.get("kind") == "qin_command_briefing_reply")
    bureau = command_endpoint_location(planner, "inst_qin_military_bureau")
    assert bureau == "loc_kanyou"
    route = command_message_route(planner.read, "loc_sanyou", bureau, round_trip=True)
    assert host["communication_travel_seconds"] == route["travel_seconds"]
    expected = CampaignTime.parse(at).add_seconds(int(route["travel_seconds"]) + 3600)
    assert CampaignTime.parse(str(host["next_due"])) == expected
    assert expected > CampaignTime.parse(at).add_hours(1)


def test_house_field_preparation_remote_request_is_not_one_hour_teleport(campaign):
    planner = _planner(campaign)
    player = copy.deepcopy(planner.read("state/player.json"))
    player["location"] = "loc_sanyou"
    planner.put("state/player.json", player)
    at, _ = _record(
        planner,
        request_id="remote-house-field-prep",
        target_ref="char_tang_ling",
        action="request",
        statement=(
            "Prepare all my troops and personal forces, House Guard and Champions, with equipment and armor "
            "for campaign departure; keep Kai in safe preparation and training."
        ),
    )
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    runtime["hosts"] = {}
    runtime["events"] = []
    sync_explicit_house_field_preparation(planner, runtime)
    host = next(row for row in runtime["hosts"].values() if row.get("kind") == "house_field_preparation_reply")
    assert int(host["communication_travel_seconds"]) > 0
    assert CampaignTime.parse(str(host["next_due"])) > CampaignTime.parse(at).add_hours(1)
    assert host["response_target_location_ref"] == "loc_sanyou"


def test_reply_courier_reroutes_when_player_moves(campaign):
    planner = _planner(campaign)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    runtime["hosts"] = {
        "host_test_reply": {
            "host_id": "host_test_reply",
            "kind": "qin_command_briefing_reply",
            "response_target_location_ref": "loc_sanyou",
            "recurrence_seconds": 0,
        }
    }
    runtime["events"] = []
    planner.put("state/runtime.json", runtime)
    player = copy.deepcopy(planner.read("state/player.json"))
    player["location"] = "loc_tang_manor"
    planner.put("state/player.json", player)
    planner._active_host_id = "host_test_reply"
    assert ensure_player_message_delivery(planner, runtime["hosts"]["host_test_reply"], str(runtime["world_time"])) is False
    rerouted = planner.read("state/runtime.json")["hosts"]["host_test_reply"]
    assert rerouted["response_courier_origin_ref"] == "loc_sanyou"
    assert rerouted["response_target_location_ref"] == "loc_tang_manor"
    assert int(rerouted["recurrence_seconds"]) > 0
    assert ensure_player_message_delivery(planner, rerouted, str(runtime["world_time"])) is True
    arrived = planner.read("state/runtime.json")["hosts"]["host_test_reply"]
    assert arrived["retire_after_settlement"] is True


def test_empty_current_detection_never_expands_to_hidden_exact_roster():
    people = {
        "ally": {"combat_state": {}, "attributes": {}, "skills": {}},
        "hidden_enemy": {"combat_state": {}, "attributes": {}, "skills": {}},
    }
    positions = {
        "ally": {"x_m": 0.0, "y_m": 0.0},
        "hidden_enemy": {"x_m": 8.0, "y_m": 0.0},
    }
    plan = build_team_plan(
        ["ally"], ["hidden_enemy"], people=people, equipment={}, controls={}, positions=positions,
        objective="survive", at_s=0.0, knowledge_by_actor={"ally": []},
    )
    assert plan["known_enemy_refs"] == []
    assert plan["assignments"] == {}
    assert known_tactical_candidates(["hidden_enemy"], plan) == []


def test_team_shared_detection_still_allows_lawful_known_target():
    people = {
        "leader": {"combat_state": {}, "attributes": {"Awareness": 60}, "skills": {"Leadership": 70}},
        "ally": {"combat_state": {}, "attributes": {"Awareness": 60}, "skills": {"Tracking": 60}},
        "enemy": {"combat_state": {}, "attributes": {}, "skills": {}},
    }
    positions = {
        "leader": {"x_m": 0.0, "y_m": 0.0},
        "ally": {"x_m": 2.0, "y_m": 0.0},
        "enemy": {"x_m": 7.0, "y_m": 0.0},
    }
    plan = build_team_plan(
        ["leader", "ally"], ["enemy"], people=people, equipment={}, controls={}, positions=positions,
        objective="survive", at_s=0.0, knowledge_by_actor={"leader": [], "ally": ["enemy"]},
    )
    assert plan["known_enemy_refs"] == ["enemy"]
    assert known_tactical_candidates(["enemy"], plan) == ["enemy"]


def test_remote_family_counsel_uses_round_trip_courier_not_fixed_fifteen_minutes(campaign):
    planner = _planner(campaign)
    player = copy.deepcopy(planner.read("state/player.json"))
    player["location"] = "loc_sanyou"
    player["current_location"] = "loc_sanyou"
    planner.put("state/player.json", player)

    at = str(planner.read("state/runtime.json")["world_time"])
    report_ref = "event_test_remote_family_counsel_report"
    _path, owner = read_causal_event_owner(planner)
    owner["causal_events"][report_ref] = {
        "event_ref": report_ref,
        "kind": "world_arc_report",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "actor_ref": "state_qin",
        "target_ref": "char_tang_wei",
        "summary": "A player-visible report exists for counsel testing.",
        "provenance": {"kind": "test", "source_owner_ref": "state_qin", "work_ref": report_ref, "late_catch_up": False},
    }
    write_causal_event_owner(planner, owner)
    _record(
        planner,
        request_id="remote-family-counsel",
        target_ref="char_tang_ling",
        action="ask",
        process_ref=report_ref,
        statement="What do you think we should do?",
    )
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    runtime["hosts"] = {}
    runtime["events"] = []
    planner._sync_family_counsel_routes(runtime)
    host = next(row for row in runtime["hosts"].values() if row.get("kind") == "family_counsel")
    parent_location = command_endpoint_location(planner, "char_tang_ling")
    assert parent_location
    route = command_message_route(planner.read, "loc_sanyou", parent_location, round_trip=True)
    assert host["communication_travel_seconds"] == route["travel_seconds"]
    assert host["communication_travel_seconds"] > 0
    expected = CampaignTime.parse(at).add_seconds(int(route["travel_seconds"]) + 15 * 60)
    assert CampaignTime.parse(str(host["next_due"])) == expected
    assert host["response_target_location_ref"] == "loc_sanyou"


def test_direct_world_arc_dispatch_uses_physical_courier_not_flat_twelve_hours(campaign):
    planner = _planner(campaign)
    player = copy.deepcopy(planner.read("state/player.json"))
    player["location"] = "loc_sanyou"
    player["current_location"] = "loc_sanyou"
    planner.put("state/player.json", player)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    runtime["hosts"] = {}
    runtime["events"] = []
    planner.put("state/runtime.json", runtime)
    at = str(runtime["world_time"])
    _schedule_report_route(
        planner, arc_ref="arc_test_direct_dispatch", source_event_ref="event_test_direct_dispatch",
        at=at, route="Field Army military dispatches", origin_state="qin",
        pressure_stage="material", visibility="direct", source_location_ref="loc_kanyou",
    )
    runtime = planner.read("state/runtime.json")
    host = next(row for row in runtime["hosts"].values() if row.get("kind") == "world_arc_report")
    route = command_message_route(planner.read, "loc_kanyou", "loc_sanyou", round_trip=False)
    travel = int(route["travel_seconds"])
    assert travel > 0
    assert host["physical_delivery"] is True
    assert host["source_location_ref"] == "loc_kanyou"
    assert host["response_target_location_ref"] == "loc_sanyou"
    assert int(host["communication_travel_seconds"]) == travel
    assert CampaignTime.parse(str(host["next_due"])) == CampaignTime.parse(at).add_seconds(travel)
    assert CampaignTime.parse(str(host["next_due"])) != CampaignTime.parse(at).add_seconds(12 * 3600)
    assert host["recurrence_seconds"] == 0



def test_player_military_pressure_memorandum_uses_courier_not_instant_delivery(campaign):
    planner = _planner(campaign)
    player = copy.deepcopy(planner.read("state/player.json"))
    player["location"] = "loc_sanyou"
    player["current_location"] = "loc_sanyou"
    planner.put("state/player.json", player)
    at = str(planner.read("state/runtime.json")["world_time"])
    planner._pending_wake_created = None

    planner._career_concentration_event(
        state_ref="state_qin", commander_ref="char_tang_wei",
        concentration_milli=1000, at=at,
    )

    owner = read_causal_event_owner(planner)[1]
    rows = [
        row for row in owner.get("causal_events", {}).values()
        if isinstance(row, dict) and row.get("kind") == "military_following_political_pressure"
    ]
    assert rows
    event = rows[-1]
    assert event["status"] == "in_transit"
    assert event["process_stage"].endswith("_memorandum_in_transit")
    assert event["delivery"]["status"] == "in_transit"
    assert event["delivery"]["source_location_ref"] == "loc_kanyou"
    assert event["delivery"]["location_ref"] == "loc_sanyou"
    runtime = planner.read("state/runtime.json")
    host = next(
        row for row in runtime.get("hosts", {}).values()
        if isinstance(row, dict) and row.get("kind") == "player_story_message_delivery"
        and row.get("story_event_ref") == event["event_ref"]
    )
    assert int(host["communication_travel_seconds"]) > 0
    assert host["source_location_ref"] == "loc_kanyou"
    assert host["response_target_location_ref"] == "loc_sanyou"
    assert planner._pending_wake_created is None


def test_player_story_delivery_supports_exact_non_owner_source_location(campaign):
    planner = _planner(campaign)
    player = copy.deepcopy(planner.read("state/player.json"))
    player["location"] = "loc_tang_manor"
    player["current_location"] = "loc_tang_manor"
    planner.put("state/player.json", player)
    at = str(planner.read("state/runtime.json")["world_time"])
    from sword_runtime.player_story_flow import _dispatch_player_story_message

    event_ref = "event_test_remote_formation_report"
    _dispatch_player_story_message(
        planner, event_ref=event_ref, at=at,
        actor_ref="formation_non_endpoint_test", source_owner_ref="formation_non_endpoint_test",
        event_kind="military_personnel_arrival", process_kind="military_career_petition",
        transit_stage="report_in_transit", delivered_stage="officer_arrived",
        delivered_summary="A local formation report reaches Wei only after travel.",
        route_label="formation courier", source_location_ref="loc_sanyou",
    )
    event = get_causal_event(planner, event_ref)
    assert isinstance(event, dict)
    assert event["status"] == "in_transit"
    assert event["delivery"]["source_location_ref"] == "loc_sanyou"
    runtime = planner.read("state/runtime.json")
    host = next(
        row for row in runtime.get("hosts", {}).values()
        if isinstance(row, dict) and row.get("story_event_ref") == event_ref
    )
    assert host["source_location_ref"] == "loc_sanyou"
    assert int(host["communication_travel_seconds"]) > 0


def test_military_allegiance_crisis_commits_locally_under_closed_formation_schema(campaign):
    result = execute_production(
        campaign,
        "military_allegiance_action",
        {
            "action": "defy_state_order",
            "formation_refs": ["formation_black_banner_01a"],
            "proposed_commander_ref": "char_tang_wei",
        },
        request_id="similar-audit-local-allegiance",
    ).receipt.result
    assert result["crisis_ref"].startswith("military_allegiance_crisis_")
    assert len(result["formation_results"]) == 1
    formation_ref = str(result["formation_results"][0]["formation_ref"])
    owner_index = json.loads((campaign / "state/index/owner-index.json").read_text())["owners"]
    formation = json.loads((campaign / owner_index[formation_ref]).read_text())
    assert formation["military_allegiance_state"]["crisis_ref"] == result["crisis_ref"]


def test_remote_military_allegiance_crisis_fails_closed_without_command_message_route(campaign):
    player_path = campaign / "state/player.json"
    player = json.loads(player_path.read_text())
    player["location"] = "loc_tang_manor"
    player["current_location"] = "loc_tang_manor"
    player_path.write_text(json.dumps(player, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    subprocess.run(["git", "-C", str(campaign), "add", "state/player.json"], check=True)
    subprocess.run(
        ["git", "-C", str(campaign), "commit", "--quiet", "-m", "test remote allegiance location"],
        check=True,
    )

    with pytest.raises(PermissionError, match="physical command-message route"):
        execute_production(
            campaign,
            "military_allegiance_action",
            {
                "action": "defy_state_order",
                "formation_refs": ["formation_black_banner_01a"],
                "proposed_commander_ref": "char_tang_wei",
            },
            request_id="similar-audit-remote-allegiance",
        )
