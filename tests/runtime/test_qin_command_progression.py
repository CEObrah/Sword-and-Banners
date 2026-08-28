from __future__ import annotations

import copy

from sword_runtime.causal_event_store import get_causal_event
from sword_runtime.player_story_flow import _event_owner_write
from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.qin_command_progression import (
    assume_probationary_command,
    command_scale_ceiling,
    command_scale_ceiling_from_player,
    normalize_new_qin_offers,
    probationary_offer_details,
    settle_probationary_reply,
)

OFFER_REF = "event_test_qin_oversized_first_command"
PARENT_REF = "formation_qin_mobile_reserve"
OPERATION_REF = "operation_arc_73745d7ca38d929e0e"


def _ensure_operation_fixture(planner, at):
    """Install a disposable Qin operation independent of the live campaign snapshot."""
    operation_path = "state/operations/operation_test_qin_probationary_command.json"
    operation_index = copy.deepcopy(planner.read("state/operations/index.json"))
    operation_index.setdefault("operations", {})[OPERATION_REF] = operation_path
    planner.put("state/operations/index.json", operation_index)
    parent = planner.read(planner.owner_path(PARENT_REF))
    planner.put(
        operation_path,
        {
            "schema": "sword-operation",
            "operation_ref": OPERATION_REF,
            "status": "active",
            "formation_refs": [PARENT_REF],
            "kind": "qin_campaign_participant_operation",
            "created_at": at,
            "location_ref": str(parent.get("location_ref", "loc_qin_regional_01")),
            "institutional_owner_ref": "state_qin",
            "administrative_authority": "state_qin",
            "assignment_authority_ref": "state_qin",
            "source_force_ref": "force_state_qin",
            "objective_refs": ["arc_ryo_fui_northern_wei_campaign", "state_wei"],
            "objective": "Synthetic probationary-command regression operation.",
        },
    )


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    return planner


def _oversized_details(planner, *, personnel=5000):
    parent = planner.read(planner.owner_path(PARENT_REF))
    return {
        "arc_ref": "arc_ryo_fui_northern_wei_campaign",
        "candidate_score": 733,
        "formation_name": str(parent.get("name", "QIN Mobile Reserve")),
        "formation_ref": PARENT_REF,
        "institution_ref": "inst_qin_military_bureau",
        "location_ref": str(parent.get("location_ref", "loc_qin_regional_01")),
        "offered_at": str(planner.read("state/runtime.json")["world_time"]),
        "operation_ref": OPERATION_REF,
        "personnel": personnel,
        "state_ref": "state_qin",
    }


def _seed_offer(planner):
    at = str(planner.read("state/runtime.json")["world_time"])
    _ensure_operation_fixture(planner, at)
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


def _make_wei_available_for_probationary_test(planner):
    # The current campaign has Wei commanding the mixed 9,500-man Tang Wei Army.
    # This disposable fixture isolates the first-Qin-command progression law by
    # clearing his current career appointment only; he is not a leaf formation
    # commander, so no retired Qin Wei Unit needs to be resurrected or detached.
    player = copy.deepcopy(planner.read("state/player.json"))
    player["authority"] = "House Tang heir; patron and commander of Tang Wei Personal Retinue; no state office"
    career = player.setdefault("career_state", {})
    career["appointments"] = []
    career.pop("verified_qin_field_command_personnel", None)
    career["current_billet"] = "none"
    career["current_command_span"] = 0
    career["office_or_command"] = "No Qin field command in this disposable progression fixture"
    planner.put("state/player.json", player)


def _install_probationary_offer(planner):
    _make_wei_available_for_probationary_test(planner)
    offer_ref, details, at = _seed_offer(planner)
    player = copy.deepcopy(planner.read("state/player.json"))
    rules = planner.read("game/data/mechanics/career-progression.json")["qin_field_command"]
    normalized = probationary_offer_details(player, rules, offer_ref, details, at)
    player["career_state"]["pending_qin_command_offers"][offer_ref] = normalized
    planner.put("state/player.json", player)
    return offer_ref, normalized, at



def test_unproven_sixteen_year_old_is_scale_matched_to_1000(campaign):
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    player = copy.deepcopy(planner.read("state/player.json"))
    player["career_state"] = {}
    rules = planner.read("game/data/mechanics/career-progression.json")["qin_field_command"]
    details = _oversized_details(planner, personnel=5000)
    normalized = probationary_offer_details(player, rules, OFFER_REF, details, at)
    assert command_scale_ceiling_from_player(player, rules, at) == 1000
    assert normalized["offer_kind"] == "qin_probationary_detachment_command"
    assert normalized["personnel"] == 1000
    assert normalized["parent_formation_ref"] == PARENT_REF
    assert normalized["parent_personnel"] == 5000
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
    offer_ref, normalized, at = _install_probationary_offer(planner)
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
    offer_ref, normalized, at = _install_probationary_offer(planner)
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
