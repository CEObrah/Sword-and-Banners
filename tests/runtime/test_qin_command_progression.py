from __future__ import annotations

import copy
import json

from sword_runtime.api.maintenance_operations import QinCommandMaintenanceOperations
from sword_runtime.causal_event_store import get_causal_event
from sword_runtime.player_story_flow import _event_owner_write
from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.qin_command_progression import (
    assume_probationary_command,
    command_scale_ceiling,
    command_scale_ceiling_from_player,
    normalize_new_qin_offers,
    repaired_offer_details,
    settle_probationary_reply,
)
from sword_runtime.service_runtime import ProductionSwordRuntime

OFFER_REF = "event_test_qin_oversized_first_command"
PARENT_REF = "formation_qin_border_line"
OPERATION_REF = "operation_arc_131572c4e8a2892bbc"


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    return planner


def _oversized_details(planner, *, personnel=8000):
    parent = planner.read(planner.owner_path(PARENT_REF))
    return {
        "arc_ref": "arc_ryo_fui_northern_wei_campaign",
        "candidate_score": 733,
        "formation_name": str(parent.get("name", "QIN Border Line")),
        "formation_ref": PARENT_REF,
        "institution_ref": "inst_qin_military_bureau",
        "location_ref": str(parent.get("location_ref", "loc_qin_eastern_depot")),
        "offered_at": str(planner.read("state/runtime.json")["world_time"]),
        "operation_ref": OPERATION_REF,
        "personnel": personnel,
        "state_ref": "state_qin",
    }


def _seed_offer(planner):
    at = str(planner.read("state/runtime.json")["world_time"])
    player = copy.deepcopy(planner.read("state/player.json"))
    career = player.setdefault("career_state", {})
    details = _oversized_details(planner)
    career["pending_qin_command_offer_refs"] = [OFFER_REF]
    career["pending_qin_command_offers"] = {OFFER_REF: details}
    career.pop("appointments", None)
    planner.put("state/player.json", player)

    operation_path = planner.read("state/operations/index.json")["operations"][OPERATION_REF]
    operation = copy.deepcopy(planner.read(operation_path))
    operation["status"] = "active"
    refs = operation.setdefault("formation_refs", [])
    if PARENT_REF not in refs:
        refs.append(PARENT_REF)
    planner.put(operation_path, operation)

    _event_owner_write(
        planner,
        OFFER_REF,
        {
            "event_ref": OFFER_REF,
            "kind": "institutional_response",
            "status": "triggered",
            "due_at": at,
            "triggered_at": at,
            "actor_ref": "inst_qin_military_bureau",
            "target_ref": "char_tang_wei",
            "basis_goal": "Synthetic oversized first Qin command regression fixture",
            "process_kind": "qin_field_command_offer",
            "process_stage": "offer_pending",
            "summary": "Qin offers Tang Wei direct command of an oversized first field formation.",
            "delivery": {
                "target_ref": "char_tang_wei",
                "location_ref": str(player.get("location", "loc_tang_manor_training_ground")),
                "route": "test courier",
            },
        },
        at,
        source_owner_ref="inst_qin_military_bureau",
    )
    return OFFER_REF, details, at


def _install_repaired_offer(planner):
    offer_ref, details, at = _seed_offer(planner)
    player = copy.deepcopy(planner.read("state/player.json"))
    rules = planner.read("game/data/mechanics/career-progression.json")["qin_field_command"]
    normalized = repaired_offer_details(player, rules, offer_ref, details, at)
    player["career_state"]["pending_qin_command_offers"][offer_ref] = normalized
    planner.put("state/player.json", player)
    return offer_ref, normalized, at


def _seed_offer_on_disk(campaign):
    player_path = campaign / "state/player.json"
    player = json.loads(player_path.read_text())
    parent = json.loads((campaign / "state/formations/qin-border-line.json").read_text())
    runtime = json.loads((campaign / "state/runtime.json").read_text())
    career = player.setdefault("career_state", {})
    details = {
        "arc_ref": "arc_ryo_fui_northern_wei_campaign",
        "candidate_score": 733,
        "formation_name": str(parent.get("name", "QIN Border Line")),
        "formation_ref": PARENT_REF,
        "institution_ref": "inst_qin_military_bureau",
        "location_ref": str(parent.get("location_ref", "loc_qin_eastern_depot")),
        "offered_at": str(runtime["world_time"]),
        "operation_ref": OPERATION_REF,
        "personnel": 8000,
        "state_ref": "state_qin",
    }
    career["pending_qin_command_offer_refs"] = [OFFER_REF]
    career["pending_qin_command_offers"] = {OFFER_REF: details}
    career.pop("appointments", None)
    player_path.write_text(json.dumps(player, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    return OFFER_REF


def test_unproven_sixteen_year_old_is_scale_matched_to_1000(campaign):
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    player = copy.deepcopy(planner.read("state/player.json"))
    player["career_state"] = {}
    rules = planner.read("game/data/mechanics/career-progression.json")["qin_field_command"]
    details = _oversized_details(planner, personnel=8000)
    normalized = repaired_offer_details(player, rules, OFFER_REF, details, at)
    assert command_scale_ceiling_from_player(player, rules, at) == 1000
    assert normalized["offer_kind"] == "qin_probationary_detachment_command"
    assert normalized["personnel"] == 1000
    assert normalized["parent_formation_ref"] == PARENT_REF
    assert normalized["parent_personnel"] == 8000
    assert normalized["formation_ref"] != normalized["parent_formation_ref"]


def test_new_offer_rewrite_preserves_schema_strict_provenance(campaign):
    planner = _planner(campaign)
    offer_ref, _details, at = _seed_offer(planner)
    before = copy.deepcopy(get_causal_event(planner, offer_ref)["provenance"])
    changed = normalize_new_qin_offers(planner, at, {offer_ref})
    assert changed == [offer_ref]
    event = get_causal_event(planner, offer_ref)
    assert event["provenance"] == before
    assert set(event["provenance"]) == {"kind", "source_owner_ref", "work_ref", "late_catch_up"}
    assert "1000-man detachment" in event["summary"]


def test_acceptance_reserves_detachment_without_splitting_parent(campaign):
    planner = _planner(campaign)
    offer_ref, normalized, at = _install_repaired_offer(planner)
    parent_path = planner.owner_path(normalized["parent_formation_ref"])
    before = int(planner.read(parent_path)["personnel"])
    wake = settle_probationary_reply(
        planner,
        {
            "offer_ref": offer_ref,
            "decision_event_ref": offer_ref + ".decision",
            "player_action": "proceed",
            "request_id": "test-qin-probationary-accept",
        },
        at,
    )
    assert wake is not None
    assert int(planner.read(parent_path)["personnel"]) == before
    player = planner.read("state/player.json")
    appointment = next(row for row in player["career_state"]["appointments"] if row.get("source_event_ref") == offer_ref)
    assert appointment["status"] == "awaiting_assumption"
    assert appointment["personnel"] == 1000
    child_path = f"state/formations/{appointment['formation_ref'].removeprefix('formation_').replace('_', '-')}.json"
    assert planner.read_optional(child_path) is None


def test_assumption_conserves_parent_plus_1000_child_and_keeps_qin_ownership(campaign):
    planner = _planner(campaign)
    offer_ref, normalized, at = _install_repaired_offer(planner)
    parent_path = planner.owner_path(normalized["parent_formation_ref"])
    parent_before = int(planner.read(parent_path)["personnel"])
    assert parent_before > 1000
    before_vacancies = int(planner.read("state/states/qin.json")["military_administration"]["commander_vacancy_count"])
    settle_probationary_reply(
        planner,
        {
            "offer_ref": offer_ref,
            "decision_event_ref": offer_ref + ".decision",
            "player_action": "proceed",
            "request_id": "test-qin-probationary-accept",
        },
        at,
    )
    player = copy.deepcopy(planner.read("state/player.json"))
    player["location"] = normalized["location_ref"]
    planner.put("state/player.json", player)
    event_ref = assume_probationary_command(planner, at)
    assert event_ref is not None
    parent = planner.read(parent_path)
    appointment = next(row for row in planner.read("state/player.json")["career_state"]["appointments"] if row.get("source_event_ref") == offer_ref)
    child = planner.read(planner.owner_path(appointment["formation_ref"]))
    assert child["personnel"] == 1000
    assert parent["personnel"] == parent_before - 1000
    assert parent["personnel"] + child["personnel"] == parent_before
    assert parent["administrative_owner"] == "state_qin"
    assert child["administrative_owner"] == "state_qin"
    assert child["commander_ref"] == "char_tang_wei"
    assert child["command_authority"] == "char_tang_wei"
    operation = planner.read(planner.read("state/operations/index.json")["operations"][normalized["operation_ref"]])
    assert normalized["parent_formation_ref"] in operation["formation_refs"]
    assert appointment["formation_ref"] in operation["formation_refs"]
    qin = planner.read("state/states/qin.json")
    assert int(qin["military_administration"]["commander_vacancy_count"]) == before_vacancies


def test_verified_1000_command_opens_3000_scale_next(campaign):
    planner = _planner(campaign)
    player = copy.deepcopy(planner.read("state/player.json"))
    player.setdefault("career_state", {})["verified_qin_field_command_personnel"] = 1000
    planner.put("state/player.json", player)
    at = str(planner.read("state/runtime.json")["world_time"])
    assert command_scale_ceiling(planner, at) == 3000


def test_explicit_maintenance_repair_updates_only_player_career_owner(campaign, tmp_path):
    offer_ref = _seed_offer_on_disk(campaign)
    runtime = ProductionSwordRuntime(campaign, tmp_path / "runtime")
    operations = QinCommandMaintenanceOperations(runtime)
    context = operations.play_context()
    revision = int(context["campaign"]["revision"])
    preview, command = operations.preview_qin_command_offer_scale_repair(
        "repair-qin-command-scale-test",
        revision,
        offer_ref,
    )
    assert preview["status"] in {"ready", "ready_execute_only"}
    assert command.actor_id == "internal:sword-autonomy"
    assert command.mode == "maintenance"
    assert command.command_type == "repair"
    assert command.payload["path"] == "state/player.json"
    assert set(command.payload["changes"]) == {"career_state"}
    repaired = command.payload["changes"]["career_state"]["pending_qin_command_offers"][offer_ref]
    assert repaired["personnel"] == 1000
    receipt = operations.execute_qin_command_offer_scale_repair(command)
    assert receipt["status"] == "committed"
    refreshed = operations.play_context()
    assert refreshed["campaign"]["revision"] == revision + 1
    assert refreshed["campaign"]["world_time"] == context["campaign"]["world_time"]
    sheet = operations.person_sheet("char_tang_wei")["person"]
    current = sheet["career_state"]["pending_qin_command_offers"][offer_ref]
    assert current["personnel"] == 1000
    assert current["parent_personnel"] == 8000
    assert sheet["career_state"]["offer_scale_repairs"][-1]["from_personnel"] == 8000
    assert sheet["career_state"]["offer_scale_repairs"][-1]["to_personnel"] == 1000
