from __future__ import annotations

import copy

from sword_runtime.api.maintenance_operations import QinCommandMaintenanceOperations
from sword_runtime.causal_event_store import get_causal_event
from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.qin_command_progression import (
    assume_probationary_command,
    command_scale_ceiling,
    normalize_new_qin_offers,
    repaired_offer_details,
    settle_probationary_reply,
)
from sword_runtime.service_runtime import ProductionSwordRuntime


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    return planner


def _pending_offer(planner):
    player = planner.read("state/player.json")
    career = player["career_state"]
    offer_ref = career["pending_qin_command_offer_refs"][0]
    return offer_ref, career["pending_qin_command_offers"][offer_ref]


def _install_repaired_offer(planner):
    at = str(planner.read("state/runtime.json")["world_time"])
    player = copy.deepcopy(planner.read("state/player.json"))
    offer_ref, details = _pending_offer(planner)
    rules = planner.read("game/data/mechanics/career-progression.json")["qin_field_command"]
    normalized = repaired_offer_details(player, rules, offer_ref, details, at)
    player["career_state"]["pending_qin_command_offers"][offer_ref] = normalized
    planner.put("state/player.json", player)
    return offer_ref, normalized, at


def test_unproven_sixteen_year_old_is_scale_matched_to_1000(campaign):
    planner = _planner(campaign)
    offer_ref, normalized, at = _install_repaired_offer(planner)
    assert command_scale_ceiling(planner, at) == 1000
    assert normalized["offer_kind"] == "qin_probationary_detachment_command"
    assert normalized["personnel"] == 1000
    assert normalized["parent_formation_ref"] == "formation_qin_border_line"
    assert normalized["parent_personnel"] == 8000
    assert normalized["formation_ref"] != normalized["parent_formation_ref"]
    assert offer_ref.startswith("event_story_qin_command_offer_")


def test_new_offer_rewrite_preserves_schema_strict_provenance(campaign):
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    offer_ref, _ = _pending_offer(planner)
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
    assert int(planner.read(parent_path)["personnel"]) == before == 8000
    player = planner.read("state/player.json")
    appointment = next(row for row in player["career_state"]["appointments"] if row.get("source_event_ref") == offer_ref)
    assert appointment["status"] == "awaiting_assumption"
    assert appointment["personnel"] == 1000
    assert planner.read_optional(f"state/formations/{appointment['formation_ref'].removeprefix('formation_').replace('_', '-')}.json") is None


def test_assumption_splits_8000_to_7000_plus_1000_and_keeps_qin_ownership(campaign):
    planner = _planner(campaign)
    offer_ref, normalized, at = _install_repaired_offer(planner)
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
    parent = planner.read(planner.owner_path(normalized["parent_formation_ref"]))
    appointment = next(row for row in planner.read("state/player.json")["career_state"]["appointments"] if row.get("source_event_ref") == offer_ref)
    child = planner.read(planner.owner_path(appointment["formation_ref"]))
    assert parent["personnel"] == 7000
    assert child["personnel"] == 1000
    assert parent["personnel"] + child["personnel"] == 8000
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
    runtime = ProductionSwordRuntime(campaign, tmp_path / "runtime")
    operations = QinCommandMaintenanceOperations(runtime)
    context = operations.play_context()
    revision = int(context["campaign"]["revision"])
    player = runtime.store.read_json("state/player.json")
    offer_ref = player["career_state"]["pending_qin_command_offer_refs"][0]
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
    assert "1000-man detachment" in refreshed["pending_wake"]["reason"]
    sheet = operations.person_sheet("char_tang_wei")["person"]
    current = sheet["career_state"]["pending_qin_command_offers"][offer_ref]
    assert current["personnel"] == 1000
    assert sheet["career_state"]["offer_scale_repairs"][-1]["from_personnel"] == 8000
