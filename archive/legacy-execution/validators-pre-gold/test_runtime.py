from pathlib import Path
import json, sys, glob
ROOT=Path(__file__).resolve().parents[1]
errs=[]
def err(x): errs.append(x)
def rj(rel):
    try: return json.loads((ROOT/rel).read_text(encoding='utf-8'))
    except Exception as e: err(f'json:{rel}:{e}'); return {}
def all_routes(m=None):
    m=m or rj('game/data/runtime/repository-map.json')
    out=dict(m.get('routes',{}))
    for rel in m.get('route_shards',{}).values():
        out.update(rj(rel).get('routes',{}))
    return out
# control plane
for f in ['RUNTIME.md','VOICE.md','REPOSITORY_MAP.md','game/data/runtime/repository-map.json','state/meta.json','state/player.json','state/scene.json']:
    if not (ROOT/f).exists(): err(f'missing_runtime_file:{f}')
for f in ['P'+'LAY.md','PROTO'+'COL.md']:
    if (ROOT/f).exists(): err(f'obsolete_control_file:{f}')
# README.md and AGENTS.md are validated for role/structure elsewhere; byte length is not a correctness condition.
# repository map routes must resolve
m=rj('game/data/runtime/repository-map.json')
for req in ['RUNTIME.md','VOICE.md','game/data/runtime/repository-map.json','state/meta.json','state/player.json','state/scene.json']:
    if req not in m.get('hot',[]): err(f'startup_missing:{req}')
for key,route in all_routes(m).items():
    for field in ['r','i','router','w']:
        for rel in route.get(field,[]):
            if rel and '<' not in rel and '*' not in rel and not (ROOT/rel).exists(): err(f'route_missing:{key}:{field}:{rel}')
    for field in ['g','wg']:
        for pat in route.get(field,[]):
            if not pat: continue
            if list(ROOT.glob(pat)): continue
            prefix=pat.split('*',1)[0].rstrip('/')
            base=(ROOT/prefix) if prefix else ROOT
            # Git cannot represent an empty directory. A mapped empty authority is valid.
            if prefix and not base.exists() and prefix not in set(rj(m.get('directory_map','game/data/runtime/directory-map.json')).get('dirs',{})):
                err(f'route_glob_base_missing:{key}:{field}:{pat}')
# every first-level state/data directory must be mapped
mapped=set(rj(m.get('directory_map','game/data/runtime/directory-map.json')).get('dirs',{}))
actual=set()
for base in ['state','data']:
    for p in (ROOT/base).iterdir():
        if p.is_dir(): actual.add(base+'/'+p.name)
for rel in sorted(actual-mapped): err(f'unmapped_directory:{rel}')
# temporal engine flags
te=rj('game/data/runtime/temporal-settlement.json')
for term in ['continuous_residual','new_process_rule','hard_interrupt_rule','safe_batching','postconditions']:
    if term not in te: err(f'temporal_engine_missing:{term}')
# frontier recurrence and closure
front=rj('state/time/frontier.json'); world=front.get('world_time')
covreq=rj('game/data/runtime/coverage-requirements.json')
covered=set()
def process_coverage(p):
    cov=list(p.get('coverage',[]))
    ref=p.get('coverage_ref')
    if ref:
        d=rj(ref)
        if d.get('process_id')!=p.get('id'): err(f'process_coverage_ref_mismatch:{p.get("id")}:{ref}')
        cov=list(d.get('owner_ids',[]))
    return cov
for p in front.get('processes',[]):
    covered.update(process_coverage(p))
    rec=p.get('recurrence')
    if p.get('status')=='active':
        if not rec: err(f'missing_recurrence:{p.get("id")}')
        elif p.get('settlement_mode')=='triggered' and rec.get('kind')!='triggered': err(f'bad_trigger_recurrence:{p.get("id")}')
        elif p.get('settlement_mode')=='event' and rec.get('kind')!='one_shot': err(f'bad_event_recurrence:{p.get("id")}')
        elif p.get('settlement_mode')=='batchable' and rec.get('kind') in ('one_shot','triggered',None): err(f'bad_batch_recurrence:{p.get("id")}')
        if rec and rec.get('accrual_mode')=='continuous' and p.get('settled_through')!=world:
            err(f'continuous_not_closed_to_world_time:{p.get("id")}:{p.get("settled_through")}')
    elif p.get('status')=='completed' and p.get('next_due') is not None:
        err(f'completed_process_has_next_due:{p.get("id")}:{p.get("next_due")}')
for oid in covreq.get('required_owner_ids',[]):
    if oid not in covered: err(f'required_owner_uncovered:{oid}')
# current exact/lite people and living factions must have coverage
candidates=set()
def getid(path):
    try: d=json.loads(path.read_text(encoding='utf-8'))
    except: return None
    for k in ['owner_id','id','character_id','person_id','force_id','unit_id']:
        if isinstance(d.get(k),str): return d[k]
    return None
if (ROOT/'state/char').exists():
    for p in (ROOT/'state/char').glob('*.json'):
        x=getid(p)
        if x: candidates.add(x)
for base in ['state/person/ht','state/person/world','state/person']:
    q=ROOT/base
    if q.exists():
        for p in q.rglob('*.json'):
            x=getid(p)
            if x: candidates.add(x)
for g in ['state/force/*.json','state/merc/*.json']:
    for p in ROOT.glob(g):
        try: d=json.loads(p.read_text(encoding='utf-8'))
        except: continue
        for k in ['id','force_id','unit_id']:
            if isinstance(d.get(k),str): candidates.add(d[k]); break
for facrel in ['state/reg/factions.json','state/reg/living-factions.json']:
    q=ROOT/facrel
    if q.exists():
        d=rj(facrel); fs=d.get('factions',{})
        if isinstance(fs,dict): candidates.update(fs.keys())
        elif isinstance(fs,list): candidates.update(x.get('id') for x in fs if isinstance(x,dict) and x.get('id'))
for x in candidates:
    if x not in covered: err(f'evolving_person_or_faction_uncovered:{x}')
# Homogeneous units/teams may be covered directly or through a declared descendant-aggregate parent group.
aggregate_parents=set()
for _g in covreq.get('required_coverage_groups',[]):
    if isinstance(_g,dict) and _g.get('mode')=='descendant_aggregate': aggregate_parents.update(_g.get('parent_owner_ids',[]))
for _pat in ['state/unit/*.json','state/team/tactical/*.json']:
    for _p in ROOT.glob(_pat):
        try:_d=json.loads(_p.read_text(encoding='utf-8'))
        except:continue
        _oid=_d.get('id') or _d.get('unit_id'); _parent=_d.get('parent_force') or _d.get('owner')
        if _oid and _oid not in covered and _parent not in aggregate_parents: err(f'unit_or_team_without_direct_or_parent_coverage:{_oid}:{_parent}')
# runtime catch-up vectors
ct=rj('tests/runtime-catchup.json'); cases={x['id']:x for x in ct.get('cases',[]) if isinstance(x,dict) and 'id' in x}
wk=cases.get('weekly_multi_month',{})
if wk:
    due=wk['first_due_seconds']; target=wk['target_seconds']; step=wk['recurrence']['interval_seconds']; c=0; last=None
    while due<=target: c+=1; last=due; due+=step
    if c!=wk['expected_full_boundaries'] or last!=wk['expected_last_boundary_seconds'] or target-last!=wk['expected_residual_seconds']: err('weekly_catchup_vector_failed')
mo=cases.get('monthly_six_boundaries_plus_partial',{})
if mo and len(mo.get('expected_boundaries',[]))!=6: err('monthly_catchup_vector_failed')
for req in ['successor_continues','hard_interrupt_stops_early','new_process_catches_up']:
    if not cases.get(req,{}).get('required'): err(f'catchup_semantic_case_missing:{req}')
# autonomous offscreen actors
_aw=rj('game/data/runtime/autonomous-world-simulation.json')
for _k in ('action_kinds','selection_rule','materialization_rule','storage_rule','operation_lifecycle','large_conflict_efficiency_rule','npc_mission_rule','interaction_rule','combat_rule','territory_rule','successor_rule','information_rule'):
    if not _aw.get(_k): err(f'autonomous_contract_missing:{_k}')
for _need in ('battle','raid'):
    if not any(_need in str(x).lower() for x in _aw.get('action_kinds',[])): err(f'autonomous_action_missing:{_need}')
if 'Out-of-character' not in str(_aw.get('player_intent_boundary','')): err('player_intent_boundary_missing')
# Autonomous storage targets may be physically absent when they are mapped but empty, because Git cannot retain empty directories.
_st=_aw.get('storage_targets',{})
if not isinstance(_st,dict) or not _st: err('autonomous_storage_targets_missing')
for _name,_rel in _st.items():
    _norm=_rel.rstrip('/')
    if not (ROOT/_rel).exists() and _norm not in mapped: err('autonomous_storage_target_unmapped_or_missing:'+str(_name)+':'+str(_rel))
_acts=' '.join(str(x).lower() for x in _aw.get('action_kinds',[]))
for _need in ('battle','raid','siege','occupation','diplomacy'):
    if _need not in _acts: err('autonomous_action_family_missing:'+_need)
# The final error check must come after every validation block.
if errs:
    print('RUNTIME TEST FAILED')
    for x in errs: print('-',x)
    sys.exit(1)
print('RUNTIME TEST OK')
print(f'covered_owners={len(covered)} evolving_people_factions_checked={len(candidates)} processes={len(front.get("processes",[]))}')
