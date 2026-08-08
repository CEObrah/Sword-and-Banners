#!/usr/bin/env python3
from pathlib import Path
import json, re

ROOT = Path(__file__).resolve().parents[1]
HISTORY = re.compile(r'\b(retired|deprecated|legacy|formerly|earlier|migration|release[- ]history|old (?:system|model|rule|layer|representation|format|behavior))\b', re.I)
COLD = re.compile(r'\b(cold|archive|archived|legacy|deprecated)\b', re.I)
VERSIONED_ID = re.compile(r'(?:\.v\d+\b|_v\d+\b|-v\d+\b)', re.I)

print('=== ACTIVE RULE HISTORY-LANGUAGE CANDIDATES ===')
for path in [ROOT/'RUNTIME.md', ROOT/'VOICE.md', *sorted((ROOT/'rules').glob('*.md'))]:
    if not path.exists():
        continue
    for n,line in enumerate(path.read_text(encoding='utf-8').splitlines(),1):
        if HISTORY.search(line) or COLD.search(line):
            print(f'{path.relative_to(ROOT)}:{n}: {line.strip()}')

print('=== PATH-NAME CANDIDATES ===')
for path in sorted(ROOT.rglob('*')):
    if '.git' in path.parts:
        continue
    rel=str(path.relative_to(ROOT))
    if COLD.search(rel):
        print(rel)

print('=== GAMEPLAY ROOT VERSION FIELDS ===')
for base in ('state','data'):
    for path in sorted((ROOT/base).rglob('*.json')):
        try:
            obj=json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            continue
        if isinstance(obj,dict) and 'version' in obj:
            print(f'{path.relative_to(ROOT)}: version={obj.get("version")!r} schema={obj.get("schema")!r}')

print('=== VERSION-LIKE SEMANTIC IDS ===')
for base in ('state','data'):
    for path in sorted((ROOT/base).rglob('*.json')):
        try:
            obj=json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            continue
        hits=[]
        def walk(x,key=''):
            if isinstance(x,dict):
                for k,v in x.items(): walk(v,k)
            elif isinstance(x,list):
                for v in x: walk(v,key)
            elif isinstance(x,str) and (key=='id' or key.endswith('_id') or key in ('node','node_id','tree_id','path_id')) and VERSIONED_ID.search(x):
                hits.append((key,x))
        walk(obj)
        if hits:
            print(f'{path.relative_to(ROOT)}: {hits[:12]}')

print('=== CHARACTER ROSTER FOOTPRINT / REDUNDANCY ===')
root=ROOT/'state/char-roster'
if root.exists():
    files=[p for p in root.rglob('*.json')]
    direct=[p for p in (root/'active-canon').glob('*.json')] if (root/'active-canon').exists() else []
    lookup=[p for p in (root/'lookup').glob('*.json')] if (root/'lookup').exists() else []
    print(f'json_files={len(files)} direct_identity_files={len(direct)} lookup_shards={len(lookup)}')
    rows=[json.loads(p.read_text(encoding='utf-8')) for p in direct]
    for key in ('schema','representation','activation_rule','life_course_ref','hints_are_authority'):
        vals=sorted({json.dumps(r.get(key),sort_keys=True) for r in rows})
        print(f'{key}: distinct={len(vals)} values={vals[:8]}')
    keysets=sorted({tuple(sorted((r.get('routing_hints') or {}).keys())) for r in rows})
    print(f'routing_hint_keysets: distinct={len(keysets)} values={keysets[:8]}')
    print(f'unique_names={len({r.get("name") for r in rows})} unique_ids={len({r.get("id") for r in rows})} unique_profile_seeds={len({(r.get("routing_hints") or {}).get("profile_seed") for r in rows})}')

print('=== CHARACTER/COLD REFERENCES ===')
needle=re.compile(r'(state/char-roster|character-cold-active|cold canonical|cold identity|cold record|cold shard|cold scene|cold template)', re.I)
count=0
for path in sorted(ROOT.rglob('*')):
    if '.git' in path.parts or not path.is_file() or path.suffix.lower() not in ('.json','.md','.py','.txt'):
        continue
    try: lines=path.read_text(encoding='utf-8').splitlines()
    except Exception: continue
    for n,line in enumerate(lines,1):
        if needle.search(line):
            print(f'{path.relative_to(ROOT)}:{n}: {line.strip()}')
            count += 1
            if count>=300:
                print('... reference output capped at 300 lines ...')
                raise SystemExit(0)
