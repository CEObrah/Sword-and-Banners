#!/usr/bin/env python3
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime'))
from sword_runtime.sim.calendar import CampaignTime

runtime_path=ROOT/'state/runtime.json'
owner_path=ROOT/'state/index/owner-index.json'
rt=json.loads(runtime_path.read_text(encoding='utf-8'))
owners=json.loads(owner_path.read_text(encoding='utf-8')).get('owners',{})
hosts=rt.setdefault('hosts',{})
events=rt.setdefault('events',[])
now=CampaignTime.parse(str(rt['world_time']))
existing_people={str(h.get('owner_ref')) for h in hosts.values() if isinstance(h,dict) and h.get('kind')=='person'}
existing_event_targets={str(e.get('target_host')) for e in events if isinstance(e,dict)}
created=[]
for ref,route in sorted(owners.items()):
    if ref=='char_tang_wei' or not isinstance(route,str) or not route.startswith('state/char/'):
        continue
    base=route.split('#',1)[0]
    p=ROOT/base
    if not p.is_file():
        continue
    person=json.loads(p.read_text(encoding='utf-8'))
    if person.get('schema')!='sab_character':
        continue
    if str(person.get('life_status',person.get('status','active'))).lower() in {'dead','deceased'}:
        continue
    if ref in existing_people:
        continue
    host_id='host_person_'+ref.replace('char_','').replace('.','_').replace('-','_')
    due=now.add_seconds(31536000)
    hosts[host_id]={
        'kind':'person','owner_ref':ref,'recurrence_seconds':31536000,
        'next_due':str(due),'resolved_through':str(now),'safe_through':str(due.add_seconds(-1)),
        'quiet_run_count':0,
    }
    if host_id not in existing_event_targets:
        events.append({
            'event_id':f'event_{host_id}_review','kind':'person_life_review','priority':95,
            'target_host':host_id,'due_at':str(due),
        })
    created.append(ref)
events.sort(key=lambda e:(str(e.get('due_at','')),int(e.get('priority',999)),str(e.get('event_id',''))))
runtime_path.write_text(json.dumps(rt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('created life hosts',len(created))
for ref in created: print(ref)
