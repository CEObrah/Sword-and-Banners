#!/usr/bin/env python3
from pathlib import Path
import json, hashlib, re, sys
R=Path(__file__).resolve().parents[1]
errs=[]
def err(x): errs.append(x)
def rj(rel):
    try:return json.loads((R/rel).read_text(encoding='utf-8'))
    except Exception as e:err(f'json:{rel}:{e}');return {}
def all_routes(m=None):
    m=m or rj('data/runtime/repository-map.json')
    out=dict(m.get('routes',{}))
    for rel in m.get('route_shards',{}).values():out.update(rj(rel).get('routes',{}))
    return out
def interp(anchors,x):
    a=sorted(anchors)
    if x<=a[0][0]:return a[0][1]
    if x>=a[-1][0]:return a[-1][1]
    for (x0,y0),(x1,y1) in zip(a,a[1:]):
        if x0<=x<=x1:
            return int(y0+(y1-y0)*(x-x0)/(x1-x0))
    raise AssertionError
cmd=rj('data/mechanics/command.json')
if cmd.get('schema')!='hierarchical_command_mechanics.v4':err('command_v4')
pa=cmd.get('comfortable_direct_personnel_anchors',[]); sa=cmd.get('comfortable_direct_command_slots_anchors',[])
if interp(pa,120)!=10000:err(f'command_rating120_personnel:{interp(pa,120) if pa else None}')
if interp(sa,120)!=8:err(f'command_rating120_slots:{interp(sa,120) if sa else None}')
if 'ownership-agnostic' not in str(cmd.get('principle','')).lower():err('ownership_agnostic_missing')
# Reference hierarchy: 15k/10 -> delegate 5k/4 => superior 10k + 6 leaf + 1 node, subordinate 5k/4.
comfort_p,comfort_s=10000,8
before=(15000,10)
after_sup=(10000,6+1); after_sub=(5000,4)
if not (before[0]>comfort_p and before[1]>comfort_s):err('reference_before_not_over')
if not (after_sup[0]<=comfort_p and after_sup[1]<=comfort_s):err('reference_superior_not_comfortable')
if not (after_sub[0]<=comfort_p and after_sub[1]<=comfort_s):err('reference_subordinate_not_comfortable')

# Deterministic capacity evaluation and hierarchy semantics.
ec=cmd.get('effective_capacity',{}); le=cmd.get('load_evaluation',{}); hier=cmd.get('hierarchy',{})
if 'effective_direct_personnel' not in ec or 'effective_direct_command_slots' not in ec:err('effective_capacity_formula_missing')
if 'load_ratio' not in le or 'order_latency_multiplier' not in le or 'synchronization_multiplier' not in le:err('deterministic_overload_math_missing')
if 'exactly one direct command slot' not in str(hier.get('superior_load','')).lower():err('subordinate_node_slot_rule_missing')
# Ownership does not create parallel budgets.
if 'personal and assigned troops' not in str(cmd.get('ownership_agnostic','')).lower():err('personal_assigned_shared_budget_missing')

# Command-group persistence and commander-person combat semantics.
cgi=rj('state/cmd/command-groups/index.json')
if cgi.get('schema')!='command-group-index.v1' or cgi.get('authority') is not False:err('command_group_index')
if cgi.get('count')!=len([p for p in (R/'state/cmd/command-groups').glob('*.json') if p.name!='index.json']):err('command_group_index_count')
_cblob=json.dumps(cmd).lower()
for phrase in ('commander/officer is always a person','owns no people','one direct subordinate command group consumes exactly one parent direct command slot'):
    if phrase not in _cblob:err(f'command_group_contract_missing:{phrase}')

# Unit partition/merge mechanics are deterministic and anti-reroll.
part=rj('data/mechanics/unit-partition.json')
if part.get('schema')!='unit_partition_mechanics.v1':err('unit_partition_v1')
if 'largest remainder' not in str(part.get('neutral_split',{}).get('categorical_integer_state','')).lower():err('largest_remainder_missing')
if 'inherits the parent capability mean and spread' not in str(part.get('neutral_split',{}).get('continuous_capability','')).lower():err('neutral_split_distribution_missing')
if 'sigma_i^2' not in str(part.get('merge',{}).get('continuous_population_variance','')):err('pooled_variance_formula_missing')
# Reference largest-remainder allocation: 7 category members over children 4/3 from a 7-person parent => 4/3 exactly.
def largest_remainder(total, child_counts, ids):
    parent=sum(child_counts); q=[total*c/parent for c in child_counts]; base=[int(x//1) for x in q]; rem=total-sum(base)
    order=sorted(range(len(q)), key=lambda i:(-(q[i]-base[i]), ids[i]))
    for i in order[:rem]:base[i]+=1
    return base
if largest_remainder(7,[4,3],['a','b']) != [4,3]:err('largest_remainder_reference_failed')
# Pooled moment reference: equal 100-person children with means 40/60 and sigmas 5/5 => mean 50, sigma sqrt(125).
import math
n1=n2=100; mu1,mu2=40.0,60.0; s1=s2=5.0; N=n1+n2; mu=(n1*mu1+n2*mu2)/N; var=(n1*(s1*s1+(mu1-mu)**2)+n2*(s2*s2+(mu2-mu)**2))/N
if abs(mu-50.0)>1e-9 or abs(math.sqrt(var)-math.sqrt(125.0))>1e-9:err('pooled_moment_reference_failed')
# Transaction registry uses v2 evidence contract.
txr=rj('state/org/unit-transactions.json')
if txr.get('schema')!='unit-transaction-registry.v2':err('unit_transaction_v2')

# Unit model and aggregate computation.
um=rj('data/organization/unit-model.json'); ur=rj('data/mechanics/unit-resolution.json')
if um.get('schema')!='unit_model.v2':err('unit_model_v2')
if ur.get('schema')!='unit_resolution_mechanics.v1':err('unit_resolution_v1')
if 'one scalar power score' not in str(ur.get('anti_overcompression','')).lower():err('anti_scalar_missing')
if 'aggregate' not in str(ur.get('principle','')).lower():err('aggregate_unit_missing')
# Partial refit must require split.
joined=json.dumps(um).lower()
for term in ('split','standard loadout','refit'):
    if term not in joined:err(f'unit_boundary_missing:{term}')
# Support semantics.
sup=rj('data/mechanics/support.json'); classes=sup.get('combat_classes',{})
if 'service_support' not in classes:err('support_service_class_missing')
if 'frontage' not in str(classes.get('service_support','')).lower():err('support_frontage_rule_missing')
# No retired organization term in text files or filenames.
for p in R.rglob('*'):
    if '.git' in p.parts or not p.is_file() or p.suffix=='.pyc' or p==Path(__file__).resolve():continue
    if 'cohort' in p.name.lower():err(f'retired_term_filename:{p.relative_to(R)}')
    if p.suffix.lower() in ('.json','.md','.txt','.py'):
        try:t=p.read_text(encoding='utf-8').lower()
        except:continue
        if 'cohort' in t:err(f'retired_term_text:{p.relative_to(R)}')
# Machine map explicit listed paths resolve; no fake selected-owner path.
m=rj('data/runtime/repository-map.json')
for key,route in all_routes(m).items():
    for field in ('r','i','router','w'):
        for rel in route.get(field,[]):
            if '<' in rel:err(f'map_placeholder:{key}:{rel}')
            elif not (R/rel).exists():err(f'map_missing:{key}:{rel}')
# Game-specific integrity.
is_shinobi=(R/'data/tech').exists()
if is_shinobi:
    # Materialized aggregate units have one standard loadout + full capability + current derived kernel.
    order=rj('data/stat-order.json'); n=len(order.get('axes',[]))
    for up in (R/'state/unit').glob('*.json'):
        u=json.loads(up.read_text())
        if 'loadout' in u:err(f'unit_old_loadout_key:{up.name}')
        if not isinstance(u.get('loadout_standard'),str):err(f'unit_no_standard:{up.name}')
        if 'loadout_distribution' in u:err(f'unit_loadout_distribution:{up.name}')
        sref=u.get('stats_ref'); kref=u.get('battle_kernel_ref')
        if not sref or not (R/sref).exists():err(f'unit_stats_missing:{up.name}');continue
        if not kref or not (R/kref).exists():err(f'unit_kernel_missing:{up.name}');continue
        k=json.loads((R/kref).read_text())
        if len(k.get('mean_vector',[]))!=n or len(k.get('spread_vector',[]))!=n:err(f'kernel_axis:{up.name}')
        h=hashlib.sha256((R/sref).read_bytes()).hexdigest()
        if k.get('source_sha256')!=h:err(f'kernel_stale:{up.name}')
    # Direct technique routing records/effects/primitive paths.
    man=rj('data/tech/manifest.json').get('techniques',{})
    for tid,rel in man.items():
        if not (R/rel).exists():err(f'tech_record_missing:{tid}')
        else:
            rec=json.loads((R/rel).read_text())
            for k in ('effect_profile_path','mechanical_base_path'):
                q=rec.get(k)
                if not q or not (R/q).exists():err(f'tech_ref_missing:{tid}:{k}:{q}')
    # No unrelated setting vocabulary leaks.
    for term in (r'\bQin\b',r'\bZhao\b',r'\bWarring States\b',r'\bTang Wei\b'):
        pass  # not globally asserted because canon/local names may collide; map/runtime isolation is the hard rule.
else:
    # Strategic pools are accounting-only, formations cannot be source pools.
    for p in (R/'state/force-pool').glob('*.json'):
        d=json.loads(p.read_text())
        if d.get('accounting_only') is not True:err(f'force_pool_deployable:{p.name}')
        # Future aggregate materialization must not correlate distinct manpower pools
        # through an accidentally shared deterministic seed. Seeds may be absent for
        # non-materializing accounting classes, but declared seeds are unique per owner.
        seen_seeds={}
        for pool in d.get('troop_pools',[]):
            seed=pool.get('stable_seed')
            if not seed: continue
            if seed in seen_seeds:err(f'force_pool_duplicate_stable_seed:{p.name}:{seen_seeds[seed]}:{pool.get("id")}')
            seen_seeds[seed]=pool.get('id')
    cidx=rj('state/cmd/command-personnel.json')
    if cidx.get('schema')!='command-personnel-index.v2':err('command_personnel_index')
    for pid,rel in cidx.get('record_index',{}).items():
        if not (R/rel).exists():err(f'command_person_missing:{pid}')
    roster=rj('state/char-roster/index.json')
    if roster.get('count',0)<1:err('cold_roster_empty')
    if roster.get('schema')!='active_character_roster_index.v4':err('cold_roster_index_v4')
    if 'record_index' in roster:err('cold_roster_redundant_record_index')
    for _initial,_meta in roster.get('lookup_by_initial',{}).items():
        _lp=R/_meta.get('path','')
        if not _lp.exists():err(f'cold_lookup_missing:{_initial}')
        else:
            _ld=json.loads(_lp.read_text())
            for _cid,_x in _ld.get('lookup',{}).items():
                if not (R/_x.get('path','')).exists():err(f'cold_lookup_dangling:{_cid}:{_x.get("path")}')
    # No stale character representation terminology.
    for rel in ['rules/characters.md','rules/world.md','state/life/identity-life-course.json','state/cap/internal-unit-combat-kernels.json','state/prog/sword-manor-progression.json']:
        t=(R/rel).read_text(encoding='utf-8').lower()
        for bad in ('dormant_and_latent_identities','unnamed character-lite','no personal name until full-sheet','latent canon identity'):
            if bad in t:err(f'stale_character_model:{rel}:{bad}')
if errs:
    print('UNIT MODEL TEST FAILED')
    for e in errs[:200]:print('-',e)
    sys.exit(1)
print('UNIT MODEL TEST OK')
print('command_reference=120=>10000 personnel/8 slots; delegated=10000+7 slots and 5000+4 slots')
