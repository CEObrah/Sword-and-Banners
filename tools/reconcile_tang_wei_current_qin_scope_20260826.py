#!/usr/bin/env python3
from __future__ import annotations
import json
from collections import defaultdict
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime'))
from sword_runtime.cohort_personnel import validate_cohort_ledger

QIN_REFS=[
 'formation_high_guard_qin_a','formation_high_guard_qin_b',
 'formation_black_banner_01a','formation_black_banner_01b',
 'formation_black_banner_02a','formation_black_banner_02b',
 'formation_black_banner_03a','formation_black_banner_03b',
 'formation_black_banner_04a','formation_black_banner_04b',
]
HOUSE_REFS=[
 'formation_red_lance_a','formation_red_lance_b','formation_high_guard_cavalry',
 'formation_high_guard_infantry_01a','formation_high_guard_infantry_01b',
 'formation_high_guard_infantry_02a','formation_high_guard_infantry_02b',
 'formation_high_guard_infantry_03a','formation_high_guard_infantry_03b',
]
HOUSE_QIN_COMMANDERS=[
 'char_qin_wei_unit_01_commander','char_qin_wei_unit_02_commander',
 'char_qin_wei_unit_03_commander','char_qin_wei_unit_04_commander',
 'char_han_shou','char_pei_rong','char_deng_kai','char_lu_cheng',
]
COMMANDER_FORMATIONS={
 'char_qin_wei_unit_01_commander':'formation_black_banner_01a',
 'char_qin_wei_unit_02_commander':'formation_black_banner_01b',
 'char_qin_wei_unit_03_commander':'formation_black_banner_02a',
 'char_qin_wei_unit_04_commander':'formation_black_banner_02b',
 'char_han_shou':'formation_black_banner_03a',
 'char_pei_rong':'formation_black_banner_03b',
 'char_deng_kai':'formation_black_banner_04a',
 'char_lu_cheng':'formation_black_banner_04b',
 'char_gao_yun':'formation_high_guard_qin_a',
 'char_han_qiu':'formation_high_guard_qin_b',
}

def load(rel): return json.loads((ROOT/rel).read_text(encoding='utf-8'))
def save(rel,d):
 p=ROOT/rel; p.parent.mkdir(parents=True,exist_ok=True)
 p.write_text(json.dumps(d,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')

def find_char(ref):
 if ref=='char_tang_wei': return ROOT/'state/player.json'
 for p in (ROOT/'state/char').glob('*.json'):
  try:d=json.loads(p.read_text(encoding='utf-8'))
  except Exception:continue
  if d.get('owner_id')==ref or d.get('id')==ref:return p
 raise RuntimeError(f'missing exact character {ref}')

def formation_map():
 out={}
 for p in (ROOT/'state/formations').glob('*.json'):
  d=json.loads(p.read_text(encoding='utf-8')); ref=d.get('formation_ref')
  if isinstance(ref,str): out[ref]=(p,d)
 return out

def recompute_force_reserve(force):
 reserve=defaultdict(int); byloc=defaultdict(lambda:defaultdict(int)); alloc=defaultdict(int); comp=defaultdict(lambda:defaultdict(int)); ext=defaultdict(lambda:defaultdict(int))
 for c in force.get('cohort_ledger',{}).get('cohorts',{}).values():
  role=str(c.get('role','unknown'))
  for loc,n in c.get('reserve_by_location',{}).items(): reserve[role]+=int(n); byloc[str(loc)][role]+=int(n)
  for ref,n in c.get('allocated_by_formation',{}).items(): alloc[str(ref)]+=int(n); comp[str(ref)][role]+=int(n)
  for ref,n in c.get('allocated_external_by_formation',{}).items():
   if int(n): ext[str(ref)][role]+=int(n)
 # Materialized people assigned inside a formation still occupy one of that
 # formation's conserved fighting slots. Mirror validate_cohort_ledger exactly.
 for assignment in force.get('materialized_assignments',{}).values():
  if not isinstance(assignment,dict) or not assignment.get('formation_ref'): continue
  ref=str(assignment['formation_ref']); n=max(1,int(assignment.get('personnel',1))); role=str(assignment.get('role','unknown'))
  alloc[ref]+=n; comp[ref][role]+=n
 force['available_by_role']=dict(sorted(reserve.items()))
 force['available_by_location']={loc:dict(sorted(row.items())) for loc,row in sorted(byloc.items()) if sum(row.values())}
 force['allocated_to_formations']={ref:{'personnel':alloc[ref],'composition':dict(sorted(comp[ref].items()))} for ref in sorted(alloc)}
 force['external_personnel_allocations']={ref:dict(sorted(row.items())) for ref,row in sorted(ext.items()) if sum(row.values())}

def main():
 forms=formation_map()
 for ref in QIN_REFS+HOUSE_REFS:
  if ref not in forms: raise RuntimeError(f'missing current Tang Wei formation {ref}')
 for ref in QIN_REFS:
  f=forms[ref][1]
  if f.get('owner_force_ref')!='force_state_qin' or f.get('administrative_owner')!='state_qin' or f.get('command_authority')!='char_tang_wei':
   raise RuntimeError((ref,'not current Qin formation under Tang Wei'))
 if sum(int(forms[r][1].get('personnel',0)) for r in QIN_REFS)!=5000: raise RuntimeError('Qin component is not 5,000')
 if sum(int(forms[r][1].get('personnel',0)) for r in HOUSE_REFS)!=4500: raise RuntimeError('House component is not 4,500')

 # Current Qin appointment authority is the ten existing state-owned leaves.
 player=load('state/player.json')
 for row in player.setdefault('career_state',{}).get('appointments',[]):
  if isinstance(row,dict) and row.get('kind')=='qin_field_command' and row.get('status')=='active':
   row['formation_name']='Tang Wei Army'
   row['formation_ref']=QIN_REFS[0]
   row['formation_refs']=list(QIN_REFS)
   row['command_group_ref']='cmdgrp.tang_wei.field_army'
   row['command_scope']='qin_component_within_mixed_9500_army'
   row['command_structure_status']='tang_wei_army_9500_house_4500_qin_5000'
   row['personnel']=5000
 player['career_state']['current_command_span']=9500
 player.setdefault('command_assignment',{})['current_command_span']=9500
 player.setdefault('command_assignment',{})['command_group_ref']='cmdgrp.tang_wei.field_army'
 player.setdefault('military_command',{})['formation_scope']='cmdgrp.tang_wei.field_army'
 player['military_command']['level']='9500_commander'
 save('state/player.json',player)

 qstate=load('state/states/qin.json')
 ap=qstate.get('appointments',{}).get('field_command:qin_border_detachment')
 if isinstance(ap,dict):
  ap['formation_name']='Tang Wei Army'
  ap['formation_ref']=QIN_REFS[0]
  ap['formation_refs']=list(QIN_REFS)
  ap['command_group_ref']='cmdgrp.tang_wei.field_army'
  ap['command_scope']='qin_component_within_mixed_9500_army'
  ap['command_structure_status']='tang_wei_army_9500_house_4500_qin_5000'
  ap['personnel']=5000
 save('state/states/qin.json',qstate)

 # The active strategic order follows the current Qin component. Historical
 # world-arc evidence is intentionally left unchanged.
 op=load('state/operations/operation_arc_131572c4e8a2892bbc.json')
 for order in op.get('operational_orders',[]):
  if not isinstance(order,dict): continue
  refs=order.get('applies_to_formation_refs')
  if isinstance(refs,list) and any(str(x).startswith('formation_qin_wei_unit_') for x in refs):
   order['applies_to_formation_refs']=list(QIN_REFS)
   order['excluded_non_state_formation_refs']=[]
 save('state/operations/operation_arc_131572c4e8a2892bbc.json',op)

 # Personal-force projection tracks the current House bodies assigned to Wei,
 # never retired House Guard/Champion formation IDs.
 pf=load('state/pforce/wei.json')
 pf['assigned_formations']=list(HOUSE_REFS)
 save('state/pforce/wei.json',pf)

 # Exact leaf-command sheets must agree with the formations they actually hold.
 for person_ref,formation_ref in COMMANDER_FORMATIONS.items():
  p=find_char(person_ref); d=json.loads(p.read_text(encoding='utf-8')); f=forms[formation_ref][1]
  d['current_formation_id']=formation_ref
  d['current_location']=str(f.get('location_ref') or d.get('current_location') or '')
  ca=d.setdefault('command_assignment',{}); ca.update({'billet':'formation_commander','formation_ref':formation_ref,'current_command_span':int(f.get('personnel',0)),'external_to_fighting_establishment':True})
  if f.get('higher_command_ref'): ca['command_group_ref']=f['higher_command_ref']
  mc=d.setdefault('military_command',{}); mc['formation_scope']=formation_ref; mc['level']='500_commander'; mc['external_to_fighting_strength']=True
  p.write_text(json.dumps(d,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')

 # These eight are House Tang people serving as external commanders of Qin
 # formations. They must not consume Qin's own exact-person manpower. Restore
 # the eight displaced Qin command-personnel bodies to the anonymous depot pool.
 qin=load('state/forces/state-qin.json')
 removed=0
 for ref in HOUSE_QIN_COMMANDERS:
  if ref in qin.get('materialized_people',{}):
   qin['materialized_people'].pop(ref,None); qin.get('materialized_assignments',{}).pop(ref,None); removed+=1
 if removed:
  cohorts=qin.get('cohort_ledger',{}).get('cohorts',{})
  candidates=[(cid,c) for cid,c in cohorts.items() if c.get('role')=='command_personnel']
  if not candidates: raise RuntimeError('no Qin command-personnel cohort to restore external House commanders')
  cid,c=sorted(candidates,key=lambda x:x[0])[0]
  rb=c.setdefault('reserve_by_location',{}); rb['loc_qin_eastern_depot']=int(rb.get('loc_qin_eastern_depot',0))+removed
 recompute_force_reserve(qin)
 validate_cohort_ledger(qin)
 save('state/forces/state-qin.json',qin)

 # Derived commander/location indexes come solely from current formations.
 assignments=defaultdict(list); locations=defaultdict(list)
 for ref,(p,f) in sorted(forms.items()):
  c=f.get('commander_ref')
  if isinstance(c,str) and c: assignments[c].append(ref)
  loc=f.get('location_ref')
  if isinstance(loc,str) and loc: locations[loc].append(ref)
 cidx=load('state/index/commander-formation-index.json')
 cidx['authority']=False; cidx['assignments']={k:sorted(v) for k,v in sorted(assignments.items())}; cidx['by_commander']={k:(sorted(v)[0] if len(v)==1 else sorted(v)) for k,v in sorted(assignments.items())}
 save('state/index/commander-formation-index.json',cidx)
 lidx=load('state/index/location-formation-index.json')
 lidx['authority']=False; lidx['locations']={k:sorted(v) for k,v in sorted(locations.items())}
 save('state/index/location-formation-index.json',lidx)
 print(json.dumps({'qin_refs':len(QIN_REFS),'qin_strength':5000,'house_refs':len(HOUSE_REFS),'house_strength':4500,'qin_external_house_people_removed':removed},indent=2))

if __name__=='__main__': main()
