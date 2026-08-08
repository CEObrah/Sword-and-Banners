#!/usr/bin/env python3
from __future__ import annotations
import copy, hashlib, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIRST_ID = 'unit_tang_wei_tang_champions_first'
SECOND_ID = 'unit_tang_wei_tang_champions_second'
FIRST_PATH = ROOT/'state/unit/tang-champions-first.json'
SECOND_PATH = ROOT/'state/unit/tang-champions-second.json'
OLD_UNIT_PATH = ROOT/'state/unit/tang-wei-household-champions.json'
FIRST_MEMBERS = [f'tw.m{i:03d}' for i in range(1,51)]
SECOND_MEMBERS = [f'tw.m{i:03d}' for i in range(51,101)]
ALL_MEMBERS = FIRST_MEMBERS + SECOND_MEMBERS


def load(rel):
    return json.loads((ROOT/rel).read_text(encoding='utf-8'))

def dump(rel, obj):
    p=ROOT/rel; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, separators=(',',':'))+'\n', encoding='utf-8')

def slug(s):
    return re.sub(r'[^a-z0-9]+','_',s.lower()).strip('_')

def make_unique_name(n, existing_docs, used):
    surnames=sorted({d['name'].split()[0] for d in existing_docs if d.get('name') and len(d['name'].split())>=2})
    givens=sorted({' '.join(d['name'].split()[1:]) for d in existing_docs if d.get('name') and len(d['name'].split())>=2})
    if not surnames or not givens:
        raise SystemExit('champion name component pool unavailable')
    h=hashlib.sha256(f'tang-champions-second|{n}'.encode()).digest()
    s0=int.from_bytes(h[:4],'big')%len(surnames)
    g0=int.from_bytes(h[4:8],'big')%len(givens)
    for off in range(len(surnames)*len(givens)):
        s=surnames[(s0 + off//len(givens))%len(surnames)]
        g=givens[(g0 + off)%len(givens)]
        name=f'{s} {g}'
        if name not in used:
            used.add(name)
            return name, s
    raise SystemExit('unable to derive unique deterministic champion name')

def update_named(rel, fn):
    d=load(rel); fn(d); dump(rel,d)

# Preconditions: this correction is only valid against the known one-company state.
old_unit=load('state/unit/tang-wei-household-champions.json')
if old_unit.get('id')!='unit_tang_wei_house_guardian_cavalry' or old_unit.get('personnel',{}).get('member_ids')!=FIRST_MEMBERS:
    raise SystemExit('unexpected pre-correction Tang champion unit')
hgc=load('state/force/house-guardian-cavalry.json')
pool=hgc['manpower_pools'][0]
if hgc.get('aggregate_personnel_count')!=300 or pool.get('count')!=300:
    raise SystemExit('unexpected House Guardian Cavalry source accounting')
pf=load('state/pforce/wei.json')
if pf.get('permanent_units')!=['unit_tang_wei_house_guardian_cavalry']:
    raise SystemExit('unexpected personal-force unit list')

# Stable role identity for both companies. The physical cavalry equipment standard remains the shared House Tang standard.
roles=load('data/people/role-profiles.json')
old_prof=roles['profiles'].pop('role.household_champion.guardian_cavalry', None)
if not old_prof:
    raise SystemExit('old champion role profile missing')
roles['profiles']['role.tang_champion']={
    'rank':'tang_champion',
    'role':'tang_champion',
    'combat_specializations':old_prof['combat_specializations'],
    'equipment_standard':old_prof['equipment_standard'],
    'mount':old_prof['mount'],
    'loyalty':old_prof['loyalty'],
    'default_narration_priority':old_prof['default_narration_priority'],
    'default_goal':'remain personally ready to protect the company assigned Tang principal under the Tang Champion standard while serving Tang Wei',
    'background_policy':'Tang Champion persistence is structural state; do not repeat data-model persistence prose as biography.',
    'relationship_defaults':[]
}
dump('data/people/role-profiles.json',roles)

# Generalize the existing shared doctrine/training from one named command pair to two peer companies.
doc=load('data/mil/doctrine-records/doc.tang_wei.household_champions.json')
principles=doc['doctrine']['principles']
repls={
    "Tang Wei's survival and freedom of movement":"the assigned protected principal's survival and freedom of movement",
    'shadow Tang Wei':'shadow the assigned protected principal',
    'threat to Tang Wei':'threat to the assigned protected principal',
    "Tang Wei's flanks and rear":"the assigned protected principal's flanks and rear",
    'unless Tang Wei himself pursues':'unless the assigned protected principal pursues',
    'when Tang Wei pursues':'when the assigned protected principal pursues',
    'if Tang Wei is wounded, unhorsed, isolated, or cut off':'if the assigned protected principal is wounded, unhorsed, isolated, or cut off',
    "local reconnaissance serves Tang Wei's immediate protection":"local reconnaissance serves the assigned protected principal's immediate protection",
    'reform around Tang Wei':'reform around the assigned protected principal'
}
newp=[]
for p in principles:
    if p.startswith('Duan Jin commands the unit; Shen Rui is deputy'):
        newp.append('each Tang Champion company obeys its own registered commander; peer-company command does not create deputy or successor authority between Duan Jin and Shen Rui')
        continue
    for a,b in repls.items(): p=p.replace(a,b)
    newp.append(p)
doc['doctrine']['principles']=newp
doc['doctrine']['role']='protective heavy cavalry and mounted precision guard for an assigned Tang principal under Tang Wei command'
dump('data/mil/doctrine-records/doc.tang_wei.household_champions.json',doc)

train=load('data/mil/training-records/train.tang_wei.household_champions.json')
newd=[]
for s in train['profile']['domains']:
    s=s.replace('around Tang Wei','around the assigned protected principal')
    s=s.replace("Tang Wei's movement", "the assigned protected principal's movement")
    s=s.replace("Tang Wei's flanks and rear", "the assigned protected principal's flanks and rear")
    s=s.replace('Duan Jin and Shen Rui command handoff, signals, messengers, and succession drills','company-level command handoff, signals, messengers, and succession drills under the registered company commander')
    newd.append(s)
train['profile']['domains']=newd
dump('data/mil/training-records/train.tang_wei.household_champions.json',train)

# Update the original fifty identities and use their saved champion cohort as deterministic cold-profile evidence
# for the historically omitted second fifty. This does not improve the remaining House Guardian pool.
existing=[]
used=set()
for i in range(1,51):
    rel=f'state/person/wei/{i:03d}.json'
    d=load(rel); existing.append(copy.deepcopy(d)); used.add(d['name'])
    d['rank']='tang_champion'; d['role']='tang_champion'; d['role_profile_ref']='role.tang_champion'
    d['current_goal']='protect Tang Wei under Duan Jin while serving in First Tang Champions'
    if isinstance(d.get('personality'),dict):
        d['personality']['dislikes']=[x.replace('careless risk to Tang Wei','careless risk to the assigned Tang principal') for x in d['personality'].get('dislikes',[])]
    dump(rel,d)

for n in range(51,101):
    h=hashlib.sha256(f'tang-champions-second-profile|{n}'.encode()).digest()
    exemplar=copy.deepcopy(existing[int.from_bytes(h[:4],'big')%50])
    name,surname=make_unique_name(n,existing,used)
    exemplar['id']=f'tw.m{n:03d}'
    exemplar['name']=name
    exemplar['family_id']=f'fam.{slug(surname)}'
    exemplar['rank']='tang_champion'; exemplar['role']='tang_champion'; exemplar['role_profile_ref']='role.tang_champion'
    exemplar['health']={'status':'healthy','fatigue':0}
    exemplar['loc']='Tang Manor'; exemplar['unit']=None
    exemplar['history']={'service':[],'promotion':[]}
    exemplar['current_goal']='protect Tang Kai under Shen Rui while remaining part of Tang Wei personal force'
    if isinstance(exemplar.get('personality'),dict):
        exemplar['personality']['dislikes']=[x.replace('careless risk to Tang Wei','careless risk to the assigned Tang principal') for x in exemplar['personality'].get('dislikes',[])]
    dump(f'state/person/wei/{n:03d}.json',exemplar)

# Correct the source accounting: 50 of the formerly anonymous 300 House Guardian Cavalry were the omitted Second Champions.
hgc['headcount']=251
hgc['aggregate_personnel_count']=250
pool['count']=250
pool['condition']['fit']=250
dump('state/force/house-guardian-cavalry.json',hgc)

# Tang Manor total population is unchanged; only classification inside the permanent martial core is corrected.
pop=load('state/pop/population-tang-manor.json')
for rec in pop['records']:
    facts=rec.get('facts',{})
    if 'core calculation' in facts:
        facts['core calculation']='250 anonymous House Guardian Cavalry + Zhao Fen + 700 anonymous House Guards + Qiu Ren + 3750 permanent anonymous Sword Manor military personnel + Wei Jian + 100-person Tang Champion personal force + Duan Jin + Shen Rui + family 4 = 4809'
dump('state/pop/population-tang-manor.json',pop)

# Issue totals remain identical because the corrected fifty already occupied the same heavy-cavalry issue slots.
inv=load('state/inv/inventories.json')
for rec in inv['records']:
    f=rec.get('facts',{})
    for k,v in list(f.items()):
        if not isinstance(v,str): continue
        v=v.replace('300 anonymous House Guardian Cavalry + Zhao Fen + 700 anonymous House Guards + Qiu Ren + 3800 permanent anonymous Sword Manor personnel + Wei Jian + 50 personal-unit cavalry',
                    '250 anonymous House Guardian Cavalry + Zhao Fen + 700 anonymous House Guards + Qiu Ren + 3800 permanent anonymous Sword Manor personnel + Wei Jian + 100 Tang Champions')
        v=v.replace('300 anonymous House Guardian Cavalry + Zhao Fen + 50 personal cavalry + 50 anonymous Sword Manor officers',
                    '250 anonymous House Guardian Cavalry + Zhao Fen + 100 Tang Champions + 50 anonymous Sword Manor officers')
        v=v.replace('300 anonymous House Guardian Cavalry + Zhao Fen + 700 anonymous House Guards + Qiu Ren + 50 personal cavalry + 50 anonymous Sword Manor officers',
                    '250 anonymous House Guardian Cavalry + Zhao Fen + 700 anonymous House Guards + Qiu Ren + 100 Tang Champions + 50 anonymous Sword Manor officers')
        f[k]=v
dump('state/inv/inventories.json',inv)

# Build two peer 50-person units. First preserves current (bad-revision) Kanyou location until gameplay correction;
# Second is stationed at Tang Manor because its standing protection assignment is Tang Kai.
first=copy.deepcopy(old_unit)
first['id']=FIRST_ID; first['name']='Tang Champions First Company'; first['personnel']['member_ids']=FIRST_MEMBERS
first['commander_id']='char_duan_jin'; first['location']='loc_kanyou'
first['lineage']={'origin':'Tang Wei Personal Retinue Tang Champions','operation':'correction of the intended two-company Tang Champion structure; First Company preserves the original first fifty','created_at':'245-BCE-12-02T09:50:00+08:00','transaction_id':'txn_tang_wei_tang_champions_form'}
second=copy.deepcopy(first)
second['id']=SECOND_ID; second['name']='Tang Champions Second Company'; second['personnel']['member_ids']=SECOND_MEMBERS
second['commander_id']='char_shen_rui'; second['location']='Tang Manor'
second['lineage']={'origin':'Tang Wei Personal Retinue Tang Champions','operation':'historical accounting correction: fifty already-equipped Tang retainers omitted from the intended Second Tang Champions are separated from House Guardian Cavalry accounting','created_at':'245-BCE-12-02T09:50:00+08:00','transaction_id':'txn_tang_wei_tang_champions_form'}
if OLD_UNIT_PATH.exists(): OLD_UNIT_PATH.unlink()
dump('state/unit/tang-champions-first.json',first); dump('state/unit/tang-champions-second.json',second)

# Personal-force ownership remains Tang Wei. Both commanders are exact people outside troop counts.
pf['members']=['char_duan_jin','char_shen_rui']+ALL_MEMBERS
pf['permanent_units']=[FIRST_ID,SECOND_ID]
pf['unassigned_personnel']=[]
dump('state/pforce/wei.json',pf)

# Peer command groups under Tang Wei. Shen is not Duan's deputy or successor.
old_duan=load('state/cmd/command-groups/cmdgrp.duan_jin.household_champions.json')
duan={
 'schema':'command-group.v1','id':'cmdgrp.duan_jin.tang_champions_first','commander_ref':'char_duan_jin','direct_unit_refs':[FIRST_ID],
 'subordinate_command_group_refs':[],'parent_command_group_ref':'cmdgrp.tang_wei.personal_force','context':'personal_guard','standing_order_refs':[],
 'location':'loc_kanyou','direct_person_refs':[],'display_name':'Duan Jin First Tang Champions Command','deputy_ref':None,'successor_refs':[],
 'authority_ref':'char_tang_wei','active_context_ref':FIRST_ID,'communication_ref':None}
shen={
 'schema':'command-group.v1','id':'cmdgrp.shen_rui.tang_champions_second','commander_ref':'char_shen_rui','direct_unit_refs':[SECOND_ID],
 'subordinate_command_group_refs':[],'parent_command_group_ref':'cmdgrp.tang_wei.personal_force','context':'protected_principal_guard','standing_order_refs':[],
 'location':'Tang Manor','direct_person_refs':[],'display_name':'Shen Rui Second Tang Champions Command','deputy_ref':None,'successor_refs':[],
 'authority_ref':'char_tang_wei','active_context_ref':SECOND_ID,'communication_ref':None}
(ROOT/'state/cmd/command-groups/cmdgrp.duan_jin.household_champions.json').unlink()
dump('state/cmd/command-groups/cmdgrp.duan_jin.tang_champions_first.json',duan)
dump('state/cmd/command-groups/cmdgrp.shen_rui.tang_champions_second.json',shen)
parent=load('state/cmd/command-groups/cmdgrp.tang_wei.personal_force.json')
parent['subordinate_command_group_refs']=[duan['id'],shen['id']]
dump('state/cmd/command-groups/cmdgrp.tang_wei.personal_force.json',parent)

# Commander sheets: separate commands and standing protection missions.
d=load('state/char/duan-jin.json')
d['goal_state']['current_goals']=['protect Tang Wei and keep First Tang Champions coherent while he pursues Qin military authority in Kanyou']
d['goal_state']['current_orders']=['command First Tang Champions in Tang Wei personal protection; accompany Tang Wei when he personally moves unless lawfully ordered otherwise']
dump('state/char/duan-jin.json',d)
s=load('state/char/shen-rui.json')
s['current_location']='loc_tang_manor_inner_citadel_family_hall'; s['life_course_state']['location_changes']=0
s['goal_state']['current_goals']=['protect Tang Kai and keep Second Tang Champions ready at Tang Manor while preserving Tang Wei freedom of action']
s['goal_state']['current_orders']=['command Second Tang Champions as a peer company under Tang Wei; remain dedicated to Tang Kai protection until Tang Wei lawfully changes the assignment']
s['runtime']['last_settled_at']='245-BCE-12-02T14:30:48+08:00'
dump('state/char/shen-rui.json',s)

# Kai is a designated commander in Wei's force, but owns no troops and has no independent field authority yet.
k=load('state/char/tang-kai.json')
k['authority']='minor principal; designated commander in Tang Wei personal force; no current troop-command authority before age eligibility'
k['role']='minor principal and designated future commander in Tang Wei personal force; no assigned troops or independent field authority'
k['career_state']['office_or_command']='designated commander in Tang Wei personal force; zero assigned troops and no independent command before age eligibility'
k['goal_state']['institutional_duties']=['hold designated future command status under Tang Wei; no troops are assigned until age eligibility and a later lawful assignment']
dump('state/char/tang-kai.json',k)
kcmd={'schema':'command-person.v1','id':'command_person.char_tang_kai','person_id':'char_tang_kai','command':{
 'representation':'exact_named_person','current_army_id':None,'role':'designated_personal_force_commander',
 'command_scope':'Tang Wei personal force designation only; zero assigned troops; no independent field authority before age eligibility',
 'current_unit_ids':[],'specialty_hint':'future command under Tang Wei after age eligibility and explicit troop assignment'}}
dump('state/cmd/command-personnel/char_tang_kai.json',kcmd)
cpi=load('state/cmd/command-personnel.json'); cpi['record_index']['char_tang_kai']='state/cmd/command-personnel/char_tang_kai.json'; cpi['count']=len(cpi['record_index']); dump('state/cmd/command-personnel.json',cpi)

# Correct the original organizational receipt instead of fabricating a later recruitment event.
tx=load('state/org/unit-transactions.json')
rec=tx['records'][0]
rec.update({
 'id':'txn_tang_wei_tang_champions_form','kind':'reorganization','timestamp':'245-BCE-12-02T09:50:00+08:00',
 'authority':'Tang Wei personal-force ownership and explicit player correction of original two-company setup','method':'historical_accounting_correction_and_structural_reorganization',
 'before':{'unit_ids':[],'personnel_total':100,'equipment_claims':{'loadout_house_guardian_cavalry':100},'named_member_ids':FIRST_MEMBERS},
 'after':{'unit_ids':[FIRST_ID,SECOND_ID],'personnel_total':100,'equipment_claims':{'loadout_house_guardian_cavalry':100},'named_member_ids':ALL_MEMBERS},
 'conservation':{'personnel_delta':0,'people':'100 Tang Champions preserved: original first fifty plus fifty historically omitted retainers removed from the anonymous House Guardian Cavalry accounting; Tang Manor permanent population unchanged','equipment':'the omitted fifty already occupied House Tang heavy-cavalry issue slots; total issued armor, helmets, shields, bows, lances, tack and horse armor remain unchanged','injuries':'all corrected champion personnel are healthy; no injury state changed','experience':'First Company individual capability preserved; Second Company cold individual-lite capability reconstructed deterministically from the saved Tang Champion cohort without raising force totals','history':'original two-company organization corrected at its 09:50 formation point; no later recruitment event invented','animals_or_mounts':'100 Tang Champion heavy-warhorse assignments replace 50 personal plus 50 of the prior anonymous House Guardian Cavalry assignments; total Tang heavy-warhorse assignments unchanged','ammunition_supplies':'100 carried 36-arrow champion quivers replace 50 personal plus 50 prior anonymous heavy-cavalry quivers; total issued arrows unchanged'},
 'capability_evidence':{'partition_authority':'data/mechanics/unit-partition.json','distribution_method':'maintenance correction of a misclassified initial cohort; deterministic cold-profile reconstruction for omitted individual-lite records from existing Tang Champion cohort, not a gameplay selection or reroll','selection_evidence_ref':None,'source_capability_refs':['state/force/house-guardian-cavalry.json','data/people/role-profiles.json','data/mil/training-records/train.tang_wei.household_champions.json'],'result_capability_refs':[str(FIRST_PATH.relative_to(ROOT)),str(SECOND_PATH.relative_to(ROOT))],'cache_rebuild_refs':['state/index/units.json','state/index/owners/tw.json']},
 'reason':'correct the original personal-force setup to two 50-person Tang Champion companies: Duan Jin protects Tang Wei; Shen Rui commands the peer company dedicated to Tang Kai while both companies remain under Tang Wei'
})
dump('state/org/unit-transactions.json',tx)

# Rebuild the small derived indexes touched by new identities.
uidx=load('state/index/units.json'); uidx['units']={FIRST_ID:'state/unit/tang-champions-first.json',SECOND_ID:'state/unit/tang-champions-second.json'}; dump('state/index/units.json',uidx)
tw=load('state/index/owners/tw.json')
for i in range(51,101): tw['owners'][f'tw.m{i:03d}']=f'state/person/wei/{i:03d}.json'
dump('state/index/owners/tw.json',tw)
owners=load('state/index/owners.json'); owners['owner_count']=sum(len(load(rel)['owners']) for rel in owners['prefix_index'].values()); dump('state/index/owners.json',owners)

# Rewrite exact old personal-unit refs in current state/data/tests, without touching legitimate House Guardian Cavalry force identity.
text_targets=[ROOT/'tools/audit.py']
for p in text_targets:
    txt=p.read_text(encoding='utf-8')
    txt=txt.replace("if d.get('rank')!='household_champion':continue", "if d.get('rank')!='tang_champion':continue")
    txt=txt.replace("if _role!='guardian_cavalry':err(f'household_champion_role:{pth.name}')", "if _role!='tang_champion':err(f'tang_champion_role:{pth.name}')")
    txt=txt.replace("err(f'household_champion_loadout:{pth.name}')", "err(f'tang_champion_loadout:{pth.name}')")
    txt=txt.replace("err(f'household_champion_mount:{pth.name}')", "err(f'tang_champion_mount:{pth.name}')")
    txt=txt.replace("err(f'household_champion_loyalty:{pth.name}')", "err(f'tang_champion_loyalty:{pth.name}')")
    txt=txt.replace("if d.get('role_profile_ref')!='role.household_champion.guardian_cavalry':err(f'household_champion_role_profile:{pth.name}')", "if d.get('role_profile_ref')!='role.tang_champion':err(f'tang_champion_role_profile:{pth.name}')")
    txt=txt.replace("err(f'household_champion_skill:{pth.name}:{k}')", "err(f'tang_champion_skill:{pth.name}:{k}')")
    p.write_text(txt,encoding='utf-8')

print('Tang Champions correction prepared: 250 House Guardian Cavalry + two 50-person Tang Champion companies; all total population/equipment/mount issue conserved.')
