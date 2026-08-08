#!/usr/bin/env python3
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]
AUDIT=ROOT/'tools/audit_release_metadata_coupling.py'
SELF=Path(__file__).resolve()

def load(rel):
    return json.loads((ROOT/rel).read_text(encoding='utf-8'))

def dump(rel,obj):
    (ROOT/rel).write_text(json.dumps(obj,separators=(',',':'))+'\n',encoding='utf-8')

# Guard the expected canonical base facts. This is structural maintenance only; time must not move.
meta=load('state/meta.json')
if meta.get('revision')!=17 or meta.get('time')!='245-BCE-12-04T07:22:48+08:00':
    raise SystemExit(f'unexpected meta base: revision={meta.get("revision")} time={meta.get("time")}')
if meta.get('version')!='3.12':
    raise SystemExit(f'unexpected meta release mirror: {meta.get("version")}')

# The root VERSION file is maintenance release bookkeeping and must be coupled nowhere except the old audit assertion.
version_file=ROOT/'VERSION'
if not version_file.exists() or version_file.read_text(encoding='utf-8').strip()!='3.12':
    raise SystemExit('unexpected VERSION file')

# Prove no live repository consumer other than tools/audit.py and this one-shot maintenance script references VERSION.
refs=[]
for p in ROOT.rglob('*'):
    if '.git' in p.parts or not p.is_file() or p.resolve() in {SELF.resolve(),AUDIT.resolve(),version_file.resolve()}:
        continue
    if p.suffix.lower() not in ('.py','.md','.json','.yml','.yaml','.txt'):
        continue
    try:text=p.read_text(encoding='utf-8')
    except Exception:continue
    if 'VERSION' in text:
        refs.append(str(p.relative_to(ROOT)))
allowed={'tools/audit.py'}
if set(refs)-allowed:
    raise SystemExit(f'VERSION has unexpected consumers: {refs}')

# Remove release metadata from live campaign meta. Revision advances once because canonical state shape changes.
meta.pop('version',None)
meta['revision']=18
dump('state/meta.json',meta)

# Meta schema/template now describe campaign state only.
ms=load('schemas/meta.schema.json')
ms['required']=[x for x in ms.get('required',[]) if x!='version']
ms.get('properties',{}).pop('version',None)
dump('schemas/meta.schema.json',ms)
mt=load('data/runtime/templates/meta.template.json')
mt['required_top_level_keys']=[x for x in mt.get('required_top_level_keys',[]) if x!='version']
root=mt.get('object_contracts',{}).get('',{})
for key in ('allowed_keys','canonical_order'):
    root[key]=[x for x in root.get(key,[]) if x!='version']
mt.get('type_contracts',{}).pop('/version',None)
dump('data/runtime/templates/meta.template.json',mt)

# Static mechanics/balance records already carry their compatibility generation in schema IDs.
static_targets=[
 ('data/balance/state-military-identities.json','state-military-identities.v38','data/runtime/templates/state-military-identities.v38.template.json',None),
 ('data/development/model.json','development-model.v38','data/runtime/templates/development-model.v38.template.json',None),
 ('data/mechanics/core.json','mechanics-core.v38','data/runtime/templates/mechanics-core.v38.template.json','schemas/mechanics-core-v38.schema.json'),
]
for rel,sid,tprel,schema_rel in static_targets:
    d=load(rel)
    if d.get('schema')!=sid or 'version' not in d:
        raise SystemExit(f'unexpected version-bearing target {rel}')
    d.pop('version')
    dump(rel,d)
    tp=load(tprel)
    tp['required_top_level_keys']=[x for x in tp.get('required_top_level_keys',[]) if x!='version']
    rc=tp.get('object_contracts',{}).get('',{})
    for key in ('allowed_keys','canonical_order'):
        rc[key]=[x for x in rc.get(key,[]) if x!='version']
    tp.get('type_contracts',{}).pop('/version',None)
    tp['writing_rules']=[x.replace('This is a cold structural contract for schema-bearing static gameplay data.','This is a registered structural contract for schema-bearing static gameplay data.') for x in tp.get('writing_rules',[])]
    dump(tprel,tp)
    if schema_rel:
        spec=load(schema_rel)
        spec['required']=[x for x in spec.get('required',[]) if x!='version']
        spec.get('properties',{}).pop('version',None)
        dump(schema_rel,spec)

# Remove the release-file coupling from the validator. The campaign revision is the state-change sequence;
# schema IDs own technical compatibility and Git owns maintenance history.
audit=ROOT/'tools/audit.py'
text=audit.read_text(encoding='utf-8')
old="_version=(ROOT/'VERSION').read_text(encoding='utf-8').strip()\nif meta.get('version')!=_version:err(f'meta_version:{meta.get(\"version\")}!={_version}')\n"
if old not in text:
    raise SystemExit('expected VERSION/meta coupling not found in tools/audit.py')
audit.write_text(text.replace(old,''),encoding='utf-8')

# Validator output should describe the current invariant, not release-history cleanup.
tci=ROOT/'tools/test_current_identities.py'
if tci.exists():
    text=tci.read_text(encoding='utf-8')
    text=text.replace('legacy release-line mutable IDs and obsolete command-prefix machinery absent','semantic mutable IDs and command routing are current')
    tci.write_text(text,encoding='utf-8')

version_file.unlink()

# Re-prove the four mirrors are gone and world time did not move.
meta2=load('state/meta.json')
if meta2.get('revision')!=18 or meta2.get('time')!='245-BCE-12-04T07:22:48+08:00' or 'version' in meta2:
    raise SystemExit('meta postcondition failed')
for rel,_,_,_ in static_targets:
    if 'version' in load(rel):raise SystemExit(f'version mirror remains: {rel}')

# Temporary maintenance machinery is not part of runtime design.
for p in (AUDIT,SELF):
    if p.exists():p.unlink()

# Restore normal read-only CI.
(ROOT/'.github/workflows/audit.yml').write_text(
"name: audit\non: [push, pull_request]\njobs:\n  audit:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.12'\n      - run: pip install jsonschema\n      - name: Run full validator stack\n        run: python tools/run_validators.py\n",encoding='utf-8')
print('release metadata separated from campaign/static gameplay data; revision=18; world time unchanged')
