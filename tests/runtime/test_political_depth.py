from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest


def planner_for(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    return ProductionCampaignPlanner(campaign)


def install_test_polity(planner, ref="polity_political_depth_test"):
    path=f"state/politics/polities/{ref}.json"
    doc={
        "schema":"sword-polity","owner_id":ref,"polity_ref":ref,"name":"Political Depth Test Polity",
        "sovereign_house_ref":"house_tang","status":"recognized_state","recognition_status":"recognized","recognized_by":["state_qin"],
        "treasury_ref":"treasury_house_tang","military_force_refs":["force_house_tang"],"military_authority_refs":["house_tang"],
        "occupied_site_refs":["loc_gyou"],"seat_claim_ref":"loc_gyou","administrative_capacity":80,
        "known_threats":{},"diplomacy":{},"court_case_refs":[],"market_access_refs":[],
    }
    planner.put(path,doc); planner._register_owner(ref,path)
    territory=copy.deepcopy(planner.read("state/territory/control.json")); territory["sites"]["loc_gyou"]["controller"]=ref; planner.put("state/territory/control.json",territory)
    return ref,path


def command(planner):
    meta=planner.read("state/meta.json")
    return SimpleNamespace(actor_id=planner.PLAYER_ACTOR, expected_revision=int(meta["revision"]), command_type="polity_action", digest="political-depth-test", submitted_at=str(meta["time"]), mode="gameplay")


def install_evidence(planner, ref, subject_ref, *, confidence=900, origin="runtime_established", evidence_refs=None):
    path=f"state/information/{ref}.json"
    doc={
        "schema":"sword-information","owner_id":ref,"information_ref":ref,"subject_ref":subject_ref,
        "fact":f"Exact test evidence about {subject_ref}","claim":f"Exact test evidence about {subject_ref}",
        "epistemic_kind":"observation","confidence_milli":confidence,"confidence":f"{confidence/1000:.3f}",
        "provenance":"test_runtime_evidence" if origin=="runtime_established" else "player_assertion",
        "evidence_refs":list(evidence_refs or []),"classification":"ordinary","location_ref":"loc_gyou","discoverability_milli":300,
        "investigation_discoverable":origin=="runtime_established","origin_authority":origin,"world_truth_authority":False,
        "claim_status":"runtime_established" if origin=="runtime_established" else "unverified_claim",
        "knowers":[planner.PLAYER_ACTOR],"holder_states":{},"deliveries":[],"created_at":str(planner._world_time()),
    }
    planner.put(path,doc); planner._register_owner(ref,path)
    return ref


def test_court_admits_exact_evidence_and_keeps_finding_separate_from_judgment(campaign):
    p=planner_for(campaign); p._reset(); polity_ref,_=install_test_polity(p)
    opened=p._dispatch_polity_action(command(p),{"polity_ref":polity_ref,"action":"open_court_case","case_kind":"corruption","subject_ref":"char_hyou","location_ref":"loc_gyou"})
    case_ref=opened["case_ref"]
    evidence_ref=install_evidence(p,"information_court_depth_hyou","char_hyou",confidence=920,evidence_refs=["physical_record:test"])
    admitted=p._dispatch_polity_action(command(p),{"polity_ref":polity_ref,"action":"submit_court_evidence","case_ref":case_ref,"evidence_refs":[evidence_ref]})
    assessment=admitted["evidentiary_assessment"]
    assert evidence_ref in assessment["unique_information_refs"]
    assert assessment["admissible_evidence_weight"] > 0
    assert assessment["objective_fact_status"] == "not_created_or_overwritten_by_court_assessment"

    case_path=p.owner_path(case_ref); case=p.read(case_path)
    for expected in ("investigating","hearing","decision_required"):
        due=str(case["next_review_at"]); polity=copy.deepcopy(p.read(p.owner_path(polity_ref))); p._autonomy_polity_court(polity_ref,polity,due); case=p.read(case_path); assert case["status"]==expected
    assert "evidentiary_assessment" in case and "decision" not in case
    p._dispatch_polity_action(command(p),{"polity_ref":polity_ref,"action":"decide_court_case","case_ref":case_ref,"policy_value":"dismiss"})
    decided=p.read(case_path)
    assert decided["status"]=="dismissed"
    assert decided["judgment_evidence_relationship"]["rule"].startswith("evidentiary support and sovereign judgment are separate")


def test_court_rejects_wrong_subject_evidence_and_early_verdict(campaign):
    p=planner_for(campaign); p._reset(); polity_ref,_=install_test_polity(p)
    opened=p._dispatch_polity_action(command(p),{"polity_ref":polity_ref,"action":"open_court_case","case_kind":"legal_dispute","subject_ref":"char_hyou"})
    bad=install_evidence(p,"information_court_wrong_subject","char_riboku")
    with pytest.raises(ValueError,match="subject"):
        p._dispatch_polity_action(command(p),{"polity_ref":polity_ref,"action":"submit_court_evidence","case_ref":opened["case_ref"],"evidence_refs":[bad]})
    with pytest.raises(ValueError,match="decision_required"):
        p._dispatch_polity_action(command(p),{"polity_ref":polity_ref,"action":"decide_court_case","case_ref":opened["case_ref"],"policy_value":"uphold"})


def test_multilateral_conference_only_adds_sovereigns_that_accept(campaign):
    p=planner_for(campaign); p._reset(); polity_ref,_=install_test_polity(p)
    result=p._dispatch_polity_action(command(p),{
        "polity_ref":polity_ref,"action":"open_coalition_conference","coalition_target_ref":"state_chu",
        "invitee_refs":["state_qin","state_zhao"],"duration_days":720,
    })
    conference=p.read(p.owner_path(result["conference_ref"]))
    assert conference["accepted_member_refs"] == [polity_ref]
    assert set(conference["pending_invitee_refs"]) == {"state_qin","state_zhao"}

    # Simulate the two sovereign decisions through the existing treaty authority:
    # Qin accepts, Zhao rejects. Invitation itself creates no membership.
    qin_ref=result["proposal_refs"]["state_qin"]; qin_path=p.owner_path(qin_ref); qin=copy.deepcopy(p.read(qin_path)); qin["status"]="accepted"; qin["responded_at"]=str(p._world_time()); qin["treaty_ref"]=p._activate_diplomatic_treaty(qin,str(p._world_time())); p.put(qin_path,qin)
    zhao_ref=result["proposal_refs"]["state_zhao"]; zhao_path=p.owner_path(zhao_ref); zhao=copy.deepcopy(p.read(zhao_path)); zhao["status"]="rejected"; zhao["responded_at"]=str(p._world_time()); p.put(zhao_path,zhao)
    conference=p._sync_diplomatic_conference(result["conference_ref"],str(p._world_time()))
    assert conference["status"] == "concluded"
    assert set(conference["accepted_member_refs"]) == {polity_ref,"state_qin"}
    assert conference["declined_invitee_refs"] == ["state_zhao"]
    treaty=p.read("state/politics/treaties.json")["records"][conference["coalition_treaty_refs"][0]]
    assert set(treaty["parties"]) == {polity_ref,"state_qin"}
    assert "state_zhao" not in treaty["parties"]


def _advance_case_to_decision_required(planner, polity_ref: str, case_ref: str) -> None:
    case_path = planner.owner_path(case_ref)
    case = planner.read(case_path)
    for expected in ("investigating", "hearing", "decision_required"):
        due = str(case["next_review_at"])
        polity = copy.deepcopy(planner.read(planner.owner_path(polity_ref)))
        planner._autonomy_polity_court(polity_ref, polity, due)
        case = planner.read(case_path)
        assert case["status"] == expected


def test_court_appeal_remands_decided_case_before_physical_enforcement(campaign):
    p = planner_for(campaign); p._reset(); polity_ref, _ = install_test_polity(p)
    opened = p._dispatch_polity_action(command(p), {
        "polity_ref": polity_ref, "action": "open_court_case",
        "case_kind": "legal_dispute", "subject_ref": "char_hyou",
    })
    case_ref = opened["case_ref"]
    _advance_case_to_decision_required(p, polity_ref, case_ref)
    p._dispatch_polity_action(command(p), {
        "polity_ref": polity_ref, "action": "decide_court_case",
        "case_ref": case_ref, "policy_value": "uphold",
    })
    decided = p.read(p.owner_path(case_ref))
    assert decided["status"] == "decided"
    appealed = p._dispatch_polity_action(command(p), {
        "polity_ref": polity_ref, "action": "appeal_court_case", "case_ref": case_ref,
    })
    case = p.read(p.owner_path(case_ref))
    assert appealed["status"] == "remanded"
    assert case["stage"] == "appeal_review"
    assert len(case["appeals"]) == 1
    assert case["appeals"][0]["prior_decision"]["value"] == "uphold"
    assert "enforcement" not in case


def test_court_office_removal_enforcement_changes_exact_polity_and_person_history(campaign):
    p = planner_for(campaign); p._reset(); polity_ref, polity_path = install_test_polity(p)
    polity = copy.deepcopy(p.read(polity_path))
    polity["officeholders"] = {
        "steward": {
            "person_ref": "char_hyou", "office": "steward",
            "polity_ref": polity_ref, "appointed_at": str(p._world_time()),
        }
    }
    p.put(polity_path, polity)
    opened = p._dispatch_polity_action(command(p), {
        "polity_ref": polity_ref, "action": "open_court_case",
        "case_kind": "corruption", "subject_ref": "char_hyou",
    })
    case_ref = opened["case_ref"]
    _advance_case_to_decision_required(p, polity_ref, case_ref)
    p._dispatch_polity_action(command(p), {
        "polity_ref": polity_ref, "action": "decide_court_case",
        "case_ref": case_ref, "policy_value": "remove_office",
    })
    result = p._dispatch_polity_action(command(p), {
        "polity_ref": polity_ref, "action": "enforce_court_case",
        "case_ref": case_ref, "remedy_kind": "office_removal",
        "person_ref": "char_hyou", "office_key": "steward",
    })
    polity = p.read(polity_path)
    case = p.read(p.owner_path(case_ref))
    _, person = p._exact_person("char_hyou", active=False)
    assert "steward" not in polity.get("officeholders", {})
    assert result["enforcement"]["status"] == "completed"
    assert case["enforcement"]["effect"]["kind"] == "office_removed"
    removals = [x for x in person.get("career_state", {}).get("appointments", []) if x.get("kind") == "office_removal"]
    assert removals and removals[-1]["legal_basis_ref"] == case_ref
