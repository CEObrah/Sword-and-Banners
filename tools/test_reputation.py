#!/usr/bin/env python3
from pathlib import Path
import json, sys
R=Path(__file__).resolve().parents[1]
errs=[]
def rj(rel):
    try:return json.loads((R/rel).read_text(encoding='utf-8'))
    except Exception as e:errs.append(f'json:{rel}:{e}');return {}
def err(x):errs.append(x)

m=rj('data/mechanics/reputation.json')
if m.get('schema')!='reputation-mechanics.v1':err('mechanics_schema')
idx=rj('state/reputation/index.json')
if idx.get('authority') is not False:err('index_authority')
# Worked deterministic evidence update.
w=m.get('worked_example',{})
fac=['source_reliability','clarity','channel_integrity','audience_relevance','corroboration']
eff=w.get('base_weight',0)
for k in fac: eff*=w.get(k,0)/100
eff=round(eff)
cap=m.get('evidence_update',{}).get('prior_mass_cap',400)
prior=min(w.get('old_mass',0),max(0,cap-eff))
new_score=round((w.get('old_score',0)*prior+w.get('signal_score',0)*eff)/(prior+eff)) if prior+eff else w.get('old_score',0)
new_mass=min(cap,prior+eff)
conf=round(min(100,20+80*new_mass/cap))
if (eff,new_score,new_mass,conf)!=(w.get('effective_weight'),w.get('new_score'),w.get('new_mass'),w.get('confidence')):
    err(f'worked_example_mismatch:{eff,new_score,new_mass,conf}:{w}')
# No global reputation/fame owner and no direct stat bonus.
blob=json.dumps(m).lower()
for phrase in ('no universal reputation vector','no_free_global_broadcast'):
    if phrase not in blob:err(f'missing_contract:{phrase}')
for bad in ('body stats','weapon stats'):
    if bad not in blob:err(f'missing_no_direct_stat_rule:{bad}')
# Current reputation is sparse: subject profiles point only to actual audience files.
subs=list((R/'state/reputation/subjects').glob('*.json'))
if len(subs)!=idx.get('subject_count'):err('subject_count')
for p in subs:
    d=json.loads(p.read_text(encoding='utf-8'))
    if d.get('authority') is not True:err(f'subject_not_authority:{p.name}')
    for aud,ref in d.get('audience_profiles',{}).items():
        q=R/ref
        if not q.exists():err(f'audience_missing:{p.name}:{aud}')
        else:
            a=json.loads(q.read_text(encoding='utf-8'))
            for section in ('standing','dimensions'):
                for key,val in a.get(section,{}).items():
                    if isinstance(val,dict) and isinstance(val.get('score'),(int,float)) and not 0<=val['score']<=100:err(f'score_range:{p.name}:{section}:{key}')
# Reputation changes must use existing communication routes rather than a duplicate global scheduler.
if m.get('propagation',{}).get('uses_existing_information_routes') is not True:err('propagation_route_contract')
# No second global/scalar reputation system may survive in ordinary current owners.
for p in (R/'state').rglob('*.json'):
    if 'reputation' in p.parts: continue
    try:d=json.loads(p.read_text(encoding='utf-8'))
    except:continue
    if isinstance(d,dict) and 'reputation' in d:
        err(f'legacy_scalar_reputation:{p.relative_to(R)}')
if errs:
    print('REPUTATION TEST FAILED')
    for x in errs:print('-',x)
    sys.exit(1)
print('REPUTATION TEST OK')
print(f'subjects={len(subs)} standing_axes={len(m.get("standing_axes",{}))}')
