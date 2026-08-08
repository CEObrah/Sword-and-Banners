#!/usr/bin/env python3
import json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
errors=[]
def load(rel): return json.loads((ROOT/rel).read_text(encoding='utf-8'))
def err(x): errors.append(x)

ext=load('state/pop/external-civil-population.json')
state_records=[r for r in ext.get('records',[]) if r.get('record_id','').startswith('civil_pool_')]
if len(state_records)!=7: err(f'external_state_source_count:{len(state_records)}')
for rec in state_records:
    rid=rec.get('record_id'); facts=rec.get('facts',{}); dist=facts.get('population_distribution')
    if not isinstance(dist,dict) or not dist: err(f'population_distribution_not_structured:{rid}'); continue
    if any(not isinstance(v,int) or v<0 for v in dist.values()): err(f'population_distribution_bad_count:{rid}')
    if sum(dist.values())!=facts.get('population_total'): err(f'population_distribution_total:{rid}:{sum(dist.values())}:{facts.get("population_total")}')

manor=load('state/pop/population-tang-manor.json')
records={r.get('record_id'):r for r in manor.get('records',[])}
over=records.get('overview',{}).get('facts',{})
detail=records.get('whole_department_civil_units',{}).get('facts',{})
dist=detail.get('population_distribution')
if not isinstance(dist,dict) or not dist: err('tang_manor_distribution_not_structured')
else:
    if any(not isinstance(v,int) or v<0 for v in dist.values()): err('tang_manor_distribution_bad_count')
    civil=sum(dist.values())+detail.get('named_department_leadership_count',0)
    if civil!=detail.get('Permanent civil household dependent and named department leadership total'): err(f'tang_manor_civil_total:{civil}')
    permanent=civil+detail.get('Permanent martial and institutional core including family',0)
    if permanent!=detail.get('Permanent total'): err(f'tang_manor_permanent_total:{permanent}')
    if permanent!=over.get('Tang Manor permanent population'): err(f'tang_manor_overview_total:{permanent}:{over.get("Tang Manor permanent population")}')

if errors:
    print('POPULATION SOURCE TEST FAILED')
    for e in errors: print('-',e)
    sys.exit(1)
print('POPULATION SOURCE TEST OK')
print('state and Tang Manor source strata are structured in-owner maps with conserved totals')
