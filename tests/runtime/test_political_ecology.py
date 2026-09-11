from __future__ import annotations

import copy

from sword_runtime.political_ecology import (
    _autonomous_recruitment_candidate,
    faction_member_influence,
    join_faction,
    leave_faction,
    split_faction,
)


def test_seeded_faction_members_are_exact_and_influence_is_derived(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    planner = ProductionCampaignPlanner(campaign)
    host = {"owner_ref": "faction_qin_noble_patrons"}
    planner._autonomy_faction(host, 1, "244-BCE-09-01T00:00:00+08:00")
    doc = planner.read("state/factions/faction_qin_noble_patrons.json")
    assert doc["membership_initialized"] is True
    assert "char_ryo_fui" in doc["person_member_refs"]
    assert "house_ryo_fui_household" in doc["house_member_refs"]
    derived = doc["derived_member_influence"]
    assert derived["person_member_count"] >= 1
    assert derived["house_member_count"] >= 1
    assert derived["total_points"] > 0
    assert "force_ref" not in doc and "treasury_ref" not in doc and "estate_ref" not in doc


def test_join_and_leave_reclassify_membership_without_assets(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    planner = ProductionCampaignPlanner(campaign)
    before_person = copy.deepcopy(planner.read(planner.owner_path("char_tou")))
    join_faction(planner, faction_ref="faction_qin_court_reform", member_ref="char_tou", member_kind="person", at="244-BCE-09-02T00:00:00+08:00", basis="test coalition choice")
    assert "char_tou" in planner.read("state/factions/faction_qin_court_reform.json")["person_member_refs"]
    assert planner.read(planner.owner_path("char_tou")) == before_person
    leave_faction(planner, faction_ref="faction_qin_court_reform", member_ref="char_tou", at="244-BCE-09-03T00:00:00+08:00", basis="test coalition exit")
    assert "char_tou" not in planner.read("state/factions/faction_qin_court_reform.json")["person_member_refs"]
    assert planner.read(planner.owner_path("char_tou")) == before_person


def test_split_transfers_members_and_resources_without_cloning(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    planner = ProductionCampaignPlanner(campaign)
    path = "state/factions/faction_qin_frontier_officers.json"
    doc = copy.deepcopy(planner.read(path))
    doc["person_member_refs"] = ["char_ousen", "char_duke_hyou", "char_tou", "char_kanki"]
    doc["resources"] = {"influence": 40, "funds_silver": 100}
    doc["membership_initialized"] = True
    planner.put(path, doc)
    before_members = set(doc["person_member_refs"])
    before_influence = doc["resources"]["influence"]
    before_funds = doc["resources"]["funds_silver"]
    new_ref = split_faction(planner, faction_ref="faction_qin_frontier_officers", at="244-BCE-09-04T00:00:00+08:00", basis="test fracture")
    assert new_ref
    source = planner.read(path); child = planner.read(planner.owner_path(new_ref))
    assert set(source["person_member_refs"]).isdisjoint(set(child["person_member_refs"]))
    assert set(source["person_member_refs"]) | set(child["person_member_refs"]) == before_members
    assert source["resources"]["influence"] + child["resources"]["influence"] == before_influence
    assert source["resources"]["funds_silver"] + child["resources"]["funds_silver"] == before_funds
    assert "force_ref" not in child and "treasury_ref" not in child and "estate_ref" not in child


def test_autonomous_faction_recruitment_adds_one_existing_fitted_member(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    ref = "faction_qin_frontier_officers"
    path = planner.owner_path(ref)
    before = copy.deepcopy(planner.read(path))
    before["membership_initialized"] = True
    before["cohesion"] = 60
    before.pop("last_autonomous_recruitment_at", None)
    planner.put(path, before)
    existing = set(before.get("person_member_refs", [])) | set(before.get("house_member_refs", []))

    planner._autonomy_faction({"owner_ref": ref}, 1, "244-BCE-12-10T00:00:00+08:00")
    after = planner.read(path)
    recruit = after.get("last_autonomous_recruitment")
    assert isinstance(recruit, dict)
    assert recruit["member_ref"] not in existing
    assert recruit["member_ref"] != "char_tang_wei"
    assert recruit["fit_score"] >= 10
    assert recruit["evidence"]
    if recruit["member_kind"] == "person":
        assert recruit["member_ref"] in after["person_member_refs"]
    else:
        assert recruit["member_ref"] in after["house_member_refs"]
    assert planner.owner_path(recruit["member_ref"])


def test_stale_alignment_index_cannot_recruit_foreign_house_into_state_faction(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    planner = ProductionCampaignPlanner(campaign); planner._reset()
    faction_ref = "faction_qin_frontier_officers"
    faction = copy.deepcopy(planner.read(planner.owner_path(faction_ref)))
    faction.pop("last_autonomous_recruitment_at", None)
    profiles = planner.read("game/data/politics/faction-profiles.json")["profiles"]
    profile = profiles[faction_ref]

    foreign_ref = "house_karin_house"
    assert planner.read(planner.owner_path(foreign_ref))["state"] == "chu"
    idx = copy.deepcopy(planner.read("state/index/faction-alignment-candidates.json"))
    idx.setdefault("by_state", {})["qin"] = {"person_refs": [], "house_refs": [foreign_ref]}
    planner.put("state/index/faction-alignment-candidates.json", idx)

    assert _autonomous_recruitment_candidate(
        planner, faction_ref, faction, profile, "244-BCE-12-10T00:00:00+08:00"
    ) is None
