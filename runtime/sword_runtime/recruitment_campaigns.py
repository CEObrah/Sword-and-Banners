"""High-resolution aggregate recruitment campaigns for player-relevant selection.

Candidate pools reserve real population bodies but never materialize thousands of
NPCs. Registered background mixtures establish starting distributions; registered
selection profiles condition those distributions. Only final acceptance transfers
survivors into military manpower/cohorts.
"""
from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, MutableMapping
from copy import deepcopy
from typing import Any

from sword_runtime.cohort_personnel import (
    add_recruits,
    apply_selection_profile,
    ensure_cohort_ledger,
    record_recruitment_cohort,
    validate_cohort_ledger,
)
from sword_runtime.training_programs import REGISTRY_PATH as TRAINING_PROGRAM_REGISTRY_PATH, resolve_program_ref, settle_cohort_program
from sword_runtime.training_instructors import instructor_contexts_for_program
from sword_runtime.training_facilities import program_facility_access
from sword_runtime.sim.calendar import CampaignTime

REGISTRY_PATH = "state/recruitment/candidate-pools.json"
PROFILE_PATH = "game/data/mil/recruitment-cohort-profiles.json"


def _apportion(total: int, weights: Mapping[str, Any], capacities: Mapping[str, int] | None = None) -> dict[str, int]:
    total=max(0,int(total)); caps={str(k):max(0,int(v)) for k,v in (capacities or {}).items()}; keys=[str(k) for k,v in weights.items() if float(v)>0]
    result={k:0 for k in keys}
    remaining=total
    while remaining>0 and keys:
        active=[k for k in keys if not caps or result[k] < caps.get(k,0)]
        if not active: break
        wsum=sum(max(0.0,float(weights[k])) for k in active)
        if wsum<=0: break
        raw={k:remaining*max(0.0,float(weights[k]))/wsum for k in active}
        grants={k:min((caps.get(k,10**18)-result[k]) if caps else 10**18,int(math.floor(raw[k]))) for k in active}
        granted=sum(grants.values())
        for k,n in grants.items(): result[k]+=n
        remaining-=granted
        if remaining<=0: break
        order=sorted(active,key=lambda k:(raw[k]-math.floor(raw[k]),float(weights[k]),k),reverse=True)
        moved=False
        for k in order:
            if remaining<=0: break
            if caps and result[k]>=caps.get(k,0): continue
            result[k]+=1; remaining-=1; moved=True
        if not moved: break
    if remaining:
        raise ValueError("candidate sourcing lacks enough eligible population")
    return {k:v for k,v in result.items() if v>0}


def _selection_score(profile: Mapping[str, Any], selection: Mapping[str, Any]) -> float:
    total=used=0.0
    for means_key,weights_key in (("attribute_means","attribute_weights"),("skill_means","skill_weights"),("aptitude_means","aptitude_weights")):
        means=profile.get(means_key,{}); weights=selection.get(weights_key,{})
        if not isinstance(means,Mapping) or not isinstance(weights,Mapping): continue
        for key,w in weights.items():
            ww=max(0.0,float(w));
            if ww and key in means: total+=float(means[key])*ww; used+=ww
    return total/used if used else 50.0


def _slice_id(campaign_ref: str, source: str, background: str) -> str:
    digest=hashlib.sha256(f"{campaign_ref}|{source}|{background}".encode()).hexdigest()[:10]
    return f"candidate_{digest}"


def _registry(planner: Any) -> dict[str, Any]:
    value=planner.read_optional(REGISTRY_PATH)
    if not isinstance(value,Mapping): return {"schema":"recruitment-candidate-pool-registry","owner_id":"recruitment_candidate_pools","campaigns":{}}
    return deepcopy(dict(value))



def _funding(planner: Any, force_ref: str) -> tuple[str, dict[str, Any], Mapping[str, Any]]:
    force=planner.read(planner.owner_path(force_ref))
    treasury_ref=str(force.get("support_treasury_ref", "")) if isinstance(force,Mapping) else ""
    if not treasury_ref:
        raise ValueError("destination force has no declared recruitment support treasury")
    treasury_path=planner.owner_path(treasury_ref); treasury=deepcopy(planner.read(treasury_path)); economy=planner.read("game/data/mechanics/economy.json")
    return treasury_path, treasury, economy

def _spend_silver(treasury: MutableMapping[str, Any], amount: float, *, reason: str) -> int:
    cost=max(0,int(math.ceil(amount-1e-9)))
    if int(treasury.get("silver",0)) < cost:
        raise ValueError(f"recruitment support treasury lacks silver for {reason}")
    treasury["silver"]=int(treasury.get("silver",0))-cost
    return cost

def _credit_recruitment_payment(planner: Any, state: str, amount: int, *, kind: str, evidence_ref: str, campaign_ref: str, location_ref: str | None = None) -> str:
    """Route recruitment silver to the exact regional private economy.

    Recruitment contact, screening, and basic-issue spending pays households,
    brokers, craftsmen, and local suppliers rather than disappearing from the
    tracked economy.  The private economy remains aggregate; no fictional
    individual payees are materialized.
    """
    amount=max(0,int(amount))
    path=f"state/economy/private/{state}.json"
    eco=deepcopy(planner.read(path))
    if eco.get("owner_id") != f"private_economy_{state}":
        raise ValueError("recruitment payment lost its regional private-economy owner")
    regional_ref = None
    if location_ref and hasattr(planner, "_local_economy_region"):
        try:
            regional_ref, regional = planner._local_economy_region(state, eco, location_ref)
            regional["cash_silver"] = int(regional.get("cash_silver", 0)) + amount
            if hasattr(planner, "_sync_local_economy_aggregate"):
                planner._sync_local_economy_aggregate(eco)
        except ValueError:
            eco["cash_silver"] = int(eco.get("cash_silver", 0)) + amount
    else:
        eco["cash_silver"]=int(eco.get("cash_silver",0))+amount
    history=eco.setdefault("recruitment_payment_history",[])
    history.append({
        "at": str(planner._world_time()),
        "campaign_ref": campaign_ref,
        "kind": kind,
        "silver": amount,
        "evidence_ref": evidence_ref,
        "regional_source_ref": regional_ref,
    })
    del history[:-48]
    if hasattr(planner, "_write_private_economy"):
        planner._write_private_economy(path, eco)
    else:
        planner.put(path,eco)
    return str(eco.get("owner_id"))

def _consume_food(treasury: MutableMapping[str, Any], amount: float, *, reason: str) -> int:
    food=max(0,int(math.ceil(amount-1e-9)))
    if int(treasury.get("food_kg",0)) < food:
        raise ValueError(f"recruitment support treasury lacks food for {reason}")
    treasury["food_kg"]=int(treasury.get("food_kg",0))-food
    return food

def start_campaign(planner: Any, payload: Mapping[str, Any], *, evidence_ref: str) -> dict[str, Any]:
    state=str(payload["state"]); campaign_ref=str(payload["campaign_ref"]); applicants=max(1,int(payload["applicant_count"])); force_ref=str(payload.get("destination_force_ref","force_tang_wei_personal")); role=str(payload.get("role","household_retainer")); location=str(payload.get("location_ref","loc_tang_manor_garrison_yard"))
    if force_ref != "force_tang_wei_personal": raise ValueError("high-resolution recruitment campaign currently supports Tang Wei's personal force only")
    treasury_path,treasury,economy=_funding(planner,force_ref); constants=economy.get("recruitment_cost_constants",{}); campaign_rules=economy.get("recruitment_campaign",{})
    contact_key=str(campaign_rules.get("default_contact_cost_key","contacted_candidate_regional")); contact_rate=float(constants.get(contact_key,0.1)); contact_cost=_spend_silver(treasury,applicants*contact_rate,reason="candidate contact")
    reg=_registry(planner); campaigns=reg.setdefault("campaigns",{})
    if campaign_ref in campaigns: raise ValueError("recruitment campaign_ref already exists")
    profile_registry=planner.read(PROFILE_PATH); source_mix=profile_registry.get("candidate_campaign_source_mix",{}); bg_mixes=profile_registry.get("population_background_mixes",{}); backgrounds=profile_registry.get("background_profiles",{})
    if not isinstance(source_mix,Mapping) or not source_mix: raise ValueError("candidate campaign source mix is unavailable")
    pop_path=f"state/population/{state}.json"; pop=deepcopy(planner.read(pop_path)); strata=pop.setdefault("strata",{}); reserved_key=str(profile_registry.get("rules",{}).get("candidate_reserved_stratum","recruitment_candidates_reserved")); capacities={k:int(strata.get(k,0)) for k in source_mix}
    source_counts=_apportion(applicants,source_mix,capacities)
    local_reservations=[]
    if hasattr(planner,"_reserve_local_candidates"):
        local_reservations=planner._reserve_local_candidates(pop,state,location,campaign_ref,source_counts,controller_ref=f"state_{state}")
        # Local reservation helpers reconcile the nested locality partition by
        # replacing the population mapping in-place.  Rebind the global strata
        # view afterwards so source -> reserved transfers update the same exact
        # population owner rather than a stale pre-reconciliation dict.
        strata=pop.setdefault("strata",{})
    slices=[]
    for source,count in source_counts.items():
        mix=bg_mixes.get(source,{}) if isinstance(bg_mixes,Mapping) else {}
        if not isinstance(mix,Mapping) or not mix: raise ValueError(f"no canonical background mixture for source stratum {source}")
        bg_counts=_apportion(count,mix)
        for bg,n in bg_counts.items():
            base=backgrounds.get(bg) if isinstance(backgrounds,Mapping) else None
            if not isinstance(base,Mapping): raise ValueError(f"unknown registered background in candidate mix: {bg}")
            slices.append({"slice_id":_slice_id(campaign_ref,source,bg),"source_stratum":source,"background_profile":bg,"count":n,"profile":deepcopy(dict(base)),"selection_history":[]})
        strata[source]=int(strata.get(source,0))-count
    strata[reserved_key]=int(strata.get(reserved_key,0))+applicants
    campaigns[campaign_ref]={"campaign_ref":campaign_ref,"state":state,"status":"screening","destination_force_ref":force_ref,"role":role,"location_ref":location,"started_at":str(planner._world_time()),"initial_applicants":applicants,"remaining_candidates":applicants,"reserved_stratum":reserved_key,"slices":slices,"stage_history":[],"provenance_ref":evidence_ref,"local_reservations":local_reservations}
    payee_ref=_credit_recruitment_payment(planner,state,contact_cost,kind="candidate_contact",evidence_ref=evidence_ref,campaign_ref=campaign_ref,location_ref=location)
    campaign=campaigns[campaign_ref]; campaign["economic_history"]=[{"kind":"candidate_contact","silver":contact_cost,"candidate_count":applicants,"payee_ref":payee_ref,"evidence_ref":evidence_ref}]
    planner.put(pop_path,pop); planner.put(treasury_path,treasury); planner.put(REGISTRY_PATH,reg)
    return {"campaign_ref":campaign_ref,"applicants":applicants,"remaining_candidates":applicants,"source_composition":source_counts,"background_composition":{s["background_profile"]:sum(x["count"] for x in slices if x["background_profile"]==s["background_profile"]) for s in slices},"silver_spent":contact_cost}


def stage_campaign(planner: Any, payload: Mapping[str, Any], *, evidence_ref: str) -> dict[str, Any]:
    campaign_ref=str(payload["campaign_ref"]); selection_ref=str(payload["selection_profile"]); reg=_registry(planner); campaign=reg.get("campaigns",{}).get(campaign_ref)
    if not isinstance(campaign,MutableMapping) or campaign.get("status") not in {"screening","training_candidate"}: raise ValueError("recruitment campaign is not open for selection")
    current=max(0,int(campaign.get("remaining_candidates",0))); target=int(payload.get("retain_count",0) or 0)
    if target<=0:
        fraction=float(payload.get("retain_fraction",0) or 0); target=max(1,int(math.floor(current*fraction))) if fraction>0 else 0
    if target<=0 or target>=current: raise ValueError("selection stage retain target must be positive and below current candidates")
    treasury_path,treasury,economy=_funding(planner,str(campaign["destination_force_ref"])); constants=economy.get("recruitment_cost_constants",{}); campaign_rules=economy.get("recruitment_campaign",{}); screen_key=str(campaign_rules.get("screening_cost_key","screened_candidate_ordinary")); screen_rate=float(constants.get(screen_key,0.1)); screening_cost=_spend_silver(treasury,current*screen_rate,reason="candidate screening")
    profiles=planner.read(PROFILE_PATH); selections=profiles.get("selection_profiles",{}); selection=selections.get(selection_ref) if isinstance(selections,Mapping) else None
    if not isinstance(selection,Mapping): raise ValueError("unknown registered recruitment selection profile")
    slices=[s for s in campaign.get("slices",[]) if isinstance(s,MutableMapping) and int(s.get("count",0))>0]
    weights={str(s["slice_id"]):int(s["count"])*math.exp((_selection_score(s.get("profile",{}),selection)-60.0)/45.0) for s in slices}; capacities={str(s["slice_id"]):int(s["count"]) for s in slices}; kept=_apportion(target,weights,capacities)
    pop_path=f"state/population/{campaign['state']}.json"; pop=deepcopy(planner.read(pop_path)); strata=pop.setdefault("strata",{}); reserved=str(campaign["reserved_stratum"]); rejected_by_source={}
    new_slices=[]
    for s in slices:
        before=int(s["count"]); after=int(kept.get(str(s["slice_id"]),0)); rejected=before-after; source=str(s["source_stratum"])
        if rejected: rejected_by_source[source]=rejected_by_source.get(source,0)+rejected; strata[source]=int(strata.get(source,0))+rejected; strata[reserved]=int(strata.get(reserved,0))-rejected
        if after<=0: continue
        fraction=after/max(1,before); apply_selection_profile(s["profile"],selection,retain_fraction=fraction); s["count"]=after; s.setdefault("selection_history",[]).append({"selection_profile":selection_ref,"before":before,"after":after,"retain_fraction":round(fraction,6),"evidence_ref":evidence_ref}); new_slices.append(s)
    local_returns=[]
    if hasattr(planner,"_release_local_candidate_rejections"):
        local_returns=planner._release_local_candidate_rejections(pop,campaign_ref,rejected_by_source)
    campaign["slices"]=new_slices; campaign["remaining_candidates"]=target; campaign.setdefault("local_return_history",[]).append({"at":str(planner._world_time()),"kind":"selection_rejections","rows":local_returns,"evidence_ref":evidence_ref}); campaign["local_return_history"]=campaign["local_return_history"][-16:]; campaign.setdefault("stage_history",[]).append({"selection_profile":selection_ref,"before":current,"after":target,"rejected":current-target,"evidence_ref":evidence_ref}); campaign["stage_history"]=campaign["stage_history"][-16:]
    payee_ref=_credit_recruitment_payment(planner,str(campaign["state"]),screening_cost,kind="candidate_screening",evidence_ref=evidence_ref,campaign_ref=campaign_ref,location_ref=str(campaign.get("location_ref", "")))
    campaign.setdefault("economic_history",[]).append({"kind":"screening","selection_profile":selection_ref,"silver":screening_cost,"candidate_count":current,"payee_ref":payee_ref,"evidence_ref":evidence_ref})
    planner.put(pop_path,pop); planner.put(treasury_path,treasury); planner.put(REGISTRY_PATH,reg)
    return {"campaign_ref":campaign_ref,"selection_profile":selection_ref,"before":current,"remaining_candidates":target,"rejected":current-target,"rejected_by_source":rejected_by_source,"silver_spent":screening_cost}


def train_campaign(planner: Any, payload: Mapping[str, Any], *, evidence_ref: str) -> dict[str, Any]:
    campaign_ref=str(payload["campaign_ref"]); hours=max(1,int(payload["hours"])); reg=_registry(planner); campaign=reg.get("campaigns",{}).get(campaign_ref)
    if not isinstance(campaign,MutableMapping) or campaign.get("status") not in {"screening","training_candidate"}: raise ValueError("recruitment campaign is not open for training")
    treasury_path,treasury,economy=_funding(planner,str(campaign["destination_force_ref"])); campaign_rules=economy.get("recruitment_campaign",{}); candidates=max(0,int(campaign.get("remaining_candidates",0))); capacity=max(1,int(campaign_rules.get("candidate_training_capacity",6000)))
    if candidates>capacity: raise ValueError("candidate pool exceeds registered residential training capacity; screen it down before sustained training")
    food_rate=float(campaign_rules.get("candidate_food_kg_per_person_day",1.6)); day_hours=max(1.0,float(campaign_rules.get("training_day_hours",24.0))); food_used=_consume_food(treasury,candidates*food_rate*hours/day_hours,reason="candidate training")
    profiles=planner.read(PROFILE_PATH); rules=planner.read("game/data/mechanics/training.json"); regimens=profiles.get("training_regimens",{}); regimen=regimens.get("house_tang_max_sustainable",{}) if isinstance(regimens,Mapping) else {}; registry=planner.read(TRAINING_PROGRAM_REGISTRY_PATH); role=str(campaign.get("role","household_retainer")); program_ref=resolve_program_ref(registry,role=role)
    changed=0
    training_start = planner._world_time()
    training_end = training_start.add_seconds(hours * 3600)
    for slice_index, s in enumerate(campaign.get("slices",[])):
        if not isinstance(s,MutableMapping) or int(s.get("count",0))<=0 or not isinstance(s.get("profile"),MutableMapping): continue
        profile=s["profile"]
        profile.setdefault("skill_edu_banks",{}); profile.setdefault("attribute_edu_banks",{}); profile.setdefault("verified_training_hours_per_person",0.0); profile.setdefault("verified_role_exposure_hours_per_person",0.0); profile.setdefault("training_history",[])
        slice_evidence=f"{evidence_ref}:slice:{slice_index}"
        instructor_contexts=instructor_contexts_for_program(
            planner,registry=registry,training_rules=rules,program_ref=program_ref,
            trainee_skills=(profile.get("skill_means",{}) if isinstance(profile.get("skill_means"),Mapping) else {}),
            student_count=max(1,int(s.get("count",0) or 0)),location_ref=str(campaign.get("location_ref","")),
            scheduled_hours=float(hours),window_start=str(training_start),window_end=str(training_end),
            evidence_ref=slice_evidence,reserve_duty=True,
        )
        drill_access=program_facility_access(planner,registry=registry,program_ref=program_ref,location_ref=str(campaign.get("location_ref","")))
        settle_cohort_program(profile,registry=registry,program_ref=program_ref,deliberate_hours=float(hours),role_exposure_hours=0.0,training_rules=rules,facility_grade=str(regimen.get("facility_grade","adequate")),equipment_grade=str(regimen.get("equipment_grade","adequate")),recovery_grade=str(regimen.get("recovery_grade","adequate")),evidence_ref=slice_evidence,instructor_context_by_drill=instructor_contexts,drill_access=drill_access)
        changed+=1
    campaign["status"]="training_candidate"; campaign["verified_training_hours_per_person"]=round(float(campaign.get("verified_training_hours_per_person",0.0))+hours,3); campaign.setdefault("stage_history",[]).append({"kind":"candidate_training","hours":hours,"evidence_ref":evidence_ref}); campaign["stage_history"]=campaign["stage_history"][-16:]; campaign.setdefault("economic_history",[]).append({"kind":"candidate_training_support","hours":hours,"food_kg":food_used,"candidate_count":candidates,"evidence_ref":evidence_ref}); planner.put(treasury_path,treasury); planner.put(REGISTRY_PATH,reg)
    return {"campaign_ref":campaign_ref,"hours":hours,"trained_slices":changed,"remaining_candidates":int(campaign.get("remaining_candidates",0)),"food_kg_consumed":food_used}


def finalize_campaign(planner: Any, payload: Mapping[str, Any], *, evidence_ref: str) -> dict[str, Any]:
    campaign_ref=str(payload["campaign_ref"]); reg=_registry(planner); campaign=reg.get("campaigns",{}).get(campaign_ref)
    if not isinstance(campaign,MutableMapping) or campaign.get("status") not in {"screening","training_candidate"}: raise ValueError("recruitment campaign cannot be finalized")
    n=max(1,int(campaign.get("remaining_candidates",0))); state=str(campaign["state"]); force_ref=str(campaign["destination_force_ref"]); role=str(campaign["role"]); loc=str(campaign["location_ref"]); pop_path=f"state/population/{state}.json"; pop=deepcopy(planner.read(pop_path)); strata=pop.setdefault("strata",{}); reserved=str(campaign["reserved_stratum"])
    treasury_path,treasury,economy=_funding(planner,force_ref); finance=economy.get("military_finance",{}); unit_cost=float(finance.get("recruitment_and_basic_issue_cost_silver_per_person",12)); issue_cost=_spend_silver(treasury,n*unit_cost,reason="accepted recruit basic issue")
    if int(strata.get(reserved,0))<n: raise ValueError("reserved candidate population is inconsistent")
    local_service=[]
    if hasattr(planner,"_finalize_local_candidate_reservations"):
        local_service=planner._finalize_local_candidate_reservations(pop,campaign_ref,force_ref)
        if sum(int(x.get("personnel",0)) for x in local_service)!=n: raise ValueError("finalized candidate locality does not match accepted population")
    strata[reserved]-=n; strata["private_household_military"]=int(strata.get("private_household_military",0))+n
    fp=planner.owner_path(force_ref); force=planner._ct_force(fp) if hasattr(planner,"_ct_force") else deepcopy(planner.read(fp)); ensure_cohort_ledger(force,at=str(planner._world_time())); add_recruits(force,role,n,location_ref=loc); force["authorized_strength"]=max(int(force.get("authorized_strength",0)),int(force.get("headcount",0)))
    profiles=planner.read(PROFILE_PATH); cohort_refs=[]
    for s in campaign.get("slices",[]):
        if not isinstance(s,Mapping) or int(s.get("count",0))<=0: continue
        cid=record_recruitment_cohort(force,role=role,count=int(s["count"]),location_ref=loc,source_population_ref=f"population_{state}",source_stratum=str(s["source_stratum"]),recruited_at=str(planner._world_time()),profile_registry=profiles,background_profile=str(s["background_profile"]),provenance_ref=evidence_ref,conditioned_profile=s.get("profile") if isinstance(s.get("profile"),Mapping) else None,selection_history=s.get("selection_history",[]),intake_ref=campaign_ref,validate=False)
        if cid: cohort_refs.append(cid)
    validate_cohort_ledger(force); campaign["status"]="finalized"; campaign["finalized_at"]=str(planner._world_time()); campaign["accepted_count"]=n; campaign["cohort_refs"]=cohort_refs; campaign["local_service_allocations"]=local_service
    payee_ref=_credit_recruitment_payment(planner,state,issue_cost,kind="accepted_basic_issue",evidence_ref=evidence_ref,campaign_ref=campaign_ref,location_ref=loc)
    force.setdefault("recruitment_history",[]).append({"kind":"player_recruitment_campaign","campaign_ref":campaign_ref,"count":n,"role":role,"at":str(planner._world_time()),"cohort_refs":cohort_refs}); force["recruitment_history"]=force["recruitment_history"][-24:]; campaign.setdefault("economic_history",[]).append({"kind":"accepted_basic_issue","silver":issue_cost,"accepted":n,"payee_ref":payee_ref,"evidence_ref":evidence_ref})
    planner.put(pop_path,pop); planner.put(fp,force); planner.put(treasury_path,treasury); planner.put(REGISTRY_PATH,reg)
    return {"campaign_ref":campaign_ref,"accepted":n,"force_ref":force_ref,"role":role,"cohort_refs":cohort_refs,"silver_spent":issue_cost}


def cancel_campaign(planner: Any, payload: Mapping[str, Any], *, evidence_ref: str) -> dict[str, Any]:
    campaign_ref=str(payload["campaign_ref"]); reg=_registry(planner); campaign=reg.get("campaigns",{}).get(campaign_ref)
    if not isinstance(campaign,MutableMapping) or campaign.get("status") not in {"screening","training_candidate"}: raise ValueError("recruitment campaign is not cancellable")
    pop_path=f"state/population/{campaign['state']}.json"; pop=deepcopy(planner.read(pop_path)); strata=pop.setdefault("strata",{}); reserved=str(campaign["reserved_stratum"]); returned={}
    for s in campaign.get("slices",[]):
        if not isinstance(s,Mapping): continue
        count=max(0,int(s.get("count",0))); source=str(s.get("source_stratum",""));
        if count: strata[source]=int(strata.get(source,0))+count; returned[source]=returned.get(source,0)+count
    total=sum(returned.values())
    local_returns=[]
    if hasattr(planner,"_release_local_candidate_rejections"):
        local_returns=planner._release_local_candidate_rejections(pop,campaign_ref,returned)
    if int(strata.get(reserved,0))<total: raise ValueError("reserved candidate population is inconsistent")
    strata[reserved]-=total; campaign["status"]="cancelled"; campaign["cancelled_at"]=str(planner._world_time()); campaign["returned_count"]=total; campaign["cancel_evidence_ref"]=evidence_ref; campaign["local_return_rows"]=local_returns
    planner.put(pop_path,pop); planner.put(REGISTRY_PATH,reg)
    return {"campaign_ref":campaign_ref,"returned":total,"returned_by_source":returned}


__all__=["REGISTRY_PATH","start_campaign","stage_campaign","train_campaign","finalize_campaign","cancel_campaign"]
