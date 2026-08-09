#!/usr/bin/env python3
from pathlib import Path
import json,sys
R=Path(__file__).resolve().parents[1]
errs=[]
def err(x):errs.append(x)
def rj(rel):
    try:return json.loads((R/rel).read_text(encoding='utf-8'))
    except Exception as e:err(f'json:{rel}:{e}');return {}
def all_routes():
    m=rj('data/runtime/repository-map.json');out=dict(m.get('routes',{}))
    for rel in m.get('route_shards',{}).values():out.update(rj(rel).get('routes',{}))
    return out
idx=rj('state/family/index.json'); mech=rj('data/mechanics/family.json')
if idx.get('schema')!='family-index.v1' or idx.get('authority') is not False:err('family_index_invalid')
if mech.get('schema')!='family-mechanics.v1':err('family_mechanics_invalid')
for phrase in ('relationship','reputation','property','health'):
    if phrase not in json.dumps(mech.get('authority_boundaries',{})).lower():err(f'family_authority_separation_missing:{phrase}')
if mech.get('player_agency',{}).get('never_choose_player_spouse') is not True:err('player_spouse_agency_missing')
if mech.get('player_agency',{}).get('never_choose_player_parenthood') is not True:err('player_parenthood_agency_missing')
if mech.get('determinism',{}).get('no_duplicate_global_clock') is None:err('family_clock_contract_missing')
# Index counts and referenced records.
for kind,folder in [('courtships','courtships'),('proposals','proposals'),('unions','unions'),('households','households'),('kinships','kinships'),('parentage','parentage'),('successions','successions'),('events','events')]:
    mp=idx.get(kind,{})
    if idx.get('counts',{}).get(kind)!=len(mp):err(f'family_count:{kind}')
    for rid,ref in mp.items():
        if not (R/ref).exists():err(f'family_missing_ref:{kind}:{rid}:{ref}')
# Person IDs that can appear in family state.
people=set()
for rel in ['state/player.json']:
    d=rj(rel); people.add(d.get('owner_id'))
for base in ['state/char','state/person']:
    q=R/base
    if q.exists():
        for p in q.rglob('*.json'):
            try:d=json.loads(p.read_text(encoding='utf-8'))
            except:continue
            oid=d.get('owner_id') or d.get('id')
            if oid:people.add(oid)
# Validate union/parentage people without forcing population-wide family records.
# Direct kinship records preserve known kinship without inventing missing parentage.
for rid,ref in idx.get('kinships',{}).items():
    d=rj(ref)
    if d.get('schema')!='family-kinship.v1' or d.get('authority') is not True:err(f'kinship_schema:{rid}')
    ps=d.get('participants',[])
    if len(ps)!=2 or len(set(ps))!=2:err(f'kinship_participants:{rid}')
    for x in ps:
        if x not in people:err(f'kinship_unknown_person:{rid}:{x}')

for rid,ref in idx.get('unions',{}).items():
    d=rj(ref)
    if d.get('schema')!='family-union.v1' or d.get('authority') is not True:err(f'union_schema:{rid}')
    for x in d.get('participants',[]):
        if x not in people:err(f'union_unknown_person:{rid}:{x}')
for rid,ref in idx.get('parentage',{}).items():
    d=rj(ref)
    if d.get('child_id') not in people:err(f'parentage_unknown_child:{rid}')
    for pl in d.get('parent_links',[]):
        if pl.get('parent_id') not in people:err(f'parentage_unknown_parent:{rid}:{pl.get("parent_id")}')
# Derived kinship must stay non-authoritative.
kin=rj('state/family/kinship-index.json')
if kin.get('schema')!='kinship-index.v1' or kin.get('authority') is not False:err('kinship_index_invalid')
# Routing and human contract.
router=rj('data/runtime/rule-router.json').get('domains',{})
for d in ('family_query','family_transition','family_succession'):
    if d not in router:err(f'family_router_missing:{d}')
routes=all_routes()
for d in ('family_person','family_transition','family_succession','family_event','family_kinship'):
    if d not in routes:err(f'family_map_missing:{d}')
h=(R/'REPOSITORY_MAP.md').read_text(encoding='utf-8').lower()
if 'updating family, marriage, household, and succession' not in h:err('family_human_map_missing')
# Existing spouse edges must point to union when a current union is known.
if (R/'state/rel/relationship-edges/char_tang_zhu.json').exists():
    for rel in ('state/rel/relationship-edges/char_tang_zhu.json','state/rel/relationship-edges/char_tang_ling.json'):
        d=rj(rel)
        for e in d.get('relationship_edges',{}).values():
            if e.get('relationship_type')=='spouse' and not e.get('institutional_union_ref'):err(f'spouse_edge_missing_union:{rel}')
# Player current state must not gain family intent simply because the system was installed.
p=rj('state/player.json')
blob=json.dumps(p).lower()
for bad in ('marriage_proposal_pending','betrothal_pending','player_wants_to_marry'):
    if bad in blob:err(f'fabricated_player_family_intent:{bad}')
if errs:
    print('FAMILY TEST FAILED')
    for x in errs:print('-',x)
    sys.exit(1)
print('FAMILY TEST OK')
print('counts='+json.dumps(idx.get('counts',{}),sort_keys=True))
