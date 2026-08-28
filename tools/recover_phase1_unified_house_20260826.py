#!/usr/bin/env python3
from __future__ import annotations
import copy, json, hashlib
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
NOW='244-BCE-09-09T20:22:48+08:00'
HOUSE_PATH=ROOT/'state/forces/house-tang.json'
SOURCE_FORCE_PATHS=[
 ROOT/'state/forces/house-tang.json', ROOT/'state/forces/sword-manor.json',
 ROOT/'state/forces/bastion-iron-wall.json', ROOT/'state/forces/bastion-red-thunder.json',
 ROOT/'state/forces/bastion-white-blade.json', ROOT/'state/forces/bastion-stone-spear.json',
]
OLD_OWNERS={
 'force_house_tang','force_sword_manor','force_bastion_iron_wall','force_bastion_red_thunder','force_bastion_white_blade','force_bastion_stone_spear'
}
ROLE_MAP={
 'guardian_cavalry':'house_cavalry','tang_champion':'house_cavalry',
 'house_guard':'house_infantry','trainee':'house_infantry','junior_disciple':'house_infantry',
 'general_disciple':'house_infantry','senior_disciple':'house_infantry','bastion_archer':'house_infantry',
 'bastion_crossbow':'house_infantry','bastion_heavy_infantry':'house_infantry','bastion_artillery':'house_infantry',
 'house_infantry':'house_infantry','house_cavalry':'house_cavalry',
}
# Old field formations are handled by phase 2 because all 4,500 bodies remain with Wei.
FIELD_OLD={
 'formation_tang_champions_first','formation_tang_champions_second','formation_tang_champions_hq',
 'formation_tang_wei_house_guard','formation_tang_wei_house_guard_duan','formation_tang_wei_house_guard_shen_rui',
 'formation_tang_wei_house_guard_gao_yun','formation_tang_wei_house_guard_han_qiu',
}

def j(path:Path): return json.loads(path.read_text())
def put(path:Path,obj): path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
def form_path(ref):
 for p in (ROOT/'state/formations').glob('*.json'):
  try:
   if j(p).get('formation_ref')==ref:return p
  except Exception: pass
 raise FileNotFoundError(ref)
def form_slug(ref): return ref.removeprefix('formation_').replace('_','-')+'.json'

def rename_map():
 m={}
 for i in range(1,16): m[f'formation_bastion_iron_wall_{i:02d}']=f'formation_house_tang_outer_wall_iron_wall_{i:02d}'
 for i in range(1,5): m[f'formation_bastion_red_thunder_{i:02d}']=f'formation_house_tang_outer_wall_red_thunder_{i:02d}'
 for i in range(1,4): m[f'formation_bastion_stone_spear_{i:02d}']=f'formation_house_tang_outer_wall_stone_spear_{i:02d}'
 for i in range(1,5): m[f'formation_bastion_white_blade_{i:02d}']=f'formation_house_tang_outer_wall_white_blade_{i:02d}'
 m.update({
  'formation_sword_manor_general_01':'formation_house_tang_inner_walls_general_01',
  'formation_sword_manor_junior_01':'formation_house_tang_inner_walls_junior_01',
  'formation_sword_manor_senior_01':'formation_house_tang_inner_walls_senior_01',
  **{f'formation_sword_manor_trainee_{i:02d}':f'formation_house_tang_inner_walls_trainee_{i:02d}' for i in range(1,5)},
  **{f'formation_house_tang_guardian_cavalry_{i:02d}':f'formation_house_tang_cavalry_{i:02d}' for i in range(1,5)},
  **{f'formation_house_tang_tang_champion_{i:02d}':f'formation_house_tang_cavalry_elite_{i:02d}' for i in range(1,5)},
  **{f'formation_house_tang_house_guard_{i:02d}':f'formation_house_tang_infantry_{i:02d}' for i in range(1,4)},
 })
 return m
FORM_MAP=rename_map()
FORCE_MAP={k:'force_house_tang' for k in OLD_OWNERS}
GROUP_MAP={
 'cmdgrp.sword_manor.field':'cmdgrp.house_tang.inner_walls','cmdgrp.sword_manor.senior':'cmdgrp.house_tang.inner_walls',
 'cmdgrp.sword_manor.general':'cmdgrp.house_tang.inner_walls','cmdgrp.sword_manor.junior':'cmdgrp.house_tang.inner_walls','cmdgrp.sword_manor.trainee':'cmdgrp.house_tang.inner_walls',
 'cmdgrp.bastion.iron_wall':'cmdgrp.house_tang.outer_wall','cmdgrp.bastion.red_thunder':'cmdgrp.house_tang.outer_wall',
 'cmdgrp.bastion.white_blade':'cmdgrp.house_tang.outer_wall','cmdgrp.bastion.stone_spear':'cmdgrp.house_tang.outer_wall',
 'cmdgrp.house_tang.guardian_cavalry':'cmdgrp.house_tang.inner_citadel','cmdgrp.house_tang.house_guard':'cmdgrp.house_tang.inner_citadel',
 'cmdgrp.house_tang.champions':'cmdgrp.house_tang.inner_citadel',
}
PROGRAM_MAP={
 'program.sword_officer':'program.commander_combined_arms','program.sword_senior_command':'program.commander_combined_arms',
 'program.bastion_senior_command':'program.commander_combined_arms','program.commander_guard':'program.commander_infantry',
 'program.commander_champion':'program.commander_cavalry','program.house_guard':'program.house_infantry',
 'program.guardian_cavalry':'program.house_cavalry','program.tang_champion':'program.house_cavalry',
 'program.sword_trainee':'program.house_infantry','program.sword_junior':'program.house_infantry',
 'program.sword_general':'program.house_infantry','program.sword_senior':'program.house_infantry',
}
TRAIN_MAP={
 'train.house_tang_internal.house_guard':'train.house_tang.house_infantry','train.house_tang_internal.heavy_cavalry':'train.house_tang.house_cavalry',
 'train.tang_wei.household_champions':'train.house_tang.house_cavalry',
}

def mapped_role(role): return ROLE_MAP.get(str(role),str(role))
def deep_map(v):
 if isinstance(v,dict):
  return {k:deep_map(x) for k,x in v.items()}
 if isinstance(v,list): return [deep_map(x) for x in v]
 if isinstance(v,str):
  if v in FORM_MAP:return FORM_MAP[v]
  if v in FORCE_MAP:return FORCE_MAP[v]
  if v in GROUP_MAP:return GROUP_MAP[v]
  if v in PROGRAM_MAP:return PROGRAM_MAP[v]
  if v in TRAIN_MAP:return TRAIN_MAP[v]
  if v in ROLE_MAP:return ROLE_MAP[v]
  return v
 return v

def relevant_person_lite_files():
 names=['house-tang-guardian-cavalry.json','house-tang-house-guard.json','house-tang-tang-champions.json','sword-manor-general-disciples.json','sword-manor-junior-disciples.json','sword-manor-senior-disciples.json','sword-manor-trainees.json']
 return [ROOT/'state/person/person-lite'/x for x in names if (ROOT/'state/person/person-lite'/x).exists()]

def collapse_person_lites(forces):
 records=[]
 by_owner={f['owner_id']:f for f in forces}
 # person-lite records carry source cohort IDs, enough to locate their authoritative force.
 cohort_owner={cid:f for f in forces for cid in f.get('cohort_ledger',{}).get('cohorts',{})}
 for p in relevant_person_lite_files():
  d=j(p); recs=d.get('records',{})
  it=recs.items() if isinstance(recs,dict) else ((r.get('id'),r) for r in recs)
  for rid,rec0 in it:
   if not rid: continue
   rec=copy.deepcopy(rec0); rec.setdefault('id',rid); records.append(rec)
   cid=rec.get('source_cohort_ref'); force=cohort_owner.get(cid)
   if not force or rid not in force.get('materialized_people',{}): continue
   a=force.get('materialized_assignments',{}).pop(rid,None)
   c=force['cohort_ledger']['cohorts'][cid]
   ref=str(a.get('formation_ref')) if isinstance(a,dict) and a.get('formation_ref') else ''
   # Every embedded old officer is still one fighting-establishment body.
   # Dematerialization returns it to that exact formation/cohort, never to
   # reserve merely because the old prestige institution is being collapsed.
   if ref:
    c.setdefault('allocated_by_formation',{})[ref]=int(c.setdefault('allocated_by_formation',{}).get(ref,0))+1
    try:
     fp=form_path(ref); ff=j(fp); rows=ff.setdefault('cohort_composition',[])
     for row in rows:
      if isinstance(row,dict) and row.get('cohort_id')==cid:
       row['count']=int(row.get('count',0))+1; break
     else: rows.append({'cohort_id':cid,'count':1})
     put(fp,ff)
    except FileNotFoundError:
     pass
   else:
    loc=str(rec.get('current_location') or c.get('home_location_ref') or force.get('source_location_ref') or 'loc_tang_manor_garrison_yard')
    c.setdefault('reserve_by_location',{})[loc]=int(c.setdefault('reserve_by_location',{}).get(loc,0))+1
   force.get('materialized_people',{}).pop(rid,None)
  p.unlink()
 return records

def merge_forces(forces):
 base=copy.deepcopy(next(f for f in forces if f['owner_id']=='force_house_tang'))
 cohorts={}
 for f in forces:
  for cid,c0 in f.get('cohort_ledger',{}).get('cohorts',{}).items():
   if cid in cohorts: raise RuntimeError('duplicate cohort '+cid)
   c=deep_map(copy.deepcopy(c0)); c['role']=mapped_role(c.get('role'))
   # rewrite formation allocation keys explicitly (deep_map does not transform dict keys)
   for key in ('allocated_by_formation','allocated_external_by_formation'):
    if isinstance(c.get(key),dict): c[key]={FORM_MAP.get(str(k),str(k)):int(v) for k,v in c[key].items()}
   cohorts[cid]=c
 base['owner_id']='force_house_tang'; base['administrative_owner']='house_tang'; base['headcount']=176060; base['authorized_strength']=176060
 base['authorized_by_role']={'house_infantry':164060,'house_cavalry':12000}; base['command_hierarchy_ref']='cmdgrp.house_tang.field_army'
 base['cohort_ledger']={'cohorts':cohorts}
 base['materialized_people']={}; base['materialized_assignments']={}; base['external_personnel_allocations']={}
 # Preserve/coalesce non-manpower convenience fields while removing extinct branches.
 base['fighting_establishment']={'house_infantry':164060,'house_cavalry':12000}
 base['officer_establishment']={'representation':'exact_named_500_plus_commanders_with_aggregate_sub500_cadre','principle':'command billet is not a troop species'}
 # Aggregate reserve and formation projections from cohort authority.
 recompute(base)
 return base

def recompute(force):
 reserve=defaultdict(int); byloc=defaultdict(lambda:defaultdict(int)); alloc=defaultdict(int); comp=defaultdict(lambda:defaultdict(int)); ext=defaultdict(lambda:defaultdict(int))
 for c in force['cohort_ledger']['cohorts'].values():
  role=str(c.get('role',''))
  for loc,n in c.get('reserve_by_location',{}).items(): reserve[role]+=int(n); byloc[str(loc)][role]+=int(n)
  for ref,n in c.get('allocated_by_formation',{}).items(): alloc[str(ref)]+=int(n); comp[str(ref)][role]+=int(n)
  for ref,n in c.get('allocated_external_by_formation',{}).items():
   if int(n): ext[str(ref)][role]+=int(n)
 for ref,a in force.get('materialized_assignments',{}).items():
  if isinstance(a,dict) and a.get('formation_ref'):
   n=max(1,int(a.get('personnel',1))); role=mapped_role(a.get('role')); alloc[str(a['formation_ref'])]+=n; comp[str(a['formation_ref'])][role]+=n
 force['available_by_role']=dict(sorted(reserve.items()))
 force['available_by_location']={k:dict(v) for k,v in sorted(byloc.items()) if sum(v.values())}
 force['allocated_to_formations']={r:{'personnel':alloc[r],'composition':dict(comp[r])} for r in sorted(alloc)}
 force['external_personnel_allocations']={r:dict(v) for r,v in sorted(ext.items()) if sum(v.values())}

def migrate_formations(house):
 for old,new in FORM_MAP.items():
  p=form_path(old); d=deep_map(j(p)); d['formation_ref']=new; d['owner_force_ref']='force_house_tang'; d['administrative_owner']='house_tang';
  # every old home defender is infantry except the original House mounted formations.
  comp=defaultdict(int)
  for role,n in d.get('composition',{}).items(): comp[mapped_role(role)]+=int(n)
  d['composition']=dict(comp); d['establishment_composition']=dict(comp); d['equipment_units_by_role']=dict(comp)
  if set(comp)=={'house_cavalry'}:
   d['registered_loadout_ref']='loadout_tang_mounted'; d['training_ref']='train.house_tang.house_cavalry'; d['doctrine_ref']='doc.house_tang_internal.heavy_cavalry'
   d['mounts']={'horse':sum(comp.values())}
  else:
   d['registered_loadout_ref']='loadout_tang_foot'; d['training_ref']='train.house_tang.house_infantry_outer_wall' if 'outer_wall' in new else 'train.house_tang.house_infantry'; d['doctrine_ref']='doc.house_tang_internal.standard'; d['mounts']={}
  d.pop('doctrine_refs_by_role',None); d.pop('training_refs_by_role',None); d['commander_ref']=None
  # cohort keys already renamed during merge; normalize cached composition roles only.
  d['cohort_composition']=[{'cohort_id':r['cohort_id'],'count':int(r['count'])} for r in d.get('cohort_composition',[]) if isinstance(r,dict) and r.get('cohort_id')]
  dst=ROOT/'state/formations'/form_slug(new); put(dst,d); p.unlink()
 recompute(house)

def choose_reserve_cohort(house,role,preferred_loc):
 candidates=[]
 for cid,c in house['cohort_ledger']['cohorts'].items():
  if c.get('role')!=role:continue
  r=c.get('reserve_by_location',{})
  candidates.append((0 if int(r.get(preferred_loc,0))>0 else 1,-sum(int(v) for v in r.values()),cid,c))
 for _,__,cid,c in sorted(candidates):
  for loc in (preferred_loc,'loc_tang_manor_garrison_yard','loc_tang_manor_training_ground','loc_tang_manor_defense_camp'):
   if int(c.get('reserve_by_location',{}).get(loc,0))>0:return cid,c,loc
  for loc,n in c.get('reserve_by_location',{}).items():
   if int(n)>0:return cid,c,loc
 raise RuntimeError('no reserve for '+role)

def name_for(ref):
 surnames=('Li','Wang','Meng','Zhang','Zhao','Bai','Fan','Huan','Gao','Lu','Tian','Sun','Jing','Du','Xu','Han','Pei','Shen','Zhou','Deng')
 givens=('Ren','Sheng','Jun','An','Yi','Ke','Rui','Zhen','Bo','Qian','Yong','Lin','Jie','He','Tao','Cheng','Ning','Ming','Shou','Rong')
 raw=int(hashlib.sha256(ref.encode()).hexdigest()[:12],16); return surnames[raw%len(surnames)]+' '+givens[(raw//len(surnames))%len(givens)]

def materialize_home_commanders(house, old_records):
 # Prefer historical named Sword/House officers, then deterministic conserved Bastion bodies.
 pool=[r for r in old_records if r.get('name')]
 used=set(); record_by_role=defaultdict(list)
 for r in pool:
  cid=r.get('source_cohort_ref'); c=house['cohort_ledger']['cohorts'].get(cid); role=c.get('role') if c else None
  if role: record_by_role[role].append(r)
 refs=[]
 for ref in sorted(FORM_MAP.values()):
  f=j(form_path(ref)); role='house_cavalry' if f.get('composition',{}).get('house_cavalry') else 'house_infantry'; loc=str(f.get('location_ref') or 'loc_tang_manor_garrison_yard')
  rec=None
  for cand in record_by_role[role]:
   if cand.get('id') not in used: rec=cand; used.add(cand.get('id')); break
  # The old Unit already owns one external command body. Materialize that
  # exact same conserved body as the named commander instead of consuming a
  # second reserve soldier.
  ext_candidates=[]
  for cid0,c0 in house['cohort_ledger']['cohorts'].items():
   held=int(c0.get('allocated_external_by_formation',{}).get(ref,0))
   if held>0: ext_candidates.append((cid0,c0,held))
  if len(ext_candidates)==1 and ext_candidates[0][2]==1:
   cid,c,_=ext_candidates[0]; c['allocated_external_by_formation'].pop(ref,None); source_mode='materialized_existing_external_command_slot'
  else:
   cid,c,rloc=choose_reserve_cohort(house,role,loc); c['reserve_by_location'][rloc]=int(c['reserve_by_location'][rloc])-1
   if c['reserve_by_location'][rloc]==0:c['reserve_by_location'].pop(rloc,None)
   source_mode='materialized_home_commander_from_reserve'
  slug=ref.removeprefix('formation_'); person_ref='char_cmd_'+slug
  house['materialized_people'][person_ref]={'personnel':1,'role':role,'source_cohort_ref':cid,'source_mode':source_mode}
  stats=(rec or {}).get('stats',{}) if isinstance((rec or {}).get('stats',{}),dict) else {}
  person={
   'schema':'sab_character','owner_id':person_ref,'owner_type':'character','name':(rec or {}).get('name') or name_for(person_ref),
   'birth_date':(rec or {}).get('birth_date','276-BCE-01-01'),'appearance':int((rec or {}).get('appearance',55)),
   'body':copy.deepcopy((rec or {}).get('body',{'adult_height_cm':174,'current_weight_kg':69,'frame':'athletic','growth_end_age':18})),
   'affiliation':['house_tang'],'role':f'Commander, {f.get("name",ref)}','life_status':'active','health_status':'fit','fatigue':0,
   'aptitude':copy.deepcopy((rec or {}).get('aptitude',{'physical_learning':110,'technical_learning':105,'tactical_learning':120,'academic_learning':95,'social_learning':100})),
   'attributes':copy.deepcopy(stats.get('attributes',{})),'skills':copy.deepcopy(stats.get('skills',{})),
   'current_location':loc,'current_formation_id':ref,'personal_loadout_ref':'loadout_tang_mounted' if role=='house_cavalry' else 'loadout_tang_foot',
   'military_rank':{'durable':True,'grade':'formation_commander'},
   'career_state':{'current_billet':'formation_commander','current_command_span':int(f.get('authorized_strength') or f.get('personnel') or 0),'office_or_command':f'Commander, {f.get("name",ref)}'},
   'command_assignment':{'billet':'formation_commander','current_command_span':int(f.get('authorized_strength') or f.get('personnel') or 0),'external_to_fighting_establishment':True,'formation_ref':ref},
   'military_command':{'external_to_fighting_strength':True,'formation_scope':ref,'level':'formation_commander'},
   'activity_contract':{'autonomous_enabled':True,'mode':'standing_role_training','training_program_ref':'program.commander_cavalry' if role=='house_cavalry' else 'program.commander_infantry','training_regimen_ref':'house_tang_max_sustainable'},
   'materialization_provenance':{'source_person_lite_ref':(rec or {}).get('id'),'source_cohort_ref':cid,'source_role':role,'reclassified_at':NOW},
  }
  put(ROOT/'state/char'/(person_ref.removeprefix('char_').replace('_','-')+'.json'),person)
  f['commander_ref']=person_ref; put(form_path(ref),f); refs.append(person_ref)
 recompute(house); return refs

def group(ref,name,commander,units,strength,parent,mission):
 return {'schema':'command-group','id':ref,'display_name':name,'context':'field_army' if parent is None else 'nested_army','authority_ref':'house_tang','commander_ref':commander,'direct_person_refs':[],'role_assignments':{},'successor_refs':[],'units':[{'kind':'formation','ref':x} for x in units],'standing_order_refs':[],'standing_doctrine_ref':'doc.house_tang.home_defense','communication_ref':None,'location':'loc_tang_manor','parent_command_group_ref':parent,'created_at':NOW,'updated_at':NOW,'organizational_state':{'authorized_direct_unit_slots':len(units),'authorized_strength':strength,'current_direct_formation_strength':strength,'current_recursive_strength':strength,'direct_unit_count':len(units),'mission':mission,'recursive_formation_count':len(units),'reorganization_need':'none','status':'active'}}

def update_group_char(ref,group_ref,span,label,higher=None):
 p=ROOT/'state/char'/(ref.removeprefix('char_').replace('_','-')+'.json'); d=j(p); d=deep_map(d); d['role']=label; d['current_formation_id']=None
 d['command_assignment']={'billet':'command_group_commander','current_command_span':span,'external_to_fighting_establishment':True,'command_group_ref':group_ref}
 d['military_command']={'external_to_fighting_strength':True,'formation_scope':group_ref,'level':f'{span}_commander','higher_commander_ref':higher}
 d.setdefault('career_state',{})['current_billet']='command_group_commander'; d['career_state']['current_command_span']=span; d['career_state']['office_or_command']=label
 d['activity_contract']={'autonomous_enabled':True,'mode':'standing_role_training','training_program_ref':'program.commander_combined_arms','training_regimen_ref':'house_tang_max_sustainable'}; put(p,d)

def create_home_groups():
 outer=sorted([x for x in FORM_MAP.values() if 'outer_wall' in x]); inner=sorted([x for x in FORM_MAP.values() if 'inner_walls' in x]); cit=sorted([x for x in FORM_MAP.values() if x not in set(outer)|set(inner)])
 def strength(refs): return sum(int(j(form_path(r)).get('personnel',0)) for r in refs)
 groups=[
  group('cmdgrp.house_tang.outer_wall','Outer Wall','char_lin_jiao',outer,strength(outer),'cmdgrp.house_tang.field_army','outer_wall_defense'),
  group('cmdgrp.house_tang.inner_walls','Inner Walls','char_pei_an',inner,strength(inner),'cmdgrp.house_tang.field_army','inner_walls_defense'),
  group('cmdgrp.house_tang.inner_citadel','Inner Citadel','char_wei_song',cit,strength(cit),'cmdgrp.house_tang.field_army','inner_citadel_reserve'),
 ]
 root={'schema':'command-group','id':'cmdgrp.house_tang.field_army','display_name':'House Tang Home Defense','context':'field_army','authority_ref':'house_tang','commander_ref':'char_tang_zhu','direct_person_refs':[],'role_assignments':{},'successor_refs':[],'units':[{'kind':'nested_army','ref':g['id']} for g in groups],'standing_order_refs':[],'standing_doctrine_ref':'doc.house_tang.home_defense','communication_ref':None,'location':'loc_tang_manor','parent_command_group_ref':None,'created_at':NOW,'updated_at':NOW,'organizational_state':{'authorized_direct_unit_slots':3,'authorized_strength':sum(g['organizational_state']['authorized_strength'] for g in groups),'current_direct_formation_strength':0,'current_recursive_strength':sum(g['organizational_state']['authorized_strength'] for g in groups),'direct_unit_count':3,'mission':'layered_home_defense','recursive_formation_count':44,'reorganization_need':'none','status':'active'}}
 # delete old House/Sword/Bastion hierarchy files
 for p in (ROOT/'state/cmd/command-groups').glob('*.json'):
  if p.name=='index.json':continue
  try:d=j(p); ref=d.get('id','')
  except Exception:continue
  if ref.startswith('cmdgrp.sword_manor') or ref.startswith('cmdgrp.bastion') or ref in {'cmdgrp.house_tang.guardian_cavalry','cmdgrp.house_tang.house_guard','cmdgrp.house_tang.champions','cmdgrp.house_tang.field_army'}: p.unlink()
 for g in groups+[root]: put(ROOT/'state/cmd/command-groups'/(g['id']+'.json'),g)
 update_group_char('char_tang_zhu',root['id'],root['organizational_state']['authorized_strength'],'House Tang Home Defense Commander')
 update_group_char('char_lin_jiao','cmdgrp.house_tang.outer_wall',groups[0]['organizational_state']['authorized_strength'],'Outer Wall Commander','char_tang_zhu')
 update_group_char('char_pei_an','cmdgrp.house_tang.inner_walls',groups[1]['organizational_state']['authorized_strength'],'Inner Walls Commander','char_tang_zhu')
 update_group_char('char_wei_song','cmdgrp.house_tang.inner_citadel',groups[2]['organizational_state']['authorized_strength'],'Inner Citadel Commander','char_tang_zhu')

def patch_static_and_runtime():
 # Doctrine records used by phase 2/home defense.
 docs={
  'doc.house_tang.home_defense':{'label':'House Tang Layered Home Defense','scope':'command_group','command_policy_v2':{'strategic_posture':'defensive_counterstroke','risk_tolerance':'measured','reserve_posture':'deep_protected','information_priority':'high','subordinate_initiative':'bounded','pursuit_policy':'restrained','revision_speed':'responsive'},'principles':['Outer Wall, Inner Walls and Inner Citadel are defensive layers, not separate troop species.','House Infantry and House Cavalry retain veteran capability by conserved cohort rather than promotion into prestige species.']},
 }
 for did,doc in docs.items(): put(ROOT/'game/data/mil/doctrine-records'/(did+'.json'),{'schema':'doctrine-record','id':did,'doctrine':doc})
 reg=j(ROOT/'game/data/mil/doctrines.json')
 if isinstance(reg.get('record_index'),dict): reg['record_index']['doc.house_tang.home_defense']='game/data/mil/doctrine-records/doc.house_tang.home_defense.json'
 else: reg['doc.house_tang.home_defense']='game/data/mil/doctrine-records/doc.house_tang.home_defense.json'
 put(ROOT/'game/data/mil/doctrines.json',reg)
 # Remove stale unsupported Tang Wei doctrine that blocks the checkpoint gate.
 for p in (ROOT/'game/data/mil/doctrine-records').glob('doc.tang_wei.*.json'):
  try:d=j(p); text=json.dumps(d)
  except Exception:continue
  if any(x in text for x in ['house_guard','guardian_cavalry','tang_champion']): p.unlink()
 reg=j(ROOT/'game/data/mil/doctrines.json')
 for key in ('record_index','doctrines'):
  if isinstance(reg.get(key),dict):
   for did,path in list(reg[key].items()):
    if str(did).startswith('doc.tang_wei.') and not (ROOT/str(path)).exists(): reg[key].pop(did,None)
 put(ROOT/'game/data/mil/doctrines.json',reg)
 # Universal House loadout/training maps already exist in checkpoint; remove old role fallbacks from deterministic map.
 d=j(ROOT/'game/data/mil/deterministic-training-programs.json')
 if isinstance(d.get('role_programs'),dict):
  for old in list(ROLE_MAP):
   if old not in {'house_infantry','house_cavalry'}: d['role_programs'].pop(old,None)
  d['role_programs']['house_infantry']='program.house_infantry'; d['role_programs']['house_cavalry']='program.house_cavalry'
 for sec in ['training_ref_programs','exact_billet_programs','role_keyword_programs','profile_programs']:
  if isinstance(d.get(sec),dict): d[sec]={k:deep_map(v) for k,v in d[sec].items() if not any(x in str(k) for x in ['sword_manor','bastion','guardian_cavalry','house_guard','tang_champion'])}
 put(ROOT/'game/data/mil/deterministic-training-programs.json',d)

def rewrite_active_state_refs():
 # Current owners/projections should use the unified identities; historical archives retain provenance.
 for p in (ROOT/'state').rglob('*.json'):
  rel=p.relative_to(ROOT).as_posix()
  if rel.startswith('state/history/') or rel.startswith('state/event/'): continue
  try:d=j(p)
  except Exception:continue
  nd=deep_map(d)
  if nd!=d: put(p,nd)

def main():
 forces=[j(p) for p in SOURCE_FORCE_PATHS]
 old_records=collapse_person_lites(forces)
 house=merge_forces(forces)
 put(HOUSE_PATH,house)
 migrate_formations(house)
 materialize_home_commanders(house,old_records)
 put(HOUSE_PATH,house)
 # Remove extinct force owners only after their conserved cohorts are merged.
 for p in SOURCE_FORCE_PATHS[1:]:
  if p.exists(): p.unlink()
 create_home_groups()
 patch_static_and_runtime()
 rewrite_active_state_refs()
 # Rewrite exact characters after broad mapping; keep old biographies but current billets/affiliations normalized.
 for p in (ROOT/'state/char').glob('*.json'):
  d=j(p); nd=deep_map(d)
  aff=nd.get('affiliation')
  if isinstance(aff,list):
   nd['affiliation']=list(dict.fromkeys('house_tang' if x in OLD_OWNERS else x for x in aff))
  if nd!=d: put(p,nd)
 # Final force projections from authoritative cohort ledger.
 house=j(HOUSE_PATH); recompute(house); house['headcount']=176060; house['authorized_strength']=176060; house['authorized_by_role']={'house_infantry':164060,'house_cavalry':12000}; put(HOUSE_PATH,house)
 print('phase1 unified House Tang complete',house['headcount'],house['authorized_by_role'],'home formations',len(FORM_MAP))
if __name__=='__main__': main()
