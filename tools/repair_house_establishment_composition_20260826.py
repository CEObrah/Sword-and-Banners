#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
changed=[]
for p in sorted((ROOT/'state/formations').glob('*.json')):
    d=json.loads(p.read_text(encoding='utf-8'))
    if d.get('owner_force_ref')!='force_house_tang':
        continue
    override=d.get('establishment_composition')
    if not isinstance(override,dict):
        continue
    authorized=int(d.get('authorized_strength',0) or 0)
    if authorized<=0 or sum(int(v) for v in override.values())==authorized:
        continue
    current=d.get('composition') if isinstance(d.get('composition'),dict) else {}
    roles=[str(k) for k,v in current.items() if int(v)>0]
    if len(roles)!=1:
        raise RuntimeError(f"{d.get('formation_ref')}: cannot infer multi-role establishment safely: {current}")
    role=roles[0]
    if role not in {'house_infantry','house_cavalry'}:
        raise RuntimeError(f"{d.get('formation_ref')}: illegal House role {role}")
    old=dict(override)
    d['establishment_composition']={role:authorized}
    p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    changed.append((d.get('formation_ref'),old,d['establishment_composition']))
print('repaired House establishment overrides',len(changed))
for ref,old,new in changed: print(ref,old,'->',new)
