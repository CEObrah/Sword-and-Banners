from pathlib import Path
import json,re
ROOT=Path(__file__).resolve().parents[1]
needles=['state/char-roster','character-identity-shard','character-roster-index','cold_profile_definition','Cold-Active','cold-active','deferred-detail','deferred_detail_routed_identity','appointments_and_command','appointment-registry']
for needle in needles:
    print(f'=== {needle} ===')
    n=0
    for p in ROOT.rglob('*'):
        if not p.is_file() or p.suffix.lower() not in {'.json','.md','.py','.yml','.yaml'}: continue
        rel=p.relative_to(ROOT).as_posix()
        if rel.startswith('.git/') or rel in {'tools/audit_roster_refs.py','tools/audit_offscreen_scaling.py'}: continue
        try: lines=p.read_text(encoding='utf-8').splitlines()
        except Exception: continue
        for i,line in enumerate(lines,1):
            if needle.lower() in line.lower():
                n+=1
                print(f'{rel}:{i}: {line[:500]}')
    print('count=',n)
print('=== PERSON LITE REFERENCES ===')
for p in sorted((ROOT/'state/person/staff').glob('*.json')):
    d=json.loads(p.read_text(encoding='utf-8')); pid=d.get('id'); refs=[]
    pat=re.compile(r'(?<![A-Za-z0-9_.-])'+re.escape(pid)+r'(?![A-Za-z0-9_.-])') if pid else None
    if not pat: continue
    for q in ROOT.rglob('*'):
        if not q.is_file() or q==p or q.suffix.lower() not in {'.json','.md','.py'}: continue
        rel=q.relative_to(ROOT).as_posix()
        if rel.startswith('.git/') or rel.startswith('tools/'): continue
        try: text=q.read_text(encoding='utf-8')
        except Exception: continue
        if pat.search(text): refs.append(rel)
    print(pid,'|',d.get('name'),'|',d.get('role'),'| refs=',','.join(sorted(refs)))
