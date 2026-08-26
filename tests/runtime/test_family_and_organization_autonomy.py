from __future__ import annotations

import copy
from pathlib import Path

from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime


def _planner(root: Path) -> ProductionCampaignPlanner:
    p = ProductionCampaignPlanner(root)
    p.PLAYER_ACTOR = "char_tang_wei"
    p._reset()
    return p


def test_npc_courtship_requires_saved_mutual_evidence_and_never_accepts_for_player(campaign: Path):
    p = _planner(campaign)
    a, b = "char_bajio", "char_yotanwa"
    ap, adoc = p._exact_person(a, active=False)
    bp, bdoc = p._exact_person(b, active=False)
    adoc, bdoc = copy.deepcopy(adoc), copy.deepcopy(bdoc)
    # Existing-person, exact co-location.  The autonomy layer still needs saved
    # relationship evidence; proximity alone does not create romance.
    p._set_person_location(adoc, "loc_gyou")
    p._set_person_location(bdoc, "loc_gyou")
    p.put(ap, adoc); p.put(bp, bdoc)
    rel = copy.deepcopy(p.read("state/relationships.json"))
    rel.setdefault("edges", []).extend([
        {"edge_ref":"rel.test.bajio.yotanwa.friend","source_ref":a,"target_ref":b,"kind":"friend","value":70,"dimensions":{"affection":70,"trust":65}},
        {"edge_ref":"rel.test.yotanwa.bajio.friend","source_ref":b,"target_ref":a,"kind":"friend","value":70,"dimensions":{"affection":70,"trust":65}},
    ])
    p.put("state/relationships.json", rel)
    at = str(p._world_time())
    p._autonomy_person({"owner_ref": a}, 1, at)
    idx = p.read("state/family/index.json")
    proposals = list(idx.get("proposals", {}))
    assert len(proposals) == 1
    proposal_ref = proposals[0]
    proposal = p.read(idx["proposals"][proposal_ref])
    assert proposal["proposer_id"] == a and proposal["target_id"] == b
    assert proposal["player_choice_required"] is False
    p._autonomy_person({"owner_ref": b}, 1, at)
    proposal = p.read(idx["proposals"][proposal_ref])
    assert proposal["status"] == "accepted"

    # Player-targeted proposals may exist, but autonomy can never accept for Wei.
    rel = copy.deepcopy(p.read("state/relationships.json"))
    rel["edges"].extend([
        {"edge_ref":"rel.test.bajio.wei.friend","source_ref":a,"target_ref":"char_tang_wei","kind":"friend","value":80,"dimensions":{"affection":80,"trust":80}},
        {"edge_ref":"rel.test.wei.bajio.friend","source_ref":"char_tang_wei","target_ref":a,"kind":"friend","value":80,"dimensions":{"affection":80,"trust":80}},
    ])
    p.put("state/relationships.json", rel)
    proposal_to_player = p._family_create_autonomous_proposal(a, "char_tang_wei", "rel.test.bajio.wei.friend", at)
    assert p._family_accept_autonomous_proposal(proposal_to_player, "char_tang_wei", at) is None


def test_autonomous_npc_betrothal_can_mature_after_real_elapsed_time(campaign: Path):
    p = _planner(campaign)
    a, b = "char_bajio", "char_yotanwa"
    ap, adoc = p._exact_person(a, active=False); bp, bdoc = p._exact_person(b, active=False)
    adoc, bdoc = copy.deepcopy(adoc), copy.deepcopy(bdoc)
    p._set_person_location(adoc, "loc_gyou"); p._set_person_location(bdoc, "loc_gyou")
    p.put(ap, adoc); p.put(bp, bdoc)
    rel = copy.deepcopy(p.read("state/relationships.json"))
    rel.setdefault("edges", []).extend([
        {"edge_ref":"rel.test.bajio.yotanwa.friend2","source_ref":a,"target_ref":b,"kind":"friend","value":75,"dimensions":{"affection":75,"trust":70}},
        {"edge_ref":"rel.test.yotanwa.bajio.friend2","source_ref":b,"target_ref":a,"kind":"friend","value":75,"dimensions":{"affection":75,"trust":70}},
    ])
    p.put("state/relationships.json", rel)
    at = str(p._world_time())
    proposal = p._family_create_autonomous_proposal(a,b,"rel.test.bajio.yotanwa.friend2",at)
    union = p._family_accept_autonomous_proposal(proposal,b,at)
    assert union
    later = str(CampaignTime.parse(at).add_days(91))
    assert p._family_mature_betrothal(min(a,b), later) == union
    idx = p.read("state/family/index.json")
    assert p.read(idx["unions"][union])["status"] == "married"


def test_generic_organization_autonomy_conserves_people_and_money(campaign: Path):
    p = _planner(campaign)
    # Inject one exact organization through its normal owner shapes so this test
    # exercises only the autonomous review, not the player founding transaction.
    ref = "organization_test_autonomy"
    path = "state/organizations/organization_test_autonomy.json"
    treasury_ref = "treasury_organization_test_autonomy"
    treasury_path = "state/treasury/treasury-organization_test_autonomy.json"
    org = {"schema":"sword-independent-organization","owner_id":ref,"name":"Test Guild","organization_class":"guild","state":"qin","location_ref":"loc_gyou","status":"active","capacity":8,"population_owned":0,"treasury_ref":treasury_ref,"member_refs":["char_bajio"],"leader_refs":[],"candidate_refs":["char_yotanwa"],"linked_force_refs":[],"policies":{"auto_admit_candidates":True},"projects":[]}
    treasury = {"schema":"treasury","owner_id":treasury_ref,"owner_type":"independent_organization","silver":500,"food_kg":0,"fodder_kg":0,"stable_monthly_flows":{},"monthly_flow_components":{},"runtime":{}}
    p.put(path,org); p.put(treasury_path,treasury); p._register_owner(ref,path); p._register_owner(treasury_ref,treasury_path)
    idx = copy.deepcopy(p.read("state/organizations/index.json")); idx.setdefault("organizations",{})[ref]=path; idx.setdefault("active_refs",[]).append(ref); p.put("state/organizations/index.json",idx)
    before_pop = int(p.read("state/population/qin.json")["population_total"])
    p._autonomy_institution({"owner_ref":ref,"organization_lifecycle":True},1,str(p._world_time()))
    after = p.read(path); after_treasury = p.read(treasury_path)
    assert set(after["member_refs"]) == {"char_bajio","char_yotanwa"}
    assert after["leader_refs"]
    assert int(after_treasury["silver"]) < 500
    assert int(p.read("state/population/qin.json")["population_total"]) == before_pop
