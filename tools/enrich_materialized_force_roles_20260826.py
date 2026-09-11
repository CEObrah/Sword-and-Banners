#!/usr/bin/env python3
"""Backfill role metadata for already-materialized conserved force bodies.

No body, cohort, formation, or headcount is created. The record only makes the
already-existing exact body's establishment role explicit so vacancy accounting
cannot mistake materialization for recruitment attrition.
"""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
owners=json.loads((ROOT/'state/index/owner-index.json').read_text()).get('owners',{})
formations={}
for fp in (ROOT/'state/formations').glob('*.json'):
    row=json.loads(fp.read_text())
    ref=row.get('formation_ref')
    if isinstance(ref,str): formations[ref]=row
changed=0
unresolved=[]
for fp in sorted((ROOT/'state/forces').glob('*.json')):
    force=json.loads(fp.read_text())
    people=force.get('materialized_people')
    cohorts=force.get('cohort_ledger',{}).get('cohorts',{})
    if not isinstance(people,dict) or not isinstance(cohorts,dict):
        continue
    local_changed=False
    for person_ref,value in list(people.items()):
        if isinstance(value,dict) and value.get('role'):
            continue
        route=owners.get(person_ref)
        if not isinstance(route,str) or '#/' in route:
            continue
        pp=ROOT/route
        if not pp.exists():
            continue
        person=json.loads(pp.read_text())
        prov=person.get('materialization_provenance') if isinstance(person.get('materialization_provenance'),dict) else {}
        cid=str(person.get('source_cohort_ref') or prov.get('source_cohort_ref') or '')
        cohort=cohorts.get(cid) if cid else None
        role=str((cohort or {}).get('role') or prov.get('source_role') or '')
        if not role:
            pop=person.get('population_provenance') if isinstance(person.get('population_provenance'),dict) else {}
            role=str(pop.get('entry_role') or '')
        if not role:
            force_assignment=force.get('materialized_assignments',{}).get(person_ref) if isinstance(force.get('materialized_assignments'),dict) else None
            if isinstance(force_assignment,dict):
                role=str(force_assignment.get('role') or '')
        if not role:
            person_role=str(person.get('role') or '')
            if person_role in {str(c.get('role')) for c in cohorts.values() if isinstance(c,dict)}:
                role=person_role
        if not role:
            assignment=person.get('command_assignment') if isinstance(person.get('command_assignment'),dict) else {}
            fref=str(person.get('current_formation_id') or assignment.get('formation_ref') or '')
            formation=formations.get(fref)
            if isinstance(formation,dict) and str(formation.get('owner_force_ref'))==str(force.get('owner_id')):
                positive=[str(r) for r,n in formation.get('composition',{}).items() if int(n)>0]
                if len(positive)==1:
                    role=positive[0]
        if not role:
            unresolved.append((str(force.get('owner_id')),person_ref))
            continue
        count=int(value.get('personnel',1)) if isinstance(value,dict) else int(value)
        record={'personnel':count,'role':role,'source_mode':'materialized_exact_person'}
        if cid:
            record['source_cohort_ref']=cid
        people[person_ref]=record
        local_changed=True; changed+=1
    if local_changed:
        fp.write_text(json.dumps(force,ensure_ascii=False,indent=2)+'\n')
print('enriched materialized role records',changed)
print('unresolved exact role records',len(unresolved))
for row in unresolved[:20]: print('UNRESOLVED',*row)
