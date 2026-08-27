#!/usr/bin/env python3
from __future__ import annotations
import copy, hashlib, json, re, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from sword_runtime.cohort_personnel import validate_cohort_ledger

NOW = '244-BCE-09-09T20:22:48+08:00'
SURNAMES = ('Li','Wang','Meng','Zhang','Zhao','Bai','Fan','Huan','Gao','Lu','Tian','Sun','Jing','Du','Xu','Han','Wei','Cao','Ren','Pei','Deng','Shen','Luo','Qiao')
GIVENS = ('Ren','Sheng','Jun','An','Yi','Ke','Rui','Zhen','Bo','Qian','Yong','Lin','Jie','He','Tao','Cheng','Shan','Ming','Yu','Zhong','Kai','Ning','Rong','Wen')
ATTRS = ('Agility','Awareness','Composure','Coordination','Endurance','Intelligence','Presence','Strength','Toughness')
SKILLS = ('Sword','Polearms','Heavy Weapons','Bow','Crossbow','Shield','Athletics','Grappling','Unarmed','Riding','Formation Fighting','Survival','Stealth','Scouting','Medicine','Engineering','Leadership','Formation Command','Tactics','Strategy','Logistics')
PRO = ('Intelligence Operations','Diplomacy','Law','Trade','Governance')


def load(rel: str): return json.loads((ROOT / rel).read_text(encoding='utf-8'))
def save(rel: str, obj) -> None:
    p = ROOT / rel; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=False) + '\n', encoding='utf-8')

def formation_files():
    for p in sorted((ROOT/'state/formations').glob('*.json')):
        d=json.loads(p.read_text(encoding='utf-8'))
        ref=d.get('formation_ref')
        if isinstance(ref,str): yield ref,p,d

def force_files():
    out={}
    for p in sorted((ROOT/'state/forces').glob('*.json')):
        d=json.loads(p.read_text(encoding='utf-8')); ref=d.get('owner_id')
        if isinstance(ref,str): out[ref]=(p,d)
    return out

def rank_for(span:int)->str:
    if span >= 10000: return 'general'
    for n in (9000,8000,7000,6000,5000,4000,3000,2000,1000,500):
        if span >= n: return f'{n}_commander'
    return '100_commander'

def unique_name(ref:str, used:set[str])->str:
    raw=int(hashlib.sha256(ref.encode()).hexdigest()[:14],16)
    for i in range(1000):
        name=f'{SURNAMES[(raw+i)%len(SURNAMES)]} {GIVENS[((raw//len(SURNAMES))+i*7)%len(GIVENS)]}'
        if name not in used:
            used.add(name); return name
    raise RuntimeError('name pool exhausted')

def num_map(src, keys, seed, base=60.0):
    src=src if isinstance(src,dict) else {}
    out={}
    for i,k in enumerate(keys):
        v=src.get(k)
        if v is None:
            v=base + ((seed >> (i % 20)) % 21)
        out[k]=round(float(v),3)
    return out

def source_cohort_for_external(force, formation_ref, role):
    for cid,c in force.get('cohort_ledger',{}).get('cohorts',{}).items():
        if str(c.get('role')) != str(role): continue
        if int(c.get('allocated_external_by_formation',{}).get(formation_ref,0) or 0)>0:
            return cid,c
    return None,None

def source_cohort_for_internal(force, formation_ref):
    rows=[]
    for cid,c in force.get('cohort_ledger',{}).get('cohorts',{}).items():
        n=int(c.get('allocated_by_formation',{}).get(formation_ref,0) or 0)
        if n<=0: continue
        role=str(c.get('role',''))
        pref=0 if role=='command_personnel' else 1 if 'retainer' in role else 2
        rows.append((pref,-n,cid,c))
    if not rows: return None,None
    return sorted(rows,key=lambda x:(x[0],x[1],x[2]))[0][2:]

def dominant_role(formation):
    comp=formation.get('composition') if isinstance(formation.get('composition'),dict) else {}
    if not comp: return 'line_infantry'
    return max(comp.items(),key=lambda kv:int(kv[1]))[0]

def loadout_for(formation, role):
    by=formation.get('registered_loadouts_by_role') if isinstance(formation.get('registered_loadouts_by_role'),dict) else {}
    if role in by: return str(by[role])
    if isinstance(formation.get('registered_loadout_ref'),str): return formation['registered_loadout_ref']
    r=str(role)
    if 'cavalry' in r or 'mounted' in r: return 'loadout_state_cavalry'
    if 'archer' in r or r=='bow': return 'loadout_state_archer'
    if 'crossbow' in r: return 'loadout_state_crossbow'
    return 'loadout_state_line_infantry'

def parent_commander(formation):
    ref=formation.get('higher_command_ref')
    if not isinstance(ref,str): return None
    p=ROOT/'state/cmd/command-groups'/f'{ref}.json'
    if not p.exists(): return None
    try: d=json.loads(p.read_text()); c=d.get('commander_ref'); return c if isinstance(c,str) else None
    except Exception: return None

def consume_external_slot(force, formation_ref):
    top=force.get('external_personnel_allocations',{}).get(formation_ref)
    if not isinstance(top,dict) or not any(int(v)>0 for v in top.values()): return None
    roles=sorted(((0 if r=='command_personnel' else 1,r,int(n)) for r,n in top.items() if int(n)>0))
    _,role,_=roles[0]
    cid,c=source_cohort_for_external(force,formation_ref,role)
    if not c: raise RuntimeError(f'{formation_ref}: top external slot has no cohort source {role}')
    c['allocated_external_by_formation'][formation_ref]=int(c['allocated_external_by_formation'][formation_ref])-1
    if c['allocated_external_by_formation'][formation_ref]<=0: c['allocated_external_by_formation'].pop(formation_ref,None)
    top[role]=int(top[role])-1
    if top[role]<=0: top.pop(role,None)
    if not top: force['external_personnel_allocations'].pop(formation_ref,None)
    return cid,c,role,'existing_external_command_slot'

def consume_internal_slot(force, formation, formation_path):
    ref=formation['formation_ref']; cid,c=source_cohort_for_internal(force,ref)
    if not c: raise RuntimeError(f'{ref}: no conserved cohort body to materialize')
    role=str(c.get('role','line_infantry'))
    c['allocated_by_formation'][ref]=int(c['allocated_by_formation'][ref])-1
    if c['allocated_by_formation'][ref]<=0: c['allocated_by_formation'].pop(ref,None)
    top=force.get('allocated_to_formations',{}).get(ref)
    if not isinstance(top,dict): raise RuntimeError(f'{ref}: no top formation allocation')
    top['personnel']=int(top.get('personnel',0))-1
    if isinstance(top.get('composition'),dict):
        top['composition'][role]=int(top['composition'].get(role,0))-1
        if top['composition'][role]<=0: top['composition'].pop(role,None)
    elif top.get('role')==role and 'personnel' not in top:
        raise RuntimeError(f'{ref}: unsupported allocation shape')
    formation['personnel']=int(formation.get('personnel',0))-1
    comp=formation.get('composition') if isinstance(formation.get('composition'),dict) else {}
    if role in comp:
        comp[role]=int(comp[role])-1
        if comp[role]<=0: comp.pop(role,None)
    # Derived cohort-composition cache must follow the authoritative cohort ledger.
    for row in formation.get('cohort_composition',[]) if isinstance(formation.get('cohort_composition'),list) else []:
        if isinstance(row,dict) and row.get('cohort_id')==cid and int(row.get('count',0) or 0)>0:
            row['count']=int(row['count'])-1
    formation['cohort_composition']=[r for r in formation.get('cohort_composition',[]) if isinstance(r,dict) and int(r.get('count',0) or 0)>0]
    return cid,c,role,'reclassified_from_fighting_formation'

def make_exact(person_ref,name,formation,cohort,source_cid,source_role,source_mode):
    seed=int(hashlib.sha256(person_ref.encode()).hexdigest()[:16],16)
    attrs=num_map(cohort.get('attribute_means',{}),ATTRS,seed,72.0)
    skills=num_map(cohort.get('skill_means',{}),SKILLS,seed>>3,55.0)
    # Existing command billet selection differentiates command judgment, not combat talent.
    span=int(formation.get('personnel',0) or 0)
    skills['Formation Command']=max(skills['Formation Command'],72.0 + seed%15)
    skills['Leadership']=max(skills['Leadership'],68.0 + (seed//17)%16)
    skills['Tactics']=max(skills['Tactics'],66.0 + (seed//101)%17)
    skills['Strategy']=max(skills['Strategy'],58.0 + (seed//1009)%18)
    skills['Logistics']=max(skills['Logistics'],58.0 + (seed//10007)%18)
    pro={k:float(20 + ((seed >> (i*5)) % 41)) for i,k in enumerate(PRO)}
    role=dominant_role(formation); loadout=loadout_for(formation,role)
    parent=formation.get('higher_command_ref') if isinstance(formation.get('higher_command_ref'),str) else None
    higher=parent_commander(formation)
    birth_year=244 + 23 + seed%24
    title=f'{span}-man Commander, {formation.get("name",formation["formation_ref"])}'
    p={
      'schema':'sab_character','owner_id':person_ref,'owner_type':'character','name':name,
      'birth_date':f'{birth_year}-BCE-{1+(seed//29)%12:02d}-{1+(seed//401)%28:02d}',
      'body':{'adult_height_cm':round(165.0+(seed%165)/10.0,1),'current_weight_kg':round(58.0+((seed//101)%220)/10.0,1),'frame':'average','growth_end_age':18,'height_anchors':[]},
      'appearance':45+seed%51,
      'affiliation':[str(formation.get('administrative_owner') or formation.get('owner_force_ref') or 'military'),str(formation.get('owner_force_ref') or '')],
      'role':title,'life_status':'active','health_status':'fit','fatigue':0,
      'aptitude':{'academic_learning':100+(seed%31),'physical_learning':100+((seed//7)%31),'social_learning':100+((seed//13)%31),'tactical_learning':110+((seed//17)%36),'technical_learning':100+((seed//23)%31)},
      'attributes':attrs,'skills':skills,'professional_skills':pro,
      'current_location':str(formation.get('location_ref') or ''),'current_formation_id':formation['formation_ref'],
      'runtime':{'last_settled_at':NOW},
      'goal_state':{'current_goals':['perform assigned command duty'],'institutional_duties':[title]},
      'military_rank':{'durable':True,'grade':rank_for(span)},
      'career_state':{'current_billet':'formation_commander','current_command_span':span,'office_or_command':title},
      'command_assignment':{'billet':'formation_commander','formation_ref':formation['formation_ref'],'current_command_span':span,'external_to_fighting_establishment':True},
      'military_command':{'external_to_fighting_strength':True,'formation_scope':formation['formation_ref'],'level':rank_for(span)},
      'activity_contract':{'autonomous_enabled':True,'mode':'standing_role_training','training_regimen_ref':'regular_army','training_program_ref':'program.commander_combined_arms'},
      'development_state':{},
      'personal_loadout_ref':loadout,'loadout_id':loadout,'equipment_loadout_id':loadout,
      'source_cohort_ref':source_cid,
      'materialization_provenance':{'source_cohort_ref':source_cid,'source_role':source_role,'source_mode':source_mode,'reclassified_at':NOW},
    }
    if parent: p['command_assignment']['command_group_ref']=parent
    if higher and higher!=person_ref: p['military_command']['higher_commander_ref']=higher
    return p

def convert_person_lite_kankoku(owners, used):
    shard_rel='state/person/person-lite/cmdgrp-kankoku-defense-army-0001.json'
    sp=ROOT/shard_rel
    if not sp.exists(): return {},0
    shard=json.loads(sp.read_text()); recs=shard.get('records',{}) if isinstance(shard.get('records'),dict) else {}
    mapping={}; converted=0
    forms={r:(p,d) for r,p,d in formation_files()}
    groups={}
    for p in (ROOT/'state/cmd/command-groups').glob('cmdgrp*.json'):
        if p.name=='index.json': continue
        d=json.loads(p.read_text());
        if isinstance(d.get('id'),str): groups[d['id']]=(p,d)
    for old,rec in list(recs.items()):
        ca=rec.get('command_assignment') if isinstance(rec.get('command_assignment'),dict) else {}
        grade=str((rec.get('military_rank') or {}).get('grade',''))
        is_army=ca.get('command_group_ref')=='cmdgrp.kankoku.defense_army' and ca.get('billet')=='army_commander'
        m=re.match(r'(\d+)_commander$',grade); scale=int(m.group(1)) if m else 0
        if not is_army and scale<500: continue
        new='char_'+old.removeprefix('officer.').replace('.','_').replace('-','_')
        mapping[old]=new
        person={
          'schema':'sab_character','owner_id':new,'owner_type':'character','name':str(rec.get('name') or unique_name(new,used)),
          'birth_date':str(rec.get('birth_date') or '278-BCE-01-01'),
          'body':copy.deepcopy(rec.get('body') or {'adult_height_cm':170.0,'current_weight_kg':70.0,'frame':'average','growth_end_age':18,'height_anchors':[]}),
          'appearance':float(rec.get('appearance',60) or 60),'affiliation':['state_qin','Kankoku Defense Army'],
          'role':str(rec.get('role') or 'Kankoku officer'),'life_status':'active','health_status':'fit','fatigue':0,
          'aptitude':copy.deepcopy(rec.get('aptitude') or {'academic_learning':110,'physical_learning':110,'social_learning':110,'tactical_learning':120,'technical_learning':110}),
          'attributes':num_map(rec.get('attributes') or (rec.get('stats',{}) if isinstance(rec.get('stats'),dict) else {}).get('attributes',{}),ATTRS,int(hashlib.sha256(new.encode()).hexdigest()[:12],16),75),
          'skills':num_map(rec.get('skills') or (rec.get('stats',{}) if isinstance(rec.get('stats'),dict) else {}).get('skills',{}),SKILLS,int(hashlib.sha256(new.encode()).hexdigest()[12:24],16),60),
          'professional_skills':{k:float(v) for k,v in (rec.get('professional_skills') or {}).items() if float(v)!=0.0},
          'current_location':str(rec.get('current_location') or 'loc_kankoku_pass'),'runtime':{'last_settled_at':NOW},
          'military_rank':copy.deepcopy(rec.get('military_rank') or {'durable':True,'grade':'500_commander'}),
          'career_state':copy.deepcopy(rec.get('career_state') or {}),'command_assignment':copy.deepcopy(ca),
          'activity_contract':copy.deepcopy(rec.get('activity_contract') or {'autonomous_enabled':True,'mode':'standing_role_training','training_regimen_ref':'regular_army','training_program_ref':'program.commander_combined_arms'}),
          'development_state':copy.deepcopy(rec.get('development_state') or {}),
          'goal_state':copy.deepcopy(rec.get('goal_state') or {'current_goals':['perform assigned command duty'],'institutional_duties':['Kankoku defense']}),
          'personal_loadout_ref':str(rec.get('personal_loadout_ref') or rec.get('loadout_id') or 'loadout_state_line_infantry'),
        }
        if not person['professional_skills']:
            seed=int(hashlib.sha256(new.encode()).hexdigest()[:16],16); person['professional_skills']={k:float(20+((seed>>(i*5))%41)) for i,k in enumerate(PRO)}
        person['loadout_id']=person['personal_loadout_ref']; person['equipment_loadout_id']=person['personal_loadout_ref']
        fr=ca.get('formation_ref')
        if isinstance(fr,str) and fr in forms:
            _,fd=forms[fr]; person['current_formation_id']=fr
            if fd.get('location_ref'): person['current_location']=fd['location_ref']
            span=int(fd.get('personnel',0) or 0) if ca.get('billet')=='formation_commander' else int(ca.get('scale',scale) or scale)
            person['career_state'].update({'current_billet':ca.get('billet'),'current_command_span':span})
            person['command_assignment']['current_command_span']=span
            person['military_command']={'external_to_fighting_strength':bool(ca.get('external_to_fighting_strength',False)),'formation_scope':fr,'level':rank_for(max(500,span))}
        if is_army:
            gp,gd=groups['cmdgrp.kankoku.defense_army']; span=int(gd.get('organizational_state',{}).get('current_recursive_strength',0) or 0)
            person['career_state'].update({'current_billet':'army_commander','current_command_span':span,'office_or_command':'Kankoku Defense Army Commander'})
            person['military_command']={'external_to_fighting_strength':True,'formation_scope':'cmdgrp.kankoku.defense_army','level':'general'}
        rel='state/char/'+new.removeprefix('char_').replace('_','-')+'.json'; save(rel,person); owners[new]=rel
        recs.pop(old,None); owners.pop(old,None); converted+=1
    shard['records']=recs; shard['record_count']=len(recs); save(shard_rel,shard)
    # Update live formation/group/cadre refs only.
    for ref,p,d in formation_files():
        changed=False
        if d.get('commander_ref') in mapping: d['commander_ref']=mapping[d['commander_ref']]; changed=True
        emb=d.get('embedded_person_refs')
        if isinstance(emb,list):
            new=[mapping.get(x,x) for x in emb]
            if new!=emb: d['embedded_person_refs']=new; changed=True
        cadre=d.get('officer_cadre')
        if isinstance(cadre,dict) and isinstance(cadre.get('materialized_refs_by_rank'),dict):
            for rank,refs in list(cadre['materialized_refs_by_rank'].items()):
                if isinstance(refs,list):
                    new=[mapping.get(x,x) for x in refs]
                    if new!=refs: cadre['materialized_refs_by_rank'][rank]=new; changed=True
        if changed: p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
    for ref,(p,d) in groups.items():
        changed=False
        if d.get('commander_ref') in mapping: d['commander_ref']=mapping[d['commander_ref']]; changed=True
        if isinstance(d.get('direct_person_refs'),list):
            new=[mapping.get(x,x) for x in d['direct_person_refs']]
            if new!=d['direct_person_refs']: d['direct_person_refs']=new; changed=True
        if isinstance(d.get('role_assignments'),dict):
            nr={mapping.get(k,k):v for k,v in d['role_assignments'].items()}
            if nr!=d['role_assignments']: d['role_assignments']=nr; changed=True
        if isinstance(d.get('successor_refs'),list):
            new=[mapping.get(x,x) for x in d['successor_refs']]
            if new!=d['successor_refs']: d['successor_refs']=new; changed=True
        if changed: p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
    return mapping,converted

def main():
    idx=load('state/index/owner-index.json'); owners=idx.setdefault('owners',{})
    used=set()
    for p in (ROOT/'state/char').glob('*.json'):
        try:
            n=json.loads(p.read_text()).get('name')
            if isinstance(n,str): used.add(n)
        except Exception: pass
    mapping,kconverted=convert_person_lite_kankoku(owners,used)
    forces=force_files()
    created=[]
    for ref,path,formation in list(formation_files()):
        if int(formation.get('personnel',0) or 0)<500 or formation.get('commander_ref'): continue
        force_ref=str(formation.get('owner_force_ref')); fp,force=forces[force_ref]
        consumed=consume_external_slot(force,ref)
        if consumed is None: consumed=consume_internal_slot(force,formation,path)
        cid,cohort,role,mode=consumed
        person_ref='char_cmd_'+ref.removeprefix('formation_')
        person_ref=person_ref.replace('.','_').replace('-','_')
        if person_ref in owners: raise RuntimeError(f'commander ref collision {person_ref}')
        name=unique_name(person_ref,used)
        person=make_exact(person_ref,name,formation,cohort,cid,role,mode)
        rel='state/char/'+person_ref.removeprefix('char_').replace('_','-')+'.json'; save(rel,person)
        force.setdefault('materialized_people',{})[person_ref]={'personnel':1,'role':role,'source_cohort_ref':cid,'source_mode':mode}
        formation['commander_ref']=person_ref
        path.write_text(json.dumps(formation,ensure_ascii=False,indent=2)+'\n')
        validate_cohort_ledger(force)
        fp.write_text(json.dumps(force,ensure_ascii=False,indent=2)+'\n')
        forces[force_ref]=(fp,force); owners[person_ref]=rel
        created.append((person_ref,name,ref,role,mode))
    idx['owners']=dict(sorted(owners.items())); save('state/index/owner-index.json',idx)
    print('converted Kankoku persistent 500+ person-lite officers',kconverted)
    print('created missing formation commanders',len(created))
    for row in created: print(row)
    # Final force-ledger verification.
    for _ref,(_p,f) in forces.items(): validate_cohort_ledger(f)

if __name__=='__main__': main()
