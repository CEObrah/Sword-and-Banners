#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def load(rel): return json.loads((ROOT/rel).read_text())
def save(rel,d): (ROOT/rel).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')

PROGRAM_MAP={
 'program.sword_officer':'program.commander_combined_arms',
 'program.sword_senior_command':'program.commander_combined_arms',
 'program.bastion_senior_command':'program.commander_combined_arms',
 'program.commander_guard':'program.commander_infantry',
 'program.commander_champion':'program.commander_cavalry',
 'program.house_guard':'program.commander_infantry',
 'program.guardian_cavalry':'program.commander_cavalry',
 'program.tang_champion':'program.commander_cavalry',
}
TRAIN_MAP={
 'train.house_tang_internal.house_guard':'train.house_tang.house_infantry',
 'train.house_tang_internal.heavy_cavalry':'train.house_tang.house_cavalry',
 'train.tang_wei.household_champions':'train.house_tang.house_cavalry',
}
CMD_MAP={
 'cmdgrp.bastion.white_blade':'cmdgrp.house_tang.outer_wall',
 'cmdgrp.bastion.red_thunder':'cmdgrp.house_tang.outer_wall',
 'cmdgrp.bastion.iron_wall':'cmdgrp.house_tang.outer_wall',
 'cmdgrp.bastion.stone_spear':'cmdgrp.house_tang.outer_wall',
 'cmdgrp.sword_manor.field':'cmdgrp.house_tang.inner_walls',
 'cmdgrp.sword_manor.senior':'cmdgrp.house_tang.inner_walls',
 'cmdgrp.sword_manor.general':'cmdgrp.house_tang.inner_walls',
 'cmdgrp.sword_manor.junior':'cmdgrp.house_tang.inner_walls',
 'cmdgrp.sword_manor.trainee':'cmdgrp.house_tang.inner_walls',
 'cmdgrp.house_tang.guardian_cavalry':'cmdgrp.house_tang.inner_citadel',
 'cmdgrp.house_tang.house_guard':'cmdgrp.house_tang.inner_citadel',
}
FORCE_MAP={
 'force_sword_manor':'force_house_tang',
 'force_bastion_white_blade':'force_house_tang',
 'force_bastion_red_thunder':'force_house_tang',
 'force_bastion_iron_wall':'force_house_tang',
 'force_bastion_stone_spear':'force_house_tang',
 'force_house_guardian_cavalry':'force_house_tang',
 'force_house_guards':'force_house_tang',
}
FORMATION_MAP={
 'formation_tang_champions_first':'formation_red_lance_a',
 'formation_tang_champions_second':'formation_red_lance_b',
 'formation_tang_champions_hq':'formation_high_guard_cavalry',
 'formation_tang_wei_house_guard':'cmdgrp.tang_wei.high_guard',
}

def walk(v):
 if isinstance(v,dict): return {k:walk(x) for k,x in v.items()}
 if isinstance(v,list): return [walk(x) for x in v]
 if isinstance(v,str):
  if v in PROGRAM_MAP: return PROGRAM_MAP[v]
  if v in TRAIN_MAP: return TRAIN_MAP[v]
  if v in CMD_MAP: return CMD_MAP[v]
  if v in FORCE_MAP: return FORCE_MAP[v]
  if v in FORMATION_MAP: return FORMATION_MAP[v]
  # scoped old Sword role IDs are no longer active formations
  if v.startswith('force_sword_manor:'): return 'cmdgrp.house_tang.inner_walls'
  return v
 return v

HOME={
 'char_tang_zhu':('cmdgrp.house_tang.field_army',165504,None,'House Tang Home Defense Commander'),
 'char_lin_jiao':('cmdgrp.house_tang.outer_wall',109974,'char_tang_zhu','Outer Wall Commander'),
 'char_pei_an':('cmdgrp.house_tang.inner_walls',30053,'char_tang_zhu','Inner Walls Commander'),
 'char_wei_song':('cmdgrp.house_tang.inner_citadel',25477,'char_tang_zhu','Inner Citadel Commander'),
}

changed=0
for path in sorted((ROOT/'state/char').glob('*.json')):
 d=json.loads(path.read_text()); nd=walk(d)
 ref=str(nd.get('owner_id',''))
 # Collapse active institutional identity while leaving biography/provenance prose alone.
 aff=nd.get('affiliation')
 if isinstance(aff,dict):
  aff.pop('corps_ref',None)
  if aff.get('institution_ref')=='institution_four_bastion_corps': aff['institution_ref']='institution_house_tang'
  aff.setdefault('house_ref','house_tang') if ('house_ref' in aff or ref in HOME) else None
 elif isinstance(aff,list):
  cleaned=[]
  for x in aff:
   sx=str(x)
   sx=FORCE_MAP.get(sx,sx)
   if sx not in cleaned: cleaned.append(sx)
  nd['affiliation']=cleaned
 # Any active House Tang person with explicit old force current formation must route to current command owner.
 if ref in HOME:
  grp,span,higher,role=HOME[ref]
  nd['role']=role
  nd['current_formation_id']=None
  nd['command_assignment']={
   'billet':'command_group_commander','current_command_span':span,
   'external_to_fighting_establishment':True,'command_group_ref':grp,
  }
  nd['military_command']={
   'external_to_fighting_strength':True,'formation_scope':grp,
   'level':f'{span}_commander','higher_commander_ref':higher,
  }
  cs=nd.setdefault('career_state',{})
  cs['current_billet']='command_group_commander'; cs['current_command_span']=span; cs['office_or_command']=role
  nd['activity_contract']={'autonomous_enabled':True,'mode':'standing_role_training','training_program_ref':'program.commander_combined_arms','training_regimen_ref':'house_tang_max_sustainable'}
 # normalize active House officer personal loadout identity without erasing historical equipment evidence
 if 'house_tang' in json.dumps(nd.get('affiliation','')).lower() or ref in HOME:
  if nd.get('loadout_id') in {'loadout_house_champion','loadout_tang_champion','loadout_guardian_cavalry'}:
   nd['loadout_id']='loadout_tang_mounted'
  if nd.get('equipment_loadout_id') in {'loadout_house_champion','loadout_tang_champion','loadout_guardian_cavalry'}:
   nd['equipment_loadout_id']='loadout_tang_mounted'
 if nd!=d:
  path.write_text(json.dumps(nd,ensure_ascii=False,indent=2)+'\n'); changed+=1
print('exact people migrated',changed)