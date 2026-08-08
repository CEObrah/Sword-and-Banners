#!/usr/bin/env python3
from pathlib import Path
import json,re
ROOT=Path(__file__).resolve().parents[1]
TARGETS=[
 ('state/meta.json','meta'),
 ('data/balance/state-military-identities.json','state-military-identities.v38'),
 ('data/development/model.json','development-model.v38'),
 ('data/mechanics/core.json','mechanics-core.v38'),
]
print('=== TARGET VERSION FIELDS ===')
for rel,schema in TARGETS:
 d=json.loads((ROOT/rel).read_text(encoding='utf-8'))
 print(rel,'schema=',d.get('schema'),'version=',d.get('version'))
 if d.get('schema')!=schema:raise SystemExit(f'unexpected schema {rel}:{d.get("schema")}')
 if 'version' not in d:raise SystemExit(f'expected version field missing {rel}')

print('=== DIRECT VERSION-FIELD COUPLING ===')
patterns=[
 re.compile(r"meta\.get\(['\"]version['\"]\)"),
 re.compile(r"\[['\"]version['\"]\]"),
 re.compile(r"get\(['\"]version['\"]"),
 re.compile(r"['\"]version['\"]\s*[:=]"),
]
for p in ROOT.rglob('*'):
 if '.git' in p.parts or not p.is_file() or p==Path(__file__).resolve() or p.suffix.lower() not in ('.py','.md','.json','.yml','.yaml','.txt'):
  continue
 try:lines=p.read_text(encoding='utf-8').splitlines()
 except Exception:continue
 for n,line in enumerate(lines,1):
  if 'version' not in line.lower():continue
  # Report likely coupling and the VERSION file references; informational only.
  if any(rx.search(line) for rx in patterns) or 'VERSION' in line or 'meta_version' in line:
   print(f'{p.relative_to(ROOT)}:{n}: {line.strip()}')

print('=== SCHEMA/TEMPLATE REQUIREMENTS ===')
reg=json.loads((ROOT/'schemas/registry.json').read_text(encoding='utf-8'))
idx=json.loads((ROOT/'data/runtime/template-index.json').read_text(encoding='utf-8'))
templates={}
for shard_rel in idx.get('shards',{}).values():
 sh=json.loads((ROOT/shard_rel).read_text(encoding='utf-8'))
 templates.update(sh.get('templates',{}))
for rel,sid in TARGETS:
 sf=reg.get(sid)
 print(f'{sid}: schema_file={sf} template={(templates.get(sid) or {}).get("path")}')
 if sf:
  spec=json.loads((ROOT/'schemas'/sf).read_text(encoding='utf-8'))
  print(' required_has_version=', 'version' in spec.get('required',[]),'property_has_version=', 'version' in spec.get('properties',{}))
 tp=(templates.get(sid) or {}).get('path')
 if tp:
  blob=(ROOT/tp).read_text(encoding='utf-8')
  print(' template_mentions_version=', 'version' in blob)

print('=== VERSION FILE REFERENCES ===')
for p in ROOT.rglob('*'):
 if '.git' in p.parts or not p.is_file() or p==Path(__file__).resolve() or p.name=='VERSION' or p.suffix.lower() not in ('.py','.md','.json','.yml','.yaml','.txt'):
  continue
 try:text=p.read_text(encoding='utf-8')
 except Exception:continue
 if re.search(r'(?<![A-Za-z])VERSION(?![A-Za-z])',text):print(p.relative_to(ROOT))
