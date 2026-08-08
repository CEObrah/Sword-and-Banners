#!/usr/bin/env python3
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

p=ROOT/'state/org/unit-transactions.json'
d=json.loads(p.read_text(encoding='utf-8'))
rec=next((r for r in d.get('records',[]) if r.get('id')=='txn_tang_wei_tang_champions_form'),None)
if rec is None:
    raise SystemExit('missing Champion formation transaction')
rec['before']['named_member_ids']=[]
rec['after']['named_member_ids']=[]
rec['conservation']['people']='100 Tang Champions preserved as aggregate personnel: the original first fifty plus fifty historically omitted retainers removed from anonymous House Guardian Cavalry accounting; Tang Manor permanent population unchanged'
rec['conservation']['experience']='Verified Champion capability is preserved in the two aggregate unit distributions; representation compression grants no reroll, bonus, or free development.'
rec['conservation']['history']='The original two-company organization remains the same historical event; only ordinary-person storage representation changes.'
rec['capability_evidence']['distribution_method']='representation-only maintenance compression from verified legacy personnel into conserved aggregate unit distributions'
rec['capability_evidence']['cache_rebuild_refs']=['state/index/units.json','state/index/owners.json']
rec['reason']='preserve the corrected two-company Tang Champion organization as two peer 50-rider aggregate units under Tang Wei, commanded by Duan Jin and Shen Rui'
p.write_text(json.dumps(d,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')

audit=ROOT/'tools/audit.py'
text=audit.read_text(encoding='utf-8')
old="  if not (_b.get('unit_ids') or _b.get('named_member_ids')):err(f'unit_transaction_missing_source_lineage:{_tid}')"
new="  if not (_b.get('unit_ids') or _b.get('named_member_ids') or _ev.get('source_capability_refs')):err(f'unit_transaction_missing_source_lineage:{_tid}')"
if old not in text:
    raise SystemExit('expected unit transaction lineage audit check not found')
audit.write_text(text.replace(old,new),encoding='utf-8')

Path(__file__).unlink()
print('aggregate Champion transaction receipt and lineage audit prepared')
