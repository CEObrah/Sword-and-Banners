#!/usr/bin/env python3
from pathlib import Path
import json,re,collections

ROOT=Path(__file__).resolve().parents[1]
SELF=Path(__file__).resolve()
TEMP_AUDITS={ROOT/'tools/audit_semantic_ids_and_contract_generations.py',ROOT/'tools/audit_superseded_creation_generations.py',SELF}
SUPERSEDED={
 'doctrine_registry.v1',
 'loadouts-index.v1',
 'repository-map.v1','repository-map.v2','repository-map.v3',
 'runtime-rule-router.v1',
 'training_profile_registry.v1',
 'unit_model.v1',
}

def readj(p):return json.loads(p.read_text(encoding='utf-8'))
def writej(p,d):p.write_text(json.dumps(d,separators=(',',':'))+'\n',encoding='utf-8')

registry_path=ROOT/'schemas/registry.json'
registry=readj(registry_path)
index=readj(ROOT/'data/runtime/template-index.json')

# Live schema usage in gameplay/static data, excluding structural templates.
usage=collections.Counter()
for base in ('state','data'):
    for p in (ROOT/base).rglob('*.json'):
        if 'data/runtime/templates' in str(p):continue
        try:d=readj(p)
        except Exception:continue
        def walk(x):
            if isinstance(x,dict):
                s=x.get('schema')
                if isinstance(s,str):usage[s]+=1
                for v in x.values():walk(v)
            elif isinstance(x,list):
                for v in x:walk(v)
        walk(d)

# Template registration and containing shard.
template_rec={}; template_shard={}
for shard_rel in index.get('shards',{}).values():
    sp=ROOT/shard_rel; sd=readj(sp)
    for sid,rec in sd.get('templates',{}).items():
        template_rec[sid]=rec; template_shard[sid]=(sp,sd)

# Explicit contract dependencies.
contract_refs=collections.defaultdict(list)
for p in (ROOT/'data/runtime/system-contracts').glob('*.json'):
    try:d=readj(p)
    except Exception:continue
    blob=json.dumps(d,sort_keys=True)
    for sid in registry:
        if sid in blob:contract_refs[sid].append(str(p.relative_to(ROOT)))

# Repository text corpus for references. Registry, the candidate's own schema/template,
# template-index registration, and temporary audit helpers are not semantic dependencies.
text_files=[]
for p in ROOT.rglob('*'):
    if '.git' in p.parts or not p.is_file() or p in TEMP_AUDITS or p.suffix.lower() not in ('.json','.md','.py','.yml','.yaml','.txt'):
        continue
    try:text=p.read_text(encoding='utf-8')
    except Exception:continue
    text_files.append((p,text))

def external_refs(sid):
    refs=[]; sf=registry.get(sid); rec=template_rec.get(sid) or {}; tpath=rec.get('path')
    own={registry_path}
    if sf:own.add(ROOT/'schemas'/sf)
    if tpath:own.add(ROOT/tpath)
    for p,text in text_files:
        if p in own:continue
        rel=str(p.relative_to(ROOT))
        if rel.startswith('data/runtime/template-index-shards/') and sid in text:continue
        needles=[sid]
        if sf:needles.append(sf)
        if tpath:needles.extend([tpath,Path(tpath).name])
        if any(n in text for n in needles):refs.append(rel)
    return sorted(set(refs))

# Prove the explicit superseded set is still unreachable except through its obsolete template registration.
for sid in sorted(SUPERSEDED):
    if sid not in registry:raise SystemExit(f'expected superseded schema missing: {sid}')
    if usage[sid]!=0:raise SystemExit(f'refusing live superseded schema: {sid} usage={usage[sid]}')
    if contract_refs[sid]:raise SystemExit(f'refusing contracted superseded schema: {sid} {contract_refs[sid]}')
    refs=external_refs(sid)
    if refs:raise SystemExit(f'refusing externally referenced superseded schema: {sid} {refs}')

# Also prune completely unreachable registered schema IDs. These have no live instances,
# no creation template, no system contract and no external reference; by construction the runtime cannot use them.
ORPHAN=set()
for sid in list(registry):
    if sid in SUPERSEDED:continue
    if usage[sid]!=0 or sid in template_rec or contract_refs[sid]:continue
    if not external_refs(sid):ORPHAN.add(sid)

print('superseded=',sorted(SUPERSEDED))
print('unreachable_registry_entries=',sorted(ORPHAN))
remove_ids=SUPERSEDED|ORPHAN

# Remove obsolete template registrations/files for superseded generations only.
changed_shards={}
for sid in sorted(SUPERSEDED):
    rec=template_rec.get(sid)
    if not rec:continue
    sp,sd=template_shard[sid]
    sd.get('templates',{}).pop(sid,None)
    changed_shards[sp]=sd
    tpath=rec.get('path')
    if tpath:
        tp=ROOT/tpath
        if not tp.exists():raise SystemExit(f'obsolete template path missing: {tpath}')
        tp.unlink()
for sp,sd in changed_shards.items():writej(sp,sd)

# Remove registry IDs. Delete a schema file only if no surviving registry ID maps to it.
removed_files=[]
removed_schema_files={registry[sid] for sid in remove_ids if sid in registry}
for sid in sorted(remove_ids):registry.pop(sid,None)
writej(registry_path,registry)
still_files=set(registry.values())
for filename in sorted(removed_schema_files-still_files):
    p=ROOT/'schemas'/filename
    if not p.exists():raise SystemExit(f'expected removable schema file missing: {filename}')
    p.unlink();removed_files.append(filename)

# Re-prove no removed schema ID survives in live state/data, contracts, or template registration.
for sid in remove_ids:
    if usage[sid]:raise SystemExit(f'removed schema had live usage: {sid}')
for shard_rel in index.get('shards',{}).values():
    sd=readj(ROOT/shard_rel)
    for sid in remove_ids:
        if sid in sd.get('templates',{}):raise SystemExit(f'removed schema remains template-registered: {sid}')
for p in (ROOT/'data/runtime/system-contracts').glob('*.json'):
    blob=p.read_text(encoding='utf-8')
    for sid in remove_ids:
        if sid in blob:raise SystemExit(f'removed schema remains in system contract: {sid}:{p.relative_to(ROOT)}')

# Temporary audit machinery is not part of the repository design.
for p in TEMP_AUDITS:
    if p.exists():p.unlink()

# Restore normal read-only CI.
(ROOT/'.github/workflows/audit.yml').write_text(
"name: audit\non: [push, pull_request]\njobs:\n  audit:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.12'\n      - run: pip install jsonschema\n      - name: Run full validator stack\n        run: python tools/run_validators.py\n",encoding='utf-8')
print(f'removed_schema_ids={len(remove_ids)} removed_schema_files={len(removed_files)} removed_template_files={sum(1 for s in SUPERSEDED if template_rec.get(s))}')
print('removed_schema_files=',removed_files)
