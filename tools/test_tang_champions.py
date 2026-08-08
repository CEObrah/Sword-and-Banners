#!/usr/bin/env python3
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
errors=[]

def load(rel):
    p=ROOT/rel
    if not p.exists():
        errors.append(f'missing:{rel}')
        return {}
    return json.loads(p.read_text(encoding='utf-8'))

def err(x): errors.append(x)

first=load('state/unit/tang-champions-first.json')
second=load('state/unit/tang-champions-second.json')
if (ROOT/'state/unit/tang-wei-household-champions.json').exists(): err('legacy_one_company_file_present')
for label,u,uid,cmd in (
    ('first',first,'unit_tang_wei_tang_champions_first','char_duan_jin'),
    ('second',second,'unit_tang_wei_tang_champions_second','char_shen_rui'),
):
    if u.get('id')!=uid: err(f'{label}_id:{u.get("id")}')
    if u.get('owner')!='char_tang_wei': err(f'{label}_owner')
    if u.get('troop_type')!='heavy_cavalry': err(f'{label}_troop_type')
    if u.get('commander_id')!=cmd: err(f'{label}_commander')
    if u.get('doctrine')!='doc.tang_wei.household_champions': err(f'{label}_doctrine')
    if u.get('training')!='train.tang_wei.household_champions': err(f'{label}_training')
    if u.get('loadout_standard')!='loadout_house_guardian_cavalry': err(f'{label}_loadout')
    per=u.get('personnel',{})
    if per.get('representation')!='named_members' or per.get('count')!=50 or len(per.get('member_ids',[]))!=50: err(f'{label}_personnel')
    if per.get('condition',{}).get('healthy')!=50: err(f'{label}_condition')
    if u.get('issue_state',{}).get('mount_issue_state',{}).get('standard_mounts_present')!=50: err(f'{label}_mounts')

m1=first.get('personnel',{}).get('member_ids',[]); m2=second.get('personnel',{}).get('member_ids',[])
if set(m1)&set(m2): err('champion_member_overlap')
expected={f'tw.m{i:03d}' for i in range(1,101)}
if set(m1+m2)!=expected: err('champion_member_union')

pf=load('state/pforce/wei.json')
if pf.get('owner')!='char_tang_wei': err('personal_force_owner')
if pf.get('permanent_units')!=['unit_tang_wei_tang_champions_first','unit_tang_wei_tang_champions_second']: err('personal_force_units')
if set(pf.get('members',[]))!={'char_duan_jin','char_shen_rui',*expected}: err('personal_force_members')

parent=load('state/cmd/command-groups/cmdgrp.tang_wei.personal_force.json')
duan=load('state/cmd/command-groups/cmdgrp.duan_jin.tang_champions_first.json')
shen=load('state/cmd/command-groups/cmdgrp.shen_rui.tang_champions_second.json')
expected_groups={'cmdgrp.duan_jin.tang_champions_first','cmdgrp.shen_rui.tang_champions_second'}
if set(parent.get('subordinate_command_group_refs',[]))!=expected_groups: err('parent_peer_groups')
for label,g,cmd,uid in (
    ('duan',duan,'char_duan_jin','unit_tang_wei_tang_champions_first'),
    ('shen',shen,'char_shen_rui','unit_tang_wei_tang_champions_second'),
):
    if g.get('commander_ref')!=cmd: err(f'{label}_group_commander')
    if g.get('direct_unit_refs')!=[uid]: err(f'{label}_group_unit')
    if g.get('parent_command_group_ref')!='cmdgrp.tang_wei.personal_force': err(f'{label}_group_parent')
    if g.get('deputy_ref') is not None: err(f'{label}_has_deputy')
    if g.get('successor_refs') not in ([],None): err(f'{label}_has_successor')
    if ({'char_duan_jin','char_shen_rui'}-{cmd}) & set(g.get('direct_person_refs',[])): err(f'{label}_contains_peer_commander')

roles=load('data/people/role-profiles.json').get('profiles',{})
if 'role.household_champion.guardian_cavalry' in roles: err('legacy_personal_role_profile')
prof=roles.get('role.tang_champion',{})
if prof.get('rank')!='tang_champion' or prof.get('role')!='tang_champion': err('tang_champion_role_profile')
if prof.get('equipment_standard')!='loadout_house_guardian_cavalry': err('tang_champion_physical_standard')

for i in range(1,101):
    d=load(f'state/person/wei/{i:03d}.json')
    if d.get('id')!=f'tw.m{i:03d}': err(f'champion_id:{i}')
    if d.get('rank')!='tang_champion' or d.get('role')!='tang_champion': err(f'champion_semantic_role:{i}')
    if d.get('role_profile_ref')!='role.tang_champion': err(f'champion_role_profile:{i}')

hgc=load('state/force/house-guardian-cavalry.json')
if hgc.get('aggregate_personnel_count')!=250 or hgc.get('headcount')!=251: err('house_guardian_cavalry_accounting')
pools=hgc.get('manpower_pools',[])
if len(pools)!=1 or pools[0].get('count')!=250 or pools[0].get('condition',{}).get('fit')!=250: err('house_guardian_cavalry_pool')

pop=load('state/pop/population-tang-manor.json')
if not any(rec.get('facts',{}).get('Permanent total')==9600 for rec in pop.get('records',[])): err('tang_manor_population_total')
if not any('100-person Tang Champion personal force' in rec.get('facts',{}).get('core calculation','') for rec in pop.get('records',[])): err('tang_manor_core_calculation')

kai=load('state/char/tang-kai.json')
kcmd=load('state/cmd/command-personnel/char_tang_kai.json')
if kcmd.get('person_id')!='char_tang_kai': err('kai_command_person')
if kcmd.get('command',{}).get('command_scope')!='army_or_unit_command_personnel': err('kai_command_scope')
if kcmd.get('command',{}).get('current_unit_ids')!=[]: err('kai_has_assigned_troops')
if kcmd.get('command',{}).get('current_army_id') is not None: err('kai_has_independent_army')
if 'zero assigned troops' not in kcmd.get('command',{}).get('specialty_hint','').lower(): err('kai_zero_troop_status_missing')
if 'no independent' not in kai.get('authority','').lower(): err('kai_independent_authority_not_blocked')

shen_char=load('state/char/shen-rui.json')
shen_text=' '.join(shen_char.get('goal_state',{}).get('current_goals',[])+shen_char.get('goal_state',{}).get('current_orders',[])).lower()
if 'tang kai' not in shen_text or 'second tang champions' not in shen_text: err('shen_kai_protection_mission')
if 'deputy' in shen_text: err('shen_still_duan_deputy')

doc=load('data/mil/doctrine-records/doc.tang_wei.household_champions.json')
train=load('data/mil/training-records/train.tang_wei.household_champions.json')
combined=json.dumps([doc,train],ensure_ascii=False)
if 'Shen Rui is deputy' in combined: err('shared_doctrine_deputy_residue')
if 'assigned protected principal' not in combined: err('shared_protected_principal_rule_missing')

idx=load('state/index/units.json').get('units',{})
if idx!={'unit_tang_wei_tang_champions_first':'state/unit/tang-champions-first.json','unit_tang_wei_tang_champions_second':'state/unit/tang-champions-second.json'}: err('unit_index')

old='unit_tang_wei_house_guardian_cavalry'
for base in ('state','data'):
    for p in (ROOT/base).rglob('*.json'):
        if old in p.read_text(encoding='utf-8'):
            err(f'legacy_personal_unit_ref:{p.relative_to(ROOT)}')

if errors:
    print('TANG CHAMPIONS TEST FAILED')
    for e in errors: print('-',e)
    sys.exit(1)
print('TANG CHAMPIONS TEST OK')
print('two peer 50-person Tang Champion companies under Tang Wei; Duan protects Wei; Shen protects Kai; Kai owns zero troops')
