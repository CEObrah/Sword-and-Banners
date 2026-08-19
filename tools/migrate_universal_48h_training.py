#!/usr/bin/env python3
"""One-shot migration to the universal 48h/week active/enrolled training clock.

The migration is deliberately provenance-safe:
- exact people receive only proven completed-cycle shortfalls under the new clock;
- aggregate state/household cohorts are caught up only when their saved verified
  counters prove an exact number of cycles under the immediately previous regimen;
- materialized person-lite officers receive only the same proven source-cohort delta;
- previously higher-hour House Tang/Sword Manor history is never reduced or replayed;
- child/civilian/reserve schedules are not promoted into the active clock;
- no campaign time, headcount, office, allegiance or future canon outcome is created.
"""
from __future__ import annotations

import argparse, copy, json, sys
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime'))

from sword_runtime.history_store import write_history_index
from sword_runtime.progression_integrity import exact_activity_shortfall
from sword_runtime.service_runtime import CommandRoutedProductionPlanner
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.training_instructors import exact_person_drill_access
from sword_runtime.training_rates import resolved_activity_regimen
from sword_runtime.training_programs import REGISTRY_PATH, resolve_program_ref, settle_cohort_program, settle_exact_program, settle_person_lite_program

PROFILES='game/data/mil/recruitment-cohort-profiles.json'
RULES='game/data/mechanics/training.json'
SESSION='game/data/mechanics/training-session.json'
CAL='game/data/people/canon-capability-calibration.json'
MIG='universal_active_48h_week_v1'
EVENT='repair_universal_active_training_244_bce_07_29'
TARGET=48*30/7


def write_json(path:Path,value:Any)->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')


def num(v:Any)->float:
    try:return float(v)
    except (TypeError,ValueError):return 0.0


def floor_map(target:MutableMapping[str,Any], floors:Mapping[str,Any])->dict[str,dict[str,float]]:
    changed={}
    for k,v in sorted(floors.items()):
        f=num(v); before=num(target.get(k,0))
        if before+1e-9>=f: continue
        after=int(f) if float(f).is_integer() else round(f,3)
        target[k]=after; changed[k]={'before':before,'after':float(after)}
    return changed


def equipment_only_access(planner,registry,program_ref,person):
    probe=copy.deepcopy(dict(person))
    for k in ('current_location','location_ref','location'):probe.pop(k,None)
    return exact_person_drill_access(planner,registry=registry,program_ref=program_ref,person=probe)


def routes(planner):
    owner=planner.read('state/index/owner-index.json').get('owners',{})
    cmd=planner.read('state/cmd/command-personnel.json').get('record_index',{})
    out={}
    if isinstance(owner,Mapping): out.update({str(k):str(v) for k,v in owner.items() if isinstance(v,str)})
    if isinstance(cmd,Mapping): out.update({str(k):str(v) for k,v in cmd.items() if isinstance(v,str)})
    return out,set(str(k) for k in cmd) if isinstance(cmd,Mapping) else set()


def repair(root:Path,apply:bool)->dict[str,Any]:
    # One-shot state repair. A rerun against an already-migrated campaign must be a
    # no-op rather than rewriting provenance counters or incrementing revision.
    meta_path=root/'state/meta.json'
    if meta_path.exists():
        existing=json.loads(meta_path.read_text(encoding='utf-8'))
        marker=existing.get('last_universal_training_repair',{}) if isinstance(existing,Mapping) else {}
        if isinstance(marker,Mapping) and str(marker.get('migration_ref',''))==MIG:
            return {
                'already_applied':True,
                'migration_ref':MIG,
                'exact_people_caught_up':int(marker.get('exact_people_caught_up',0) or 0),
                'exact_hours_caught_up':int(marker.get('exact_hours_caught_up',0) or 0),
                'aggregate_cohorts_caught_up':int(marker.get('aggregate_cohorts_caught_up',0) or 0),
                'person_lite_caught_up':int(marker.get('person_lite_caught_up',0) or 0),
                'canon_people_calibrated':int(marker.get('canon_people_calibrated',0) or 0),
                'bastion_current_setting_baseline_cohorts':int(marker.get('bastion_current_setting_baseline_cohorts',0) or 0),
                'staged_files':0,
            }
    p=CommandRoutedProductionPlanner(root); p._reset(); p._ensure_activity_routes()
    world=str(p.read('state/runtime.json').get('world_time'))
    profiles=p.read(PROFILES); registry=p.read(REGISTRY_PATH); rules=p.read(RULES); session=p.read(SESSION); cal=p.read(CAL)
    rts,cmdrefs=routes(p)

    # Canon current-capability/aptitude floors, including newly registered main cast.
    calibrated=[]
    for ref,spec in sorted((cal.get('characters',{}) or {}).items()):
        route=rts.get(str(ref))
        if not route or not route.startswith('state/char/') or not isinstance(spec,Mapping): continue
        person=copy.deepcopy(p.read(route))
        if person.get('schema')!='sab_character': continue
        apt=person.setdefault('aptitude',{}); attrs=person.setdefault('attributes',{}); skills=person.setdefault('skills',{})
        if not all(isinstance(x,MutableMapping) for x in (apt,attrs,skills)): continue
        da=floor_map(apt,spec.get('aptitude_floors',{}) if isinstance(spec.get('aptitude_floors'),Mapping) else {})
        db=floor_map(attrs,spec.get('attribute_floors',{}) if isinstance(spec.get('attribute_floors'),Mapping) else {})
        dc=floor_map(skills,spec.get('skill_floors',{}) if isinstance(spec.get('skill_floors'),Mapping) else {})
        ds=person.setdefault('development_state',{})
        current_cal=ds.get('canon_capability_calibration') if isinstance(ds.get('canon_capability_calibration'),Mapping) else {}
        needs_record = bool(da or db or dc or str(current_cal.get('calibration_ref','')) != str(cal.get('calibration_ref','')))
        if needs_record:
            record={'calibration_ref':cal.get('calibration_ref'),'recorded_at':world,'tier':str(spec.get('tier','')),'aptitude_changes':da,'attribute_changes':db,'skill_changes':dc,'rule':'floor-only current capability calibration; no future history or outcome is pre-granted'}
            ds['canon_capability_calibration']=record
            ds.setdefault('canon_capability_calibration_history',[]).append(record)
            ds['canon_capability_calibration_history']=ds['canon_capability_calibration_history'][-4:]
            apt['source']='user_authorized_canon_current_calibration'
            p.put(route,person); calibrated.append(ref)

    # Exact-person completed-cycle shortfall under new 48h/week active/enrolled clock.
    exact=[]
    for ref,route in sorted(rts.items()):
        if not route.startswith('state/char/'): continue
        try: person=copy.deepcopy(p.read(route))
        except Exception: continue
        if person.get('schema')!='sab_character': continue
        contract=p._command_activity_contract(person) if ref in cmdrefs else p._effective_activity_contract(person)
        if not isinstance(contract,Mapping) or str(contract.get('mode',''))=='age_appropriate_household_training': continue
        proof=exact_activity_shortfall(person,contract,profiles)
        missing=int(proof.get('shortfall_hours',0) or 0)
        if missing<=0: continue
        activity=person.get('autonomous_activity_state',{}) if isinstance(person.get('autonomous_activity_state'),Mapping) else {}
        at=str(activity.get('last_completed_at',activity.get('last_cycle_at',world)))
        program_ref,training_ref,resolved_role=p._activity_training_context(person,contract)
        regimen_ref,regimen=resolved_activity_regimen(person,contract,profiles)
        before_reviews=int(person.setdefault('development_state',{}).get('completed_reviews',0) or 0)
        before_settled=int(person['development_state'].get('settled_training_hours',0) or 0)
        before_verified=int(person['development_state'].get('verified_deliberate_training_hours',before_settled) or 0)
        result=settle_exact_program(person,registry=registry,program_ref=program_ref,hours=missing,at=CampaignTime.parse(at),training_rules=rules,session_rules=session,facility_grade=str(regimen.get('facility_grade','adequate')),equipment_grade=str(regimen.get('equipment_grade','adequate')),recovery_grade=str(regimen.get('recovery_grade','adequate')),feedback_grade=str(regimen.get('feedback_grade','ordinary')),cursor_key='autonomous_deterministic_training_cursor',drill_access=equipment_only_access(p,registry,program_ref,person))
        person['development_state']['verified_deliberate_training_hours']=before_verified+missing
        person['development_state']['completed_reviews']=before_reviews
        person['development_state'].setdefault('universal_training_migration_history',[]).append({'migration_ref':MIG,'recorded_at':world,'completed_cycles':proof.get('completed_cycles',0),'expected_verified_hours':proof.get('expected_hours',0),'verified_before':before_verified,'added_verified_hours':missing,'gain_bearing_hours':max(0,int(person['development_state'].get('settled_training_hours',0) or 0)-before_settled),'program_ref':program_ref,'regimen_ref':regimen_ref,'training_ref':training_ref or None,'resolved_role':resolved_role or None,'historical_instructor_claim':False,'historical_location_claim':False,'result':result})
        person['development_state']['universal_training_migration_history']=person['development_state']['universal_training_migration_history'][-4:]
        p.put(route,person); exact.append({'person_ref':ref,'hours':missing})

    # Aggregate force cohorts: only force families with numerically proven previous rates.
    previous={
      'state-':(112.0,'regular_army'),
      'house_':(120.0,'household_professional'),
    }
    cohort_delta={}; cohorts=[]
    for fp in sorted((root/'state/forces').glob('*.json')):
        name=fp.name; old=None; regimen_ref=None
        for prefix,(rate,reg) in previous.items():
            if name.startswith(prefix): old=rate; regimen_ref=reg; break
        if old is None: continue
        rel=str(fp.relative_to(root)); force=copy.deepcopy(p.read(rel)); ledger=force.get('cohort_ledger',{}).get('cohorts',{}) if isinstance(force,Mapping) else {}
        if not isinstance(ledger,MutableMapping): continue
        changed=0
        regimen=profiles.get('training_regimens',{}).get(regimen_ref,{})
        for cid,c in sorted(ledger.items()):
            if not isinstance(c,MutableMapping): continue
            hist=c.get('universal_training_migration_history',[])
            if isinstance(hist,list) and any(isinstance(x,Mapping) and x.get('migration_ref')==MIG for x in hist): continue
            trained=num(c.get('verified_training_hours_per_person',0))
            cycles=round(trained/old) if old>0 else 0
            if cycles<=0 or abs(trained-cycles*old)>0.01: continue
            target=cycles*TARGET; add=max(0.0,target-trained)
            if add<=1e-6: continue
            role=str(c.get('role','')); program=resolve_program_ref(registry,role=role or None)
            result=settle_cohort_program(c,registry=registry,program_ref=program,deliberate_hours=add,role_exposure_hours=0.0,training_rules=rules,facility_grade=str(regimen.get('facility_grade','adequate')),equipment_grade=str(regimen.get('equipment_grade','adequate')),recovery_grade=str(regimen.get('recovery_grade','adequate')),evidence_ref=f'universal_training:{MIG}:{force.get("owner_id")}:{cid}')
            c.setdefault('universal_training_migration_history',[]).append({'migration_ref':MIG,'recorded_at':world,'proven_previous_cycles':cycles,'previous_rate_per_30d':old,'verified_before':trained,'target_verified_hours':round(target,3),'added_deliberate_hours':round(add,3),'program_ref':program,'historical_instructor_claim':False,'result':result})
            c['universal_training_migration_history']=c['universal_training_migration_history'][-4:]
            cohort_delta[str(cid)]=add; cohorts.append({'force_ref':force.get('owner_id'),'cohort_ref':cid,'hours':round(add,3)}); changed+=1
        if changed: p.put(rel,force)

    # Materialized person-lite from migrated cohorts get the same one-time differential.
    pl=[]; cmd=p.read('state/cmd/command-personnel.json').get('record_index',{})
    if isinstance(cmd,Mapping):
      for ref,route in sorted((str(k),str(v)) for k,v in cmd.items() if isinstance(v,str)):
        try: person=copy.deepcopy(p.read(route))
        except Exception: continue
        if person.get('schema')!='person-lite': continue
        src=str(person.get('source_cohort_ref','')); add=cohort_delta.get(src)
        if not add: continue
        dev=person.setdefault('development_state',{}); hist=dev.get('universal_training_migration_history',[])
        if isinstance(hist,list) and any(isinstance(x,Mapping) and x.get('migration_ref')==MIG for x in hist): continue
        contract=p._effective_activity_contract(person); program,training_ref,resolved_role=p._activity_training_context(person,contract if isinstance(contract,Mapping) else {})
        result=settle_person_lite_program(person,registry=registry,program_ref=program,deliberate_hours=add,role_exposure_hours=0.0,training_rules=rules,facility_grade='adequate',equipment_grade='adequate',recovery_grade='adequate',evidence_ref=f'universal_training:{MIG}:{ref}')
        dev=person.setdefault('development_state',{}); dev.setdefault('universal_training_migration_history',[]).append({'migration_ref':MIG,'recorded_at':world,'source_cohort_ref':src,'added_deliberate_hours':round(add,3),'program_ref':program,'training_ref':training_ref or None,'resolved_role':resolved_role or None,'historical_instructor_claim':False,'result':result}); dev['universal_training_migration_history']=dev['universal_training_migration_history'][-4:]
        p.put(route,person); pl.append({'person_ref':ref,'hours':round(add,3)})

    # Current-setting Four Bastion cohorts already encode completed qualification in
    # their saved means. Baseline those means without inventing historical months;
    # future cycles are settled by the standing House Tang monthly owner.
    bastion_baselines=0
    for rel in (
        'state/forces/bastion-iron-rampart.json',
        'state/forces/bastion-red-crane.json',
        'state/forces/bastion-white-lantern.json',
        'state/forces/bastion-deep-earth.json',
    ):
        try: force=copy.deepcopy(p.read(rel))
        except Exception: continue
        ledger=force.get('cohort_ledger',{}).get('cohorts',{}) if isinstance(force,Mapping) else {}
        changed=False
        if isinstance(ledger,MutableMapping):
            for cohort in ledger.values():
                if not isinstance(cohort,MutableMapping): continue
                if isinstance(cohort.get('training_tracking_baseline'),Mapping): continue
                cohort.setdefault('verified_training_hours_per_person',0.0)
                cohort.setdefault('verified_role_exposure_hours_per_person',0.0)
                cohort['training_tracking_baseline']={
                    'migration_ref':MIG,
                    'tracking_started_at':world,
                    'baseline_kind':'current_setting_qualified_capability',
                    'source_kind':'standing_establishment_rebaseline',
                    'rule':'Saved cohort attributes, skills and aptitudes are authoritative current-setting qualified capability at training-tracking start. No pre-tracking EDU or months are invented; future active-service development accrues through the universal 48h/week standing military clock and actual curriculum/instructor/facility/equipment/command access.',
                }
                bastion_baselines+=1; changed=True
        if changed: p.put(rel,force)

    p._ensure_activity_routes()
    hist=copy.deepcopy(p.read('state/history/events/index.json')); events=hist.setdefault('events',[])
    if not any(isinstance(x,Mapping) and x.get('event_id')==EVENT for x in events):
        events.append({'event_id':EVENT,'kind':'explicit_repair','at':world,'path':'universal active/enrolled training clock + hierarchical training delivery + canon calibration','reason':'replace temporary tiered training-hour ladder with one 48h/week active/enrolled clock, catch up only proven under-settlement, and calibrate user-authorized main-canon current capability','universal_deliberate_hours_per_7d':48.0,'universal_deliberate_hours_per_30d':round(TARGET,6),'exact_people_caught_up':len(exact),'exact_hours_caught_up':sum(x['hours'] for x in exact),'aggregate_cohorts_caught_up':len(cohorts),'person_lite_caught_up':len(pl),'canon_people_calibrated':calibrated,'bastion_current_setting_baseline_cohorts':bastion_baselines,'bastion_future_training_owner':'host_sword_manor','rule':'no history is reduced; no missing months are invented; mass instruction capacity is the saved command hierarchy rather than an artificial Units-per-instructor cap'})
        write_history_index(p,hist)
    meta=copy.deepcopy(p.read('state/meta.json')); meta['revision']=int(meta.get('revision',0))+1; meta['last_universal_training_repair']={'at':world,'event_ref':EVENT,'migration_ref':MIG,'exact_people_caught_up':len(exact),'exact_hours_caught_up':sum(x['hours'] for x in exact),'aggregate_cohorts_caught_up':len(cohorts),'person_lite_caught_up':len(pl),'canon_people_calibrated':len(calibrated),'bastion_current_setting_baseline_cohorts':bastion_baselines,'bastion_future_training_owner':'host_sword_manor'}; p.put('state/meta.json',meta)
    summary={'world_time':world,'exact_people_caught_up':len(exact),'exact_hours_caught_up':sum(x['hours'] for x in exact),'exact_people':exact,'aggregate_cohorts_caught_up':len(cohorts),'aggregate_hours_added':round(sum(x['hours'] for x in cohorts),3),'person_lite_caught_up':len(pl),'canon_people_calibrated':calibrated,'bastion_current_setting_baseline_cohorts':bastion_baselines,'staged_files':len(p._writes)}
    if apply:
        for rel,val in sorted(p._writes.items()): write_json(root/rel,val)
    return summary


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--apply',action='store_true'); a=ap.parse_args(); print(json.dumps(repair(Path(a.root).resolve(),apply=a.apply),indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())
