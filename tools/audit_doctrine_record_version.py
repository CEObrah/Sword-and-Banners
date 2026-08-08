#!/usr/bin/env python3
from pathlib import Path
import json,re
ROOT=Path(__file__).resolve().parents[1]
SELF=Path(__file__).resolve()
records=sorted((ROOT/'data/mil/doctrine-records').glob('*.json'))
versions=[]
for p in records:
    d=json.loads(p.read_text(encoding='utf-8'))
    doc=d.get('doctrine',{})
    if 'version' in doc: versions.append((p,doc.get('version')))
print(f'doctrine_records={len(records)} version_fields={len(versions)} distinct_versions={sorted({v for _,v in versions})}')
for p,v in versions[:5]: print(f'sample {p.relative_to(ROOT)} version={v}')

# Find actual consumers outside doctrine records/schema/template/audit. Broad contextual matches are reported,
# but only direct access patterns are strong evidence of use.
strong=[]; contextual=[]
patterns=[
    re.compile(r"doctrine[^\n]{0,80}get\(['\"]version['\"]\)",re.I),
    re.compile(r"doctrine[^\n]{0,80}\[['\"]version['\"]\]",re.I),
    re.compile(r"['\"]doctrine['\"][^\n]{0,80}['\"]version['\"]",re.I),
]
ignore_prefixes=('data/mil/doctrine-records/','schemas/doctrine-record-v1.schema.json','data/runtime/templates/doctrine-record.v1.template.json')
for p in ROOT.rglob('*'):
    if '.git' in p.parts or not p.is_file() or p.resolve()==SELF.resolve() or p.suffix.lower() not in ('.py','.json','.md','.yml','.yaml','.txt'):
        continue
    rel=str(p.relative_to(ROOT))
    if any(rel.startswith(x) for x in ignore_prefixes):continue
    try:lines=p.read_text(encoding='utf-8').splitlines()
    except Exception:continue
    for n,line in enumerate(lines,1):
        if any(rx.search(line) for rx in patterns):strong.append((rel,n,line.strip()))
        elif 'doctrine' in line.lower() and 'version' in line.lower():contextual.append((rel,n,line.strip()))
print('=== DIRECT DOCTRINE VERSION CONSUMERS ===')
for x in strong:print(f'{x[0]}:{x[1]}: {x[2]}')
print(f'direct_consumers={len(strong)}')
print('=== CONTEXTUAL DOCTRINE+VERSION LINES ===')
for x in contextual[:80]:print(f'{x[0]}:{x[1]}: {x[2]}')
print(f'contextual_lines={len(contextual)}')

# Report other static-data payload version fields so doctrine cleanup is not mistaken for a blanket policy.
print('=== OTHER NESTED VERSION FIELDS ===')
count=0
for base in ('data','state'):
  for p in (ROOT/base).rglob('*.json'):
    if p.parent==ROOT/'data/mil/doctrine-records':continue
    try:d=json.loads(p.read_text(encoding='utf-8'))
    except Exception:continue
    def walk(x,path=''):
      global count
      if isinstance(x,dict):
        for k,v in x.items():
          np=f'{path}/{k}'
          if k=='version':
            print(f'{p.relative_to(ROOT)}{np}={v!r}');count+=1
          walk(v,np)
      elif isinstance(x,list):
        for i,v in enumerate(x):walk(v,f'{path}/{i}')
    walk(d)
print(f'other_version_fields={count}')

# Disposable proof: remove doctrine payload versions and update only the registered template in this checkout.
# The workflow will run the full validator stack after this script; no branch write occurs from this audit workflow.
if strong:
    raise SystemExit('direct doctrine-version consumer exists; no disposable removal test')
for p,_ in versions:
    d=json.loads(p.read_text(encoding='utf-8'));d['doctrine'].pop('version',None)
    p.write_text(json.dumps(d,separators=(',',':'))+'\n',encoding='utf-8')
tp=ROOT/'data/runtime/templates/doctrine-record.v1.template.json'
t=json.loads(tp.read_text(encoding='utf-8'))
doc=t.get('object_contracts',{}).get('/doctrine',{})
for key in ('allowed_keys','canonical_order'):
    doc[key]=[x for x in doc.get(key,[]) if x!='version']
t.get('type_contracts',{}).pop('/doctrine/version',None)
tp.write_text(json.dumps(t,separators=(',',':'))+'\n',encoding='utf-8')
print('disposable doctrine-version removal staged for validator proof')
