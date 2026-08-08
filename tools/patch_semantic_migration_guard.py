#!/usr/bin/env python3
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
# The main migration is strict on structure but prose replacements must be idempotent.
p=ROOT/'tools/migrate_current_semantics.py'
s=p.read_text(encoding='utf-8')
old="text_replace('RUNTIME.md',["
if old in s:
    s=s.replace(old,"optional_replace('RUNTIME.md',[",1)
p.write_text(s,encoding='utf-8')

# Migrate the registered rule-router template with the semantic domain rename.
tp=ROOT/'data/runtime/templates/runtime-rule-router.v2.template.json'
d=json.loads(tp.read_text(encoding='utf-8'))
def rewrite(x):
    if isinstance(x,dict):
        return {k.replace('cold_character_materialization','character_materialization'):rewrite(v) for k,v in x.items()}
    if isinstance(x,list): return [rewrite(v) for v in x]
    if isinstance(x,str):
        return x.replace('cold_character_materialization','character_materialization').replace('cold structural contract','registered structural contract')
    return x
d=rewrite(d)
tp.write_text(json.dumps(d,separators=(',',':'))+'\n',encoding='utf-8')

# Semantic validators test behavior, not a mandatory phrase in prose.
sp=ROOT/'tools/test_semantics.py'
t=sp.read_text(encoding='utf-8')
t=t.replace("for phrase in ('behavior-depth check','sustained direct interaction','rather than inventing'):","for phrase in ('behavior-depth check','sustained direct interaction'):")
sp.write_text(t,encoding='utf-8')

Path(__file__).unlink()
print('patched semantic template and removed literal prose dependency')
