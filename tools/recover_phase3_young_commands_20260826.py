#!/usr/bin/env python3
from __future__ import annotations
import copy, hashlib, json
from pathlib import Path
from collections import defaultdict
ROOT=Path(__file__).resolve().parents[1]
NOW='244-BCE-09-09T20:22:48+08:00'
QIN_LOC='loc_qin_eastern_depot'
YOUNG_LOC='loc_qin_regional_01'

def load(rel): return json.loads((ROOT/rel).read_text())
def save(rel,obj):
 p=ROOT/rel; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
def fpath(ref):
 for p in (ROOT/'state/formations').glob('*.json'):
  try:
   if json.loads(p.read_text()).get('formation_ref')==ref:return p
  except Exception: pass
 raise FileNotFoundError(ref)
def loadf(ref): return json.loads(fpath(ref).read_text())
def savef(d): save('state/formations/'+d['formation_ref'].removeprefix('formation_').replace('_','-')+'.json',d)
def char_path(ref):
 for p in (ROOT/'state/char').glob('*.json'):
  try:
   if json.loads(p.read_text()).get('owner_id')==ref:return p
  except Exception: pass
 return None

def recompute_force(force):
 reserve=defaultdict(int); byloc=defaultdict(lambda:defaultdict(int)); alloc=defaultdict(int); comp=defaultdict(lambda:defaultdict(int))
 for c in force.get('cohort_ledger',{}).get('cohorts',{}).values():
  role=str(c.get('role',''))
  for loc,n in c.get('reserve_by_location',{}).items(): reserve[role]+=int(n); byloc[loc][role]+=int(n)
  for ref,n in c.get('allocated_by_formation',{}).items(): alloc[ref]+=int(n); comp[ref][role]+=int(n)
 for a in force.get('materialized_assignments',{}).values():
  if isinstance(a,dict) and a.get('formation_ref'):
   ref=str(a['formation_ref']); n=max(1,int(a.get('personnel',1))); role=str(a.get('role','unknown')); alloc[ref]+=n; comp[ref][role]+=n
 force['available_by_role']=dict(sorted(reserve.items()))
 force['available_by_location']={k:dict(v) for k,v in sorted(byloc.items()) if sum(v.values())}
 force['allocated_to_formations']={r:{'personnel':alloc[r],'composition':dict(comp[r])} for r in sorted(alloc)}

def release_qin_formation(qin,ref,loc):
 ff=loadf(ref); total=0
 for c in qin['cohort_ledger']['cohorts'].values():
  n=int(c.get('allocated_by_formation',{}).pop(ref,0)); total+=n
  if n: c.setdefault('reserve_by_location',{})[loc]=int(c.setdefault('reserve_by_location',{}).get(loc,0))+n
 if total!=int(ff.get('personnel',0)): raise RuntimeError(('release mismatch',ref,total,ff.get('personnel')))
 qin.get('allocated_to_formations',{}).pop(ref,None)
 fpath(ref).unlink()

def split_house_1000(force_path,mount_path,old_ref,a_ref,b_ref,a_name,b_name,doctrine,loadout,cmd_a,cmd_b,parent):
 force=load(force_path); old=loadf(old_ref); cohort_rows=[]
 # Convert each old cohort allocation into exact 500/500 shares without changing bodies.
 remaining_a=500; remaining_b=500
 for cid,c in force.get('cohort_ledger',{}).get('cohorts',{}).items():
  n=int(c.get('allocated_by_formation',{}).pop(old_ref,0))
  if not n: continue
  take_a=min(remaining_a,n); remaining_a-=take_a; n-=take_a
  take_b=min(remaining_b,n); remaining_b-=take_b; n-=take_b
  if n: raise RuntimeError(('unexpected old allocation excess',old_ref,cid,n))
  if take_a: c.setdefault('allocated_by_formation',{})[a_ref]=take_a
  if take_b: c.setdefault('allocated_by_formation',{})[b_ref]=take_b
  cohort_rows.append((cid,take_a,take_b))
 if remaining_a or remaining_b: raise RuntimeError(('house split shortage',old_ref,remaining_a,remaining_b))
 def make(ref,name,commander,which):
  d=copy.deepcopy(old); d['formation_ref']=ref; d['name']=name; d['personnel']=500; d['authorized_strength']=500; d['composition']={'cavalry':500}; d['commander_ref']=commander; d['command_authority']=parent.split('.',2)[1] if False else ('char_mou_ten' if 'gaku' in ref else 'char_ou_hon'); d['higher_command_ref']=parent; d['parent_command_group_ref']=parent; d['cohort_composition']=[]; d['mounts']={'horse':500}; d['equipment_units_by_role']={'cavalry':500}; d['doctrine_ref']=doctrine; d['registered_loadouts_by_role']={'cavalry':loadout}; d['officer_cadre']={'rank_inventory':{'500_commander':0,'100_commander':5},'materialized_refs_by_rank':{'500_commander':[],'100_commander':[]}}
  for cid,aa,bb in cohort_rows:
   n=aa if which=='a' else bb
   if n:d['cohort_composition'].append({'cohort_id':cid,'count':n})
  return d
 savef(make(a_ref,a_name,cmd_a,'a')); savef(make(b_ref,b_name,cmd_b,'b')); fpath(old_ref).unlink()
 recompute_force(force); save(force_path,force)
 mounts=load(mount_path); oldmount=mounts.setdefault('allocated_to_formations',{}).pop(old_ref,{})
 horses=int(oldmount.get('horse',0));
 if horses<1000: raise RuntimeError(('mount split shortage',old_ref,horses))
 mounts['allocated_to_formations'][a_ref]={'horse':500}; mounts['allocated_to_formations'][b_ref]={'horse':500}; save(mount_path,mounts)

def group(ref,name,commander,units,strength,doctrine,parent=None,roles=None,direct=None,successors=None,loc=YOUNG_LOC):
 return {'schema':'command-group','id':ref,'display_name':name,'context':'nested_army' if parent else 'independent_field_command','authority_ref':'state_qin','commander_ref':commander,'direct_person_refs':direct or [],'role_assignments':roles or {},'successor_refs':successors or [],'units':[{'kind':k,'ref':r} for k,r in units],'standing_order_refs':[],'standing_doctrine_ref':doctrine,'communication_ref':None,'location':loc,'parent_command_group_ref':parent,'created_at':NOW,'updated_at':NOW,'active_context_ref':'operation_arc_131572c4e8a2892bbc','organizational_state':{'authorized_direct_unit_slots':len(units),'authorized_strength':strength,'current_direct_formation_strength':sum(loadf(r).get('personnel',0) for k,r in units if k=='formation'),'current_recursive_strength':strength,'direct_unit_count':len(units),'mission':'young_independent_command' if not parent else 'household_subcommand','recursive_formation_count':sum(1 for k,r in units if k=='formation'),'reorganization_need':'none','status':'active'}}

def set_existing_char(ref,*,role,span,assignment,formation=None,location=YOUNG_LOC,billet=None,program='program.commander_combined_arms',regimen='regular_army',rank=None):
 p=char_path(ref)
 if not p: raise RuntimeError(('missing existing char',ref))
 d=json.loads(p.read_text()); d['role']=role; d['current_location']=location
 d['career_state']=copy.deepcopy(d.get('career_state',{})); d['career_state']['current_assignment_ref']=assignment; d['career_state']['current_command_span']=span; d['career_state']['office_or_command']=role; d['career_state']['current_billet']=billet or role; d['career_state']['future_canon_guaranteed']=False
 if rank: d['military_rank']={'durable':True,'grade':rank}
 if formation:
  d['current_formation_id']=formation; d['command_assignment']={'external_to_fighting_establishment':True,'formation_ref':formation,'command_group_ref':assignment if assignment.startswith('cmdgrp.') else None,'billet':'formation_commander','current_command_span':span}
 else:
  d.pop('current_formation_id',None); d['command_assignment']={'external_to_fighting_establishment':True,'command_group_ref':assignment,'billet':'command_group_commander' if span>=500 else 'staff_or_internal_command','current_command_span':span}
 d['activity_contract']={'autonomous_enabled':True,'mode':'standing_role_training','training_regimen_ref':regimen,'training_program_ref':program}
 p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')

def canon_char(ref,name,affiliation,role,*,tier='veteran',loadout='loadout_state_line_infantry',location=YOUNG_LOC,birth_year=272,program='program.commander_combined_arms',formation=None,group_ref=None,span=0):
 p=char_path(ref)
 if p: return
 tiers={
  'ordinary':({'Strength':88,'Agility':91,'Endurance':96,'Coordination':92,'Awareness':90,'Composure':92,'Intelligence':86,'Presence':86,'Toughness':94},{'Athletics':96,'Sword':82,'Polearms':92,'Bow':70,'Riding':72,'Formation Fighting':92,'Formation Command':72,'Leadership':75,'Tactics':72,'Scouting':70}),
  'veteran':({'Strength':104,'Agility':106,'Endurance':112,'Coordination':108,'Awareness':110,'Composure':112,'Intelligence':102,'Presence':101,'Toughness':108},{'Athletics':112,'Sword':104,'Polearms':114,'Bow':86,'Riding':92,'Formation Fighting':118,'Formation Command':104,'Leadership':105,'Tactics':101,'Scouting':93}),
  'elite':({'Strength':116,'Agility':120,'Endurance':120,'Coordination':122,'Awareness':124,'Composure':122,'Intelligence':116,'Presence':112,'Toughness':116},{'Athletics':124,'Sword':118,'Polearms':126,'Bow':98,'Riding':118,'Formation Fighting':130,'Formation Command':122,'Leadership':120,'Tactics':118,'Scouting':105}),
 }
 attrs,skills=copy.deepcopy(tiers[tier]); seed=int(hashlib.sha256(ref.encode()).hexdigest()[:8],16)
 # Deterministic individual variation avoids clone sheets while keeping tier parity.
 for i,k in enumerate(attrs): attrs[k]=max(20,attrs[k]+((seed>>(i%16))%9)-4)
 for i,k in enumerate(skills): skills[k]=max(10,skills[k]+((seed>>((i+5)%16))%11)-5)
 body={'adult_height_cm':168+(seed%17),'current_weight_kg':58+(seed%19),'frame':'athletic','growth_end_age':18,'growth_profile_id':'human_height_to_18','height_anchors':[]}
 d={'schema':'sab_character','owner_id':ref,'owner_type':'character','name':name,'birth_date':f'{birth_year}-BCE-{1+(seed%12):02d}-{1+((seed//12)%28):02d}','body':body,'appearance':45+(seed%31),'affiliation':[affiliation,'state_qin'],'role':role,'life_status':'active','health_status':'healthy','fatigue':0,'aptitude':{'physical_learning':110+(seed%31),'technical_learning':110+((seed//7)%31),'tactical_learning':115+((seed//13)%36),'academic_learning':95+((seed//17)%31),'social_learning':95+((seed//23)%31)},'attributes':attrs,'skills':skills,'professional_skills':{},'current_location':location,'equipment_loadout_id':loadout,'loadout_id':loadout,'career_state':{'current_professional_path':'qin_officer_or_veteran','office_or_command':role,'current_assignment_ref':group_ref or formation,'current_command_span':span,'current_billet':role,'future_canon_guaranteed':False},'activity_contract':{'autonomous_enabled':True,'mode':'standing_role_training','training_regimen_ref':'regular_army','training_program_ref':program},'background':{'origin':'Qin','canon_affiliation':affiliation},'development_state':{}}
 if span>=500 and formation:
  d['military_rank']={'durable':True,'grade':'500_commander' if span==500 else '1000_commander'}; d['current_formation_id']=formation; d['command_assignment']={'external_to_fighting_establishment':True,'formation_ref':formation,'command_group_ref':group_ref,'billet':'formation_commander','current_command_span':span}
 elif span>=500 and group_ref:
  d['military_rank']={'durable':True,'grade':'1000_commander' if span==1000 else '500_commander'}; d['command_assignment']={'external_to_fighting_establishment':True,'command_group_ref':group_ref,'billet':'command_group_commander','current_command_span':span}
 save('state/char/'+ref.removeprefix('char_').replace('_','-')+'.json',d)

def main():
 # Hi Shin: return the former separate Karyoten 500 bodies to Qin; strategist stays exact staff/internal HQ defense.
 qin=load('state/forces/state-qin.json')
 try: release_qin_formation(qin,'formation_qin_karyoten_command',QIN_LOC)
 except FileNotFoundError: pass
 for ref,commander in [('formation_qin_hi_shin_main','char_so_sui'),('formation_qin_kyoukai_command','char_kyoukai')]:
  f=loadf(ref); f['commander_ref']=commander; f['command_authority']='char_shin'; f['higher_command_ref']='cmdgrp.shin.hi_shin'; f['parent_command_group_ref']='cmdgrp.shin.hi_shin'; savef(f)
 recompute_force(qin); save('state/forces/state-qin.json',qin)
 # Split the two existing 1,000 household cavalry establishments into exact 500 leaves.
 split_house_1000('state/forces/house_mou_family.json','state/mounts/house-mou-family.json','formation_house_mou_gaku_ka_elite','formation_gaku_ka_house_a','formation_gaku_ka_house_b','Gaku Ka Household Cavalry A','Gaku Ka Household Cavalry B','doc.gaku_ka.house_cavalry','loadout_mou_house_cavalry','char_ko_zen','char_kan_reki','cmdgrp.mou_ten.gaku_ka.house_1000')
 split_house_1000('state/forces/house_ou_family.json','state/mounts/house-ou-family.json','formation_house_ou_gyoku_hou_elite','formation_gyoku_hou_house_a','formation_gyoku_hou_house_b','Gyoku Hou Household Cavalry A','Gyoku Hou Household Cavalry B','doc.gyoku_hou.house_cavalry','loadout_ou_house_cavalry','char_ban_you','char_shou_taku','cmdgrp.ou_hon.gyoku_hou.house_1000')
 # Exact leaf command on the Qin cores.
 for ref,commander,authority,higher in [('formation_qin_gaku_ka_core','char_ai_sen','char_mou_ten','cmdgrp.mou_ten.gaku_ka'),('formation_qin_gyoku_hou_core','char_a_ka_kin','char_ou_hon','cmdgrp.ou_hon.gyoku_hou')]:
  f=loadf(ref); f['commander_ref']=commander; f['command_authority']=authority; f['higher_command_ref']=higher; f['parent_command_group_ref']=higher; savef(f)
 # Groups.
 save('state/cmd/command-groups/cmdgrp.shin.hi_shin.json',group('cmdgrp.shin.hi_shin','Hi Shin','char_shin',[('formation','formation_qin_hi_shin_main'),('formation','formation_qin_kyoukai_command')],1000,'doc.hi_shin.command',roles={'char_karyoten':'strategist_and_hq_defense'},direct=['char_karyoten'],successors=['char_kyoukai'],loc=QIN_LOC))
 save('state/cmd/command-groups/cmdgrp.mou_ten.gaku_ka.house_1000.json',group('cmdgrp.mou_ten.gaku_ka.house_1000','Gaku Ka Household Wing','char_riku_sen',[('formation','formation_gaku_ka_house_a'),('formation','formation_gaku_ka_house_b')],1000,'doc.gaku_ka.house_cavalry','cmdgrp.mou_ten.gaku_ka'))
 save('state/cmd/command-groups/cmdgrp.mou_ten.gaku_ka.json',group('cmdgrp.mou_ten.gaku_ka','Gaku Ka','char_mou_ten',[('nested_army','cmdgrp.mou_ten.gaku_ka.house_1000'),('formation','formation_qin_gaku_ka_core')],1500,'doc.gaku_ka.command',successors=['char_riku_sen']))
 save('state/cmd/command-groups/cmdgrp.ou_hon.gyoku_hou.house_1000.json',group('cmdgrp.ou_hon.gyoku_hou.house_1000','Gyoku Hou Household Wing','char_kan_jou',[('formation','formation_gyoku_hou_house_a'),('formation','formation_gyoku_hou_house_b')],1000,'doc.gyoku_hou.house_cavalry','cmdgrp.ou_hon.gyoku_hou'))
 save('state/cmd/command-groups/cmdgrp.ou_hon.gyoku_hou.json',group('cmdgrp.ou_hon.gyoku_hou','Gyoku Hou','char_ou_hon',[('nested_army','cmdgrp.ou_hon.gyoku_hou.house_1000'),('formation','formation_qin_gyoku_hou_core')],1500,'doc.gyoku_hou.command',successors=['char_kan_jou']))
 # Current top commanders and key leaf commanders.
 set_existing_char('char_shin',role='Commander, Hi Shin',span=1000,assignment='cmdgrp.shin.hi_shin',formation=None,location=QIN_LOC,billet='Hi Shin 1,000-Man Commander',rank='1000_commander')
 set_existing_char('char_kyoukai',role='500-man Commander, Hi Shin',span=500,assignment='cmdgrp.shin.hi_shin',formation='formation_qin_kyoukai_command',location=QIN_LOC,rank='500_commander')
 set_existing_char('char_karyoten',role='Strategist and 100-man HQ Defense Commander, Hi Shin',span=100,assignment='cmdgrp.shin.hi_shin',formation=None,location=QIN_LOC,billet='Strategist / 100-man HQ defense',program='program.strategist',regimen='professional_officer')
 set_existing_char('char_mou_ten',role='Commander, Gaku Ka',span=1500,assignment='cmdgrp.mou_ten.gaku_ka',formation=None,rank='1000_commander')
 set_existing_char('char_ou_hon',role='Commander, Gyoku Hou',span=1500,assignment='cmdgrp.ou_hon.gyoku_hou',formation=None,rank='1000_commander')
 # Canon useful cast, preloaded by user instruction.
 hi=[
 ('char_so_sui','So Sui','elite'),('char_en_hi_shin','En','veteran'),('char_den_yuu','Den Yuu','veteran'),('char_hai_rou','Hai Rou','veteran'),('char_den_ei','Den Ei','veteran'),('char_ryuu_sen','Ryuu Sen','veteran'),('char_kyo_gai','Kyo Gai','veteran'),('char_chu_tetsu','Chu Tetsu','veteran'),('char_suu_gen','Suu Gen','elite'),('char_shou_sa','Shou Sa','veteran'),('char_ryuu_yuu','Ryuu Yuu','veteran'),('char_bi_hei','Bi Hei','ordinary'),('char_taku_kei','Taku Kei','veteran'),('char_seki_hi_shin','Seki','veteran'),('char_ro_en','Ro En','veteran'),('char_chiku','Chiku','ordinary'),('char_ga_ro','Ga Ro','elite'),('char_gaku_rai','Gaku Rai','elite'),('char_na_ki','Na Ki','elite'),('char_sou_jin','Sou Jin','veteran'),('char_sou_tan','Sou Tan','veteran'),('char_kan_to','Kan To','veteran'),('char_den_ten','Den Ten','ordinary'),('char_den_kutsu','Den Kutsu','ordinary'),('char_son_kan','Son Kan','ordinary'),('char_sou_ko','Sou Ko','ordinary'),('char_sou_kuu','Sou Kuu','ordinary')]
 for ref,name,tier in hi:
  form='formation_qin_hi_shin_main' if ref=='char_so_sui' else None; span=500 if ref=='char_so_sui' else 0
  canon_char(ref,name,'Hi Shin',('500-man Commander, Hi Shin' if span else f'Hi Shin member: {name}'),tier=tier,location=QIN_LOC,birth_year=272 if tier!='ordinary' else 274,formation=form,group_ref='cmdgrp.shin.hi_shin',span=span)
 gaku=[('char_riku_sen','Riku Sen','elite',1000,None),('char_ko_zen','Ko Zen','veteran',500,'formation_gaku_ka_house_a'),('char_kan_reki','Kan Reki','veteran',500,'formation_gaku_ka_house_b'),('char_ai_sen','Ai Sen','elite',500,'formation_qin_gaku_ka_core'),('char_ko_ryuu_gaku','Ko Ryuu','veteran',0,None),('char_sen_sai','Sen Sai','veteran',0,None),('char_shuu_gyoku','Shuu Gyoku','veteran',0,None)]
 for ref,name,tier,span,form in gaku: canon_char(ref,name,'Gaku Ka',('1,000-man Commander, Gaku Ka' if span==1000 else '500-man Commander, Gaku Ka' if span==500 else f'Gaku Ka officer: {name}'),tier=tier,loadout='loadout_mou_house_cavalry',formation=form,group_ref='cmdgrp.mou_ten.gaku_ka.house_1000' if span==1000 else 'cmdgrp.mou_ten.gaku_ka',span=span)
 gyoku=[('char_kan_jou','Kan Jou','elite',1000,None),('char_ban_you','Ban You','veteran',500,'formation_gyoku_hou_house_a'),('char_shou_taku','Shou Taku','veteran',500,'formation_gyoku_hou_house_b'),('char_a_ka_kin','A Ka Kin','elite',500,'formation_qin_gyoku_hou_core'),('char_gi_kou','Gi Kou','veteran',0,None),('char_kaku_ei','Kaku Ei','veteran',0,None),('char_kou_ri','Kou Ri','veteran',0,None)]
 for ref,name,tier,span,form in gyoku: canon_char(ref,name,'Gyoku Hou',('1,000-man Commander, Gyoku Hou' if span==1000 else '500-man Commander, Gyoku Hou' if span==500 else f'Gyoku Hou officer: {name}'),tier=tier,loadout='loadout_ou_house_cavalry',formation=form,group_ref='cmdgrp.ou_hon.gyoku_hou.house_1000' if span==1000 else 'cmdgrp.ou_hon.gyoku_hou',span=span)
 # Operation records peer commands without making them children of Tang Wei Army.
 op='state/operations/operation_arc_131572c4e8a2892bbc.json'
 if (ROOT/op).exists():
  d=load(op); d.setdefault('runtime',{})['peer_qin_command_group_refs']=['cmdgrp.shin.hi_shin','cmdgrp.mou_ten.gaku_ka','cmdgrp.ou_hon.gyoku_hou']; save(op,d)
 print('young commands complete')
if __name__=='__main__': main()
