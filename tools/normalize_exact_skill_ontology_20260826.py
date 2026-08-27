#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
orders=json.loads((ROOT/'game/data/mechanics/stat-orders.json').read_text(encoding='utf-8'))['profiles']['military_person']
core=[str(x) for x in orders['skill_order']]
professional={str(x) for x in orders['professional_skill_order']}
changed=[]
for p in [ROOT/'state/player.json', *sorted((ROOT/'state/char').glob('*.json'))]:
    d=json.loads(p.read_text(encoding='utf-8'))
    if d.get('schema')!='sab_character':
        continue
    skills=d.get('skills') if isinstance(d.get('skills'),dict) else {}
    extra=set(skills)-set(core)
    if extra:
        raise RuntimeError(f'{p}: non-core skills in core map: {sorted(extra)}')
    before=len(skills)
    # Semantics-preserving migration: historical missing core keys were read as zero.
    normalized={name: skills[name] if name in skills else 0 for name in core}
    pro=d.get('professional_skills') if isinstance(d.get('professional_skills'),dict) else {}
    bad=set(pro)-professional
    if bad:
        raise RuntimeError(f'{p}: unknown professional skills: {sorted(bad)}')
    sparse={k:v for k,v in pro.items() if float(v)!=0.0}
    if normalized!=skills or sparse!=pro:
        d['skills']=normalized
        d['professional_skills']=sparse
        p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        changed.append((str(p.relative_to(ROOT)),before,len(normalized)))
print('normalized exact skill sheets',len(changed))
for row in changed: print(*row)
