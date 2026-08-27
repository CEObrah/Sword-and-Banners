from __future__ import annotations

import copy

from sword_runtime.campaign_command_cycle import (
    campaign_command_projection,
    settle_campaign_command_host,
    sync_campaign_command_cycle,
)
from sword_runtime.downtime import _PLAYER_FACING_EVENT_KINDS
from sword_runtime.production_planner import ProductionCampaignPlanner


OPERATION_REF = "operation_arc_131572c4e8a2892bbc"
EXPECTED_CAMPAIGN_COMMANDERS = {
    "char_tang_wei",
    "char_mou_gou",
    "char_ousen",
    "char_kanki",
    "char_ouki",
    "char_tou",
    "char_mou_bu",
    "char_cmd_qin_mobile_reserve",
    "char_shou_hei_kun",
}
EXPECTED_QIN_COURT = {
    "char_ei_sei",
    "char_ryo_fui",
    "char_ri_shi",
    "char_ketsu_shi",
    "char_shou_bun_kun",
    "char_heki",
    "char_shou_hei_kun",
}



def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    return planner


def _campaign_formation_locations(planner):
    op_path = planner.read("state/operations/index.json")["operations"][OPERATION_REF]
    operation = planner.read(op_path)
    refs = list(operation.get("formation_refs", []))
    for participant_ref in operation.get("campaign_participant_operation_refs", []):
        participant_path = planner.read("state/operations/index.json")["operations"][participant_ref]
        refs.extend(planner.read(participant_path).get("formation_refs", []))
    return {
        ref: planner.read(planner.owner_path(ref)).get("location_ref")
        for ref in dict.fromkeys(refs)
    }


def _register_cycle(planner):
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    sync_campaign_command_cycle(planner, runtime)
    planner.put("state/runtime.json", runtime)
    return runtime


def _hold_council(planner, runtime):
    projection = campaign_command_projection(planner, OPERATION_REF)
    assert projection is not None
    host = next(row for row in runtime["hosts"].values() if row.get("kind") == "campaign_command_council")
    due_at = projection["war_council"]["scheduled_at"]
    result = settle_campaign_command_host(planner, host, due_at)
    assert result is not None
    return result, due_at


def _enter_field_phase(planner):
    op_path = planner.owner_path(OPERATION_REF)
    operation = copy.deepcopy(planner.read(op_path))
    operation["campaign_phase"] = "operational_area_arrival"
    operation["order_status"] = "awaiting_follow_on_direction"
    planner.put(op_path, operation)


def test_campaign_cycle_registers_full_qin_command_chain_without_moving_armies(campaign):
    planner = _planner(campaign)
    formation_locations = _campaign_formation_locations(planner)

    runtime = _register_cycle(planner)
    projection = campaign_command_projection(planner, OPERATION_REF)

    assert projection is not None
    assert projection["status"] == "war_council_assembling"
    assert projection["superior_command_ref"] == "inst_qin_military_bureau"
    assert projection["supreme_commander_ref"] is None
    assert projection["forum_kind"] == "royal_court"
    assert projection["court_state_ref"] == "state_qin"
    assert set(projection["participant_commander_refs"]) == EXPECTED_CAMPAIGN_COMMANDERS
    assert projection["war_council"]["status"] == "summoned"
    assert any(host.get("kind") == "campaign_command_council" for host in runtime["hosts"].values())

    assert _campaign_formation_locations(planner) == formation_locations
    cycle = planner.read(planner.owner_path(projection["cycle_ref"]))
    assert cycle["authority"] is True
    assert cycle["operation_ref"] == OPERATION_REF
    assert planner.read(planner.owner_path(OPERATION_REF))["campaign_command_cycle_ref"] == projection["cycle_ref"]


def test_war_council_moves_exact_commanders_after_real_travel_delay_but_never_their_armies(campaign):
    planner = _planner(campaign)
    formation_locations = _campaign_formation_locations(planner)
    runtime = _register_cycle(planner)

    result, due_at = _hold_council(planner, runtime)

    assert EXPECTED_CAMPAIGN_COMMANDERS <= set(result["present_person_refs"])
    assert EXPECTED_QIN_COURT <= set(result["present_person_refs"])
    projection = campaign_command_projection(planner, OPERATION_REF)
    assert projection is not None
    assert projection["war_council"]["status"] == "held"
    assert projection["war_council"]["held_at"] == due_at
    assert projection["supreme_commander_ref"] == "char_mou_gou"
    assert projection["superior_command_ref"] == "char_mou_gou"
    operation = planner.read(planner.owner_path(OPERATION_REF))
    assert operation["campaign_commander_ref"] == "char_mou_gou"
    assert operation["institutional_owner_ref"] == "state_qin"
    assert operation["operational_orders"][-1]["issuer_ref"] == "state_qin"
    assert operation["operational_orders"][-1]["superior_commander_ref"] == "char_mou_gou"
    directive = operation["campaign_command_directives"][-1]
    assert directive["issuer_ref"] == "state_qin"
    assert directive["issuing_commander_ref"] == "char_mou_gou"
    assert directive["kind"] == "hold_staging_and_report"
    assert directive["base_operational_order_ref"] == operation["last_operational_order_ref"]
    assert set(directive["applies_to_formation_refs"]) == {
        "formation_black_banner_01a", "formation_black_banner_01b",
        "formation_black_banner_02a", "formation_black_banner_02b",
        "formation_black_banner_03a", "formation_black_banner_03b",
        "formation_black_banner_04a", "formation_black_banner_04b",
        "formation_high_guard_qin_a", "formation_high_guard_qin_b",
    }
    assert "formation_red_lance_a" in directive["excluded_non_state_formation_refs"]
    for person_ref in EXPECTED_CAMPAIGN_COMMANDERS:
        assert planner.read(planner.owner_path(person_ref)).get("current_location") == "loc_kanyou"
    for person_ref in EXPECTED_QIN_COURT:
        assert person_ref in set(result["present_person_refs"])
    assert _campaign_formation_locations(planner) == formation_locations

    events = planner.read("state/event/events-messages-and-movement.json")["causal_events"]
    event = events[result["event_ref"]]
    assert event["kind"] == "campaign_command_council"
    assert EXPECTED_CAMPAIGN_COMMANDERS <= set(event["present_person_refs"])
    assert EXPECTED_QIN_COURT <= set(event["present_person_refs"])
    assert event["campaign_command_context"]["forum_kind"] == "royal_court"
    court = event["campaign_command_context"]["court_session"]
    assert court["sovereign_ref"] == "char_ei_sei"
    assert court["court_role_by_person_ref"]["char_ryo_fui"] == "chancellor"
    assert event["campaign_command_context"]["friendly_total_strength"] == 176800
    assert event["campaign_command_context"]["current_superior_directive"]["issuing_commander_ref"] == "char_mou_gou"
    assert event["campaign_command_context"]["own_command_snapshot"]["personnel"] == 9500


def test_pre_entry_staging_does_not_schedule_empty_daily_headquarters_cycle(campaign):
    planner = _planner(campaign)
    runtime = _register_cycle(planner)
    _result, council_at = _hold_council(planner, runtime)

    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    runtime["world_time"] = council_at
    runtime.setdefault("scheduler", {})["causal_settled_through"] = council_at
    sync_campaign_command_cycle(planner, runtime)
    planner.put("state/runtime.json", runtime)

    kinds = {row.get("kind") for row in runtime["hosts"].values()}
    assert "campaign_command_dawn" not in kinds
    assert "campaign_command_evening" not in kinds
    projection = campaign_command_projection(planner, OPERATION_REF)
    assert projection["daily_cycle"]["status"] == "paused_until_field_operations"
    assert projection["daily_cycle"]["paused_campaign_phase"] == "awaiting_entry_authority"


def test_dawn_and_evening_command_cycle_reports_upward_without_choosing_wei_tactics(campaign):
    planner = _planner(campaign)
    runtime = _register_cycle(planner)
    _result, council_at = _hold_council(planner, runtime)
    _enter_field_phase(planner)

    operation_before = copy.deepcopy(planner.read(planner.owner_path(OPERATION_REF)))
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    runtime["world_time"] = council_at
    runtime.setdefault("scheduler", {})["causal_settled_through"] = council_at
    sync_campaign_command_cycle(planner, runtime)
    planner.put("state/runtime.json", runtime)

    dawn_host = next(row for row in runtime["hosts"].values() if row.get("kind") == "campaign_command_dawn")
    evening_host = next(row for row in runtime["hosts"].values() if row.get("kind") == "campaign_command_evening")
    dawn = settle_campaign_command_host(planner, dawn_host, dawn_host["next_due"])
    evening = settle_campaign_command_host(planner, evening_host, evening_host["next_due"])

    assert dawn is not None and evening is not None
    assert dawn["command_context"]["friendly_total_strength"] == 176800
    assert evening["command_context"]["own_command_snapshot"]["personnel"] == 9500
    assert "char_lin_zhen" in dawn["present_person_refs"]

    cycle_ref = campaign_command_projection(planner, OPERATION_REF)["cycle_ref"]
    cycle = planner.read(planner.owner_path(cycle_ref))
    reports = cycle["upward_reports"][-2:]
    assert [row["phase"] for row in reports] == ["dawn", "evening"]
    assert all(row["from_ref"] == "char_tang_wei" for row in reports)
    assert all(row["to_ref"] == "char_mou_gou" for row in reports)
    assert all(row["personnel"] == 9500 for row in reports)
    assert all(row["directive_ref"] for row in reports)

    operation_after = planner.read(planner.owner_path(OPERATION_REF))
    assert operation_after.get("operational_orders") == operation_before.get("operational_orders")
    assert operation_after.get("formation_refs") == operation_before.get("formation_refs")
    assert operation_after.get("campaign_phase") == operation_before.get("campaign_phase")


def test_named_campaign_commander_becomes_weis_superior_without_transferring_qin_authority(campaign):
    planner = _planner(campaign)
    op_path = planner.owner_path(OPERATION_REF)
    operation = copy.deepcopy(planner.read(op_path))
    operation["campaign_commander_ref"] = "char_mou_gou"
    planner.put(op_path, operation)

    runtime = _register_cycle(planner)
    projection = campaign_command_projection(planner, OPERATION_REF)

    assert projection is not None
    assert projection["supreme_commander_ref"] == "char_mou_gou"
    assert projection["superior_command_ref"] == "char_mou_gou"
    assert projection["coordination_authority_ref"] == "inst_qin_military_bureau"
    current_order = projection["current_superior_order"]
    assert current_order["issuer_ref"] == "state_qin"
    assert current_order["superior_command_ref"] == "char_mou_gou"
    assert planner.read(op_path)["institutional_owner_ref"] == "state_qin"
    assert any(host.get("kind") == "campaign_command_council" for host in runtime["hosts"].values())


def test_daily_headquarters_follows_wei_after_the_army_leaves_the_royal_court(campaign):
    planner = _planner(campaign)
    runtime = _register_cycle(planner)
    _result, council_at = _hold_council(planner, runtime)
    _enter_field_phase(planner)

    player = copy.deepcopy(planner.read("state/player.json"))
    player["location"] = "loc_qin_eastern_depot"
    planner.put("state/player.json", player)
    lin_path = planner.owner_path("char_lin_zhen")
    lin = copy.deepcopy(planner.read(lin_path))
    lin["current_location"] = "loc_qin_eastern_depot"
    planner.put(lin_path, lin)

    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    runtime["world_time"] = council_at
    runtime.setdefault("scheduler", {})["causal_settled_through"] = council_at
    sync_campaign_command_cycle(planner, runtime)
    planner.put("state/runtime.json", runtime)
    dawn_host = next(row for row in runtime["hosts"].values() if row.get("kind") == "campaign_command_dawn")
    dawn = settle_campaign_command_host(planner, dawn_host, dawn_host["next_due"])

    assert dawn is not None
    assert dawn["command_context"]["field_headquarters_location_ref"] == "loc_qin_eastern_depot"
    assert "char_lin_zhen" in dawn["present_person_refs"]
    events = planner.read("state/event/events-messages-and-movement.json")["causal_events"]
    assert events[dawn["event_ref"]]["delivery"]["location_ref"] == "loc_qin_eastern_depot"


def test_campaign_command_events_are_real_downtime_boundaries():
    assert "campaign_command_council" in _PLAYER_FACING_EVENT_KINDS
    assert "campaign_command_dawn_briefing" in _PLAYER_FACING_EVENT_KINDS
    assert "campaign_command_evening_sitrep" in _PLAYER_FACING_EVENT_KINDS


def test_new_superior_order_is_delivered_as_its_own_headquarters_event(campaign):
    planner = _planner(campaign)
    runtime = _register_cycle(planner)
    _result, council_at = _hold_council(planner, runtime)

    op_path = planner.owner_path(OPERATION_REF)
    operation = copy.deepcopy(planner.read(op_path))
    order = {
        "order_ref": "operational_order_test_follow_on",
        "issued_at": council_at,
        "issuer_ref": "state_qin",
        "superior_commander_ref": "char_mou_gou",
        "coordination_authority_ref": "inst_qin_military_bureau",
        "objective": "maintain concentration and prepare the eastern road for lawful advance",
        "status": "issued_awaiting_commander_execution",
        "actionability_status": "actionable",
        "applies_to_formation_refs": list(operation["operational_orders"][-1].get("applies_to_formation_refs", [])),
        "excluded_non_state_formation_refs": list(operation["operational_orders"][-1].get("excluded_non_state_formation_refs", [])),
    }
    operation.setdefault("operational_orders", []).append(order)
    operation["last_operational_order_ref"] = order["order_ref"]
    operation["last_operational_order_at"] = council_at
    planner.put(op_path, operation)

    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    runtime["world_time"] = council_at
    runtime.setdefault("scheduler", {})["causal_settled_through"] = council_at
    sync_campaign_command_cycle(planner, runtime)
    planner.put("state/runtime.json", runtime)

    host = next(
        row for row in runtime["hosts"].values()
        if row.get("kind") == "campaign_command_superior_order"
        and row.get("phase_instance_ref") == order["order_ref"]
    )
    result = settle_campaign_command_host(planner, host, host["next_due"])
    assert result is not None
    assert result["command_context"]["delivered_superior_order"]["order_ref"] == order["order_ref"]
    events = planner.read("state/event/events-messages-and-movement.json")["causal_events"]
    assert events[result["event_ref"]]["kind"] == "campaign_command_superior_order"
    cycle = planner.read(planner.owner_path(campaign_command_projection(planner, OPERATION_REF)["cycle_ref"]))
    assert order["order_ref"] in cycle["delivered_superior_order_refs"]


def test_concluded_battle_gets_separate_after_action_command_review(campaign):
    planner = _planner(campaign)
    runtime = _register_cycle(planner)
    _result, council_at = _hold_council(planner, runtime)

    op_path = planner.owner_path(OPERATION_REF)
    operation = copy.deepcopy(planner.read(op_path))
    battlefield_ref = "battlefield_test_campaign_review"
    formation_ref = operation["formation_refs"][0]
    after_action = {
        "battlefield_ref": battlefield_ref,
        "reviewed_at": council_at,
        "outcome": {
            "winner_side_ref": "state_qin",
            "loser_side_ref": "state_wei",
            "reason": "test_conclusion",
        },
        "battle_event_refs": [],
        "side_summary": {},
        "formation_summary": [{
            "formation_ref": formation_ref,
            "side_ref": "state_qin",
            "personnel_remaining": 490,
            "battle_killed": 10,
            "status": "deployed",
            "readiness": 80,
            "fatigue": 10,
            "cohesion": 90,
            "morale": 80,
        }],
        "scope": "field_battle_after_action",
    }
    operation.setdefault("battlefields", {})[battlefield_ref] = {
        "battlefield_ref": battlefield_ref,
        "status": "ended",
        "after_action": copy.deepcopy(after_action),
    }
    operation["last_battlefield_after_action"] = copy.deepcopy(after_action)
    planner.put(op_path, operation)

    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    runtime["world_time"] = council_at
    runtime.setdefault("scheduler", {})["causal_settled_through"] = council_at
    sync_campaign_command_cycle(planner, runtime)
    planner.put("state/runtime.json", runtime)

    host = next(
        row for row in runtime["hosts"].values()
        if row.get("kind") == "campaign_command_after_action"
        and str(row.get("phase_instance_ref", "")).startswith(battlefield_ref + "|")
    )
    result = settle_campaign_command_host(planner, host, host["next_due"])
    assert result is not None
    assert result["command_context"]["battlefield_after_action"]["battlefield_ref"] == battlefield_ref
    events = planner.read("state/event/events-messages-and-movement.json")["causal_events"]
    assert events[result["event_ref"]]["kind"] == "campaign_command_after_action_review"
    cycle = planner.read(planner.owner_path(campaign_command_projection(planner, OPERATION_REF)["cycle_ref"]))
    assert cycle["after_action_reviews"][-1]["battlefield_ref"] == battlefield_ref
    assert cycle["upward_reports"][-1]["phase"] == "after_action"
    assert cycle["upward_reports"][-1]["battle_killed"] == 10


def test_campaign_command_order_and_after_action_events_are_downtime_boundaries():
    assert "campaign_command_superior_order" in _PLAYER_FACING_EVENT_KINDS
    assert "campaign_command_after_action_review" in _PLAYER_FACING_EVENT_KINDS
