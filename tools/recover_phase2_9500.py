#!/usr/bin/env python3
from __future__ import annotations
import copy, json, re
from pathlib import Path
from collections import defaultdict
ROOT=Path(__file__).resolve().parents[1]
NOW='244-BCE-09-09T20:22:48+08:00'
LOC='loc_qin_eastern_depot'

def load(rel): return json.loads((ROOT/rel).read_text())
def save(rel,obj):
 p=ROOT/rel; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
def fpath(ref):
 for p in (ROOT/'state/formations').glob('*.json'):
  try:
   if json.loads(p.read_text()).get('formation_ref')==ref: return p
  except Exception: pass
 raise FileNotFoundError(ref)
def loadf(ref): return json.loads(fpath(ref).read_text())
def slug(ref): return ref.removeprefix('formation_').replace('_','-')+'.json'
def savef(d): save('state/formations/'+slug(d['formation_ref']),d)

def cohort_comp_add(formation, cid, n):
 rows=formation.setdefault('cohort_composition',[])
 for row in rows:
  if row.get('cohort_id')==cid:
   row['count']=int(row.get('count',0))+n; return
 rows.append({'cohort_id':cid,'count':n})

def find_record_files():
 files=[]
 for pat in ('house-tang-guardian-cavalry.json','house-tang-house-guard.json','house-tang-tang-champions.json','sword-manor-general-disciples.json','sword-manor-junior-disciples.json','sword-manor-senior-disciples.json','sword-manor-trainees.json'):
  p=ROOT/'state/person/person-lite'/pat
  if p.exists(): files.append(p)
 return files

def dematerialize_old_house_person_lite(house):
 records={}
 cohorts=house['cohort_ledger']['cohorts']
 for p in find_record_files():
  d=json.loads(p.read_text()); recs=d.get('records',{})
  it=recs.items() if isinstance(recs,dict) else ((r.get('id'),r) for r in recs)
  for rid,rec in it:
   if not rid: continue
   records[rid]=copy.deepcopy(rec)
   if rid not in house.get('materialized_people',{}): continue
   cid=rec.get('source_cohort_ref')
   if cid not in cohorts: raise RuntimeError(('missing source cohort',rid,cid))
   a=house.get('materialized_assignments',{}).pop(rid,None)
   if isinstance(a,dict) and a.get('formation_ref'):
    ref=str(a['formation_ref']); cohorts[cid].setdefault('allocated_by_formation',{})[ref]=int(cohorts[cid].setdefault('allocated_by_formation',{}).get(ref,0))+1
    try:
     ff=loadf(ref); cohort_comp_add(ff,cid,1); savef(ff)
    except FileNotFoundError: pass
   else:
    loc=str(rec.get('current_location') or cohorts[cid].get('home_location_ref') or 'loc_tang_manor_garrison_yard')
    cohorts[cid].setdefault('reserve_by_location',{})[loc]=int(cohorts[cid].setdefault('reserve_by_location',{}).get(loc,0))+1
   house['materialized_people'].pop(rid,None)
  p.unlink()
 return records

def demat_qin_internal(qin, refs):
 cohorts=qin['cohort_ledger']['cohorts']; refs=set(refs)
 removed=[]
 for pid,a in list(qin.get('materialized_assignments',{}).items()):
  if not isinstance(a,dict) or a.get('formation_ref') not in refs: continue
  ref=str(a['formation_ref']); role=str(a.get('role') or '')
  # Reclassify the same body into a cohort of the same role already serving this formation.
  candidates=[]
  for cid,c in cohorts.items():
   if str(c.get('role'))==role and int(c.get('allocated_by_formation',{}).get(ref,0))>0: candidates.append(cid)
  if not candidates:
   for cid,c in cohorts.items():
    if str(c.get('role'))==role: candidates.append(cid)
  if not candidates: raise RuntimeError(('no qin source cohort for internal officer',pid,role,ref))
  cid=candidates[0]; cohorts[cid].setdefault('allocated_by_formation',{})[ref]=int(cohorts[cid].setdefault('allocated_by_formation',{}).get(ref,0))+1
  ff=loadf(ref); cohort_comp_add(ff,cid,1); savef(ff)
  qin['materialized_assignments'].pop(pid,None); qin.get('materialized_people',{}).pop(pid,None); removed.append(pid)
  # Remove routed person-lite record if present.
  for p in (ROOT/'state/person/person-lite').glob('*.json'):
   try: d=json.loads(p.read_text())
   except Exception: continue
   recs=d.get('records')
   if isinstance(recs,dict) and pid in recs:
    recs.pop(pid,None); d['record_count']=len(recs); p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
 return removed

def recompute_force(force):
 reserve=defaultdict(int); byloc=defaultdict(lambda:defaultdict(int)); alloc=defaultdict(int); comp=defaultdict(lambda:defaultdict(int))
 for c in force['cohort_ledger']['cohorts'].values():
  role=str(c.get('role',''))
  for loc,n in c.get('reserve_by_location',{}).items(): reserve[role]+=int(n); byloc[loc][role]+=int(n)
  for ref,n in c.get('allocated_by_formation',{}).items(): alloc[ref]+=int(n); comp[ref][role]+=int(n)
 # Embedded materialized assignments count inside formation personnel.
 for a in force.get('materialized_assignments',{}).values():
  if not isinstance(a,dict) or not a.get('formation_ref'): continue
  ref=str(a['formation_ref']); n=max(1,int(a.get('personnel',1))); role=str(a.get('role','unknown')); alloc[ref]+=n; comp[ref][role]+=n
 force['available_by_role']=dict(sorted(reserve.items()))
 force['available_by_location']={k:dict(v) for k,v in sorted(byloc.items()) if sum(v.values())}
 force['allocated_to_formations']={ref:{'personnel':alloc[ref],'composition':dict(comp[ref])} for ref in sorted(alloc)}

def release_formation(force, ref, loc):
 ff=loadf(ref); cohorts=force['cohort_ledger']['cohorts']; got=0
 for c in cohorts.values():
  n=int(c.get('allocated_by_formation',{}).pop(ref,0)); got+=n
  if n: c.setdefault('reserve_by_location',{})[loc]=int(c.setdefault('reserve_by_location',{}).get(loc,0))+n
 # Any embedded materialized assignments should have been dematerialized before this.
 if any(isinstance(a,dict) and a.get('formation_ref')==ref for a in force.get('materialized_assignments',{}).values()): raise RuntimeError(('live materialized assignment while releasing',ref))
 fpath(ref).unlink(); return ff,got

def take_role(force, role, count, loc, preferred=None):
 cohorts=force['cohort_ledger']['cohorts']; need=count; rows=[]
 order=[]
 for cid in preferred or []:
  if cid in cohorts and cid not in order: order.append(cid)
 for cid,c in cohorts.items():
  if str(c.get('role'))==role and cid not in order: order.append(cid)
 for cid in order:
  c=cohorts[cid]
  if str(c.get('role'))!=role: continue
  r=c.setdefault('reserve_by_location',{}); avail=int(r.get(loc,0))
  if avail<=0: continue
  take=min(need,avail); r[loc]=avail-take
  if r[loc]==0: r.pop(loc,None)
  rows.append({'cohort_id':cid,'count':take}); need-=take
  if need==0: break
 if need: raise RuntimeError(('reserve shortage',role,count,need,loc))
 return rows

def allocate_formation(force, ref, name, composition, template, commander, higher, doctrine, training, loadouts=None, preferred=None):
 total=sum(composition.values()); ff=copy.deepcopy(template)
 ff['formation_ref']=ref; ff['name']=name; ff['personnel']=total; ff['authorized_strength']=total; ff['composition']=dict(composition); ff['owner_force_ref']=force['owner_id']; ff['commander_ref']=commander; ff['command_authority']='char_tang_wei'; ff['higher_command_ref']=higher; ff['location_ref']=LOC; ff['cohort_composition']=[]; ff['doctrine_ref']=doctrine; ff['training_ref']=training
 ff.pop('doctrine_refs_by_role',None); ff.pop('training_refs_by_role',None)
 if loadouts:
  ff['registered_loadouts_by_role']=loadouts
 elif len(composition)==1:
  role=next(iter(composition)); ff['registered_loadout_ref']='loadout_tang_mounted' if role=='house_cavalry' else ff.get('registered_loadout_ref')
 ff['equipment_units_by_role']=dict(composition)
 ff['mounts']={'horse':sum(n for r,n in composition.items() if 'cavalry' in r)} if any('cavalry' in r for r in composition) else {}
 pref=preferred or {}
 for role,n in composition.items():
  rows=take_role(force,role,n,LOC,pref.get(role));
  for row in rows:
   force['cohort_ledger']['cohorts'][row['cohort_id']].setdefault('allocated_by_formation',{})[ref]=int(force['cohort_ledger']['cohorts'][row['cohort_id']].setdefault('allocated_by_formation',{}).get(ref,0))+row['count']
   ff['cohort_composition'].append(row)
 savef(ff); return ff

def char_path(ref):
 for p in (ROOT/'state/char').glob('*.json'):
  try:
   if json.loads(p.read_text()).get('owner_id')==ref: return p
  except Exception: pass
 return None

def promote_record(house, rec, new_ref, *, span, role_label, scope, higher, source_role_hint=None):
 # consume one conserved reserve body from its source cohort after dematerialization
 cid=rec.get('source_cohort_ref'); c=house['cohort_ledger']['cohorts'].get(cid)
 if not c: raise RuntimeError(('missing promote cohort',new_ref,cid))
 role=str(c.get('role') or source_role_hint or 'house_infantry')
 reserves=c.setdefault('reserve_by_location',{}); loc=None
 for cand in (str(rec.get('current_location') or ''),LOC,'loc_tang_manor_garrison_yard','loc_tang_manor_training_ground','loc_tang_manor_defense_camp'):
  if cand and int(reserves.get(cand,0))>0: loc=cand; break
 if loc is None:
  for k,v in reserves.items():
   if int(v)>0: loc=k; break
 if loc is None: raise RuntimeError(('no reserve body to promote',new_ref,cid))
 reserves[loc]=int(reserves[loc])-1
 if reserves[loc]==0: reserves.pop(loc,None)
 house.setdefault('materialized_people',{})[new_ref]=1
 stats=rec.get('stats',{}) if isinstance(rec.get('stats'),dict) else {}
 d={'schema':'sab_character','owner_id':new_ref,'owner_type':'character','name':rec.get('name',new_ref),'birth_date':rec.get('birth_date','280-BCE-01-01'),'body':copy.deepcopy(rec.get('body',{'adult_height_cm':175,'current_weight_kg':70,'frame':'athletic','growth_end_age':18})),'appearance':int(rec.get('appearance',55)),'affiliation':['house_tang','Tang Wei Personal Retinue'],'role':role_label,'life_status':'active','health_status':'fit','fatigue':0,'aptitude':copy.deepcopy(rec.get('aptitude',{})),'attributes':copy.deepcopy(stats.get('attributes',{})),'skills':copy.deepcopy(stats.get('skills',{})),'professional_skills':copy.deepcopy(rec.get('professional_skills',{})),'current_location':LOC,'loadout_id':'loadout_tang_mounted','personal_loadout_ref':'loadout_tang_mounted','equipment_loadout_id':'loadout_tang_mounted','runtime':{'last_settled_at':NOW},'goal_state':{'current_goals':['serve Tang Wei Army and preserve the command entrusted to me'],'institutional_duties':[role_label]},'military_rank':{'durable':True,'grade':f'{span}_commander' if span in {500,1000,2000,4000} else 'unranked'},'career_state':{'current_billet':'formation_commander','current_command_span':span,'office_or_command':role_label},'command_assignment':{'billet':'formation_commander','current_command_span':span,'external_to_fighting_establishment':True,'formation_ref':scope},'military_command':{'external_to_fighting_strength':True,'formation_scope':scope,'level':f'{span}_commander','higher_commander_ref':higher},'activity_contract':{'mode':'standing_role_training','training_program_ref':'program.commander_cavalry' if role=='house_cavalry' else 'program.commander_combined_arms'},'development_state':copy.deepcopy(rec.get('development_state',{})),'materialization_provenance':{'source_person_lite_ref':rec.get('id'),'source_cohort_ref':cid,'source_role':role,'reclassified_at':NOW}}
 p=ROOT/'state/char'/(new_ref.removeprefix('char_').replace('_','-')+'.json'); p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n'); return new_ref

def update_char_command(ref, span, label, scope, higher, rank=None, location=LOC):
 p=char_path(ref)
 if not p: raise RuntimeError(('missing exact char', ref))
 d=json.loads(p.read_text())
 old_authority=d.get('authority')
 d['role']=label
 d['current_location']=location
 career=d.setdefault('career_state',{})
 history=career.setdefault('assignment_history',[])
 history.append({'kind':'field_reassignment','prior_authority':old_authority,'new_role':label,'at':NOW})
 del history[:-16]
 career.update({'career_changes':int(career.get('career_changes',0)),'current_billet':'formation_commander','current_command_span':span,'office_or_command':label})
 d['command_assignment']={'billet':'formation_commander','current_command_span':span,'external_to_fighting_establishment':True,'formation_ref':scope}
 d['military_command']={'external_to_fighting_strength':True,'formation_scope':scope,'level':f'{span}_commander','higher_commander_ref':higher}
 d['military_rank']={'durable':True,'grade':rank or (f'{span}_commander' if span in {500,1000,2000,4000} else 'unranked')}
 d['authority']=('Tang Wei field officer commanding Qin-owned troops; Qin retains administrative troop ownership.' if ref.startswith('char_qin_wei_unit_') else 'House Tang field officer under Tang Wei active field command.')
 # Preserve existing institutional/House membership. Reassignment changes current
 # duty and training context, not the person's durable affiliation.
 d.setdefault('goal_state',{})['institutional_duties']=[label]
 activity=d.setdefault('activity_contract',{})
 activity['autonomous_enabled']=True
 activity['mode']='standing_role_training'
 activity['training_regimen_ref']='elite_command' if ref=='char_lin_zhen' else 'professional_officer'
 p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')

def group(ref,name,commander,units,strength,doctrine,parent,mission,authority='char_tang_wei',roles=None,direct=None):
 return {'schema':'command-group','id':ref,'display_name':name,'context':'field_army' if parent is None else 'nested_army','authority_ref':authority,'commander_ref':commander,'direct_person_refs':direct or [],'role_assignments':roles or {},'successor_refs':[],'units':[{'kind':k,'ref':r} for k,r in units],'standing_order_refs':[],'standing_doctrine_ref':doctrine,'communication_ref':None,'location':LOC,'parent_command_group_ref':parent,'updated_at':NOW,'created_at':NOW,'organizational_state':{'authorized_direct_unit_slots':len(units),'authorized_strength':strength,'current_direct_formation_strength':0,'current_recursive_strength':strength,'direct_unit_count':len(units),'mission':mission,'recursive_formation_count':0,'reorganization_need':'none','status':'active'},'active_context_ref':'operation_arc_131572c4e8a2892bbc'}
def saveg(g): save('state/cmd/command-groups/'+g['id']+'.json',g)

def write_doctrines():
 docs={
 'doc.tang_wei.field_army':{'label':'Tang Wei Army: protected command, mission pressure, decisive commander intervention','scope':'command_group','command_policy_v2':{'strategic_posture':'adaptive_decisive_maneuver','risk_tolerance':'assertive','reserve_posture':'ready_counterstroke','information_priority':'very_high','subordinate_initiative':'very_high','pursuit_policy':'controlled','revision_speed':'rapid'},'principles':['Black Banner fights the main battle. High Guard preserves headquarters and command continuity. Red Lance preserves Tang Wei and enables decisive personal intervention.','Enemy command locations require real observation, reports, scouts, standards, prisoners or courier intelligence; doctrine grants no omniscience.']},
 'doc.tang_wei.red_lance':{'label':'Red Lance commander-protection doctrine','scope':'formation','formation_policy_v2':{'battlefield_role':'elite_mobile_intervention','contact_style':'protective','charge_policy':'opportunity_only','pursuit_policy':'none','disengagement':'protected_withdrawal'},'principles':['Anchor on Tang Wei current physical position. Preserve his life, mobility, target route and extraction corridor.','Never autonomously pursue or detach. A 500-man detachment requires an explicit lawful order.','Prevent ordinary troops from swamping Wei and isolate high-priority command-node contact when physically possible.']},
 'doc.tang_wei.high_guard':{'label':'High Guard headquarters-preservation doctrine','scope':'formation','formation_policy_v2':{'battlefield_role':'guard_support','contact_style':'protective','charge_policy':'advantage_required','pursuit_policy':'none','disengagement':'hold_until_ordered'},'principles':['Anchor on Tang Wei Army headquarters wherever headquarters physically relocates.','The permanent 3,000 Tang Infantry core never reinforces Black Banner away from headquarters.','The 500 Tang Cavalry remains local HQ interception/protection. Only the 1,000 Qin reserve is outward-flexible by default.']},
 'doc.tang_wei.black_banner':{'label':'Black Banner mission-first battle doctrine','scope':'formation','formation_policy_v2':{'battlefield_role':'line_assault','contact_style':'ordered','charge_policy':'advantage_required','pursuit_policy':'controlled','disengagement':'protected_withdrawal'},'principles':['Accomplish the assigned objective: hold, attack, fix, cross, expose reserves and absorb ordinary operational attrition.','Mission-first casualty tolerance is not suicidal expendability; impossible objectives still require revision, withdrawal or reinforcement.']},
 'doc.house_tang.home_defense':{'label':'House Tang layered home-defense doctrine','scope':'command_group','command_policy_v2':{'strategic_posture':'defensive_counterstroke','risk_tolerance':'measured','reserve_posture':'deep_protected','information_priority':'high','subordinate_initiative':'bounded','pursuit_policy':'restrained','revision_speed':'responsive'}}}
 for did,doctrine in docs.items(): save('game/data/mil/doctrine-records/'+did+'.json',{'schema':'doctrine-record','id':did,'doctrine':doctrine})
 reg=load('game/data/mil/doctrines.json'); mp=reg.setdefault('doctrines',reg if isinstance(reg.get('doctrines'),dict) else {})
 # registry is top-level mapping in this repository
 if 'doctrines' not in reg:
  for did in docs: reg[did]='game/data/mil/doctrine-records/'+did+'.json'
 else:
  for did in docs: mp[did]='game/data/mil/doctrine-records/'+did+'.json'
 # remove stale active Tang Wei old taxonomy records from registry + files
 for key in list(reg.keys()):
  if key.startswith('doc.tang_wei.') and key not in docs and isinstance(reg.get(key),str): reg.pop(key,None)
 if isinstance(reg.get('doctrines'),dict):
  for key in list(reg['doctrines']):
   if key.startswith('doc.tang_wei.') and key not in docs: reg['doctrines'].pop(key,None)
 save('game/data/mil/doctrines.json',reg)
 for p in (ROOT/'game/data/mil/doctrine-records').glob('doc.tang_wei.*.json'):
  did=json.loads(p.read_text()).get('id')
  if did not in docs: p.unlink()

def main():
 house=load('state/forces/house-tang.json'); old_records=dematerialize_old_house_person_lite(house); recompute_force(house); save('state/forces/house-tang.json',house)
 # Save old templates and release exact 4,500 House field bodies.
 house_old=['formation_tang_champions_first','formation_tang_champions_second','formation_tang_champions_hq','formation_tang_wei_house_guard','formation_tang_wei_house_guard_duan','formation_tang_wei_house_guard_shen_rui','formation_tang_wei_house_guard_gao_yun','formation_tang_wei_house_guard_han_qiu']
 house_templates={r:loadf(r) for r in house_old}
 for r in house_old:
  ff,n=release_formation(house,r,LOC)
  if n!=int(ff['personnel']): raise RuntimeError(('house release mismatch',r,n,ff['personnel']))
 # Mounts: release old House field allocations, then allocate only 1,500 cavalry horses.
 hm=load('state/mounts/house-tang.json'); freed=0
 for r in house_old:
  row=hm.get('allocated_to_formations',{}).pop(r,None)
  if isinstance(row,dict): freed+=int(row.get('horse',0))
 hm.setdefault('regional_reserve',{}).setdefault(LOC,{})
 hm['regional_reserve'][LOC]['horse']=int(hm['regional_reserve'][LOC].get('horse',0))+freed
 # Promote 14 distinct parent commanders from the strongest old person-lite command candidates.
 candidates=[]
 for rec in old_records.values():
  stats=rec.get('stats',{}).get('skills',{}); scale=int(rec.get('command_assignment',{}).get('scale',0) or 0)
  if scale<500: continue
  score=float(stats.get('Formation Command',0))+float(stats.get('Leadership',0))+float(stats.get('Tactics',0))+0.5*float(stats.get('Strategy',0))+0.25*float(stats.get('Awareness',0))
  candidates.append((score,rec))
 candidates.sort(key=lambda x:x[0],reverse=True)
 used=[]
 def promote_for(tag,span,label,scope,higher,prefer_cav=False):
  pick=None
  for _,rec in candidates:
   if rec.get('id') in used: continue
   src=house['cohort_ledger']['cohorts'].get(rec.get('source_cohort_ref'),{}); role=src.get('role')
   if prefer_cav and role!='house_cavalry': continue
   if (not prefer_cav) and role!='house_infantry': continue
   if not any(int(v)>0 for v in src.get('reserve_by_location',{}).values()): continue
   pick=rec; break
  if pick is None:
   for _,rec in candidates:
    if rec.get('id') in used: continue
    src=house['cohort_ledger']['cohorts'].get(rec.get('source_cohort_ref'),{})
    if any(int(v)>0 for v in src.get('reserve_by_location',{}).values()): pick=rec; break
  if pick is None:
   # Recovery may have already collapsed the old person-lite rank rosters. Materialize
   # the same kind of conserved command candidate directly from a reserve cohort.
   desired='house_cavalry' if prefer_cav else 'house_infantry'
   chosen=None; home_loc=None
   for cid,src in house['cohort_ledger']['cohorts'].items():
    if src.get('role')!=desired: continue
    for loc,n in src.get('reserve_by_location',{}).items():
     if loc!=LOC and int(n)>0: chosen=(cid,src); home_loc=loc; break
    if chosen: break
   if chosen is None: raise RuntimeError('not enough command candidates')
   cid,src=chosen
   pick={'id':'recovery_candidate_'+tag,'name':'Tang '+tag.replace('_',' ').title(),'source_cohort_ref':cid,'current_location':home_loc,
         'stats':{'attributes':copy.deepcopy(src.get('attribute_means',{})),'skills':copy.deepcopy(src.get('skill_means',{}))},
         'aptitude':copy.deepcopy(src.get('aptitude_means',{})),'professional_skills':copy.deepcopy(src.get('professional_skill_means',{})),
         'development_state':{},'birth_date':'276-BCE-01-01','appearance':55}
  used.append(pick['id']); ref='char_tang_command_'+tag
  return promote_record(house,pick,ref,span=span,role_label=label,scope=scope,higher=higher)
 red_parent=promote_for('red_lance_1000',1000,'Commander, Red Lance','cmdgrp.tang_wei.red_lance','char_tang_wei',True)
 black_parent=promote_for('black_banner_4000',4000,'Commander, Black Banner','cmdgrp.tang_wei.black_banner','char_tang_wei')
 black_w1=promote_for('black_banner_wing_1',2000,'2,000-man Commander, Black Banner First Wing','cmdgrp.tang_wei.black_banner.wing_1',black_parent)
 black_w2=promote_for('black_banner_wing_2',2000,'2,000-man Commander, Black Banner Second Wing','cmdgrp.tang_wei.black_banner.wing_2',black_parent)
 black_units=[promote_for(f'black_banner_unit_{i}',1000,f'1,000-man Commander, Black Banner Unit {i}',f'cmdgrp.tang_wei.black_banner.unit_{i}',black_w1 if i<=2 else black_w2) for i in range(1,5)]
 hg_foot=promote_for('high_guard_foot_core',3000,'3,000-man Commander, High Guard Foot Core','cmdgrp.tang_wei.high_guard.foot_core','char_lin_zhen')
 hg_wing=promote_for('high_guard_foot_wing',2000,'2,000-man Commander, High Guard Foot Wing','cmdgrp.tang_wei.high_guard.foot_wing',hg_foot)
 hg_units=[promote_for(f'high_guard_unit_{i}',1000,f'1,000-man Commander, High Guard Infantry Unit {i}',f'cmdgrp.tang_wei.high_guard.unit_{i}',hg_wing if i<=2 else hg_foot) for i in range(1,4)]
 hg_qin=promote_for('high_guard_qin_reserve',1000,'1,000-man Commander, High Guard Qin Reserve','cmdgrp.tang_wei.high_guard.qin_reserve','char_lin_zhen')
 # Existing exact leaf commanders.
 hg_inf_leaf=['char_sword_manor_trainee_commander','char_sword_manor_trainee_training_officer','char_sword_manor_junior_commander','char_sword_manor_junior_training_officer','char_sword_manor_general_commander','char_sword_manor_general_training_officer']
 for i,ref in enumerate(hg_inf_leaf): update_char_command(ref,500,f'500-man Commander, High Guard Infantry {i+1}',f'formation_high_guard_infantry_{i//2+1:02d}{"ab"[i%2]}',hg_units[i//2],rank='500_commander')
 update_char_command('char_gao_yun',500,'500-man Commander, High Guard Qin Reserve A','formation_high_guard_qin_a',hg_qin,rank='500_commander')
 update_char_command('char_han_qiu',500,'500-man Commander, High Guard Qin Reserve B','formation_high_guard_qin_b',hg_qin,rank='500_commander')
 update_char_command('char_ren_qiao',500,'500-man Commander, High Guard Cavalry','formation_high_guard_cavalry','char_lin_zhen',rank='500_commander')
 update_char_command('char_duan_jin',500,'500-man Commander, Red Lance A','formation_red_lance_a',red_parent,rank='500_commander')
 update_char_command('char_shen_rui',500,'500-man Commander, Red Lance B','formation_red_lance_b',red_parent,rank='500_commander')
 update_char_command('char_lin_zhen',4500,'Commander, High Guard; Chief Strategist, Tang Wei Army','cmdgrp.tang_wei.high_guard','char_tang_wei',rank='unranked')
 # Allocate House leaf bodies. Prefer old veteran cohorts at the field location.
 cav_t=house_templates['formation_tang_champions_first']; inf_t=house_templates['formation_tang_wei_house_guard_duan']
 for ref,name,cmd in [('formation_red_lance_a','Red Lance A','char_duan_jin'),('formation_red_lance_b','Red Lance B','char_shen_rui')]:
  allocate_formation(house,ref,name,{'house_cavalry':500},cav_t,cmd,'cmdgrp.tang_wei.red_lance','doc.tang_wei.red_lance','train.house_tang.house_cavalry',{'house_cavalry':'loadout_tang_mounted'})
 for i,cmd in enumerate(hg_inf_leaf):
  ref=f'formation_high_guard_infantry_{i//2+1:02d}{"ab"[i%2]}'
  allocate_formation(house,ref,f'High Guard Infantry {i//2+1}{"AB"[i%2]}',{'house_infantry':500},inf_t,cmd,f'cmdgrp.tang_wei.high_guard.unit_{i//2+1}','doc.tang_wei.high_guard','train.house_tang.house_infantry',{'house_infantry':'loadout_tang_foot'})
 allocate_formation(house,'formation_high_guard_cavalry','High Guard Cavalry',{'house_cavalry':500},cav_t,'char_ren_qiao','cmdgrp.tang_wei.high_guard','doc.tang_wei.high_guard','train.house_tang.house_cavalry',{'house_cavalry':'loadout_tang_mounted'})
 # House mount allocation.
 for ref in ['formation_red_lance_a','formation_red_lance_b','formation_high_guard_cavalry']:
  if int(hm['regional_reserve'][LOC].get('horse',0))<500: raise RuntimeError('house horse shortage')
  hm['regional_reserve'][LOC]['horse']-=500; hm.setdefault('allocated_to_formations',{})[ref]={'horse':500}
 save('state/mounts/house-tang.json',hm); recompute_force(house); save('state/forces/house-tang.json',house)
 # Qin: dematerialize the 24 embedded old command-cadre person-lite bodies, release 16,800, then reissue 5,000.
 qin=load('state/forces/state-qin.json'); qold=[f'formation_qin_wei_unit_{i:02d}' for i in range(1,9)]; demat_qin_internal(qin,qold)
 qtemplates={r:loadf(r) for r in qold}; released_pref=defaultdict(list)
 for r in qold:
  # remember cohort IDs serving Wei before release so the new 5,000 draws from the same veteran pool first
  for cid,c in qin['cohort_ledger']['cohorts'].items():
   if int(c.get('allocated_by_formation',{}).get(r,0))>0 and cid not in released_pref[str(c.get('role'))]: released_pref[str(c.get('role'))].append(cid)
  ff,n=release_formation(qin,r,LOC)
  if n!=int(ff['personnel']): raise RuntimeError(('qin release mismatch',r,n,ff['personnel']))
 qm=load('state/mounts/qin.json'); qfreed=0
 for r in qold:
  row=qm.get('allocated_to_formations',{}).pop(r,None)
  if isinstance(row,dict): qfreed+=int(row.get('horse',0))
 qm.setdefault('regional_reserve',{}).setdefault(LOC,{})
 qm['regional_reserve'][LOC]['horse']=int(qm['regional_reserve'][LOC].get('horse',0))+qfreed
 # 10 x 500 leaves with five 1,000-equivalent totals of 750/125/75/50.
 leaf_comps=[]
 for i in range(10):
  leaf_comps.append({'line_infantry':375,'archer':62 if i%2==0 else 63,'light_cavalry':38 if i%2==0 else 37,'heavy_cavalry':25})
 # High Guard Qin reserve leaves.
 qtmpl=qtemplates[qold[0]]
 for ref,name,cmd,comp in [('formation_high_guard_qin_a','High Guard Qin Reserve A','char_gao_yun',leaf_comps[0]),('formation_high_guard_qin_b','High Guard Qin Reserve B','char_han_qiu',leaf_comps[1])]:
  allocate_formation(qin,ref,name,comp,qtmpl,cmd,'cmdgrp.tang_wei.high_guard.qin_reserve','doc.tang_wei.high_guard',qtmpl.get('training_ref','train.qin.combined'),preferred=released_pref)
 # Black Banner eight 500s.
 bb_cmds=['char_qin_wei_unit_01_commander','char_qin_wei_unit_02_commander','char_qin_wei_unit_03_commander','char_qin_wei_unit_04_commander','char_han_shou','char_pei_rong','char_deng_kai','char_lu_cheng']
 for i,cmd in enumerate(bb_cmds,1):
  unit=(i+1)//2; suffix='a' if i%2 else 'b'; ref=f'formation_black_banner_{unit:02d}{suffix}'; comp=leaf_comps[i+1]
  allocate_formation(qin,ref,f'Black Banner {unit}{suffix.upper()}',comp,qtmpl,cmd,f'cmdgrp.tang_wei.black_banner.unit_{unit}','doc.tang_wei.black_banner',qtmpl.get('training_ref','train.qin.combined'),preferred=released_pref)
  update_char_command(cmd,500,f'500-man Commander, Black Banner {unit}{suffix.upper()}',ref,black_units[unit-1],rank='500_commander')
 # Reallocate exactly 625 horses to new Qin cavalry bodies.
 for ref in ['formation_high_guard_qin_a','formation_high_guard_qin_b']+[f'formation_black_banner_{u:02d}{s}' for u in range(1,5) for s in 'ab']:
  ff=loadf(ref); horses=sum(int(v) for k,v in ff['composition'].items() if 'cavalry' in k)
  if int(qm['regional_reserve'][LOC].get('horse',0))<horses: raise RuntimeError('qin horse shortage')
  qm['regional_reserve'][LOC]['horse']-=horses; qm.setdefault('allocated_to_formations',{})[ref]={'horse':horses}; ff['mounts']={'horse':horses}; savef(ff)
 save('state/mounts/qin.json',qm); recompute_force(qin); save('state/forces/state-qin.json',qin)
 # Remove old Tang Wei command tree except the root, then build exact hierarchy.
 for p in (ROOT/'state/cmd/command-groups').glob('cmdgrp.tang_wei.*.json'):
  if p.name!='cmdgrp.tang_wei.field_army.json': p.unlink()
 saveg(group('cmdgrp.tang_wei.red_lance','Red Lance',red_parent,[('formation','formation_red_lance_a'),('formation','formation_red_lance_b')],1000,'doc.tang_wei.red_lance','cmdgrp.tang_wei.field_army','commander_protection'))
 # High Guard units / wing / core / reserve.
 for i in range(1,4):
  refs=[('formation',f'formation_high_guard_infantry_{i:02d}a'),('formation',f'formation_high_guard_infantry_{i:02d}b')]
  parent='cmdgrp.tang_wei.high_guard.foot_wing' if i<=2 else 'cmdgrp.tang_wei.high_guard.foot_core'
  saveg(group(f'cmdgrp.tang_wei.high_guard.unit_{i}',f'High Guard Infantry Thousand {i}',hg_units[i-1],refs,1000,'doc.tang_wei.high_guard',parent,'hq_infantry_thousand'))
 saveg(group('cmdgrp.tang_wei.high_guard.foot_wing','High Guard Foot Wing',hg_wing,[('nested_army','cmdgrp.tang_wei.high_guard.unit_1'),('nested_army','cmdgrp.tang_wei.high_guard.unit_2')],2000,'doc.tang_wei.high_guard','cmdgrp.tang_wei.high_guard.foot_core','hq_infantry_wing'))
 saveg(group('cmdgrp.tang_wei.high_guard.foot_core','High Guard Permanent Tang Infantry Core',hg_foot,[('nested_army','cmdgrp.tang_wei.high_guard.foot_wing'),('nested_army','cmdgrp.tang_wei.high_guard.unit_3')],3000,'doc.tang_wei.high_guard','cmdgrp.tang_wei.high_guard','permanent_hq_infantry_core'))
 saveg(group('cmdgrp.tang_wei.high_guard.qin_reserve','High Guard Qin Reserve',hg_qin,[('formation','formation_high_guard_qin_a'),('formation','formation_high_guard_qin_b')],1000,'doc.tang_wei.high_guard','cmdgrp.tang_wei.high_guard','flexible_qin_reserve'))
 saveg(group('cmdgrp.tang_wei.high_guard','High Guard','char_lin_zhen',[('nested_army','cmdgrp.tang_wei.high_guard.foot_core'),('nested_army','cmdgrp.tang_wei.high_guard.qin_reserve'),('formation','formation_high_guard_cavalry')],4500,'doc.tang_wei.high_guard','cmdgrp.tang_wei.field_army','headquarters_command',roles={'char_lin_zhen':'strategist'}))
 # Black Banner hierarchy.
 for i in range(1,5):
  refs=[('formation',f'formation_black_banner_{i:02d}a'),('formation',f'formation_black_banner_{i:02d}b')]; parent='cmdgrp.tang_wei.black_banner.wing_1' if i<=2 else 'cmdgrp.tang_wei.black_banner.wing_2'
  saveg(group(f'cmdgrp.tang_wei.black_banner.unit_{i}',f'Black Banner Thousand {i}',black_units[i-1],refs,1000,'doc.tang_wei.black_banner',parent,'main_battle_thousand'))
 saveg(group('cmdgrp.tang_wei.black_banner.wing_1','Black Banner First Wing',black_w1,[('nested_army','cmdgrp.tang_wei.black_banner.unit_1'),('nested_army','cmdgrp.tang_wei.black_banner.unit_2')],2000,'doc.tang_wei.black_banner','cmdgrp.tang_wei.black_banner','main_battle_wing'))
 saveg(group('cmdgrp.tang_wei.black_banner.wing_2','Black Banner Second Wing',black_w2,[('nested_army','cmdgrp.tang_wei.black_banner.unit_3'),('nested_army','cmdgrp.tang_wei.black_banner.unit_4')],2000,'doc.tang_wei.black_banner','cmdgrp.tang_wei.black_banner','main_battle_wing'))
 saveg(group('cmdgrp.tang_wei.black_banner','Black Banner',black_parent,[('nested_army','cmdgrp.tang_wei.black_banner.wing_1'),('nested_army','cmdgrp.tang_wei.black_banner.wing_2')],4000,'doc.tang_wei.black_banner','cmdgrp.tang_wei.field_army','main_battle_workhorse'))
 army=group('cmdgrp.tang_wei.field_army','Tang Wei Army','char_tang_wei',[('nested_army','cmdgrp.tang_wei.red_lance'),('nested_army','cmdgrp.tang_wei.high_guard'),('nested_army','cmdgrp.tang_wei.black_banner')],9500,'doc.tang_wei.field_army',None,'field_army',roles={'char_lin_zhen':'chief_strategist'},direct=['char_lin_zhen']); army['successor_refs']=['char_lin_zhen']; saveg(army)
 write_doctrines()
 # Current operation now references only Wei's actual 9,500; Hi Shin is no longer nested here (phase 3 will rebaseline its independent command).
 op=load('state/operations/operation_arc_131572c4e8a2892bbc.json'); op['command_group_ref']='cmdgrp.tang_wei.field_army'; op['authority_basis']['command_group_ref']='cmdgrp.tang_wei.field_army'; op['formation_refs']=['formation_red_lance_a','formation_red_lance_b']+[f'formation_high_guard_infantry_{i:02d}{s}' for i in range(1,4) for s in 'ab']+['formation_high_guard_cavalry','formation_high_guard_qin_a','formation_high_guard_qin_b']+[f'formation_black_banner_{i:02d}{s}' for i in range(1,5) for s in 'ab']; save('state/operations/operation_arc_131572c4e8a2892bbc.json',op)
 # Clean old command personnel index entries that pointed into deleted old House person-lite rosters; exact chars route through owner index later.
 cp=load('state/cmd/command-personnel.json'); idx=cp.get('record_index',{})
 if isinstance(idx,dict):
  cp['record_index']={k:v for k,v in idx.items() if not any(x in str(v) for x in ('house-tang-guardian-cavalry.json','house-tang-house-guard.json','house-tang-tang-champions.json','sword-manor-'))}; cp['count']=len(cp['record_index'])
 save('state/cmd/command-personnel.json',cp)
 print('phase2 complete: Tang Wei Army 9500')
if __name__=='__main__': main()
