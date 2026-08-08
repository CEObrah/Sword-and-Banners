#!/usr/bin/env python3
import json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
errors=[]
def load(path): return json.loads(path.read_text(encoding='utf-8'))
def err(x): errors.append(x)

structured_records=0
for path in sorted((ROOT/'state/pop').glob('*.json')):
    doc=load(path)
    for rec in doc.get('records',[]):
        facts=rec.get('facts',{})
        if 'population_distribution' not in facts:
            continue
        structured_records+=1
        rid=rec.get('record_id',path.name)
        dist=facts.get('population_distribution')
        if not isinstance(dist,dict) or not dist:
            err(f'population_distribution_not_structured:{path.name}:{rid}')
            continue
        if any(not isinstance(v,int) or v<0 for v in dist.values()):
            err(f'population_distribution_bad_count:{path.name}:{rid}')
        if 'population_total' in facts and sum(dist.values())!=facts.get('population_total'):
            err(f'population_distribution_total:{path.name}:{rid}:{sum(dist.values())}:{facts.get("population_total")}')

if structured_records<10:
    err(f'too_few_structured_population_records:{structured_records}')

manor=load(ROOT/'state/pop/population-tang-manor.json')
records={r.get('record_id'):r for r in manor.get('records',[])}
over=records.get('overview',{}).get('facts',{})
detail=records.get('whole_department_civil_units',{}).get('facts',{})
dist=detail.get('population_distribution',{})
if isinstance(dist,dict):
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
print(f'structured_source_records={structured_records}; in-owner source maps conserve declared totals')
