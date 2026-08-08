from __future__ import annotations

import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {'.json', '.md', '.py', '.yml', '.yaml'}


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None


def text_files():
    for p in ROOT.rglob('*'):
        if not p.is_file() or p.suffix.lower() not in TEXT_SUFFIXES:
            continue
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith('.git/'):
            continue
        yield p, rel


char_files = sorted((ROOT / 'state/char').glob('*.json'))
chars = []
for p in char_files:
    d = load_json(p) or {}
    chars.append({
        'id': d.get('owner_id'),
        'name': d.get('name'),
        'runtime_status': d.get('runtime_status'),
        'role': d.get('role_archetype'),
        'path': p.relative_to(ROOT).as_posix(),
    })

player = load_json(ROOT / 'state/player.json') or {}
player_id = player.get('id') or player.get('owner_id') or 'char_tang_wei'

all_text = {}
for p, rel in text_files():
    try:
        all_text[rel] = p.read_text(encoding='utf-8')
    except Exception:
        pass

IGNORE_REF_PREFIXES = (
    'state/index/',
    'state/time/coverage/',
    'tools/',
    'tests/',
    'schemas/',
    'data/runtime/templates/',
)
IGNORE_REF_FILES = {'state/life/identity-life-course.json'}


def refs_for(cid: str | None, own_path: str | None = None):
    if not cid:
        return [], []
    refs = []
    strong = []
    pat = re.compile(r'(?<![A-Za-z0-9_])' + re.escape(cid) + r'(?![A-Za-z0-9_])')
    for rel, text in all_text.items():
        if rel == own_path or rel.startswith('state/char-roster/'):
            continue
        if pat.search(text):
            refs.append(rel)
            if rel.startswith('state/') and not rel.startswith(IGNORE_REF_PREFIXES) and rel not in IGNORE_REF_FILES:
                strong.append(rel)
    return sorted(refs), sorted(strong)


exact_zero_strong = []
exact_strong = []
status_counts = Counter()
for c in chars:
    status_counts[str(c['runtime_status'] or '<none>')] += 1
    refs, strong = refs_for(c['id'], c['path'])
    c['refs'] = refs
    c['strong'] = strong
    (exact_strong if strong else exact_zero_strong).append(c)

roster_index = load_json(ROOT / 'state/char-roster/index.json') or {}
roster_entries = []
for p in sorted((ROOT / 'state/char-roster/shards').glob('*.json')):
    d = load_json(p) or {}
    for cid, rec in (d.get('identities') or {}).items():
        hints = (rec or {}).get('routing_hints') or {}
        refs, strong = refs_for(cid, p.relative_to(ROOT).as_posix())
        roster_entries.append({
            'id': cid,
            'name': (rec or {}).get('name'),
            'unresolved': bool(hints.get('unresolved_route')),
            'activity_owner': hints.get('activity_owner_hint') or hints.get('source_owner_hint'),
            'state_hint': hints.get('state_or_affiliation_hint'),
            'refs': refs,
            'strong': strong,
        })

roster_unresolved = [r for r in roster_entries if r['unresolved']]
roster_strong = [r for r in roster_entries if r['strong']]
roster_zero_refs = [r for r in roster_entries if not r['refs']]
roster_no_strong = [r for r in roster_entries if not r['strong']]

person_files = sorted((ROOT / 'state/person').rglob('*.json')) if (ROOT / 'state/person').exists() else []

office_key_hits = []
role_key_hits = []
for rel, text in all_text.items():
    if not rel.endswith('.json'):
        continue
    if load_json(ROOT / rel) is None:
        continue
    raw = text.lower()
    if any(k in raw for k in ('"office"', '"offices"', '"incumbent"', '"office_holder"', '"holder_id"')):
        office_key_hits.append(rel)
    if any(k in raw for k in ('"role_slot"', '"role_slots"', '"vacancy"', '"succession"')):
        role_key_hits.append(rel)

fort_keys = ['wall_height', 'artillery', 'ammunition', 'water', 'repair_stock', 'garrison', 'food_stock']
fort_hits = defaultdict(list)
for rel, text in all_text.items():
    if not rel.endswith('.json'):
        continue
    low = text.lower()
    for k in fort_keys:
        if k in low:
            fort_hits[k].append(rel)

geo_files = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / 'state/geo').rglob('*.json')) if (ROOT / 'state/geo').exists() else []

rule_history = []
release_terms = re.compile(r'\b(migration|deprecated|release|previous version|old version|legacy behavior|patch notes?)\b', re.I)
for p in sorted((ROOT / 'rules').glob('*.md')):
    for i, line in enumerate(p.read_text(encoding='utf-8').splitlines(), 1):
        if release_terms.search(line):
            rule_history.append((p.relative_to(ROOT).as_posix(), i, line.strip()))

branch_rows = []
try:
    subprocess.run(['git', 'fetch', 'origin', '+refs/heads/*:refs/remotes/origin/*', '--prune'], cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    out = subprocess.check_output(['git', 'for-each-ref', '--format=%(refname:short)', 'refs/remotes/origin'], cwd=ROOT, text=True)
    for ref in sorted(x.strip() for x in out.splitlines() if x.strip() and x.strip() != 'origin/HEAD'):
        name = ref.removeprefix('origin/')
        if name == 'main':
            continue
        counts = subprocess.check_output(['git', 'rev-list', '--left-right', '--count', f'origin/main...{ref}'], cwd=ROOT, text=True).strip().split()
        behind, ahead = map(int, counts)
        anc = subprocess.run(['git', 'merge-base', '--is-ancestor', ref, 'origin/main']).returncode == 0
        branch_rows.append((name, behind, ahead, anc))
except Exception as e:
    print('BRANCH_AUDIT_ERROR', repr(e))

print('=== NAMED PEOPLE ===')
print(f'exact_character_files={len(chars)} player_owner={player_id} deferred_named_identities={len(roster_entries)} person_lite_files={len(person_files)}')
print('exact_runtime_status_counts=' + json.dumps(dict(status_counts), sort_keys=True))
print(f'exact_with_strong_state_refs={len(exact_strong)} exact_without_strong_state_refs={len(exact_zero_strong)}')
print('EXACT_STRONG')
for c in exact_strong:
    print(f"  {c['id']} | {c['name']} | {c['role']} | strong={','.join(c['strong'])}")
print('EXACT_ZERO_STRONG')
for c in exact_zero_strong:
    print(f"  {c['id']} | {c['name']} | {c['role']} | refs={','.join(c['refs'])}")

print('=== DEFERRED ROSTER ===')
print(f"index_declared_count={roster_index.get('count')} actual={len(roster_entries)} unresolved_route={len(roster_unresolved)} with_strong_state_refs={len(roster_strong)} without_strong_state_refs={len(roster_no_strong)} zero_refs_outside_roster={len(roster_zero_refs)}")
print('ROSTER_STRONG')
for r in roster_strong:
    print(f"  {r['id']} | {r['name']} | strong={','.join(r['strong'])}")
print('ROSTER_ROUTING_COUNTS')
routing_counts = Counter(str(r['activity_owner'] or '<none>') for r in roster_entries)
print(json.dumps(dict(routing_counts), sort_keys=True))

print('=== ROLE/OFFICE STRUCTURE ===')
print(f'office_key_files={len(office_key_hits)} role_slot_or_succession_files={len(role_key_hits)}')
for rel in sorted(set(office_key_hits + role_key_hits)):
    print('  ' + rel)

print('=== FORTIFICATION PARITY ===')
print(f'geo_files={len(geo_files)}')
for k in fort_keys:
    vals = sorted(set(fort_hits[k]))
    print(f'{k}_files={len(vals)} ' + ','.join(vals[:30]))

print('=== ACTIVE RULE HISTORY PROSE CANDIDATES ===')
print(f'count={len(rule_history)}')
for rel, line, text in rule_history:
    print(f'  {rel}:{line}: {text}')

print('=== BRANCHES ===')
print(f'non_main_branches={len(branch_rows)} fully_ancestor_of_main={sum(1 for _,_,_,a in branch_rows if a)} divergent_or_ahead={sum(1 for _,_,_,a in branch_rows if not a)}')
for name, behind, ahead, anc in branch_rows:
    print(f'  {name} behind={behind} ahead={ahead} ancestor={anc}')
