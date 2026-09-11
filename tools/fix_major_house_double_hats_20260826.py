#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime'))
from sword_runtime.cohort_personnel import validate_cohort_ledger

NOW='244-BCE-09-09T20:22:48+08:00'
CONFIG=[
 ('cmdgrp.house_go_military_house.field_army','state/forces/house_go_military_house.json','formation_house_go_military_house_01','char_go_house_field_commander','state_wei','Wei','house_go_military_house','Go Household Army Commander'),
 ('cmdgrp.house_kanki_retinue_house.field_army','state/forces/house_kanki_retinue_house.json','formation_house_kanki_retinue_house_01','char_kanki_house_field_commander','state_qin','Qin','house_kanki_retinue_house','Kanki Household Army Commander'),
 ('cmdgrp.house_karin_house.field_army','state/forces/house_karin_house.json','formation_house_karin_house_01','char_karin_house_field_commander','state_chu','Chu','house_karin_house','Ka Rin Household Army Commander'),
 ('cmdgrp.house_mou_family.field_army','state/forces/house_mou_family.json','formation_house_mou_family_01','char_mou_house_field_commander','state_qin','Qin','house_mou_family','Mou Household Army Commander'),
 ('cmdgrp.house_ouki_household.field_army','state/forces/house_ouki_household.json','formation_house_ouki_household_01','char_ouki_house_field_commander','state_qin','Qin','house_ouki_household','Ou Ki Household Army Commander'),
 ('cmdgrp.house_ou_family.field_army','state/forces/house_ou_family.json','formation_house_ou_family_01','char_ou_family_field_commander','state_qin','Qin','house_ou_family','Ou Family Household Army Commander'),
 ('cmdgrp.house_riboku_household.field_army','state/forces/house_riboku_household.json','formation_house_riboku_household_01','char_riboku_house_field_commander','state_zhao','Zhao','house_riboku_household','Ri Boku Household Army Commander'),
 ('cmdgrp.house_shou_bun_kun_household.field_army','state/forces/house_shou_bun_kun_household.json','formation_house_shou_bun_kun_household_01','char_shou_bun_kun_house_field_commander','state_qin','Qin','house_shou_bun_kun_household','Shou Bun Kun Household Army Commander'),
 ('cmdgrp.house_tou_household.field_army','state/forces/house_tou_household.json','formation_house_tou_household_01','char_tou_house_field_commander','state_qin','Qin','house_tou_household','Tou Household Army Commander'),
]
SURNAMES=('Li','Wang','Zhang','Zhao','Bai','Fan','Gao','Lu','Tian','Sun','Jing','Du','Xu','Han','Wei','Huang','Cao','Ren','Pei','Deng')
GIVENS=('Ren','Sheng','Jun','An','Yi','Ke','Rui','Zhen','Bo','Qian','Yong','Lin','Jie','He','Tao','Cheng','Shan','Ming','Yu','Zhong')

def load(rel): return json.loads((ROOT/rel).read_text())
def save(rel,d): (ROOT/rel).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def find_formation(ref):
 for p in (ROOT/'state/formations').glob('*.json'):
  d=json.loads(p.read_text())
  if d.get('formation_ref')==ref: return p,d
 raise FileNotFoundError(ref)
def find_group(ref):
 p=ROOT/'state/cmd/command-groups'/f'{ref}.json'
 if not p.exists(): raise FileNotFoundError(p)
 return p,json.loads(p.read_text())
def unique_name(ref,used):
 raw=int(hashlib.sha256(ref.encode()).hexdigest()[:12],16)
 for i in range(400):
  name=f'{SURNAMES[(raw+i)%len(SURNAMES)]} {GIVENS[((raw//len(SURNAMES))+i*7)%len(GIVENS)]}'
  if name not in used: used.add(name); return name
 raise RuntimeError('name pool exhausted')
def round_stats(src,keys,kind='skill'):
 out={}
 for k in keys:
  v=float(src.get(k,0) or 0); out[k]=int(round(v))
 return out

# Build existing name set.
used=set()
for p in (ROOT/'state/char').glob('*.json'):
 try:
  n=json.loads(p.read_text()).get('name')
  if isinstance(n,str): used.add(n)
 except Exception: pass

owners=load('state/index/owner-index.json')
created=[]
for group_ref,force_rel,source_form_ref,person_ref,state_ref,state_label,house_ref,role_label in CONFIG:
 gp,group=find_group(group_ref)
 if group.get('commander_ref')==person_ref and owners.get('owners',{}).get(person_ref):
  continue
 fp=ROOT/force_rel; force=json.loads(fp.read_text())
 form_path,formation=find_formation(source_form_ref)
 # Reclassify one anonymous fighting household body into the new zero-fighting-strength parent commander.
 candidates=[]
 for cid,c in force.get('cohort_ledger',{}).get('cohorts',{}).items():
  n=int(c.get('allocated_by_formation',{}).get(source_form_ref,0) or 0)
  if n<=0: continue
  role=str(c.get('role',''))
  pref=0 if role=='household_retainer' else 1
  candidates.append((pref,-n,cid,c))
 if not candidates: raise RuntimeError(f'no anonymous conserved source body for {group_ref}')
 _,_,cid,cohort=sorted(candidates,key=lambda x:(x[0],x[1],x[2]))[0]
 role=str(cohort.get('role'))
 allocated=cohort.setdefault('allocated_by_formation',{})
 held=int(allocated.get(source_form_ref,0)); allocated[source_form_ref]=held-1
 if allocated[source_form_ref]<=0: allocated.pop(source_form_ref,None)
 # Formation-local cached slice and composition must lose that same body.
 found=False
 for row in formation.get('cohort_composition',[]):
  if isinstance(row,dict) and row.get('cohort_id')==cid and int(row.get('count',0))>0:
   row['count']=int(row['count'])-1; found=True; break
 if not found: raise RuntimeError(f'{source_form_ref} missing cohort cache {cid}')
 formation['cohort_composition']=[r for r in formation.get('cohort_composition',[]) if int(r.get('count',0) or 0)>0]
 formation['personnel']=int(formation.get('personnel',0))-1
 comp=formation.setdefault('composition',{}); comp[role]=int(comp.get(role,0))-1
 if comp[role]<=0: comp.pop(role,None)
 top=force.setdefault('allocated_to_formations',{}).get(source_form_ref)
 if not isinstance(top,dict): raise RuntimeError(f'missing top allocation {source_form_ref}')
 top['personnel']=int(top.get('personnel',0))-1
 tcomp=top.setdefault('composition',{}); tcomp[role]=int(tcomp.get(role,0))-1
 if tcomp[role]<=0: tcomp.pop(role,None)
 # Exact representation now owns the conserved body outside fighting formation strength.
 force.setdefault('materialized_people',{})[person_ref]={'personnel':1,'role':role,'source_cohort_ref':cid,'source_mode':'materialized_house_army_commander'}
 # No materialized_assignments row: this person is not inside a fighting formation.
 attrs=round_stats(cohort.get('attribute_means',{}),['Agility','Awareness','Composure','Coordination','Endurance','Intelligence','Presence','Strength','Toughness'])
 skills=round_stats(cohort.get('skill_means',{}),['Athletics','Bow','Crossbow','Engineering','Formation Command','Formation Fighting','Grappling','Heavy Weapons','Leadership','Logistics','Medicine','Polearms','Riding','Scouting','Shield','Stealth','Strategy','Survival','Sword','Tactics','Unarmed'])
 # Selection for an already-existing senior household command billet is represented
 # by bounded command-domain differentiation, not a blanket combat-stat inflation.
 h=int(hashlib.sha256(person_ref.encode()).hexdigest()[:8],16)
 skills['Formation Command']=max(skills.get('Formation Command',0),68+(h%9))
 skills['Leadership']=max(skills.get('Leadership',0),66+((h//11)%9))
 skills['Tactics']=max(skills.get('Tactics',0),64+((h//101)%10))
 skills['Strategy']=max(skills.get('Strategy',0),58+((h//1009)%12))
 skills['Logistics']=max(skills.get('Logistics',0),58+((h//10007)%12))
 age=28+(h%17); birth_year=244+age
 name=unique_name(person_ref,used)
 span=max(0,int(group.get('organizational_state',{}).get('current_recursive_strength',0))-1)
 person={
  'schema':'sab_character','owner_id':person_ref,'owner_type':'character','name':name,
  'birth_date':f'{birth_year}-BCE-{1+(h//17)%12:02d}-{1+(h//211)%28:02d}',
  'body':{'adult_height_cm':round(168.0+(h%140)/10.0,1),'current_weight_kg':round(58.0+(h%220)/10.0,1),'frame':'average','growth_end_age':18,'height_anchors':[]},
  'appearance':55+(h%31),
  'aptitude':{'academic_learning':100+((h//3)%21),'physical_learning':100+((h//5)%21),'social_learning':105+((h//7)%21),'tactical_learning':112+((h//11)%21),'technical_learning':100+((h//13)%21)},
  'attributes':attrs,'skills':skills,'professional_skills':{'Diplomacy':25+((h//17)%26),'Governance':15+((h//19)%26),'Intelligence Operations':20+((h//23)%26),'Law':15+((h//29)%26),'Trade':15+((h//31)%26)},
  'affiliation':[state_label,state_ref,house_ref],
  'authority':f'Exact commander of {group_ref}; materialized from one already-conserved household military body.',
  'background':f'Existing senior {state_label} household officer made exact when the persistent 500+ no-double-hat command rule was enforced. The same body was removed from {source_form_ref}; force headcount did not change.',
  'current_location':str(group.get('location') or formation.get('location_ref') or ''),'role':role_label,
  'military_rank':{'durable':True,'grade':'4000_commander' if span>=4000 else '2000_commander'},
  'career_state':{'current_billet':'command_group_commander','current_command_span':span,'office_or_command':role_label},
  'command_assignment':{'billet':'command_group_commander','current_command_span':span,'external_to_fighting_establishment':True,'command_group_ref':group_ref},
  'development_state':{'verified_training_hours':0.0,'verified_role_exposure_hours':0.0},
  'activity_contract':{'autonomous_enabled':True,'mode':'standing_role_training','training_regimen_ref':'regular_army','training_program_ref':'program.commander_combined_arms'},
  'health_status':'fit','life_status':'active','fatigue':0,
  'personal_loadout_ref':'loadout_state_line_infantry','loadout_id':'loadout_state_line_infantry','equipment_loadout_id':'loadout_state_line_infantry',
  'goal_state':{'current_goals':[f'command {role_label} effectively'],'institutional_duties':[role_label]},
  'runtime':{'last_settled_at':NOW},'current_formation_id':None,
  'military_command':{'external_to_fighting_strength':True,'formation_scope':group_ref,'level':'household_army_commander'},
  'source_cohort_ref':cid,'materialized_from_force_ref':str(force.get('owner_id')),
 }
 char_rel='state/char/'+person_ref.removeprefix('char_').replace('_','-')+'.json'
 save(char_rel,person)
 owners.setdefault('owners',{})[person_ref]=char_rel
 group['commander_ref']=person_ref
 group.setdefault('direct_person_refs',[])
 group['updated_at']=NOW
 gp.write_text(json.dumps(group,ensure_ascii=False,indent=2)+'\n')
 form_path.write_text(json.dumps(formation,ensure_ascii=False,indent=2)+'\n')
 validate_cohort_ledger(force)
 fp.write_text(json.dumps(force,ensure_ascii=False,indent=2)+'\n')
 created.append((person_ref,name,group_ref,cid,role))

save('state/index/owner-index.json',owners)
print('created',len(created),'distinct conserved house-army commanders')
for row in created: print(row)
