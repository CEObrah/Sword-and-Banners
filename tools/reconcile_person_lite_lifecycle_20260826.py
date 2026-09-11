#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def load(rel): return json.loads((ROOT/rel).read_text(encoding='utf-8'))
def save(rel,d):
    p=ROOT/rel; p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(d,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')

def route_exists(route:str)->bool:
    if not isinstance(route,str) or not route: return False
    base,sep,frag=route.partition('#'); p=ROOT/base
    if not p.is_file(): return False
    if not sep: return True
    try: cur=json.loads(p.read_text(encoding='utf-8'))
    except Exception: return False
    for raw in frag.lstrip('/').split('/'):
        if not raw: continue
        key=raw.replace('~1','/').replace('~0','~')
        if isinstance(cur,dict) and key in cur: cur=cur[key]
        elif isinstance(cur,list) and key.isdigit() and int(key)<len(cur): cur=cur[int(key)]
        else: return False
    return True

def main():
    mapping={
        'char_house_tang_guardian_cavalry_operations_officer':'char_house_tang_house_cavalry_operations_officer',
        'char_house_tang_house_guard_operations_officer':'char_house_tang_house_infantry_operations_officer',
    }
    rows={
      mapping['char_house_tang_guardian_cavalry_operations_officer']:{
        'src':'state/char/house-tang-guardian-cavalry-operations-officer.json',
        'dst':'state/char/house-tang-house-cavalry-operations-officer.json',
        'authority':'House Cavalry Operations Officer','role':'Operations Officer, House Cavalry Command',
        'office':'Operations Officer, House Cavalry Command','current_formation_id':'force_house_tang:house_cavalry',
      },
      mapping['char_house_tang_house_guard_operations_officer']:{
        'src':'state/char/house-tang-house-guard-operations-officer.json',
        'dst':'state/char/house-tang-house-infantry-operations-officer.json',
        'authority':'House Infantry Operations Officer','role':'Operations Officer, House Infantry Command',
        'office':'Operations Officer, House Infantry Command','current_formation_id':'force_house_tang:house_infantry',
      },
    }
    # Consolidate each migrated officer to one current exact identity. Historical
    # service/development evidence is retained; only live identity/billet labels move.
    for new,row in rows.items():
        src=ROOT/row['src']; dst=ROOT/row['dst']
        if src.is_file():
            d=json.loads(src.read_text(encoding='utf-8'))
        elif dst.is_file():
            d=json.loads(dst.read_text(encoding='utf-8'))
        else:
            raise RuntimeError(f'missing operations officer source for {new}')
        d['owner_id']=new; d['authority']=row['authority']; d['role']=row['role']; d['current_formation_id']=row['current_formation_id']
        if isinstance(d.get('career_state'),dict): d['career_state']['office_or_command']=row['office']
        dst.parent.mkdir(parents=True,exist_ok=True); dst.write_text(json.dumps(d,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
        if src != dst and src.exists(): src.unlink()

    cp=load('state/cmd/command-personnel.json'); routes=cp.setdefault('record_index',{})
    for old,new in mapping.items(): routes.pop(old,None)
    routes['char_house_tang_house_cavalry_operations_officer']='state/char/house-tang-house-cavalry-operations-officer.json'
    routes['char_house_tang_house_infantry_operations_officer']='state/char/house-tang-house-infantry-operations-officer.json'
    for ref in ('staff.chu.karin.chu_yan','staff.chu.karin.lan_qi'):
        routes[ref]=f'state/person/person-lite/chu-karin-staff.json#/records/{ref}'
    # Drop only objectively broken routes. A live but currently unassigned exact
    # officer is not stale merely because no command group currently references them.
    routes={ref:route for ref,route in routes.items() if route_exists(route)}
    cp['record_index']=dict(sorted(routes.items())); cp['count']=len(routes); save('state/cmd/command-personnel.json',cp)

    rt=load('state/runtime.json'); hosts=rt.setdefault('hosts',{}); removed=[]
    for hid,h in list(hosts.items()):
        if not isinstance(h,dict): continue
        owner=str(h.get('owner_ref',''))
        if owner in mapping:
            hosts.pop(hid,None); removed.append(hid); continue
        refs=h.get('routed_person_refs')
        if isinstance(refs,list): h['routed_person_refs']=sorted(set(mapping.get(str(x),str(x)) for x in refs))
    if removed:
        dead=set(removed); rt['events']=[e for e in rt.get('events',[]) if not (isinstance(e,dict) and e.get('target_host') in dead)]
    save('state/runtime.json',rt)

    loc=load('state/index/person-location-index.json')
    def remap(v):
        if isinstance(v,dict): return {mapping.get(str(k),str(k)):remap(x) for k,x in v.items()}
        if isinstance(v,list): return [mapping.get(x,x) if isinstance(x,str) else remap(x) for x in v]
        return mapping.get(v,v) if isinstance(v,str) else v
    save('state/index/person-location-index.json',remap(loc))

    # Non-force person-lite command staff need one annual mortality host. Force-owned
    # person-lite bodies stay on their cohort mortality path to avoid double death.
    owners=load('state/index/owner-index.json').get('owners',{})
    rt=load('state/runtime.json'); hosts=rt.setdefault('hosts',{}); events=rt.setdefault('events',[])
    existing_event_targets={str(e.get('target_host')) for e in events if isinstance(e,dict)}
    sys_path_added=False
    import sys
    runtime_path=str(ROOT/'runtime')
    if runtime_path not in sys.path: sys.path.insert(0,runtime_path); sys_path_added=True
    from sword_runtime.sim.calendar import CampaignTime
    now=CampaignTime.parse(str(rt['world_time'])); created_lite=[]
    for person_ref,route in sorted(routes.items()):
        if '#/records/' not in str(route) or not route_exists(route):
            continue
        base,_,frag=str(route).partition('#'); rec=json.loads((ROOT/base).read_text(encoding='utf-8'))
        for raw in frag.lstrip('/').split('/'):
            if raw: rec=rec[raw.replace('~1','/').replace('~0','~')]
        if not isinstance(rec,dict) or rec.get('schema')!='person-lite':
            continue
        if str(rec.get('life_status',rec.get('status','active'))).lower() in {'dead','deceased','destroyed'}:
            continue
        force_owned=False; owner_ref=str(rec.get('owner',''))
        owner_route=owners.get(owner_ref) if owner_ref else None
        if isinstance(owner_route,str) and route_exists(owner_route):
            owner_doc=load(owner_route.split('#',1)[0])
            materialized=owner_doc.get('materialized_people') if isinstance(owner_doc,dict) else None
            force_owned=isinstance(materialized,dict) and person_ref in materialized
        if force_owned:
            continue
        host_id='host_person_'+person_ref.replace('char_','').replace('.','_').replace('-','_')
        # Remove accidental duplicates under a different host key for the same owner.
        duplicate=[hid for hid,h in hosts.items() if hid!=host_id and isinstance(h,dict) and h.get('kind')=='person' and h.get('owner_ref')==person_ref]
        for hid in duplicate: hosts.pop(hid,None)
        if duplicate:
            dset=set(duplicate); events[:]=[e for e in events if not (isinstance(e,dict) and e.get('target_host') in dset)]
        if host_id not in hosts:
            due=now.add_seconds(31536000)
            hosts[host_id]={'kind':'person','owner_ref':person_ref,'recurrence_seconds':31536000,'next_due':str(due),'resolved_through':str(now),'safe_through':str(due.add_seconds(-1)),'quiet_run_count':0}
            created_lite.append(person_ref)
        if host_id not in existing_event_targets and not any(isinstance(e,dict) and e.get('target_host')==host_id for e in events):
            events.append({'event_id':f'event_{host_id}_review','kind':'person_life_review','priority':95,'target_host':host_id,'due_at':hosts[host_id]['next_due']})
    events.sort(key=lambda e:(str(e.get('due_at','')) if isinstance(e,dict) else '',int(e.get('priority',999)) if isinstance(e,dict) else 999,str(e.get('event_id','')) if isinstance(e,dict) else ''))
    save('state/runtime.json',rt)
    print('command personnel routes',len(routes))
    print('removed old duplicate life hosts',removed)
    print('created non-force person-lite life hosts',created_lite)

if __name__=='__main__': main()
