from __future__ import annotations

import copy
import json

from sword_runtime.api.interaction_surface import INTERACTION_ATTEMPT_PREFIX
from sword_runtime.causal_event_store import get_causal_event
from sword_runtime.production_runtime_planner import ProductionCampaignPlanner
from sword_runtime.qin_command_support_flow import (
    settle_qin_command_support,
    settle_qin_supply_convoy,
    sync_qin_command_support,
)
from sword_runtime.sim.calendar import CampaignTime

FORMATION_REF = "formation_qin_wei_unit_01"
OPERATION_REF = "operation_arc_131572c4e8a2892bbc"
OFFICE = "field_command:test_qin_support"


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner.PLAYER_ACTOR = "char_tang_wei"
    planner._reset()
    return planner


def _seed_active_scope(planner, *, formation_refs=None):
    refs = list(formation_refs or [FORMATION_REF])
    player = copy.deepcopy(planner.read("state/player.json"))
    player.setdefault("career_state", {})["appointments"] = [{
        "kind": "qin_field_command",
        "office": OFFICE,
        "state_ref": "state_qin",
        "formation_ref": refs[0],
        "formation_refs": refs,
        "operation_ref": OPERATION_REF,
        "status": "active",
    }]
    planner.put("state/player.json", player)
    for ref in refs:
        path = planner.owner_path(ref)
        formation = copy.deepcopy(planner.read(path))
        formation["administrative_owner"] = "state_qin"
        formation["command_authority"] = "char_tang_wei"
        planner.put(path, formation)


def _record_attempt(
    planner,
    *,
    request_id: str,
    action: str,
    target_ref: str,
    formation_refs=None,
    statement: str = "",
):
    at = str(planner.read("state/runtime.json")["world_time"])
    attempt = {
        "schema": "sword-interaction-attempt.v1",
        "surface_digest": "a" * 64,
        "request_id": request_id,
        "actor_id": "char_tang_wei",
        "target_ref": target_ref,
        "action": action,
        "process_ref": None,
        "player_statement": statement,
        "formation_refs": list(formation_refs or []),
        "posture": "field command support",
        "world_response_status": "not_established_by_attempt",
    }
    history = copy.deepcopy(planner.read("state/history/events/index.json"))
    history["events"].append({
        "at": at,
        "event_id": f"scene_{request_id}",
        "kind": "scene_consequence",
        "summary": INTERACTION_ATTEMPT_PREFIX + json.dumps(
            attempt, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
    })
    planner.put("state/history/events/index.json", history)
    return at


def _support_hosts(runtime):
    return [row for row in runtime["hosts"].values() if row.get("kind") == "qin_command_support_review"]


def test_active_qin_provisioning_attempt_registers_institution_owned_support(campaign):
    planner = _planner(campaign)
    _seed_active_scope(planner)
    formation = planner.read(planner.owner_path(FORMATION_REF))
    _record_attempt(
        planner,
        request_id="test-qin-provisions",
        action="request",
        target_ref=str(formation["location_ref"]),
        formation_refs=[FORMATION_REF],
        statement="I request Qin provisions and grain for my assigned unit.",
    )
    runtime = copy.deepcopy(planner.read("state/runtime.json"))

    sync_qin_command_support(planner, runtime)
    sync_qin_command_support(planner, runtime)

    hosts = _support_hosts(runtime)
    assert len(hosts) == 1
    assert hosts[0]["owner_ref"] == "inst_qin_military_bureau"
    assert hosts[0]["support_kind"] == "provisioning"
    assert hosts[0]["formation_refs"] == [FORMATION_REF]


def test_qin_provisioning_direct_issue_conserves_exact_depot_grain(campaign):
    planner = _planner(campaign)
    _seed_active_scope(planner)
    depot = copy.deepcopy(planner.read("state/depots/qin.json"))
    depot["stocks"]["grain_kg"] = 1_000_000
    depot["stocks"]["fodder_kg"] = 1_000_000
    planner.put("state/depots/qin.json", depot)

    formation_path = planner.owner_path(FORMATION_REF)
    formation = copy.deepcopy(planner.read(formation_path))
    formation["location_ref"] = str(depot["location_ref"])
    formation.setdefault("logistics", {})["food_kg"] = 0
    formation["logistics"]["fodder_kg"] = 0
    formation["mounts"] = {}
    planner.put(formation_path, formation)
    at = _record_attempt(
        planner,
        request_id="test-qin-direct-provisions",
        action="request",
        target_ref=str(depot["location_ref"]),
        formation_refs=[FORMATION_REF],
        statement="Issue campaign food to this Qin unit.",
    )
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    sync_qin_command_support(planner, runtime)
    host = _support_hosts(runtime)[0]
    before = int(planner.read("state/depots/qin.json")["stocks"]["grain_kg"])

    wake = settle_qin_command_support(planner, host, at)

    expected = int(2000 * 0.8 * 14)
    after_depot = planner.read("state/depots/qin.json")
    after_formation = planner.read(formation_path)
    assert wake is not None
    assert int(after_formation["logistics"]["food_kg"]) == expected
    assert int(after_depot["stocks"]["grain_kg"]) == before - expected
    assert get_causal_event(planner, wake["campaign_event_ref"])["process_stage"] == "provisioning"


def test_remote_qin_provisioning_stays_in_convoy_escrow_until_arrival(campaign):
    planner = _planner(campaign)
    _seed_active_scope(planner)
    depot = copy.deepcopy(planner.read("state/depots/qin.json"))
    depot["stocks"]["grain_kg"] = 1_000_000
    depot["stocks"]["fodder_kg"] = 1_000_000
    planner.put("state/depots/qin.json", depot)

    formation_path = planner.owner_path(FORMATION_REF)
    formation = copy.deepcopy(planner.read(formation_path))
    destination = "loc_qin_regional_02"
    if destination == str(depot.get("location_ref")):
        destination = "loc_qin_eastern_depot"
    formation["location_ref"] = destination
    formation.setdefault("logistics", {})["food_kg"] = 0
    formation["logistics"]["fodder_kg"] = 0
    formation["mounts"] = {}
    planner.put(formation_path, formation)
    planner._route_travel_hours = lambda *_args, **_kwargs: 12
    at = _record_attempt(
        planner,
        request_id="test-qin-remote-provisions",
        action="request",
        target_ref=destination,
        formation_refs=[FORMATION_REF],
        statement="Send provisions to my Qin unit.",
    )
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    sync_qin_command_support(planner, runtime)
    host = _support_hosts(runtime)[0]
    before = int(planner.read("state/depots/qin.json")["stocks"]["grain_kg"])

    settle_qin_command_support(planner, host, at)

    expected = int(2000 * 0.8 * 14)
    assert int(planner.read("state/depots/qin.json")["stocks"]["grain_kg"]) == before - expected
    assert int(planner.read(formation_path)["logistics"]["food_kg"]) == 0
    runtime_after = planner.read("state/runtime.json")
    convoy_hosts = [row for row in runtime_after["hosts"].values() if row.get("kind") == "qin_command_supply_convoy"]
    assert len(convoy_hosts) == 1
    convoy_host = convoy_hosts[0]
    field_depot = planner.read(convoy_host["destination_depot_path"])
    assert convoy_host["convoy_ref"] in field_depot["incoming_convoys"]

    arrival = str(CampaignTime.parse(at).add_seconds(12 * 3600))
    settle_qin_supply_convoy(planner, convoy_host, arrival)

    after_formation = planner.read(formation_path)
    after_field = planner.read(convoy_host["destination_depot_path"])
    assert int(after_formation["logistics"]["food_kg"]) == expected
    assert convoy_host["convoy_ref"] not in after_field.get("incoming_convoys", {})


def test_operation_request_gets_exact_non_fabricating_qin_briefing(campaign):
    planner = _planner(campaign)
    _seed_active_scope(planner)
    at = _record_attempt(
        planner,
        request_id="test-qin-operation-brief",
        action="request",
        target_ref=OPERATION_REF,
        statement="Give me actionable intelligence for the operation.",
    )
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    sync_qin_command_support(planner, runtime)
    host = _support_hosts(runtime)[0]
    assert host["support_kind"] == "operational_briefing"

    wake = settle_qin_command_support(planner, host, at)

    response = get_causal_event(planner, wake["campaign_event_ref"])
    assert response["process_stage"] == "operational_briefing"
    assert "does not itself establish an enemy contact, march route, or battle plan" in response["summary"]
    assert "does not move" not in response["summary"].lower()
