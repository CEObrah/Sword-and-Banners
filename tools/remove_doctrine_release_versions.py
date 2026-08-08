#!/usr/bin/env python3
from pathlib import Path
import json,re

ROOT=Path(__file__).resolve().parents[1]
SELF=Path(__file__).resolve()
AUDIT=ROOT/'tools/audit_doctrine_record_version.py'

def load(rel):return json.loads((ROOT/rel).read_text(encoding='utf-8'))
def dump(rel,obj):(ROOT/rel).write_text(json.dumps(obj,separators=(',',':'))+'\n',encoding='utf-8')

meta=load('state/meta.json')
if meta.get('revision')!=18 or meta.get('time')!='245-BCE-12-04T07:22:48+08:00':
    raise SystemExit(f'unexpected canonical base: {meta.get("revision")} {meta.get("time")}')

records=sorted((ROOT/'data/mil/doctrine-records').glob('*.json'))
versioned=[]
for p in records:
    d=json.loads(p.read_text(encoding='utf-8'))
    if d.get('schema')!='doctrine-record.v1':raise SystemExit(f'unexpected doctrine schema: {p.name}')
    if 'version' in d.get('doctrine',{}):
        if d['doctrine']['version']!=1:raise SystemExit(f'nontrivial doctrine version requires manual review: {p.name}:{d["doctrine"]["version"]}')
        versioned.append(p)
if len(records)!=127 or len(versioned)!=115:
    raise SystemExit(f'unexpected doctrine inventory: records={len(records)} versioned={len(versioned)}')

# Re-prove no runtime/tool/rule directly consumes doctrine.version. The doctrine rule itself is being rewritten below.
patterns=[
    re.compile(r"doctrine[^\n]{0,80}get\(['\"]version['\"]\)",re.I),
    re.compile(r"doctrine[^\n]{0,80}\[['\"]version['\"]\]",re.I),
    re.compile(r"['\"]doctrine['\"][^\n]{0,80}['\"]version['\"]",re.I),
]
ignore={SELF.resolve(),AUDIT.resolve(),(ROOT/'rules/doctrine.md').resolve(),(ROOT/'data/runtime/templates/doctrine-record.v1.template.json').resolve(),(ROOT/'schemas/doctrine-record-v1.schema.json').resolve()}
for p in ROOT.rglob('*'):
    if '.git' in p.parts or not p.is_file() or p.resolve() in ignore or p.parent==ROOT/'data/mil/doctrine-records' or p.suffix.lower() not in ('.py','.json','.md','.yml','.yaml','.txt'):
        continue
    try:text=p.read_text(encoding='utf-8')
    except Exception:continue
    for rx in patterns:
        if rx.search(text):raise SystemExit(f'doctrine.version consumer exists: {p.relative_to(ROOT)}')

# Doctrine records contain current doctrine facts only. Numeric release/revision mirrors are not gameplay state.
for p in versioned:
    d=json.loads(p.read_text(encoding='utf-8'))
    d['doctrine'].pop('version',None)
    p.write_text(json.dumps(d,separators=(',',':'))+'\n',encoding='utf-8')

tp=load('data/runtime/templates/doctrine-record.v1.template.json')
doc=tp.get('object_contracts',{}).get('/doctrine',{})
for key in ('allowed_keys','canonical_order'):
    doc[key]=[x for x in doc.get(key,[]) if x!='version']
tp.get('type_contracts',{}).pop('/doctrine/version',None)
tp['writing_rules']=[x.replace('This is a cold structural contract for schema-bearing static gameplay data.','This is a registered structural contract for schema-bearing static gameplay data.') for x in tp.get('writing_rules',[])]
dump('data/runtime/templates/doctrine-record.v1.template.json',tp)

# Active doctrine law: semantic standards and real familiarization, no gameplay release/version chain.
(ROOT/'rules/doctrine.md').write_text('''# Doctrine, Tendencies, and Orders\n\n## Doctrine layers\n\n1. Institutional doctrine\n2. Unit-type doctrine\n3. Unit-specific doctrine\n4. Commander interpretation\n5. Temporary battle orders\n\nHigher-numbered layers may override lower layers within lawful authority. Temporary orders never rewrite permanent doctrine.\n\n## Permanent doctrine and reform\n\nA doctrine record represents a current durable military standard under a stable semantic doctrine ID. Doctrine records carry doctrine facts, not release numbers. A materially different durable standard uses a meaningful semantic doctrine ID; never append a software-style version suffix merely because doctrine changed.\n\nA unit's `doctrine` reference is the durable standard it can presently execute as doctrine. Doctrinal reform requires a real decision, dissemination, instructor preparation, drills, equipment where needed, time, and familiarization. A unit does not switch its doctrine reference until the required transition has actually completed under training/development mechanics. Partial preparation grants no automatic target-doctrine benefit; only effects independently supported by completed training, temporary orders, commander capability, equipment and current unit state may apply.\n\nWhen a material doctrine change is being prepared, keep the target doctrine and its training/familiarization work in the causal reform/training transaction rather than cloning the unit or inventing a numeric doctrine revision. Once the transition completes, change the unit's doctrine reference atomically and retain only the receipts/history required by the transaction contract.\n\n## Combat tendencies\n\nEach meaningful unit stores persistent tendencies such as aggression, initiative, caution, adaptability, flank bias, ambush bias, counterattack bias, pursuit bias, reserve bias, withdrawal willingness, casualty tolerance, objective focus, ally support, formation discipline, and commander dependence.\n\nTendencies describe habitual execution, not personality for every anonymous soldier. They evolve slowly from saved battle and training history.\n\n## Fairness and battle snapshots\n\nNPC institutions may create and reform doctrine through autonomous strategic processes. They may not retroactively invent the perfect doctrine after observing the player's battle plan.\n\nAt battle start, snapshot the resolved doctrine reference and doctrine content actually available to the unit, completed reform/training state that can affect execution, tendencies, commander, posture, orders, stats, equipment, morale, cohesion, fatigue, supply, terrain, and known intelligence. Historical resolution relies on that settled snapshot/receipt, not on a mutable numeric doctrine version.\n''',encoding='utf-8')

# Remove a redundant faction-specific release-version check. The registered closed doctrine template now owns this structurally for every doctrine record.
lw=ROOT/'tools/test_living_world.py'
text=lw.read_text(encoding='utf-8')
old="""# Current House Tang/Sword Manor doctrine records carry current doctrine only, not release versions.\nfor p in [ROOT/'data/mil/doctrine-records/doc.house_tang.core.json']+list((ROOT/'data/mil/doctrine-records').glob('doc.house_tang_internal.*.json'))+list((ROOT/'data/mil/doctrine-records').glob('doc.sword_manor_institution.*.json')):\n    d=json.loads(p.read_text(encoding='utf-8'))\n    if 'version' in d.get('doctrine',{}):fail('doctrine_release_version:'+p.name)\n\n"""
if old not in text:raise SystemExit('expected redundant doctrine release-version test block missing')
lw.write_text(text.replace(old,''),encoding='utf-8')

# Re-prove every doctrine record is current-only and the template cannot reintroduce the field.
for p in records:
    d=json.loads(p.read_text(encoding='utf-8'))
    if 'version' in d.get('doctrine',{}):raise SystemExit(f'doctrine version remains: {p.name}')
if '/doctrine/version' in load('data/runtime/templates/doctrine-record.v1.template.json').get('type_contracts',{}):
    raise SystemExit('doctrine template still permits version')

# No campaign state changed.
meta2=load('state/meta.json')
if meta2.get('revision')!=18 or meta2.get('time')!='245-BCE-12-04T07:22:48+08:00':raise SystemExit('campaign state changed during doctrine maintenance')

for p in (AUDIT,SELF):
    if p.exists():p.unlink()
(ROOT/'.github/workflows/audit.yml').write_text(
"name: audit\non: [push, pull_request]\njobs:\n  audit:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.12'\n      - run: pip install jsonschema\n      - name: Run full validator stack\n        run: python tools/run_validators.py\n",encoding='utf-8')
print(f'removed {len(versioned)} unused doctrine release mirrors; doctrine reform rule now uses semantic standards and real training transitions')
