#!/usr/bin/env python3
from pathlib import Path
import json,re,collections

ROOT=Path(__file__).resolve().parents[1]
VERSIONED=re.compile(r'(?i)(?:[._-]v\d+\b)')
SCHEMAISH_KEYS={'schema','template_id','target_schema','source_schema','schema_id','schema_version','contract_version'}
TECH_PATH_PREFIXES=('schemas/','data/runtime/templates/','data/runtime/system-contracts/','data/runtime/template-index','tools/','tests/')

json_docs=[]
for base in ('state','data'):
  for p in sorted((ROOT/base).rglob('*.json')):
    try:d=json.loads(p.read_text(encoding='utf-8'))
    except Exception:continue
    json_docs.append((p,d))

print('=== VERSION-LIKE SEMANTIC GAMEPLAY IDS ===')
hits=[]
def walk(x,path,key='',file=None):
  if isinstance(x,dict):
    for k,v in x.items():walk(v,path+[k],k,file)
  elif isinstance(x,list):
    for i,v in enumerate(x):walk(v,path+[str(i)],key,file)
  elif isinstance(x,str):
    # schema/template compatibility values are technical, not gameplay IDs.
    if key in SCHEMAISH_KEYS: return
    # file refs may legitimately contain versioned schema/template filenames.
    if key.endswith('_ref') or key.endswith('_path') or key in {'path','source','template','template_path'}: return
    # semantic identifiers and explicit tree/progression node-like fields only.
    if key=='id' or key.endswith('_id') or key in {'node','node_id','tree','tree_id','path_id','stage_id','track_id','branch_id','record_id','process_id','event_id','operation_id','unit_id','force_id','character_id','person_id'}:
      if VERSIONED.search(x):hits.append((str(file.relative_to(ROOT)),'.'.join(path),x))
for p,d in json_docs:walk(d,[],file=p)
for h in hits:print(': '.join(h))
print(f'semantic_version_hits={len(hits)}')

print('=== ROOT VERSION FIELDS OUTSIDE TECHNICAL RUNTIME ===')
root_versions=[]
for p,d in json_docs:
  if isinstance(d,dict) and 'version' in d:
    root_versions.append((str(p.relative_to(ROOT)),d.get('schema'),d.get('version')))
for x in root_versions:print(x)
print(f'root_version_fields={len(root_versions)}')

print('=== REGISTERED SCHEMA USAGE ===')
registry=json.loads((ROOT/'schemas/registry.json').read_text(encoding='utf-8'))
usage=collections.Counter()
for p,d in json_docs:
  def count(x):
    if isinstance(x,dict):
      s=x.get('schema')
      if isinstance(s,str):usage[s]+=1
      for v in x.values():count(v)
    elif isinstance(x,list):
      for v in x:count(v)
  count(d)
# template and system-contract dependency map
index=json.loads((ROOT/'data/runtime/template-index.json').read_text(encoding='utf-8'))
template_by_schema={}
for shard_rel in index.get('shards',{}).values():
  shard=json.loads((ROOT/shard_rel).read_text(encoding='utf-8'))
  for sid,rec in shard.get('templates',{}).items():
    if isinstance(rec,dict):template_by_schema[sid]=rec.get('path')
contracts=[]
for p in (ROOT/'data/runtime/system-contracts').glob('*.json'):
  try:c=json.loads(p.read_text(encoding='utf-8'))
  except Exception:continue
  contracts.append((p,c))
contract_refs=collections.defaultdict(list)
for p,c in contracts:
  for sid in c.get('owner_templates',[]):contract_refs[sid].append(str(p.relative_to(ROOT)))

# group version generations by a conservative base only for technical schema IDs.
def family(s):
  return re.sub(r'(?i)(?:[._-]v\d+)$','',s)
groups=collections.defaultdict(list)
for sid in registry:groups[family(sid)].append(sid)
multis={k:sorted(v) for k,v in groups.items() if len(v)>1}
for fam,sids in sorted(multis.items()):
  print(f'FAMILY {fam}')
  for sid in sids:
    print(f'  {sid}: usage={usage[sid]} template={template_by_schema.get(sid)!r} system_contracts={contract_refs.get(sid,[])} schema_file={registry[sid]}')

print('=== STRONG SUPERSEDED TECHNICAL GENERATION CANDIDATES ===')
strong=[]
for fam,sids in multis.items():
  # candidate is a registered generation with no live instances, no registered template, no system contract ownership,
  # while a sibling generation is demonstrably live.
  sibling_live=any(usage[s]>0 or template_by_schema.get(s) or contract_refs.get(s) for s in sids)
  if not sibling_live:continue
  for sid in sids:
    if usage[sid]==0 and not template_by_schema.get(sid) and not contract_refs.get(sid):
      strong.append((sid,registry[sid],fam))
      print(f'{sid} -> schemas/{registry[sid]} family={fam}')
print(f'strong_generation_candidates={len(strong)}')

print('=== ACTIVE GAMEPLAY RULE RELEASE-HISTORY CANDIDATES ===')
# Informational only. Exclude ordinary domain words such as migration, old age, veteran, etc.
patterns=[re.compile(x,re.I) for x in [r'\bdeprecated\b',r'\bretired\b',r'\bformerly\b',r'\bprevious version\b',r'\bolder version\b',r'\brelease[- ]history\b',r'\bbackward compat']]
for p in [ROOT/'RUNTIME.md',ROOT/'VOICE.md',*sorted((ROOT/'rules').glob('*.md'))]:
  for n,line in enumerate(p.read_text(encoding='utf-8').splitlines(),1):
    if any(rx.search(line) for rx in patterns):print(f'{p.relative_to(ROOT)}:{n}: {line.strip()}')
