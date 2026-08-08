#!/usr/bin/env python3
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]

def load(rel):
    return json.loads((ROOT/rel).read_text(encoding='utf-8'))

# Registered schema filenames are live technical compatibility dependencies.
registry=load('schemas/registry.json')
registered_schema_files={str(v) for v in registry.values()}

# Registered template paths are live creation/structural dependencies.
template_paths=set()
idx=load('data/runtime/template-index.json')
for shard_rel in idx.get('shards',{}).values():
    shard=load(shard_rel)
    for rec in shard.get('templates',{}).values():
        if isinstance(rec,dict) and rec.get('path'):
            template_paths.add(rec['path'])

# Build current text corpus for direct references outside candidate files.
text_files=[]
for p in ROOT.rglob('*'):
    if '.git' in p.parts or not p.is_file():
        continue
    if p.suffix.lower() not in ('.json','.md','.py','.yml','.yaml','.txt'):
        continue
    try: text=p.read_text(encoding='utf-8')
    except Exception: continue
    text_files.append((p,text))

def referenced_elsewhere(path:Path, needles):
    for p,text in text_files:
        if p==path: continue
        if any(n and n in text for n in needles):
            return True
    return False

print('=== UNREGISTERED SCHEMA FILES ===')
strong_schema=[]
for p in sorted((ROOT/'schemas').glob('*.schema.json')):
    if p.name in registered_schema_files:
        continue
    rel=str(p.relative_to(ROOT))
    ref=referenced_elsewhere(p,(rel,p.name))
    print(f'{rel} referenced_elsewhere={ref}')
    if not ref: strong_schema.append(rel)

print('=== UNINDEXED TEMPLATE FILES ===')
strong_template=[]
for p in sorted((ROOT/'data/runtime/templates').glob('*.template.json')):
    rel=str(p.relative_to(ROOT))
    if rel in template_paths:
        continue
    ref=referenced_elsewhere(p,(rel,p.name))
    print(f'{rel} referenced_elsewhere={ref}')
    if not ref: strong_template.append(rel)

print('=== STRONG ZERO-REFERENCE DELETION CANDIDATES ===')
for rel in strong_schema+strong_template:
    print(rel)
print(f'strong_candidates={len(strong_schema)+len(strong_template)} schemas={len(strong_schema)} templates={len(strong_template)}')

# Active gameplay rule history-language inventory is informational only; no wording gate.
print('=== ACTIVE RULE HISTORY-LANGUAGE REVIEW ===')
terms=('retired','deprecated','legacy','migration','formerly','old system','old model','old rule')
for p in [ROOT/'RUNTIME.md',ROOT/'VOICE.md',*sorted((ROOT/'rules').glob('*.md'))]:
    text=p.read_text(encoding='utf-8')
    for n,line in enumerate(text.splitlines(),1):
        low=line.lower()
        if any(t in low for t in terms):
            print(f'{p.relative_to(ROOT)}:{n}: {line.strip()}')
