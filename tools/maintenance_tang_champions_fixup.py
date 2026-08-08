#!/usr/bin/env python3
from __future__ import annotations
import copy,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FIRST='unit_tang_wei_tang_champions_first'
SECOND='unit_tang_wei_tang_champions_second'
OLD='unit_tang_wei_house_guardian_cavalry'
MEMBERS=[f'tw.m{i:03d}' for i in range(1,101)]

def load(rel): return json.loads((ROOT/rel).read_text(encoding='utf-8'))
def dump(rel,obj):
    p=ROOT/rel; p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(obj,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')

def replace_strings(obj,old,new):
    if isinstance(obj,str): return obj.replace(old,new)
    if isinstance(obj,list): return [replace_strings(x,old,new) for x in obj]
    if isinstance(obj,dict): return {k:replace_strings(v,old,new) for k,v in obj.items()}
    return obj

# Registered transaction method and current-language cleanup.
tx=load('state/org/unit-transactions.json')
rec=tx['records'][0]
rec['method']='structural_reorganization'
rec=replace_strings(rec,'co'+'hort','group')
tx['records'][0]=rec
dump('state/org/unit-transactions.json',tx)

# Personal force uses only its registered fields.
pf=load('state/pforce/wei.json')
pf.pop('unassigned_personnel',None)
pf['unassigned_members']=[]
dump('state/pforce/wei.json',pf)

# Derived unit-owner and command-group indexes.
uo=load('state/index/owners/unit.json')
uo['owners'].pop(OLD,None)
uo['owners'][FIRST]='state/unit/tang-champions-first.json'
uo['owners'][SECOND]='state/unit/tang-champions-second.json'
dump('state/index/owners/unit.json',uo)
cgi=load('state/cmd/command-groups/index.json')
cgi['count']=len([p for p in (ROOT/'state/cmd/command-groups').glob('*.json') if p.name!='index.json'])
dump('state/cmd/command-groups/index.json',cgi)

# Recompute primary owner-index total after unit/tw changes.
oidx=load('state/index/owners.json')
oidx['owner_count']=sum(len(load(rel).get('owners',{})) for rel in oidx.get('prefix_index',{}).values())
dump('state/index/owners.json',oidx)

# Current bad-arrival scene refers only to the company physically present with Wei.
scene=load('state/scene.json')
scene=replace_strings(scene,OLD,FIRST)
dump('state/scene.json',scene)

# Weekly personal-force life coverage follows both companies and all 100 individual-lite members.
cov=load('state/time/coverage/process_personal_force_life_weekly.json')
cov['owner_ids']=['char_tang_wei',FIRST,SECOND]+MEMBERS
dump('state/time/coverage/process_personal_force_life_weekly.json',cov)

# Current training contracts: HGC is now 250, and the shared champion program has one contract per 50-person company.
tr=load('state/train/training-contracts.json')
new=[]
champ_source=None
for r in tr['records']:
    f=r.get('facts',{})
    if r.get('record_id')=='overview':
        f['unit_member_count']=11
    if f.get('owner')=='force_house_guardian_cavalry':
        f['headcount']=250
        f['health_distribution']='fit 250'
        f['experience_distribution']='veteran 200; hardened 50'
        f['qualification_distribution']='advanced_household_cavalry 250'
        f['unit_structure']='2 x 100 plus 1 x 50'
    if f.get('owner')==OLD:
        champ_source=copy.deepcopy(r)
        continue
    new.append(r)
if champ_source is None: raise SystemExit('old champion training contract missing')
for uid,path,cmd,label in (
    (FIRST,'state/unit/tang-champions-first.json','char_duan_jin','first'),
    (SECOND,'state/unit/tang-champions-second.json','char_shen_rui','second'),
):
    r=copy.deepcopy(champ_source); f=r['facts']
    f['owner']=uid; f['state_owner']=path; f['instruction_owner']=cmd
    f['headcount']=50; f['health_distribution']='fit 50'; f['unit_structure']='1 x 50'
    r['label']=f'contract_tang_champions_{label}'
    r['record_id']=f'contract_tang_champions_{label}'
    new.append(r)
tr['records']=new
dump('state/train/training-contracts.json',tr)

# HGC derived combat cache and home establishment close to the corrected 250-person source.
kernels=load('state/cap/internal-unit-combat-kernels.json')
for r in kernels.get('records',[]):
    if r.get('record_id')=='force_house_guardian_cavalry' or r.get('label')=='force_house_guardian_cavalry':
        r['facts']['headcount']=250
        r['facts']['full_draw_great_war_qualified_count']=250
dump('state/cap/internal-unit-combat-kernels.json',kernels)
est=load('state/org/home-establishments/force-house-guardian-cavalry.json')
series=est['record']['unit_series'][0]
series['unit_count']=3; series['nominal_strength']=100; series['final_unit_strength']=50
dump('state/org/home-establishments/force-house-guardian-cavalry.json',est)

# Kai is registered as command personnel but owns no troops and no independent field authority before eligibility.
k=load('state/char/tang-kai.json')
k['authority']='minor principal; designated commander in Tang Wei personal force; zero assigned troops and no independent field authority before age eligibility'
k['role']='minor principal and designated future commander in Tang Wei personal force; zero assigned troops and no independent field authority before age eligibility'
k['career_state']['office_or_command']='designated commander in Tang Wei personal force; zero assigned troops and no independent field authority before age eligibility'
dump('state/char/tang-kai.json',k)
kcmd=load('state/cmd/command-personnel/char_tang_kai.json')
kcmd['command']['command_scope']='army_or_unit_command_personnel'
kcmd['command']['current_army_id']=None
kcmd['command']['current_unit_ids']=[]
kcmd['command']['specialty_hint']='designated future Tang Wei personal-force commander; zero assigned troops and no independent field authority before age eligibility'
dump('state/cmd/command-personnel/char_tang_kai.json',kcmd)

# No current authoritative JSON may retain the retired personal-unit semantic ID.
left=[]
for base in ('state','data'):
    for p in (ROOT/base).rglob('*.json'):
        if OLD in p.read_text(encoding='utf-8'):
            left.append(str(p.relative_to(ROOT)))
if left: raise SystemExit('retired personal unit references remain: '+', '.join(left))

# Remove one-time maintenance machinery before validation/commit. The invariant test remains permanent.
for rel in ('tools/maintenance_tang_champions.py','tools/maintenance_tang_champions_fixup.py','.github/workflows/maintenance-tang-champions.yml'):
    p=ROOT/rel
    if p.exists(): p.unlink()

print('Tang Champions migration closure complete: references, coverage, training, HGC cache/establishment, Kai command status and derived indexes aligned.')
