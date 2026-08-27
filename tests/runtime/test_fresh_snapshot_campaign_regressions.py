from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from sword_runtime.campaign_briefing import build_campaign_dossier, ensure_actionable_mission_packet, render_campaign_briefing
from sword_runtime.production_runtime_planner import ProductionCampaignPlanner


OPERATION_REF = "operation_arc_131572c4e8a2892bbc"
PEER_OPERATIONS = {
    "operation_qin_mou_gou_northern_wei_campaign": 73_200,
    "operation_qin_ouki_northern_wei_campaign": 46_100,
    "operation_qin_mou_bu_northern_wei_campaign": 40_000,
    "operation_qin_mobile_reserve_northern_wei_campaign": 5_000,
    "operation_qin_eastern_reserve_northern_wei_campaign": 3_000,
}


def _planner(campaign: Path) -> ProductionCampaignPlanner:
    planner = ProductionCampaignPlanner(campaign)
    planner.PLAYER_ACTOR = "char_tang_wei"
    planner._reset()
    return planner


def _campaign_operation(planner: ProductionCampaignPlanner) -> dict:
    path = planner.read("state/operations/index.json")["operations"][OPERATION_REF]
    return planner.read(path)


def test_fresh_snapshot_restores_full_qin_campaign_roster(campaign):
    planner = _planner(campaign)
    dossier = build_campaign_dossier(planner, OPERATION_REF)

    assert dossier["own"]["strength"] == 9_500
    assert dossier["own"]["assigned_strength"] == 5_000
    assert dossier["own"]["auxiliary_strength"] == 4_500
    assert dossier["friendly_total_strength"] == 176_800

    peers = {row["operation_ref"]: row for row in dossier["other_friendly_participants"]}
    assert set(peers) == set(PEER_OPERATIONS)
    assert {ref: row["strength"] for ref, row in peers.items()} == PEER_OPERATIONS

    commander_names = {
        name
        for row in peers.values()
        for name in [entry.get("name") for entry in row.get("commanders", [])]
        if name
    }
    assert {"Kanki", "Mou Gou", "Ousen", "Ouki", "Tou", "Mou Bu", "Fan Yi", "Shou Hei Kun"} <= commander_names

    operation = _campaign_operation(planner)
    order = operation["operational_orders"][-1]
    assert set(operation["campaign_participant_operation_refs"]) == set(PEER_OPERATIONS)
    assert set(order["mission_packet"]["friendly_participant_operation_refs"]) == set(PEER_OPERATIONS)



def test_completed_kanyou_staging_is_not_reopened_by_briefing_refresh(campaign):
    planner = _planner(campaign)
    before = _campaign_operation(planner)
    assert before["campaign_phase"] == "awaiting_entry_authority"
    assert before["order_status"] == "awaiting_entry_authority"
    assert len(before["operational_orders"]) == 1
    assert before["last_operational_order_ref"] == "operational_order_669dd21e8390d23c6b"
    assert before["operational_orders"][0]["status"] == "staged_awaiting_entry_authority"
    assert before["operational_orders"][0]["actionability_status"] == "completed"
    assert before["operational_orders"][0]["mission_packet"]["phase_status"] == "completed"

    dossier = build_campaign_dossier(planner, OPERATION_REF)
    packet = ensure_actionable_mission_packet(
        planner, OPERATION_REF, dossier, at="244-BCE-09-16T20:22:48+08:00"
    )
    after = _campaign_operation(planner)
    assert packet["phase_status"] == "completed"
    assert after["campaign_phase"] == "awaiting_entry_authority"
    assert after["order_status"] == "awaiting_entry_authority"
    assert len(after["operational_orders"]) == 1
    assert after["last_operational_order_ref"] == "operational_order_669dd21e8390d23c6b"
    assert after["operational_orders"][0]["status"] == "staged_awaiting_entry_authority"

    rendered = render_campaign_briefing(planner, dossier, packet)
    assert "completed its lawful staging at Kanyou" in rendered
    assert "standing orders record concentration at Kanyou as complete" in rendered
    assert "require the field command to complete its concentration at Kanyou" not in rendered

def test_campaign_roster_guard_fails_closed_if_a_saved_peer_owner_disappears(campaign):
    planner = _planner(campaign)
    missing_ref = "operation_qin_ouki_northern_wei_campaign"
    index = copy.deepcopy(planner.read("state/operations/index.json"))
    index["operations"].pop(missing_ref)
    planner.put("state/operations/index.json", index)

    with pytest.raises(ValueError, match="campaign participant roster lost exact operation owner"):
        build_campaign_dossier(planner, OPERATION_REF)


def test_current_qin_briefing_is_single_clean_claim_and_player_facing(campaign):
    root = Path(campaign)
    planner = _planner(campaign)
    dossier = build_campaign_dossier(planner, OPERATION_REF)
    operation = _campaign_operation(planner)
    rendered = render_campaign_briefing(planner, dossier, operation["operational_orders"][-1]["mission_packet"])

    assert "176,800" in rendered
    assert "9,500" in rendered
    assert "5,000 are Qin-assigned" in rendered
    assert "4,500 are House or retinue troops" in rendered
    for forbidden in (
        "actionable",
        "Executable staff packet",
        "executable packet",
        "mission packet",
        "current operation owners",
        "omniscient exact truth",
    ):
        assert forbidden.lower() not in rendered.lower()

    index = json.loads((root / "state/information/index.json").read_text())
    qin_refs = [ref for ref in index["claims"] if ref.startswith("information.qin_campaign_briefing.")]
    assert qin_refs == ["information.qin_campaign_briefing.a98b9575d13e9931a873"]
    assert not any(ref.startswith("information.campaign_phase.") for ref in index["claims"])

    info = json.loads((root / index["claims"][qin_refs[0]]).read_text())
    assert info["claim"] == rendered
    assert info["fact"] == rendered


def test_tang_ling_identity_and_mother_relationship_are_explicit(campaign):
    root = Path(campaign)
    tang_ling = json.loads((root / "state/char/tang-ling.json").read_text())
    assert tang_ling["sex"] == "female"
    assert tang_ling["pronouns"]["subject"] == "she"
    assert tang_ling["pronouns"]["object"] == "her"
    assert tang_ling["family_role"] == "mother of Tang Wei and Tang Kai"

    for child in ("tang_wei", "tang_kai"):
        parentage = json.loads((root / f"state/family/parentage/parentage.{child}.birth_parents.json").read_text())
        mother = next(row for row in parentage["parent_links"] if row["parent_id"] == "char_tang_ling")
        assert mother["kind"] == "biological"
        assert mother["relation_role"] == "mother"


def test_house_digest_distinguishes_full_establishment_from_growth_ceiling(campaign):
    root = Path(campaign)
    events = json.loads((root / "state/event/events-messages-and-movement.json").read_text())["causal_events"]
    summary = events["event_story_house_digest_c3e3670a8b3ea0d23210"]["summary"]
    assert "current authorized formations are fully manned" in summary
    assert "does not mean House Tang has reached its military growth ceiling" in summary
    assert "Further expansion can authorize additional formations" in summary
    assert "No establishment vacancies" not in summary


def test_fresh_snapshot_is_revision_one_and_has_no_superseded_qin_briefing_refs(campaign):
    root = Path(campaign)
    meta = json.loads((root / "state/meta.json").read_text())
    assert meta["revision"] == 1

    stale_tokens = (
        "information.qin_campaign_briefing.b4554e2a86b4c3edae39",
        "information.qin_campaign_briefing.6a750937c71138b6b974",
        "actionable staging packet",
    )
    state_files = [
        root / "state/information/index.json",
        root / "state/information/subject-index.json",
        root / "state/history/events/index.json",
        root / "state/event/events-messages-and-movement.json",
    ]
    combined = "\n".join(path.read_text() for path in state_files)
    for token in stale_tokens:
        assert token not in combined


def test_fresh_snapshot_peer_campaign_operations_only_use_mobilized_formations(campaign: Path) -> None:
    operation_index = json.loads((campaign / "state/operations/index.json").read_text(encoding="utf-8"))["operations"]
    owners = json.loads((campaign / "state/index/owner-index.json").read_text(encoding="utf-8"))["owners"]
    for operation_ref in PEER_OPERATIONS:
        operation = json.loads((campaign / operation_index[operation_ref]).read_text(encoding="utf-8"))
        assert operation["status"] in {"active", "mobilizing"}
        for formation_ref in operation["formation_refs"]:
            formation = json.loads((campaign / owners[formation_ref]).read_text(encoding="utf-8"))
            assert formation["mobilized"] is True, (operation_ref, formation_ref)


def test_fresh_snapshot_active_peer_operations_are_co_located(campaign: Path) -> None:
    operation_index = json.loads((campaign / "state/operations/index.json").read_text(encoding="utf-8"))["operations"]
    owners = json.loads((campaign / "state/index/owner-index.json").read_text(encoding="utf-8"))["owners"]
    for operation_ref in PEER_OPERATIONS:
        operation = json.loads((campaign / operation_index[operation_ref]).read_text(encoding="utf-8"))
        if operation["status"] != "active":
            continue
        locations = set()
        for formation_ref in operation["formation_refs"]:
            formation = json.loads((campaign / owners[formation_ref]).read_text(encoding="utf-8"))
            locations.add(formation["location_ref"])
        assert locations == {operation["location_ref"]}, (operation_ref, locations, operation["location_ref"])
