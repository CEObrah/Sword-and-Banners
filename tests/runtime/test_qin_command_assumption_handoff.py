from __future__ import annotations

import copy
import json

import pytest

from sword_runtime.api.interaction_surface import INTERACTION_ATTEMPT_PREFIX
from sword_runtime.qin_command_assumption_flow import (
    _settle_assumption,
    _write_receiving_event,
    sync_qin_command_assumption_flow,
)
from sword_runtime.qin_detachment_command import _assign_detachment_operation_to_wei
from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.vitality import summarize_playability_vitality

PARENT_REF = "formation_qin_mobile_reserve"
OPERATION_REF = "operation_arc_131572c4e8a2892bbc"
CHILD_REF = "formation_test_qin_assumption_detachment"
OFFICE = f"field_command:{CHILD_REF}"
SOURCE_REF = "event_test_qin_assumption_offer"


class _PlannerStore:
    def __init__(self, planner):
        self.planner = planner

    def read_json(self, path):
        return self.planner.read(path)


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    meta = copy.deepcopy(planner.read("state/meta.json"))
    planner.PLAYER_ACTOR = str(meta["player_id"])
    planner._reset()
    return planner


def _seed_awaiting(planner, *, at_location=True):
    parent = planner.read(planner.owner_path(PARENT_REF))
    report_to = str(parent["location_ref"])
    player = copy.deepcopy(planner.read("state/player.json"))
    player["location"] = report_to if at_location else "loc_tang_manor_training_ground"
    career = player.setdefault("career_state", {})
    career["appointments"] = [{
        "kind": "qin_field_command",
        "offer_kind": "qin_probationary_detachment_command",
        "office": OFFICE,
        "state_ref": "state_qin",
        "formation_ref": CHILD_REF,
        "formation_name": "Test Qin Probationary Detachment",
        "parent_formation_ref": PARENT_REF,
        "operation_ref": OPERATION_REF,
        "personnel": 1000,
        "appointed_at": str(planner.read("state/runtime.json")["world_time"]),
        "source_event_ref": SOURCE_REF,
        "report_to_location_ref": report_to,
        "prior_authority": "House Tang heir",
        "status": "awaiting_assumption",
    }]
    planner.put("state/player.json", player)

    op_path = planner.read("state/operations/index.json")["operations"][OPERATION_REF]
    operation = copy.deepcopy(planner.read(op_path))
    operation["status"] = "active"
    refs = operation.setdefault("formation_refs", [])
    if PARENT_REF not in refs:
        refs.append(PARENT_REF)
    planner.put(op_path, operation)

    qin = copy.deepcopy(planner.read("state/states/qin.json"))
    qin.setdefault("appointments", {})[OFFICE] = {
        "person_ref": "char_tang_wei",
        "offer_kind": "qin_probationary_detachment_command",
        "formation_ref": CHILD_REF,
        "parent_formation_ref": PARENT_REF,
        "operation_ref": OPERATION_REF,
        "personnel": 1000,
        "appointed_at": str(planner.read("state/runtime.json")["world_time"]),
        "source_event_ref": SOURCE_REF,
        "report_to_location_ref": report_to,
        "status": "awaiting_assumption",
    }
    planner.put("state/states/qin.json", qin)
    return report_to


def _record_attempt(planner, *, request_id="report-qin-command", action="report", actor="char_tang_wei", target_ref=None):
    runtime = planner.read("state/runtime.json")
    at = str(runtime["world_time"])
    player = planner.read("state/player.json")
    target_ref = target_ref or str(player["location"])
    attempt = {
        "schema": "sword-interaction-attempt.v1",
        "surface_digest": "a" * 64,
        "request_id": request_id,
        "actor_id": actor,
        "target_ref": target_ref,
        "action": action,
        "process_ref": None,
        "player_statement": "I report to assume the Qin command already accepted.",
        "formation_refs": [],
        "posture": "Report through the lawful receiving authority.",
        "world_response_status": "not_established_by_attempt",
    }
    history = copy.deepcopy(planner.read("state/history/events/index.json"))
    history["events"].append({
        "at": at,
        "event_id": f"scene_{request_id}",
        "kind": "scene_consequence",
        "summary": INTERACTION_ATTEMPT_PREFIX + json.dumps(attempt, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    })
    planner.put("state/history/events/index.json", history)


def _receiving_hosts(runtime):
    return [row for row in runtime["hosts"].values() if row.get("kind") == "qin_command_receiving"]


def _assumption_hosts(runtime):
    return [row for row in runtime["hosts"].values() if row.get("kind") == "qin_command_assumption"]


def test_report_registers_one_institution_owned_receiving_host_and_is_idempotent(campaign):
    planner = _planner(campaign)
    report_to = _seed_awaiting(planner)
    _record_attempt(planner, target_ref=report_to)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))

    sync_qin_command_assumption_flow(planner, runtime)
    sync_qin_command_assumption_flow(planner, runtime)

    hosts = _receiving_hosts(runtime)
    assert len(hosts) == 1
    assert hosts[0]["owner_ref"] == "inst_qin_military_bureau"
    assert hosts[0]["appointment_office"] == OFFICE
    assert hosts[0]["report_to_location_ref"] == report_to
    appointment = planner.read("state/player.json")["career_state"]["appointments"][-1]
    assert appointment["status"] == "awaiting_assumption"
    assert planner.read_optional(f"state/formations/{CHILD_REF.removeprefix('formation_').replace('_', '-')}.json") is None


def test_receiver_handoff_then_final_process_conserves_force_and_activates_command(campaign):
    planner = _planner(campaign)
    report_to = _seed_awaiting(planner)
    parent_before = int(planner.read(planner.owner_path(PARENT_REF))["personnel"])
    _record_attempt(planner, target_ref=report_to)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    sync_qin_command_assumption_flow(planner, runtime)
    receiving = _receiving_hosts(runtime)
    assert len(receiving) == 1

    at = str(runtime["world_time"])
    receiver_ref = _write_receiving_event(planner, receiving[0], at)
    assert isinstance(receiver_ref, str)
    appointment = planner.read("state/player.json")["career_state"]["appointments"][-1]
    assert appointment["status"] == "awaiting_assumption"

    runtime2 = copy.deepcopy(runtime)
    sync_qin_command_assumption_flow(planner, runtime2)
    final_hosts = _assumption_hosts(runtime2)
    assert len(final_hosts) == 1
    assumed_ref = _settle_assumption(planner, final_hosts[0], at)
    assert isinstance(assumed_ref, str)

    player = planner.read("state/player.json")
    appointment = next(row for row in player["career_state"]["appointments"] if row.get("office") == OFFICE)
    assert appointment["status"] == "active"
    parent = planner.read(planner.owner_path(PARENT_REF))
    child = planner.read(planner.owner_path(CHILD_REF))
    assert int(parent["personnel"]) + int(child["personnel"]) == parent_before
    assert int(child["personnel"]) == 1000
    assert child["administrative_owner"] == "state_qin"
    assert child["commander_ref"] == "char_tang_wei"
    assert child["command_authority"] == "char_tang_wei"


@pytest.mark.parametrize("case", ["wrong_location", "wrong_actor", "no_appointment"])
def test_invalid_report_attempts_do_not_register_receiving_host(campaign, case):
    planner = _planner(campaign)
    report_to = _seed_awaiting(planner, at_location=case != "wrong_location")
    if case == "no_appointment":
        player = copy.deepcopy(planner.read("state/player.json"))
        player["career_state"]["appointments"] = []
        planner.put("state/player.json", player)
    _record_attempt(
        planner,
        actor="char_someone_else" if case == "wrong_actor" else "char_tang_wei",
        target_ref=report_to,
    )
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    sync_qin_command_assumption_flow(planner, runtime)
    assert _receiving_hosts(runtime) == []


def test_duplicate_report_attempts_collapse_to_one_appointment_receiving_host(campaign):
    planner = _planner(campaign)
    report_to = _seed_awaiting(planner)
    _record_attempt(planner, request_id="report-qin-command-1", action="report", target_ref=report_to)
    _record_attempt(planner, request_id="report-qin-command-2", action="seek_contact", target_ref=report_to)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    sync_qin_command_assumption_flow(planner, runtime)
    assert len(_receiving_hosts(runtime)) == 1


def test_vitality_flags_awaiting_command_at_report_site_until_receiving_path_exists(campaign):
    planner = _planner(campaign)
    report_to = _seed_awaiting(planner)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    runtime["hosts"] = {
        key: value for key, value in runtime.get("hosts", {}).items()
        if value.get("kind") not in {"qin_command_receiving", "qin_command_assumption"}
    }
    planner.put("state/runtime.json", runtime)

    before = summarize_playability_vitality(_PlannerStore(planner))
    assert before["blocked_awaiting_qin_command_assumptions"] == 1
    assert "awaiting_qin_command_at_report_site_without_receiving_path" in before["diagnostics"]

    _record_attempt(planner, target_ref=report_to)
    routed = copy.deepcopy(planner.read("state/runtime.json"))
    sync_qin_command_assumption_flow(planner, routed)
    planner.put("state/runtime.json", routed)
    after = summarize_playability_vitality(_PlannerStore(planner))
    assert after["blocked_awaiting_qin_command_assumptions"] == 0
    assert "awaiting_qin_command_at_report_site_without_receiving_path" not in after["diagnostics"]


def test_registered_detachment_operation_transfers_assignment_authority_without_manpower_ownership(campaign):
    planner = _planner(campaign)
    op_path = planner.read("state/operations/index.json")["operations"][OPERATION_REF]
    operation = copy.deepcopy(planner.read(op_path))
    refs = [f"formation_qin_wei_unit_{i:02d}" for i in range(1, 5)]
    operation["formation_refs"] = refs
    operation["kind"] = "state_world_arc_operation"
    operation["autonomous"] = True
    operation["administrative_authority"] = "state_qin"
    operation["administrative_authorities"] = ["state_qin"]
    operation.pop("assignment_authority_ref", None)
    planner.put(op_path, operation)

    _assign_detachment_operation_to_wei(
        planner,
        op_path,
        operation,
        refs=refs,
        office="field_command:qin_border_detachment",
        offer_ref="event_test_registered_detachment_offer",
    )

    assigned = planner.read(op_path)
    assert assigned["administrative_authority"] == "char_tang_wei"
    assert assigned["administrative_authorities"] == ["char_tang_wei"]
    assert assigned["assignment_authority_ref"] == "char_tang_wei"
    assert assigned["institutional_owner_ref"] == "state_qin"
    assert assigned["source_force_ref"] == "force_state_qin"
    assert assigned["command_group_ref"] == "cmdgrp.tang_wei.field_army"
    assert assigned["autonomous"] is False
    for ref in refs:
        formation = planner.read(planner.owner_path(ref))
        assert formation["owner_force_ref"] == "force_state_qin"
        assert formation["administrative_owner"] == "state_qin"
