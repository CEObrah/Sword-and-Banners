#!/usr/bin/env python3
from pathlib import Path
import json,re,collections

ROOT=Path(__file__).resolve().parents[1]
registry=json.loads((ROOT/'schemas/registry.json').read_text(encoding='utf-8'))
idx=json.loads((ROOT/'data/runtime/template-index.json').read_text(encoding='utf-8'))

templates={}
for shard_rel in idx.get('shards',{}).values():
    shard=json.loads((ROOT/shard_rel).read_text(encoding='utf-8'))
    for sid,rec in shard.get('templates',{}).items():
        if isinstance(rec,dict): templates[sid]=rec

# Count live schema instances in state/data, excluding structural templates themselves.
usage=collections.Counter()
for base in ('state','data'):
    for p in (ROOT/base).rglob('*.json'):
        if 'data/runtime/templates' in str(p): continue
        try:d=json.loads(p.read_text(encoding='utf-8'))
        except Exception: continue
        def walk(x):
            if isinstance(x,dict):
                s=x.get('schema')
                if isinstance(s,str):usage[s]+=1
                for v in x.values():walk(v)
            elif isinstance(x,list):
                for v in x:walk(v)
        walk(d)

# System-contract and runtime direct references are explicit live dependencies.
contract_refs=collections.defaultdict(list)
for p in (ROOT/'data/runtime/system-contracts').glob('*.json'):
    try:d=json.loads(p.read_text(encoding='utf-8'))
    except Exception:continue
    blob=json.dumps(d,sort_keys=True)
    for sid in registry:
        if sid in blob:contract_refs[sid].append(str(p.relative_to(ROOT)))

# Plain-text references excluding registry and the schema/template that define the candidate itself.
text_files=[]
for p in ROOT.rglob('*'):
    if '.git' in p.parts or not p.is_file() or p.suffix.lower() not in ('.json','.md','.py','.yml','.yaml','.txt'):
        continue
    try:text=p.read_text(encoding='utf-8')
    except Exception:continue
    text_files.append((p,text))

def external_refs(sid):
    refs=[]; sf=registry.get(sid); tpath=(templates.get(sid) or {}).get('path')
    ignore={ROOT/'schemas/registry.json'}
    if sf: ignore.add(ROOT/'schemas'/sf)
    if tpath: ignore.add(ROOT/tpath)
    # template-index shards necessarily register current templates; ignore only the entry for the candidate when deciding whether it is semantically used.
    for p,text in text_files:
        if p in ignore:continue
        rel=str(p.relative_to(ROOT))
        if rel.startswith('data/runtime/template-index-shards/') and sid in text:continue
        needles=[sid]
        if sf: needles.append(sf)
        if tpath: needles.extend([tpath,Path(tpath).name])
        if any(n in text for n in needles):refs.append(rel)
    return sorted(set(refs))

def parse_version(s):
    m=re.search(r'(?i)(?:[._-]v)(\d+)$',s)
    return int(m.group(1)) if m else None

def family(s):
    return re.sub(r'(?i)(?:[._-]v\d+)$','',s)

groups=collections.defaultdict(list)
for sid in registry:
    v=parse_version(sid)
    if v is not None:groups[family(sid)].append((v,sid))

print('=== SUPERSEDED REGISTERED GENERATIONS ===')
candidates=[]
for fam,gens in sorted(groups.items()):
    if len(gens)<2:continue
    gens=sorted(gens)
    live_versions=[v for v,s in gens if usage[s]>0]
    if not live_versions:continue
    max_live=max(live_versions)
    for v,sid in gens:
        if v>=max_live or usage[sid]>0:continue
        refs=external_refs(sid)
        print(f'{sid}: version={v} newer_live={max_live} usage={usage[sid]} template={(templates.get(sid) or {}).get("path")!r} contract_refs={contract_refs.get(sid,[])} external_refs={refs}')
        if not contract_refs.get(sid) and not refs:
            candidates.append(sid)

print('=== FULLY UNINSTANTIATED REGISTERED FAMILIES ===')
# Entire versioned families with no live instances may also be dead; report only, never auto-classify.
for fam,gens in sorted(groups.items()):
    if len(gens)<1:continue
    if all(usage[s]==0 for _,s in gens):
        print(f'{fam}:')
        for v,sid in sorted(gens):
            print(f'  {sid}: template={(templates.get(sid) or {}).get("path")!r} contract_refs={contract_refs.get(sid,[])} external_refs={external_refs(sid)}')

print('=== STRONG REMOVAL SET ===')
for sid in candidates:print(sid)
print(f'strong_superseded_candidates={len(candidates)}')
