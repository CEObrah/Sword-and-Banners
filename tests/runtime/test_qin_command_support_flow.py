from __future__ import annotations

import copy
import hashlib
import json
from types import SimpleNamespace

from sword_runtime.api.interaction_surface import INTERACTION_ATTEMPT_PREFIX, record_interaction_attempt
from sword_runtime.causal_event_store import get_causal_event
from sword_runtime.api.stable_operations import StableCampaignOperations
from sword_runtime.campaign_briefing import reconcile_campaign_arrival
from sword_runtime.production_runtime_planner import ProductionCampaignPlanner
from sword_runtime.qin_command_support_flow import (
    settle_qin_command_support,
    sync_qin_command_support,
)
from sword_runtime.sim.calendar import CampaignTime

FORMATION_REF = "formation_black_banner_01a"
QIN_FORMATION_REFS = [
    "formation_high_guard_qin_a", "formation_high_guard_qin_b",
    "formation_black_banner_01a", "formation_black_banner_01b",
    "formation_black_banner_02a", "formation_black_banner_02b",
    "formation_black_banner_03a", "formation_black_banner_03b",
    "formation_black_banner_04a", "formation_black_banner_04b",
]
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

    # Campaign-briefing tests exercise the pre-march staff-briefing scenario.
    # Seed that physical assembly explicitly instead of inheriting the mutable live save.
    if len(refs) > 1:
        op_path = planner.read("state/operations/index.json")["operations"][OPERATION_REF]
        operation = copy.deepcopy(planner.read(op_path))
        operation["location_ref"] = "loc_qin_eastern_depot"
        planner.put(op_path, operation)
        opposing = set(operation.get("opposing_formation_refs", []))
        for ref in operation.get("formation_refs", []):
            if not isinstance(ref, str) or ref in opposing:
                continue
            path = planner.owner_path(ref)
            formation = copy.deepcopy(planner.read(path))
            formation["location_ref"] = "loc_qin_eastern_depot"
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
        "surface_digest": hashlib.sha256(request_id.encode("utf-8")).hexdigest(),
        "actor_id": "char_tang_wei",
        "target_ref": target_ref,
        "action": action,
        "process_ref": None,
        "player_statement": statement,
        "formation_refs": list(formation_refs or []),
        "posture": "field command support",
        "world_response_status": "not_established_by_attempt",
    }
    record_interaction_attempt(
        planner,
        INTERACTION_ATTEMPT_PREFIX + json.dumps(
            attempt, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
        at=at,
    )
    return at


def _support_hosts(runtime, request_id=None):
    rows = [row for row in runtime["hosts"].values() if row.get("kind") == "qin_command_support_review"]
    if request_id is not None:
        expected = f"interaction_attempt_{hashlib.sha256(request_id.encode('utf-8')).hexdigest()[:24]}"
        rows = [row for row in rows if row.get("work_ref") == expected]
    return rows


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

    hosts = _support_hosts(runtime, "test-qin-provisions")
    assert len(hosts) == 1
    assert hosts[0]["owner_ref"] == "inst_qin_military_bureau"
    assert hosts[0]["support_kind"] == "provisioning"
    assert hosts[0]["formation_refs"] == [FORMATION_REF]


def test_qin_provisioning_returns_derived_supply_without_ration_transfer(campaign):
    planner = _planner(campaign)
    _seed_active_scope(planner)
    formation_path = planner.owner_path(FORMATION_REF)
    formation_before = copy.deepcopy(planner.read(formation_path))
    depot_before = copy.deepcopy(planner.read("state/depots/qin.json"))
    at = _record_attempt(
        planner,
        request_id="test-qin-derived-provisions",
        action="request",
        target_ref=str(formation_before["location_ref"]),
        formation_refs=[FORMATION_REF],
        statement="Review supply for this Qin unit.",
    )
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    sync_qin_command_support(planner, runtime)
    host = _support_hosts(runtime, "test-qin-derived-provisions")[0]

    wake = settle_qin_command_support(planner, host, at)

    assert wake is not None
    event = get_causal_event(planner, wake["campaign_event_ref"])
    assert event["process_stage"] == "provisioning"
    assert "strategic supply" in event["summary"]
    assert "handled by the strategic support network rather than issued as formation inventory" in event["summary"]
    assert planner.read(formation_path) == formation_before
    assert planner.read("state/depots/qin.json") == depot_before
    runtime_after = planner.read("state/runtime.json")
    assert not any(row.get("kind") == "qin_command_supply_convoy" for row in runtime_after.get("hosts", {}).values())


def test_qin_supply_review_works_when_unit_is_remote_without_creating_convoy(campaign):
    planner = _planner(campaign)
    _seed_active_scope(planner)
    formation_path = planner.owner_path(FORMATION_REF)
    formation = copy.deepcopy(planner.read(formation_path))
    formation["location_ref"] = "loc_qin_regional_02"
    planner.put(formation_path, formation)
    at = _record_attempt(
        planner,
        request_id="test-qin-remote-supply-review",
        action="request",
        target_ref="loc_qin_regional_02",
        formation_refs=[FORMATION_REF],
        statement="Report the supply condition of my remote Qin unit.",
    )
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    sync_qin_command_support(planner, runtime)
    host = _support_hosts(runtime, "test-qin-remote-supply-review")[0]
    wake = settle_qin_command_support(planner, host, at)
    event = get_causal_event(planner, wake["campaign_event_ref"])
    assert "nearest support" in event["summary"]
    assert not any(row.get("kind") == "qin_command_supply_convoy" for row in planner.read("state/runtime.json").get("hosts", {}).values())


def test_operation_request_gets_playable_qin_campaign_briefing_and_mission_packet(campaign):
    planner = _planner(campaign)
    refs = list(QIN_FORMATION_REFS)
    _seed_active_scope(planner, formation_refs=refs)
    at = _record_attempt(
        planner,
        request_id="test-qin-operation-brief",
        action="request",
        target_ref=OPERATION_REF,
        statement="Who are we attacking, what forces do they have, who is joining this campaign, and am I fighting alone?",
    )
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    sync_qin_command_support(planner, runtime)
    host = _support_hosts(runtime, "test-qin-operation-brief")[0]
    assert host["support_kind"] == "operational_briefing"

    wake = settle_qin_command_support(planner, host, at)
    response = get_causal_event(planner, wake["campaign_event_ref"])
    summary = response["summary"]
    assert response["process_stage"] == "operational_briefing"
    assert "Other Qin forces formally tied to this campaign" in summary
    assert "Mou Bu" in summary
    assert "Ousen" in summary
    assert "Sanyou" in summary
    assert "official estimate" in summary
    assert "reported opposing commanders" in summary
    assert "no confirmed battle contact" in summary

    info_ref = wake["information_ref"]
    info = planner.read(f"state/information/{info_ref}.json")
    assert info["classification"] == "command_intelligence"
    assert info["epistemic_kind"] == "official_military_briefing"
    assert info["world_truth_authority"] is False
    assert "char_tang_wei" in info["knowers"]
    assert info["campaign_context"]["enemy_intelligence"]["confidence_milli"] < 1000

    op_path = planner.read("state/operations/index.json")["operations"][OPERATION_REF]
    operation = planner.read(op_path)
    assert operation["order_status"] == "staff_briefed_awaiting_commander_execution"
    order = operation["operational_orders"][-1]
    assert order["actionability_status"] == "actionable"
    assert order["status"] == "staff_briefed_awaiting_commander_execution"
    assert order["mission_packet"]["mission_phase"] == "campaign_muster_and_staging"
    assert order["mission_packet"]["destination_ref"] == "loc_kanyou"
    assert order["mission_packet"]["strategic_target_ref"] == "loc_sanyou"
    assert order["mission_packet"]["rendezvous_location_ref"] == "loc_qin_eastern_depot"
    assert order["mission_packet"]["hostile_entry_authorized"] is False
    assert order["mission_packet"]["entry_status"] == "awaiting_war_or_entry_authority"
    assert order["mission_packet"]["agency_rule"].startswith("This packet establishes Qin's immediate lawful destination")


def test_identical_qin_campaign_briefing_reuses_one_information_claim(campaign):
    planner = _planner(campaign)
    refs = list(QIN_FORMATION_REFS)
    _seed_active_scope(planner, formation_refs=refs)
    at = _record_attempt(planner, request_id="test-qin-brief-a", action="request", target_ref=OPERATION_REF, statement="Give me the campaign briefing.")
    runtime = copy.deepcopy(planner.read("state/runtime.json")); sync_qin_command_support(planner, runtime)
    wake_a = settle_qin_command_support(planner, _support_hosts(runtime, "test-qin-brief-a")[0], at)
    at2 = _record_attempt(planner, request_id="test-qin-brief-b", action="request", target_ref=OPERATION_REF, statement="Repeat the unchanged campaign briefing.")
    runtime2 = copy.deepcopy(planner.read("state/runtime.json")); sync_qin_command_support(planner, runtime2)
    wake_b = settle_qin_command_support(planner, _support_hosts(runtime2, "test-qin-brief-b")[0], at2)
    assert wake_a["information_ref"] == wake_b["information_ref"]
    info_index = planner.read("state/information/index.json")
    assert info_index["by_holder"]["char_tang_wei"].count(wake_a["information_ref"]) == 1


def test_play_context_exposes_actionable_campaign_packet_after_briefing(campaign):
    planner = _planner(campaign)
    refs = list(QIN_FORMATION_REFS)
    _seed_active_scope(planner, formation_refs=refs)
    at = _record_attempt(planner, request_id="test-qin-context-brief", action="request", target_ref=OPERATION_REF, statement="Brief me on the campaign and my orders.")
    runtime_state = copy.deepcopy(planner.read("state/runtime.json")); sync_qin_command_support(planner, runtime_state)
    wake = settle_qin_command_support(planner, _support_hosts(runtime_state, "test-qin-context-brief")[0], at)

    class _PlannerStore:
        def read_json(self, path): return planner.read(path)
    class _Runtime:
        store = _PlannerStore()
    operations = StableCampaignOperations(_Runtime())
    views = operations._controlled_operation_views(set(refs))
    view = next(row for row in views if row["operation_ref"] == OPERATION_REF)
    assert view["location_ref"] == "loc_qin_eastern_depot"
    assert view["campaign_arc_ref"] == "arc_ryo_fui_northern_wei_campaign"
    assert view["briefing_information_ref"] == wake["information_ref"]
    assert view["operational_area_ref"] == "loc_kanyou"
    assert view["strategic_target_ref"] == "loc_sanyou"
    assert view["entry_status"] == "awaiting_war_or_entry_authority"
    assert view["current_operational_order"]["actionability_status"] == "actionable"
    assert view["campaign_context"]["other_friendly_participants"]


def test_arrival_handoff_completes_only_after_all_assigned_units_reach_operational_area(campaign):
    planner = _planner(campaign)
    refs = list(QIN_FORMATION_REFS)
    _seed_active_scope(planner, formation_refs=refs)
    at = _record_attempt(planner, request_id="test-qin-arrival-brief", action="request", target_ref=OPERATION_REF, statement="Brief me.")
    runtime_state = copy.deepcopy(planner.read("state/runtime.json")); sync_qin_command_support(planner, runtime_state)
    settle_qin_command_support(planner, _support_hosts(runtime_state, "test-qin-arrival-brief")[0], at)

    op_path = planner.read("state/operations/index.json")["operations"][OPERATION_REF]
    operation = planner.read(op_path)
    opposing = set(operation.get("opposing_formation_refs", []))
    participants = [ref for ref in operation.get("formation_refs", []) if ref not in opposing]
    assert set(refs).issubset(participants)
    straggler = refs[-1]
    for ref in participants:
        path = planner.owner_path(ref)
        formation = copy.deepcopy(planner.read(path))
        formation["location_ref"] = "loc_qin_eastern_depot" if ref == straggler else "loc_kanyou"
        planner.put(path, formation)
    path = planner.owner_path(straggler)
    formation = copy.deepcopy(planner.read(path))
    assert reconcile_campaign_arrival(planner, OPERATION_REF, destination_ref="loc_kanyou", at=at, unit_duties=[]) is None

    formation["location_ref"] = "loc_kanyou"
    planner.put(path, formation)
    handoff = reconcile_campaign_arrival(
        planner, OPERATION_REF, destination_ref="loc_kanyou", at=at,
        unit_duties=[{"formation_ref": refs[0], "duty_id": "forward_security"}],
    )
    assert handoff is not None
    assert handoff["phase"] == "awaiting_entry_authority"
    assert "hostile entry is not yet authorized" in handoff["summary"]
    op_path = planner.read("state/operations/index.json")["operations"][OPERATION_REF]
    operation = planner.read(op_path)
    assert operation["order_status"] == "awaiting_entry_authority"
    assert operation["campaign_phase"] == "awaiting_entry_authority"
    assert operation["last_phase_information_ref"] == handoff["information_ref"]


def test_pending_qin_strategic_order_routes_one_automatic_staff_briefing(campaign):
    planner = _planner(campaign)
    refs = list(QIN_FORMATION_REFS)
    _seed_active_scope(planner, formation_refs=refs)
    op_path = planner.read("state/operations/index.json")["operations"][OPERATION_REF]
    operation = copy.deepcopy(planner.read(op_path))
    order = copy.deepcopy(operation["operational_orders"][-1])
    order["order_ref"] = "operational_order_test_auto_briefing_new"
    order["status"] = "strategic_directive_pending_operational_briefing"
    order["actionability_status"] = "pending_operational_briefing"
    order.pop("mission_packet", None)
    order.pop("staff_briefed_at", None)
    operation["operational_orders"].append(order)
    operation["last_operational_order_ref"] = order["order_ref"]
    operation["order_status"] = "awaiting_operational_briefing"
    planner.put(op_path, operation)

    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    sync_qin_command_support(planner, runtime)
    auto = [row for row in runtime["hosts"].values() if row.get("kind") == "qin_command_support_review" and row.get("support_kind") == "operational_briefing" and str(row.get("work_ref", "")).startswith("auto_qin_campaign_briefing_")]
    assert len(auto) == 1
    sync_qin_command_support(planner, runtime)
    auto2 = [row for row in runtime["hosts"].values() if row.get("kind") == "qin_command_support_review" and row.get("support_kind") == "operational_briefing" and str(row.get("work_ref", "")).startswith("auto_qin_campaign_briefing_")]
    assert len(auto2) == 1


def test_automatic_unchanged_qin_briefing_is_suppressed_after_first_delivery(campaign):
    planner = _planner(campaign)
    refs = list(QIN_FORMATION_REFS)
    _seed_active_scope(planner, formation_refs=refs)
    op_path = planner.read("state/operations/index.json")["operations"][OPERATION_REF]
    operation = copy.deepcopy(planner.read(op_path))
    order = copy.deepcopy(operation["operational_orders"][-1])
    order["order_ref"] = "operational_order_test_auto_briefing_duplicate"
    order["objective"] = "establish a fresh Qin screening posture before the next northern Wei campaign phase"
    order["status"] = "strategic_directive_pending_operational_briefing"
    order["actionability_status"] = "pending_operational_briefing"
    order.pop("mission_packet", None)
    order.pop("staff_briefed_at", None)
    operation["operational_orders"].append(order)
    operation["last_operational_order_ref"] = order["order_ref"]
    operation["order_status"] = "awaiting_operational_briefing"
    planner.put(op_path, operation)

    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    sync_qin_command_support(planner, runtime)
    host = next(row for row in runtime["hosts"].values() if row.get("kind") == "qin_command_support_review" and str(row.get("work_ref", "")).startswith("auto_qin_campaign_briefing_"))
    at = str(planner.read("state/runtime.json")["world_time"])
    first = settle_qin_command_support(planner, host, at)
    assert first is not None and first.get("information_ref")

    duplicate = copy.deepcopy(host)
    duplicate["work_ref"] = "auto_qin_campaign_briefing_duplicate_regression"
    second = settle_qin_command_support(planner, duplicate, at)
    assert second is None
    delivery = planner.read("state/index/qin-command-support-delivery.json")["by_operation"][OPERATION_REF]
    assert delivery == {"information_ref": first["information_ref"]}


def test_grouped_travel_path_triggers_campaign_arrival_handoff(campaign):
    planner = _planner(campaign)
    refs = list(QIN_FORMATION_REFS)
    _seed_active_scope(planner, formation_refs=refs)
    at = _record_attempt(planner, request_id="test-qin-grouped-travel-handoff", action="request", target_ref=OPERATION_REF, statement="Brief me.")
    runtime_state = copy.deepcopy(planner.read("state/runtime.json")); sync_qin_command_support(planner, runtime_state)
    settle_qin_command_support(planner, _support_hosts(runtime_state, "test-qin-grouped-travel-handoff")[0], at)

    op_path = planner.read("state/operations/index.json")["operations"][OPERATION_REF]
    operation = planner.read(op_path)
    opposing = set(operation.get("opposing_formation_refs", []))
    participants = [ref for ref in operation.get("formation_refs", []) if ref not in opposing]
    for ref in participants:
        path = planner.owner_path(ref)
        formation = copy.deepcopy(planner.read(path))
        formation["location_ref"] = "loc_kanyou"
        planner.put(path, formation)

    command = SimpleNamespace(command_type="travel")
    result = planner._command_layer_qin_command_support(
        command,
        {"destination_ref": "loc_kanyou", "formation_refs": [refs[0]]},
        lambda: {"world_time": at, "destination": "loc_kanyou"},
    )
    assert result["campaign_handoff"]["phase"] == "awaiting_entry_authority"
    after = planner.read(op_path)
    assert after["campaign_phase"] == "awaiting_entry_authority"
    assert after["last_phase_information_ref"] == result["campaign_handoff"]["information_ref"]
