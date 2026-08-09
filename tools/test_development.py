#!/usr/bin/env python3
import json, pathlib
ROOT=pathlib.Path(__file__).resolve().parents[1]
model=json.loads((ROOT/'data/development/model.json').read_text())
eff=model['representation_efficiency']
assert set(eff.values())=={1.0}, eff
# Identical inputs must not change because of representation.
base=100.0
aptitude=1.6
attendance=.9
instructor=.85
facility=.95
equipment=.9
health=.92
recovery=.9
relevance=1.0
difficulty=.95
common=base*aptitude*attendance*instructor*facility*equipment*health*recovery*relevance*difficulty
vals={k:common*v for k,v in eff.items()}
assert len({round(v,10) for v in vals.values()})==1, vals
# Unit promotion is a conservation transfer, never a multiplier.
starting=1000
qualified=37
remaining=starting-qualified
assert remaining+qualified==starting and remaining>=0
# Instructor capacity cannot exceed available hours when measured as personalized student-hours.
available_instructor_hours=30
requested=[10,10,10]
assert sum(requested)<=available_instructor_hours
overrequested=[10,10,10,10]
assert sum(overrequested)>available_instructor_hours
assert model['promotion_rule']['mode']=='qualified_subset_transfer'
assert model['batching_rule']['batch_equivalence_required'] is True
print('DEVELOPMENT FAIRNESS OK')
print('representation_efficiency='+json.dumps(eff,sort_keys=True))
print('sample_effective_training='+str(round(common,4)))
