from __future__ import annotations

import copy

from sword_runtime.causal_event_store import get_causal_event
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
    assert int(settled["personnel"]) == before_personnel
    assert settled["administrative_owner"] == before_owner
    assert "soldiers" not in loyalty


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
