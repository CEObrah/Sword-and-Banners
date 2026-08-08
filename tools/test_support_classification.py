#!/usr/bin/env python3
from pathlib import Path
import json,re,sys

ROOT=Path(__file__).resolve().parents[1]
errors=[]
FORBIDDEN={'medical','medic','medics','courier','couriers'}
CLASS_KEYS={'role','troop_type','specialty'}
GENERATOR_KEYS=CLASS_KEYS|{'series_id','source_manpower_id','stable_unit_id_pattern'}

def tokens(value):
    return [x for x in re.split(r'[^a-z0-9]+',str(value).lower()) if x]

def bad(value):
    return any(x in FORBIDDEN for x in tokens(value))

def inspect(value,path,keys):
    if isinstance(value,dict):
        for k,v in value.items():
            p=f'{path}/{k}'
            if k in keys and isinstance(v,str) and bad(v):
                errors.append(f'forbidden_military_support_classification:{p}:{v}')
            inspect(v,p,keys)
    elif isinstance(value,list):
        for i,v in enumerate(value): inspect(v,f'{path}/{i}',keys)

def load(path):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except Exception as exc:
        errors.append(f'json:{path.relative_to(ROOT)}:{exc}');return None

# Active/materializable military owners. Civilian population owners are intentionally excluded.
for rel in ('state/unit','state/force','state/force-pool','state/merc'):
    base=ROOT/rel
    if not base.exists(): continue
    for p in base.glob('*.json'):
        d=load(p)
        if d is not None: inspect(d,str(p.relative_to(ROOT)),CLASS_KEYS)

# Home establishments are unit generators, so also ban medical/courier semantics in generator IDs/sources.
base=ROOT/'state/org/home-establishments'
if base.exists():
    for p in base.glob('*.json'):
        d=load(p)
        if d is not None: inspect(d,str(p.relative_to(ROOT)),GENERATOR_KEYS)

# Current troop-type registry itself must not define medical/courier troop classes.
types=load(ROOT/'data/organization/troop-types.json') or {}
for tid in types.get('types',{}):
    if bad(tid): errors.append(f'forbidden_troop_type_registry:{tid}')

support=load(ROOT/'data/mechanics/support.json') or {}
blob=json.dumps(support,ensure_ascii=False).lower()
required=(
    'scouts are military reconnaissance troops, not couriers',
    'medical personnel and couriers are excluded from this class',
    'never create military units or command slots',
    'consume no military unit command slots',
)
for phrase in required:
    if phrase not in blob: errors.append(f'support_contract_missing:{phrase}')

runtime=(ROOT/'RUNTIME.md').read_text(encoding='utf-8').lower()
for phrase in (
    'scouts are reconnaissance troops, not couriers',
    'never military units and never military unit command slots',
    'creating a mutable owner is deterministic template instantiation, never free-form json authorship',
):
    if phrase not in runtime: errors.append(f'runtime_contract_missing:{phrase}')

if errors:
    print('SUPPORT CLASSIFICATION TEST FAILED')
    for e in errors[:250]: print('-',e)
    if len(errors)>250: print('...',len(errors)-250,'more')
    sys.exit(1)
print('SUPPORT CLASSIFICATION TEST OK')
print('military scouts preserved; civilian medical/courier roles excluded from units and generators')
