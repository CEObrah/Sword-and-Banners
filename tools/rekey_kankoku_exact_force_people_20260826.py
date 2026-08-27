#!/usr/bin/env python3
from __future__ import annotations
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime'))
from sword_runtime.cohort_personnel import validate_cohort_ledger
p=ROOT/'state/forces/state-qin.json'; q=json.loads(p.read_text(encoding='utf-8'))
mp=q.setdefault('materialized_people',{}); ma=q.setdefault('materialized_assignments',{})
changed=[]
for old in sorted([r for r in list(mp) if r.startswith('officer.qin.kankoku.') and r!='officer.qin.kankoku.army.chief_of_staff']):
    new='char_'+old.removeprefix('officer.').replace('.','_').replace('-','_')
    # Conversion is lawful only when the exact replacement really exists.
    char_path=ROOT/'state/char'/f"{new.removeprefix('char_').replace('_','-')}.json"
    if not char_path.is_file():
        raise RuntimeError(f'missing exact Kankoku replacement for {old}: {new}')
    value=mp.pop(old)
    if new in mp: raise RuntimeError(f'duplicate Kankoku force materialization {new}')
    mp[new]=value
    if old in ma:
        if new in ma: raise RuntimeError(f'duplicate Kankoku assignment {new}')
        ma[new]=ma.pop(old)
    changed.append((old,new))
validate_cohort_ledger(q)
p.write_text(json.dumps(q,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
print('rekeyed',len(changed),'Kankoku exact force people')
for row in changed: print(row)
