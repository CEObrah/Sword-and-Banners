from __future__ import annotations

import copy

from sword_runtime.causal_event_store import get_causal_event
from sword_runtime.history_store import write_history_index
from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    return planner


def test_military_career_routing_uses_scheduler_known_people_without_global_scans(campaign):
    planner = _planner(campaign)
    before = copy.deepcopy(planner.read("state/runtime.json"))
    planner._ensure_military_career_routes()
    runtime = planner.read("state/runtime.json")
    military_hosts = [host for host in runtime["hosts"].values() if isinstance(host, dict) and host.get("kind") == "military_career"]
    assert military_hosts
    routed = {ref for host in military_hosts for ref in host.get("routed_person_refs", [])}
    assert "char_ouki" in routed
    assert len(routed) == len(set(routed))
    assert all(
        runtime["metrics"][key] == before["metrics"][key]
        for key in ("global_person_scans", "global_faction_scans", "global_force_scans", "global_house_scans")
    )


def test_commander_dossiers_are_general_and_player_not_special_cased(campaign):
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    planner._settle_person_career("char_ouki", at)
    planner._settle_person_career("char_tang_wei", at)
    network = planner.read("state/military/career-network/index.json")
    assert "char_ouki" in network["commanders"]
    assert "char_tang_wei" in network["commanders"]
    ouki = planner.read(network["commanders"]["char_ouki"])
    wei = planner.read(network["commanders"]["char_tang_wei"])
    assert ouki["schema"] == wei["schema"] == "sword-commander-career-dossier.v1"
    assert ouki["authority"] is False and wei["authority"] is False
    player = planner.read("state/player.json")
    assert not player.get("military_career_state", {}).get("active_petition_refs")


def test_transfer_interest_creates_petition_and_never_teleports_officer(campaign):
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    path, original = planner._exact_person("char_ouki", active=False)
    person = copy.deepcopy(dict(original))
    before_location = person.get("current_location", person.get("location"))
    before_formation = person.get("current_formation_id")
    petition_ref = planner._create_petition(
        person,
        state_ref="state_qin",
        desired_commander_ref="char_tang_wei",
        request_kind="campaign_attachment",
        attraction_milli=900,
        evidence_refs=[],
        at=at,
    )
    assert petition_ref
    planner.put(path, person)
    petition = planner.read(planner._petition_path(petition_ref))
    assert petition["status"] == "submitted"
    after = planner.read(path)
    assert after.get("current_location", after.get("location")) == before_location
    assert after.get("current_formation_id") == before_formation

    review_at = str(CampaignTime.parse(at).add_days(15))
    planner._settle_petitions("state_qin", review_at)
    petition = planner.read(planner._petition_path(petition_ref))
    assert petition["status"] == "awaiting_commander_response"
    assert petition["institutional_decision"] == "approved_subject_to_prospective_commander_response"
    assert get_causal_event(planner, petition["delivered_event_ref"])["target_ref"] == "char_tang_wei"
    after_review = planner.read(path)
    assert after_review.get("current_formation_id") == before_formation


def test_resolved_petition_reference_does_not_permanently_latch_officer(campaign):
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    path, original = planner._exact_person("char_ouki", active=False)
    person = copy.deepcopy(dict(original))
    petition_ref = planner._create_petition(
        person,
        state_ref="state_qin",
        desired_commander_ref="char_tang_wei",
        request_kind="campaign_attachment",
        attraction_milli=900,
        evidence_refs=[],
        at=at,
    )
    assert petition_ref
    planner.put(path, person)
    petition_path = planner._petition_path(petition_ref)
    petition = copy.deepcopy(planner.read(petition_path))
    petition["status"] = "rejected"
    planner.put(petition_path, petition)
    persisted = planner.read(path)
    assert petition_ref in persisted["military_career_state"]["active_petition_refs"]
    assert planner._active_petition_refs(persisted) == []


def test_cross_state_service_is_not_treated_as_ordinary_transfer(campaign):
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    network = planner._career_network()
    dossier_path = "state/military/career-network/commanders/char_test_zhao_general.json"
    planner.put(dossier_path, {
        "schema": "sword-commander-career-dossier.v1",
        "authority": False,
        "commander_ref": "char_test_zhao_general",
        "state_ref": "state_zhao",
        "formation_ref": None,
        "command_scale": 10000,
        "public_reputation_milli": 900,
        "institutional_reputation_milli": 900,
        "casualty_stewardship_milli": 800,
        "logistics_reliability_milli": 800,
        "promotion_opportunity_milli": 800,
        "political_risk_milli": 200,
        "evidence_refs": [],
        "published_at": at,
        "public_summary": "A distinguished Zhao general.",
    })
    network.setdefault("commanders", {})["char_test_zhao_general"] = dossier_path
    planner.put("state/military/career-network/index.json", network)

    person_path, original = planner._exact_person("char_ouki", active=False)
    person = copy.deepcopy(dict(original))
    person["military_loyalty_state"] = {
        "schema": "sword-named-military-loyalty.v1",
        "state_ref": "state_qin",
        "state_allegiance_milli": 900,
        "institutional_professional_milli": 900,
        "formation_bond_milli": 500,
        "legitimacy_belief_milli": 800,
        "commander_bonds": {},
        "house_patron_bonds": {},
        "resentment_by_person": {},
        "recent_memory": [],
    }
    petition_ref = planner._create_petition(
        person,
        state_ref="state_qin",
        desired_commander_ref="char_test_zhao_general",
        request_kind="permanent_transfer",
        attraction_milli=900,
        evidence_refs=[],
        at=at,
    )
    assert petition_ref
    planner.put(person_path, person)
    review_at = str(CampaignTime.parse(at).add_days(15))
    planner._settle_petitions("state_qin", review_at)
    petition = planner.read(planner._petition_path(petition_ref))
    assert petition["request_kind"] == "foreign_service_request"
    assert petition["desired_state_ref"] == "state_zhao"
    assert petition["attraction_milli"] == 540
    assert planner.read(person_path).get("state") == original.get("state")


def test_formation_loyalty_is_cohort_scale_and_preserves_ownership_and_manpower(campaign):
    planner = _planner(campaign)
    path, original = planner._load_formation("formation_qin_border_line")
    formation = copy.deepcopy(dict(original))
    before_personnel = int(formation["personnel"])
    before_owner = formation["administrative_owner"]
    formation["commander_ref"] = "char_ouki"
    planner.put(path, formation)
    at = str(planner.read("state/runtime.json")["world_time"])
    planner._update_formation_loyalty("formation_qin_border_line", at)
    settled = planner.read(path)
    loyalty = settled["military_loyalty_state"]
    assert loyalty["schema"] == "sword-formation-loyalty.v1"
    assert "commander_bonds" in loyalty and "char_ouki" in loyalty["commander_bonds"]
    assert "state_allegiance" in loyalty["axes"]
    assert "formation_identity" in loyalty["axes"]
    assert "allegiance_distribution" in loyalty
    assert int(settled["personnel"]) == before_personnel
    assert settled["administrative_owner"] == before_owner
    assert "soldiers" not in loyalty


def test_causal_battle_memory_changes_loyalty_without_changing_manpower(campaign):
    planner = _planner(campaign)
    path, original = planner._load_formation("formation_qin_border_line")
    formation = copy.deepcopy(dict(original))
    formation["commander_ref"] = "char_ouki"
    planner.put(path, formation)
    at = str(planner.read("state/runtime.json")["world_time"])
    planner._update_formation_loyalty("formation_qin_border_line", at)
    before = copy.deepcopy(planner.read(path))
    before_loyalty = before["military_loyalty_state"]
    before_bond = int(before_loyalty["commander_bonds"]["char_ouki"])
    before_disaffection = int(before_loyalty["axes"]["disaffection"])

    history = copy.deepcopy(planner.read("state/history/events/index.json"))
    history["events"].append({
        "at": at,
        "event_id": "event_test_loyalty_catastrophic_loss",
        "kind": "battle_result",
        "summary": "formation_qin_border_line suffered catastrophic mass casualty losses after being sacrificed in a failed withdrawal.",
    })
    write_history_index(planner, history)
    planner._update_formation_loyalty("formation_qin_border_line", at)
    after = planner.read(path)
    after_loyalty = after["military_loyalty_state"]
    assert int(after_loyalty["commander_bonds"]["char_ouki"]) < before_bond
    assert int(after_loyalty["axes"]["disaffection"]) > before_disaffection
    assert any(row.get("event_ref") == "event_test_loyalty_catastrophic_loss" for row in after_loyalty["recent_memory"])
    assert after["personnel"] == before["personnel"]
    assert after["administrative_owner"] == before["administrative_owner"]
    assert after["owner_force_ref"] == before["owner_force_ref"]


def test_crisis_allegiance_uses_immediate_officers_and_never_changes_ownership(campaign):
    planner = _planner(campaign)
    path, original = planner._load_formation("formation_qin_border_line")
    formation = copy.deepcopy(dict(original))
    formation["commander_ref"] = "char_ouki"
    planner.put(path, formation)
    at = str(planner.read("state/runtime.json")["world_time"])
    planner._update_formation_loyalty("formation_qin_border_line", at)
    before = copy.deepcopy(planner.read(path))
    low = planner.evaluate_formation_allegiance(
        "formation_qin_border_line",
        proposed_commander_ref="char_ouki",
        order_legitimacy_milli=150,
        immediate_officer_support_milli=100,
    )
    high = planner.evaluate_formation_allegiance(
        "formation_qin_border_line",
        proposed_commander_ref="char_ouki",
        order_legitimacy_milli=150,
        immediate_officer_support_milli=900,
    )
    assert high["follow_proposed_commander_milli"] > low["follow_proposed_commander_milli"]
    assert high["administrative_ownership_changed"] == 0
    after = planner.read(path)
    assert after["administrative_owner"] == before["administrative_owner"]
    assert after["owner_force_ref"] == before["owner_force_ref"]
    assert after["personnel"] == before["personnel"]


def test_independent_command_pressure_is_reachable_for_elite_officers(campaign):
    planner = _planner(campaign)
    _path, ouki = planner._exact_person("char_ouki", active=False)
    prefs = planner._career_preferences(ouki)
    threshold = int(planner._military_rules()["career_review"]["independence_threshold_milli"])
    assert prefs["independence"] >= threshold
