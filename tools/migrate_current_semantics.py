#!/usr/bin/env python3
from pathlib import Path
import json, shutil, re

ROOT = Path(__file__).resolve().parents[1]

def load(rel):
    return json.loads((ROOT/rel).read_text(encoding='utf-8'))

def dump(rel, obj):
    p=ROOT/rel; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, separators=(',',':'))+'\n', encoding='utf-8')

def text_replace(rel, replacements):
    p=ROOT/rel; text=p.read_text(encoding='utf-8')
    for old,new in replacements:
        if old not in text:
            raise SystemExit(f'missing expected text in {rel}: {old[:120]!r}')
        text=text.replace(old,new)
    p.write_text(text, encoding='utf-8')

def optional_replace(rel, replacements):
    p=ROOT/rel; text=p.read_text(encoding='utf-8')
    for old,new in replacements:
        text=text.replace(old,new)
    p.write_text(text, encoding='utf-8')

# ---------------------------------------------------------------------------
# Lossless compact canonical-identity migration: 306 files + lookup copies ->
# one authoritative shard per initial. Shared policy lives once in the index.
# ---------------------------------------------------------------------------
old_index=load('state/char-roster/index.json')
old_dir=ROOT/'state/char-roster/active-canon'
old_files=sorted(old_dir.glob('*.json'))
if not old_files:
    raise SystemExit('expected current per-identity roster records')
if len(old_files)!=int(old_index.get('count',-1)):
    raise SystemExit(f'pre-migration roster count mismatch: files={len(old_files)} index={old_index.get("count")}')

records={}
shared={k:set() for k in ('schema','representation','activation_rule','life_course_ref','hints_are_authority')}
for p in old_files:
    d=json.loads(p.read_text(encoding='utf-8'))
    cid=d.get('id')
    if not cid or cid in records:
        raise SystemExit(f'duplicate/missing roster id: {cid}')
    records[cid]=d
    for k in shared: shared[k].add(json.dumps(d.get(k), sort_keys=True))
for k,v in shared.items():
    if len(v)!=1:
        raise SystemExit(f'nonuniform shared roster field {k}: {v}')

# Resolve the existing authoritative lookup partition and prove it matches all records.
partition={}
old_lookup_dir=ROOT/'state/char-roster/lookup'
for p in sorted(old_lookup_dir.glob('*.json')):
    d=json.loads(p.read_text(encoding='utf-8')); initial=d.get('initial')
    if not initial: raise SystemExit(f'lookup shard missing initial: {p}')
    for cid,entry in d.get('lookup',{}).items():
        if cid in partition: raise SystemExit(f'identity appears in two lookup shards: {cid}')
        rec=records.get(cid)
        if rec is None: raise SystemExit(f'lookup identity missing direct record: {cid}')
        if entry.get('name')!=rec.get('name'): raise SystemExit(f'name mismatch: {cid}')
        expected=f'state/char-roster/active-canon/{cid}.json'
        if entry.get('path')!=expected: raise SystemExit(f'lookup path mismatch: {cid}:{entry.get("path")}')
        partition[cid]=initial
if set(partition)!=set(records):
    raise SystemExit(f'lookup/direct identity set mismatch: lookup={len(partition)} records={len(records)}')

# Immutable pre-migration digest used only inside this transaction to prove no fact loss.
def canonical_identity_map_from_records():
    return {cid:{'name':d['name'],'routing_hints':d.get('routing_hints',{})} for cid,d in sorted(records.items())}
pre_map=canonical_identity_map_from_records()

# New registered schemas.
identity_shard_schema={
 '$schema':'https://json-schema.org/draft/2020-12/schema',
 'type':'object','required':['schema','authority','initial','count','identities'],
 'properties':{
  'schema':{'const':'character-identity-shard.v1'},
  'authority':{'const':True},
  'initial':{'type':'string','minLength':1,'maxLength':1},
  'count':{'type':'integer','minimum':0},
  'identities':{'type':'object','additionalProperties':{
   'type':'object','required':['name','routing_hints'],'additionalProperties':False,
   'properties':{
    'name':{'type':'string','minLength':1},
    'routing_hints':{'type':'object','additionalProperties':False,'properties':{
     'source_owner_hint':{'type':'string'},'unresolved_route':{'type':'boolean'},
     'state_or_affiliation_hint':{'type':'string'},'role_template_hint':{'type':'string'},
     'profile_seed':{'type':'string'},'activity_owner_hint':{'type':'string'},
     'location_hint':{'type':'string'},'source_unit_hint':{'type':'string'}
    }}
   }
  }}
 },'additionalProperties':False
}
roster_index_schema={
 '$schema':'https://json-schema.org/draft/2020-12/schema',
 'type':'object','required':['schema','id','authority','count','representation','activation_rule','materialization','life_course_ref','hints_are_authority','routing_rule','shards_by_initial'],
 'properties':{
  'schema':{'const':'character-roster-index.v1'},'id':{'type':'string'},'authority':{'const':False},
  'count':{'type':'integer','minimum':0},'representation':{'type':'string'},'activation_rule':{'type':'string'},
  'materialization':{'type':'string'},'life_course_ref':{'type':'string'},'hints_are_authority':{'type':'boolean'},
  'routing_rule':{'type':'string'},
  'shards_by_initial':{'type':'object','additionalProperties':{
   'type':'object','required':['path','count'],'additionalProperties':False,
   'properties':{'path':{'type':'string'},'count':{'type':'integer','minimum':0}}
  }}
 },'additionalProperties':False
}
dump('schemas/character-identity-shard-v1.schema.json', identity_shard_schema)
dump('schemas/character-roster-index-v1.schema.json', roster_index_schema)

identity_template={
 'schema':'file-template.v1','template_id':'template.character-identity-shard.v1','target_schema':'character-identity-shard.v1',
 'source_schema':'schemas/character-identity-shard-v1.schema.json','scope':'mutable_state','current_directories':['state/char-roster/shards'],
 'unknown_key_policy':'reject','required_top_level_keys':['authority','count','identities','initial','schema'],
 'object_contracts':{
  '':{'mode':'closed','allowed_keys':['schema','authority','initial','count','identities'],'canonical_order':['schema','authority','initial','count','identities']},
  '/identities':{'mode':'open_map'},
  '/identities/*':{'mode':'closed','allowed_keys':['name','routing_hints'],'canonical_order':['name','routing_hints']},
  '/identities/*/routing_hints':{'mode':'closed','allowed_keys':['source_owner_hint','unresolved_route','state_or_affiliation_hint','role_template_hint','profile_seed','activity_owner_hint','location_hint','source_unit_hint'],'canonical_order':['source_owner_hint','unresolved_route','state_or_affiliation_hint','role_template_hint','profile_seed','activity_owner_hint','location_hint','source_unit_hint']}
 },
 'type_contracts':{'':['object'],'/schema':['string'],'/authority':['boolean'],'/initial':['string'],'/count':['integer'],'/identities':['object'],'/identities/*':['object'],'/identities/*/name':['string'],'/identities/*/routing_hints':['object'],'/identities/*/routing_hints/source_owner_hint':['string'],'/identities/*/routing_hints/unresolved_route':['boolean'],'/identities/*/routing_hints/state_or_affiliation_hint':['string'],'/identities/*/routing_hints/role_template_hint':['string'],'/identities/*/routing_hints/profile_seed':['string'],'/identities/*/routing_hints/activity_owner_hint':['string'],'/identities/*/routing_hints/location_hint':['string'],'/identities/*/routing_hints/source_unit_hint':['string']},
 'array_contracts':{},
 'writing_rules':['Load this registered template before creating or structurally editing a target shard.','Do not add an unregistered field; structure changes require maintenance first.','The identities map may add or remove canonical IDs only through a lawful identity/materialization transaction.','A template controls shape, not campaign facts.']
}
index_template={
 'schema':'file-template.v1','template_id':'template.character-roster-index.v1','target_schema':'character-roster-index.v1',
 'source_schema':'schemas/character-roster-index-v1.schema.json','scope':'mutable_state','current_directories':['state/char-roster'],
 'unknown_key_policy':'reject','required_top_level_keys':['activation_rule','authority','count','hints_are_authority','id','life_course_ref','materialization','representation','routing_rule','schema','shards_by_initial'],
 'object_contracts':{
  '':{'mode':'closed','allowed_keys':['schema','id','authority','count','representation','activation_rule','materialization','life_course_ref','hints_are_authority','routing_rule','shards_by_initial'],'canonical_order':['schema','id','authority','count','representation','activation_rule','materialization','life_course_ref','hints_are_authority','routing_rule','shards_by_initial']},
  '/shards_by_initial':{'mode':'open_map'},
  '/shards_by_initial/*':{'mode':'closed','allowed_keys':['path','count'],'canonical_order':['path','count']}
 },
 'type_contracts':{'':['object'],'/schema':['string'],'/id':['string'],'/authority':['boolean'],'/count':['integer'],'/representation':['string'],'/activation_rule':['string'],'/materialization':['string'],'/life_course_ref':['string'],'/hints_are_authority':['boolean'],'/routing_rule':['string'],'/shards_by_initial':['object'],'/shards_by_initial/*':['object'],'/shards_by_initial/*/path':['string'],'/shards_by_initial/*/count':['integer']},
 'array_contracts':{},
 'writing_rules':['Load this registered template before structurally editing the canonical identity roster index.','Shard counts are derived from authoritative shard contents; the index never owns duplicate identity facts.','A template controls shape, not campaign facts.']
}
dump('data/runtime/templates/character-identity-shard.v1.template.json', identity_template)
dump('data/runtime/templates/character-roster-index.v1.template.json', index_template)

# Register the new structures and retire only superseded character-roster structure generations.
reg=load('schemas/registry.json')
for key in list(reg):
    if key.startswith('active_character_') or key=='cold-active-identity.v1':
        reg.pop(key)
reg['character-identity-shard.v1']='character-identity-shard-v1.schema.json'
reg['character-roster-index.v1']='character-roster-index-v1.schema.json'
dump('schemas/registry.json', reg)

aidx=load('data/runtime/template-index-shards/a.json')
for key in list(aidx.get('templates',{})):
    if key.startswith('active_character_'):
        aidx['templates'].pop(key)
dump('data/runtime/template-index-shards/a.json', aidx)
cidx=load('data/runtime/template-index-shards/c.json')
cidx.setdefault('templates',{}).pop('cold-active-identity.v1',None)
cidx['templates']['character-identity-shard.v1']={'path':'data/runtime/templates/character-identity-shard.v1.template.json','source_schema':'schemas/character-identity-shard-v1.schema.json','scope':'mutable_state'}
cidx['templates']['character-roster-index.v1']={'path':'data/runtime/templates/character-roster-index.v1.template.json','source_schema':'schemas/character-roster-index-v1.schema.json','scope':'mutable_state'}
dump('data/runtime/template-index-shards/c.json', cidx)

# Authoritative identity shards.
new_root=ROOT/'state/char-roster/shards'
new_root.mkdir(parents=True, exist_ok=True)
shards={}
for initial in sorted(set(partition.values())):
    ids=sorted(cid for cid,i in partition.items() if i==initial)
    identities={cid:{'name':records[cid]['name'],'routing_hints':records[cid].get('routing_hints',{})} for cid in ids}
    rel=f'state/char-roster/shards/{initial}.json'
    dump(rel, {'schema':'character-identity-shard.v1','authority':True,'initial':initial,'count':len(ids),'identities':identities})
    shards[initial]={'path':rel,'count':len(ids)}
new_index={
 'schema':'character-roster-index.v1','id':'roster.canon_active_world','authority':False,'count':len(records),
 'representation':'deferred_detail_routed_identity',
 'activation_rule':'Materialize only on causal relevance after reconciling routing hints against current world authority and conserving one real source person exactly once.',
 'materialization':'Roster entries own canonical name and routing hints only. Exact body, capability, office, location, equipment, knowledge, relationships and current goals are resolved only when causal evidence requires materialization.',
 'life_course_ref':'state/life/identity-life-course.json','hints_are_authority':False,
 'routing_rule':'Known character_id selects exactly one initial shard from the first character after the char_ prefix; name-only discovery loads only plausible initial shards. The shard is authoritative for canonical name and routing hints.',
 'shards_by_initial':shards
}
dump('state/char-roster/index.json', new_index)
post_map={}
for initial,meta in shards.items():
    d=load(meta['path'])
    for cid,x in d['identities'].items(): post_map[cid]={'name':x['name'],'routing_hints':x['routing_hints']}
if pre_map!=post_map:
    raise SystemExit('lossless identity migration check failed')

# Remove the duplicated file forest and all superseded roster schemas/templates.
shutil.rmtree(old_dir)
shutil.rmtree(old_lookup_dir)
for p in (ROOT/'schemas').glob('active-character-*.schema.json'): p.unlink()
for p in (ROOT/'schemas').glob('cold-active-identity-*.schema.json'): p.unlink()
for p in (ROOT/'data/runtime/templates').glob('active_character_*.template.json'): p.unlink()
for p in (ROOT/'data/runtime/templates').glob('cold-active-identity*.template.json'): p.unlink()

# ---------------------------------------------------------------------------
# Routing and system ownership: current semantic names, one shard per lookup.
# ---------------------------------------------------------------------------
chars=load('data/runtime/system-contracts/characters.json')
paths=chars.setdefault('authority_paths',[])
if 'state/char-roster/' not in paths: paths.append('state/char-roster/')
for t in ('character-identity-shard.v1','character-roster-index.v1'):
    if t not in chars.setdefault('owner_templates',[]): chars['owner_templates'].append(t)
chars['read_first']=[
 'exact/lite owner when materialized',
 'for a deferred-detail canonical identity, the one authoritative initial shard plus only causal source/office/relationship/knowledge/career references',
 'for a behavior-light exact owner in sustained or personality-sensitive interaction, load only its routed behavior support profile before assigning distinctive behavior'
]
chars['invariants']=[
 'Never invent player intent.',
 'Unknown is better than filler.',
 'No skill, rank, behavior, office, location, equipment, knowledge, or relationship growth without causal evidence and time.',
 'Do not back-project future canon achievements.',
 'Behavior support profiles are evidence-limited inputs, never a second character-state authority.',
 'Deferred-detail roster identities own canonical name and routing hints only; materialization conserves one real source person exactly once.'
]
dump('data/runtime/system-contracts/characters.json', chars)

scidx=load('data/runtime/system-contract-index.json')
scidx['purpose']='Load-on-demand update contracts. Load one only when creating or mutating that system.'
dump('data/runtime/system-contract-index.json', scidx)
tidx=load('data/runtime/template-index.json')
tidx['purpose']='Registered structure lookup. Choose the shard by the first character of the target schema ID.'
dump('data/runtime/template-index.json', tidx)

repo=load('data/runtime/repository-map.json')
repo['retrieval_invariants']=[x.replace('one cold route shard','one routed route shard') for x in repo.get('retrieval_invariants',[])]
repo['routes']['write_template_lookup']['note']='Before creating or structurally changing JSON, resolve the target schema to one registered template shard. No unregistered fields.'
ri=repo.get('route_index',{})
if 'cold_canon_roster' in ri: ri['character_identity_roster']=ri.pop('cold_canon_roster')
if 'cold_character_materialization' in ri: ri['character_materialization']=ri.pop('cold_character_materialization')
dump('data/runtime/repository-map.json', repo)

people=load('data/runtime/repository-routes/people.json')
routes=people['routes']
routes.pop('cold_canon_roster',None); routes.pop('cold_character_materialization',None)
routes['character_identity_roster']={'i':['state/char-roster/index.json'],'g':['state/char-roster/shards/*.json'],'note':'Known character_id selects one authoritative initial shard; name-only discovery loads only plausible initial shards. Exact/lite materialization occurs only on causal need.'}
routes['character_materialization']={'domain':'character_materialization'}
dump('data/runtime/repository-routes/people.json', people)

rr=load('data/runtime/rule-router.json')
dom=rr['domains']
old=dom.pop('cold_character_materialization',None)
dom['character_materialization']=old or ['rules/characters.md','rules/memory.md','state/char-roster/index.json']
dump('data/runtime/rule-router.json', rr)

# ---------------------------------------------------------------------------
# Active rules describe current behavior only. No migration/release-history prose.
# ---------------------------------------------------------------------------
text_replace('RUNTIME.md',[
 ('Structural writes use one exact cold file template plus the relevant system update contract.','Structural writes use the registered file template plus the relevant system update contract.'),
 ('Cold canonical identities are routing compression, not frozen people.','Deferred-detail canonical identities are routed representations, not frozen people.'),
 ('Load one primary cold scene module from `data/runtime/narration-router.json`; at most one causal secondary, never all modules.','Load one primary routed scene module from `data/runtime/narration-router.json`; at most one causal secondary, never all modules.')
])
text_replace('VOICE.md',[
 ('`data/runtime/narration-router.json` owns cold scene-specific narration modules.','`data/runtime/narration-router.json` owns load-on-demand scene-specific narration modules.')
])
text_replace('REPOSITORY_MAP.md',[
 ('| Cold canon identity | direct `state/char-roster/active-canon/<id>.json` | materialize only when causally active |','| Deferred-detail canon identity | `state/char-roster/index.json` -> one authoritative initial shard | materialize only when causally active |')
])

# Character runtime is small enough to state the current rule directly.
(ROOT/'rules/character-runtime.md').write_text('''# Runtime Character Behavior\n\nUse this rule for ordinary interaction with an already-routed or materialized character. Load `rules/characters.md` only when creating/materializing a person, changing representation depth, or resolving character structure.\n\n## Authority order\n\nFor an active character, behavior comes from the smallest relevant saved set:\n\n1. explicit bespoke `behavior` or compact personality state;\n2. when inline behavior is insufficient, the one load-on-demand support profile routed by `data/people/behavior-profile-index.json`;\n3. current goals, duties, appointments, relationships, knowledge and recent history;\n4. established role/career/canon characterization already saved in the owner;\n5. general human constraints from this rule.\n\nMissing personality detail is unknown, not permission to invent filler. A behavior-light exact character acts conservatively from current duty, knowledge, incentives and proven traits until distinctive behavior is supported by source/campaign evidence.\n\nBefore a behavior-light exact character enters sustained direct interaction, independent high-stakes decision-making, recurring command, or a scene where personality can materially change the result, perform a behavior-depth check. If the owner ID is routed by `data/people/behavior-profile-index.json`, load exactly that profile, then only causal source/canon hints, office/duty, relationships, knowledge, goals and campaign history. Persist a compact behavior anchor only when those sources support it. Insufficient evidence keeps the character role-driven and restrained. Brief routine contact does not require forced deepening.\n\n## Runtime decision rule\n\nA character chooses only among actions they can know, attempt and authorize. Weight current goals, institutional duty, relationships, risk, health/fatigue, available resources, prior consequences and established behavior. Rank, canon importance and narrative attention never grant free competence or information.\n\nDo not infer the player character's voluntary thoughts, dialogue, commitments or choices.\n\n## Knowledge and relationships\n\nUse relationship/knowledge authority for consequential social state. Shared affiliation is not automatically a personal relationship. Knowledge arrives only through valid observation, records, reports, messengers, scouts, spies or other saved paths.\n\n## Updating an NPC\n\nPersist only changes caused by the event: health/fatigue to the body/condition owner; capability through registered development/training; relationship/knowledge/reputation to their authorities; role/office/assignment/command to institutional owners; goals only when causally revised; behavior only when repeated or decisive evidence makes it persistent. Do not write narration summaries or developer/audit commentary back as character facts.\n\n## Deferred-detail routed identities\n\nA deferred-detail canonical identity is a real named world identity without fabricated exact current body state. Load its one authoritative initial shard. When causal relevance requires an exact/lite actor, use `rules/characters.md` to resolve only state justified by current time, source organization, age, canon anchor, campaign history and conserved source population. Future achievements or later-series ranks are never back-projected.\n''',encoding='utf-8')

# Current terminology in the full character/world rules.
optional_replace('rules/characters.md',[
 ('Generic crude/common/military/superior/masterwork/exceptional combat tiers are retired. Equipment capability comes from its actual pattern fields, current condition, fit, carriage, and any explicitly named physical craft trait.','Equipment capability comes from actual pattern fields, current condition, fit, carriage, and any explicitly named physical craft trait.'),
 ('cold-active routed identities','deferred-detail routed identities'),('Cold-active routed identities','Deferred-detail routed identities'),
 ('cold-active routed named identity','deferred-detail routed named identity'),('cold-active/routed','deferred-detail/routed'),
 ('cold-active','deferred-detail'),('Cold active','Deferred-detail'),('cold active','deferred-detail'),
 ('Cold status','Deferred-detail representation'),('cold status','deferred-detail representation'),
 ('Cold full','Deferred-detail full'),('cold full','deferred-detail full'),('A cold profile','A deferred-detail profile'),('a cold profile','a deferred-detail profile'),
 ('- no cold personal periodic clocks;','- deferred-detail identities have no personal periodic clocks by default;'),
 ('Do not restore mass-generated trait filler.','Unsupported trait filler is not character state.')
])
optional_replace('rules/world.md',[
 ('Monthly world-close events process registered cold domains','Monthly world-close events process registered offscreen aggregate domains'),
 ('## Cold-active canonical identities','## Deferred-detail canonical identities'),
 ('Cold-active status','Deferred-detail representation'),('cold-active status','deferred-detail representation'),
 ('Cold-active identities','Deferred-detail identities'),('cold-active identities','deferred-detail identities'),
 ('Cold active routed identity','Deferred-detail routed identity'),('cold active routed identity','deferred-detail routed identity'),
 ('Cold active identity','Deferred-detail identity'),('cold active identity','deferred-detail identity'),
 ('Cold active routed identities','Deferred-detail routed identities'),('cold active routed identities','deferred-detail routed identities'),
 ('Cold status','Deferred-detail representation'),('cold status','deferred-detail representation')
])
text_replace('rules/org.md',[
 ("World-owned forces have their normal home establishment. Tang Wei's unorganized personal retinue remains `permanent_units: []` until the player creates units. OOC/preview discussion never creates organization or intent.","World-owned forces retain their lawful home establishment. Tang Wei's personal-force owner records only units and named people actually created, assigned, attached, hired or otherwise placed under his authority. OOC/preview discussion never creates organization, assignment or intent."),
])
# Other domain wording: preserve ordinary meanings such as physical cold or a cold relationship.
for rel,repls in {
 'rules/economy.md':[('Cold macro reviews may remain aggregate','Offscreen macro reviews may remain aggregate')],
 'rules/family.md':[('cold family-event provenance','family-event provenance'),('Historical events stay cold unless','Historical events stay load-on-demand unless'),('Cold populations may batch','Aggregate populations may batch'),('cold event provenance','event provenance')],
 'rules/independent.md':[('normally cold aggregate owners','normally offscreen aggregate owners')],
 'rules/logistics.md':[('Stationary cold forces may batch','Stationary offscreen aggregate forces may batch')],
 'rules/memory.md':[('Cold receipts, closed operations, old testimony, and detailed historical logs remain outside ordinary context','Closed receipts, completed operations, old testimony, and detailed historical logs remain outside ordinary context'),('keep closed receipts and unrelated world registries cold.','keep closed receipts and unrelated world registries load-on-demand.'),('cold forensic history','load-on-demand forensic history'),('cold history stays cold unless causally relevant','closed history stays load-on-demand unless causally relevant')],
 'rules/reputation.md':[('Event files are cold causal history','Event files are load-on-demand causal history')],
 'rules/states.md':[('Cold civil and military units','Offscreen aggregate civil and military units'),('Cold named identities','Deferred-detail named identities'),('cold-active routed named identity','deferred-detail routed named identity')],
 'rules/settlements.md':[('and dissolve or archive when that operational arrangement ends.','and dissolve when that operational arrangement ends; any required causal receipt remains load-on-demand rather than becoming a duplicate formation owner.')]
}.items(): optional_replace(rel,repls)

# Generic maintenance templates should say what they are, not call themselves "cold".
for p in (ROOT/'data/runtime/templates').glob('*.template.json'):
    s=p.read_text(encoding='utf-8')
    s=s.replace('Load this cold template','Load this registered template')
    p.write_text(s,encoding='utf-8')

# ---------------------------------------------------------------------------
# Validators protect structure/mechanics, not words or historical snapshots.
# ---------------------------------------------------------------------------
audit=ROOT/'tools/audit.py'; s=audit.read_text(encoding='utf-8')
start=s.index('# No latent identity directory after cold-active roster migration.')
end=s.index('# Troop pools are accounting objects',start)
new_block='''# Canonical deferred-detail identity roster: authoritative shards, derived index, no per-character file forest.\nif (ROOT/'data/latent-identities').exists():err('obsolete_latent_identity_directory_present')\n_car=rj(ROOT/'state/char-roster/index.json') or {}\nif _car.get('schema')!='character-roster-index.v1' or _car.get('authority') is not False:err('character_roster_index_invalid')\n_seen_roster=set(); _roster_total=0\nfor _initial,_e in _car.get('shards_by_initial',{}).items():\n _sh=rj(ROOT/_e.get('path','')) or {}; _ids=_sh.get('identities',{})\n if _sh.get('schema')!='character-identity-shard.v1' or _sh.get('authority') is not True or _sh.get('initial')!=_initial:err(f'character_roster_shard_header:{_initial}')\n if len(_ids)!=int(_e.get('count',-1)) or len(_ids)!=int(_sh.get('count',-2)):err(f'character_roster_shard_count:{_initial}')\n for _cid,_x in _ids.items():\n  if _cid in _seen_roster:err(f'character_roster_duplicate_id:{_cid}')\n  _seen_roster.add(_cid); _roster_total+=1\n  if not isinstance(_x.get('name'),str) or not _x.get('name'):err(f'character_roster_missing_name:{_cid}')\n  if not isinstance(_x.get('routing_hints'),dict):err(f'character_roster_missing_routing_hints:{_cid}')\nif _roster_total!=int(_car.get('count',-1)):err(f'character_roster_total:{_roster_total}:{_car.get("count")}')\nif (ROOT/'state/char-roster/active-canon').exists() or (ROOT/'state/char-roster/lookup').exists():err('per_character_roster_storage_reintroduced')\n\n'''
s=s[:start]+new_block+s[end:]
start=s.index('# Cold active roster, never obsolete latent authority.')
end=s.index('# Command-person direct records',start)
new_block='''# Canonical identity life-course route remains single-owner and shard-backed.\n_life=rj(ROOT/'state/life/identity-life-course.json') or {}; _roster=rj(ROOT/'state/char-roster/index.json') or {}\nif (_life.get('records') or [{}])[0].get('facts',{}).get('canon_roster_owner')!='state/char-roster/index.json':err('life_course_roster_route_missing')\nif _roster.get('count',0)<1:err('character_roster_empty')\nif _roster.get('schema')!='character-roster-index.v1':err('character_roster_schema_missing')\n\n'''
s=s[:start]+new_block+s[end:]
audit.write_text(s,encoding='utf-8')

unit=ROOT/'tools/test_unit_model.py'; s=unit.read_text(encoding='utf-8')
# Remove the repository-wide retired-word scanner; structural invariants are validated directly.
lex_start=s.index('# No retired organization term in text files or filenames.')
lex_end=s.index('# Machine map explicit listed paths resolve;',lex_start)
s=s[:lex_start]+'# Organization semantics are validated structurally; prose vocabulary is not a correctness gate.\n'+s[lex_end:]
# Replace old roster-shape assertions.
old_start=s.index("    roster=rj('state/char-roster/index.json')")
old_end=s.index('    # No stale character representation terminology.',old_start)
new='''    roster=rj('state/char-roster/index.json')\n    if roster.get('schema')!='character-roster-index.v1' or roster.get('authority') is not False:err('character_roster_index')\n    seen=set(); total=0\n    for initial,meta in roster.get('shards_by_initial',{}).items():\n        rel=meta.get('path'); sh=rj(rel) if rel else {}\n        ids=sh.get('identities',{})\n        if sh.get('schema')!='character-identity-shard.v1' or sh.get('authority') is not True or sh.get('initial')!=initial:err(f'character_roster_shard:{initial}')\n        if len(ids)!=meta.get('count') or len(ids)!=sh.get('count'):err(f'character_roster_shard_count:{initial}')\n        for cid,rec in ids.items():\n            if cid in seen:err(f'character_roster_duplicate:{cid}')\n            seen.add(cid); total+=1\n            if not rec.get('name') or not isinstance(rec.get('routing_hints'),dict):err(f'character_roster_identity_shape:{cid}')\n    if total!=roster.get('count'):err(f'character_roster_total:{total}:{roster.get("count")}')\n    if (R/'state/char-roster/active-canon').exists() or (R/'state/char-roster/lookup').exists():err('per_character_roster_files_present')\n'''
s=s[:old_start]+new+s[old_end:]
s=s.replace('Behavior-light cold/exact characters have an explicit deepening gate rather than generic filler.','Behavior-light exact characters use an explicit deepening gate rather than generic filler.')
s=s.replace('cold exact profiles may stay compact','deferred-detail profiles may stay compact')
unit.write_text(s,encoding='utf-8')

# Keep current semantic route names in tests/tool output when present.
for rel in ('tools/test_semantics.py','tools/test_routing.py','tools/test_current_identities.py'):
    p=ROOT/rel; t=p.read_text(encoding='utf-8')
    t=t.replace('cold_character_materialization','character_materialization').replace('cold_canon_roster','character_identity_roster')
    t=t.replace('cold roster','character roster').replace('cold_roster','character_roster').replace('cold-active','deferred-detail').replace('cold_active','deferred_detail')
    p.write_text(t,encoding='utf-8')

# Remove release-style hard-coded current roster identity values from validators if any remain.
for p in (ROOT/'tools').glob('*.py'):
    t=p.read_text(encoding='utf-8')
    t=t.replace("if int(_car.get('count',0))!=306:err(f'active_roster_expected_306:{_car.get(\"count\")}')\n",'')
    p.write_text(t,encoding='utf-8')

# Meta revision changes once for this canonical state-shape migration; world time does not advance.
meta=load('state/meta.json')
if meta.get('revision')!=16: raise SystemExit(f'unexpected starting revision: {meta.get("revision")}')
meta['revision']=17
dump('state/meta.json',meta)

# Structural old-token closure: these are removed representations/paths, not vocabulary bans.
for rel in ('data/runtime/repository-map.json','data/runtime/repository-routes/people.json','data/runtime/rule-router.json','schemas/registry.json'):
    blob=(ROOT/rel).read_text(encoding='utf-8')
    for token in ('cold_canon_roster','cold_character_materialization','cold-active-identity.v1','active-canon/'):
        if token in blob: raise SystemExit(f'obsolete structural token remains in {rel}: {token}')

# Temporary inventory/migration tools are not repository features.
for rel in ('tools/audit_current_semantics.py','tools/migrate_current_semantics.py'):
    p=ROOT/rel
    if p.exists(): p.unlink()

# Restore normal read-only CI after the one-shot candidate is assembled.
(ROOT/'.github/workflows/audit.yml').write_text("name: audit\non: [push, pull_request]\njobs:\n  audit:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.12'\n      - run: pip install jsonschema\n      - name: Run full validator stack\n        run: python tools/run_validators.py\n",encoding='utf-8')
print(f'migrated {len(records)} canonical identities into {len(shards)} authoritative shards; campaign time unchanged')
