#!/usr/bin/env python3
from __future__ import annotations
import json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime'))
from sword_runtime.engine import COMMAND_TYPES
from sword_runtime.sim.calendar import CampaignTime
from jsonschema import validators as jsonschema_validators

checks=[]
def check(name,fn):
    try:
        detail=fn(); checks.append((name,True,'' if detail is None else str(detail)))
    except Exception as e: checks.append((name,False,f'{type(e).__name__}: {e}'))
def j(path): return json.load(open(ROOT/path))
def ok(v,msg='failed'): assert v,msg; return None

check('architecture_roots',lambda: ok(all((ROOT/x).is_dir() for x in ('runtime','game','state'))))
check('cross_game_runtime_separation',lambda: ok(not re.search(r'(^|\n)\s*(from|import)\s+shinobi', '\n'.join(p.read_text(errors='ignore') for p in (ROOT/'runtime/sword_runtime').rglob('*.py')), re.I)))
check('registered_top_level_schemas',lambda: (lambda reg: ok(all(not isinstance(d:=json.load(open(p)),dict) or not isinstance(d.get('schema'),str) or d['schema'] in reg for p in list((ROOT/'state').rglob('*.json'))+list((ROOT/'game').rglob('*.json'))))) (j('game/schemas/registry.json')))
check('unique_mutable_authority',lambda: (lambda owners: ok(len(owners)==len(set(owners)) and all((ROOT/p).is_file() for p in owners.values())))(j('state/index/owner-index-gold.json')['owners']))
def active_owner_routing():
    owners=j('state/index/owner-index-gold.json')['owners']
    for p in (ROOT/'state').rglob('*.json'):
        d=json.load(open(p))
        if isinstance(d,dict) and isinstance(d.get('owner_id'),str): ok(owners.get(d['owner_id'])==p.relative_to(ROOT).as_posix(),f"unrouted active owner {d['owner_id']}")
check('all_active_owner_ids_routed',active_owner_routing)
check('single_relationship_authority',lambda: ok((ROOT/'state/relationships-gold.json').is_file() and not (ROOT/'state/rel').exists() and (ROOT/'archive/legacy-execution/relationships-pre-gold').is_dir()))
check('retired_execution_paths',lambda: ok(all(not (ROOT/p).exists() for p in ('state/process-state','state/unit','state/force-pool','game/data/runtime')) and (ROOT/'archive/legacy-execution').is_dir()))
check('current_only_runtime_router',lambda: ok(set(j('runtime/contracts/repository-map.json'))=={'runtime_authority','game_authority','campaign_authority','transaction_entrypoint','scheduler_owner','owner_index','player_interface','ordinary_gameplay_mutation','legacy_execution_authority'}))
check('unversioned_gameplay_tree',lambda: ok(not re.search(r'\bversion\b|\bv[0-9]+\b|release[- ]history', (ROOT/'game/rules/process.md').read_text(), re.I)))
check('semantic_command_surface',lambda: ok(len(COMMAND_TYPES)>=45 and set(j('game/data/mechanics/command-catalog.json')['commands'])==set(COMMAND_TYPES)))

def safe_horizon():
    rt=j('state/runtime.json')
    for h in rt['hosts'].values():
        if h.get('next_due'):
            ok(CampaignTime.parse(h['resolved_through'])<=CampaignTime.parse(h['safe_through'])<CampaignTime.parse(h['next_due']))
check('scheduler_safe_horizons',safe_horizon)
check('zero_global_polling',lambda: ok(all(j('state/runtime.json')['metrics'][k]==0 for k in ('global_person_scans','global_faction_scans','global_force_scans','global_house_scans'))))
check('autonomous_actor_coverage',lambda: (lambda rt: ok(sum(1 for h in rt['hosts'].values() if h['kind']=='state')==7 and sum(1 for h in rt['hosts'].values() if h['kind']=='house')>=10 and sum(1 for h in rt['hosts'].values() if h['kind']=='institution')>=42 and sum(1 for h in rt['hosts'].values() if h['kind']=='faction')>=15))(j('state/runtime.json')))
check('mercenary_causal_hosts',lambda: (lambda rt: ok(sum(1 for h in rt['hosts'].values() if h.get('kind')=='mercenary')==60 and sum(1 for h in rt['hosts'].values() if h.get('kind')=='person')>=70 and sum(1 for h in rt['hosts'].values() if h.get('kind')=='interstate')==1))(j('state/runtime.json')))
def active_mercenary_schema_integrity():
    registry=j('game/schemas/registry.json')
    compiled={}
    for p in (ROOT/'state/merc').rglob('*.json'):
        d=json.load(open(p)); schema_id=d.get('schema')
        ok(isinstance(schema_id,str) and schema_id in registry,f'unregistered mercenary schema in {p.relative_to(ROOT)}')
        if schema_id not in compiled:
            schema=j('game/schemas/'+registry[schema_id]); cls=jsonschema_validators.validator_for(schema); cls.check_schema(schema); compiled[schema_id]=cls(schema)
        errors=list(compiled[schema_id].iter_errors(d)); ok(not errors,f'{p.relative_to(ROOT)}: {errors[0].message if errors else "invalid"}')
check('active_mercenary_schema_integrity',active_mercenary_schema_integrity)
def rules_runtime_parity():
    parity=j('game/data/mechanics/rules-runtime-parity.json')
    entries=parity.get('entries',[])
    refs=[str(e.get('rule_ref')) for e in entries]
    actual={p.relative_to(ROOT).as_posix() for p in (ROOT/'game/rules').rglob('*.md')}
    ok(set(refs)==actual, f'parity coverage mismatch missing={sorted(actual-set(refs))} extra={sorted(set(refs)-actual)}')
    ok(len(refs)==len(set(refs)),'duplicate rule parity entries')
    engine=(ROOT/'runtime/sword_runtime/engine.py').read_text()
    development=(ROOT/'runtime/sword_runtime/development.py').read_text()
    host_kinds={str(h.get('kind')) for h in j('state/runtime.json')['hosts'].values()}
    for e in entries:
        status=str(e.get('implementation_status'))
        commands={str(x) for x in e.get('production_commands',[])}
        hooks=[str(x) for x in e.get('runtime_hooks',[])]
        hosts={str(x) for x in e.get('causal_host_kinds',[])}
        ok(commands<=set(COMMAND_TYPES),f"{e['rule_ref']} lists nonproduction commands {sorted(commands-set(COMMAND_TYPES))}")
        ok(hosts<=host_kinds,f"{e['rule_ref']} lists missing host kinds {sorted(hosts-host_kinds)}")
        for hook in hooks:
            token=hook.split('.')[-1]
            ok(token in engine or token in development,f"{e['rule_ref']} lists missing runtime hook {hook}")
        if status in {'live','mixed'}:
            ok(bool(commands or hooks or hosts),f"{e['rule_ref']} claims {status} without executable production hook")
        if status in {'mixed','descriptive','deferred'}:
            ok(bool(str(e.get('deferred_scope','')).strip()),f"{e['rule_ref']} {status} entry must state nonimplemented/descriptive scope")
check('rules_to_runtime_parity',rules_runtime_parity)

def exact_person_causal_hosts():
    owners=j('state/index/owner-index-gold.json')['owners']
    chars={ref for ref in owners if str(ref).startswith('char_')}
    hosted={str(h.get('owner_ref')) for h in j('state/runtime.json')['hosts'].values() if h.get('kind')=='person'}
    ok(chars<=hosted,f'exact people without person hosts: {sorted(chars-hosted)[:8]}')
check('exact_person_causal_hosts',exact_person_causal_hosts)

check('autonomous_interstate_history_loop',lambda: (lambda rt,cfg,idx: ok(sum(1 for h in rt['hosts'].values() if h.get('kind')=='interstate')==1 and bool(cfg.get('theaters')) and idx.get('interstate_warring_states')=='state/politics/interstate-history.json'))(j('state/runtime.json'),j('game/data/world/autonomous-theaters.json'),j('state/index/owner-index-gold.json')['owners']))

check('hostile_rules_parity_suite_mandatory',lambda: (lambda suite: ok('tests/runtime/test_rules_parity_adversarial.py' in suite))((ROOT/'tools/run_gold_suite.py').read_text()))
check('command_wide_hostile_matrix_mandatory',lambda: (lambda suite: ok('tests/runtime/test_hostile_command_matrix.py' in suite))((ROOT/'tools/run_gold_suite.py').read_text()))

check('server_owned_chronology_and_preview_security',lambda: (lambda src: ok('submitted_at must equal authoritative campaign world time' in src and 'contested outcomes are execute-only' in src.lower() and 'command.command_type' in src))((ROOT/'runtime/sword_runtime/engine.py').read_text()))

check('player_authority_is_capability_scoped',lambda: (lambda a: ok(a['actor_ref']=='char_tang_wei' and a.get('state_offices')==[] and all(r.get('authority_ref') not in {'state_qin','state_zhao','state_chu','state_wei','state_han','state_yan','state_qi'} for r in a.get('roles',[]))))(j('state/authority/char-tang-wei.json')))
def populations():
    for s in ('qin','zhao','chu','wei','han','yan','qi'):
        p=j(f'state/population/{s}.json'); ok(p['population_total']==sum(p['strata'].values()),s)
check('population_conservation',populations)
def forces():
    for s in ('qin','zhao','chu','wei','han','yan','qi'):
        f=j(f'state/forces/state-{s}.json'); n=sum(f['available_by_role'].values())+sum((v['personnel'] if isinstance(v,dict) else v) for v in f['allocated_to_formations'].values())+sum((v.get('personnel',1) if isinstance(v,dict) else v) for v in f['materialized_people'].values()); ok(n==f['headcount'],s)
check('force_conservation',forces)
def mounts():
    for s in ('qin','zhao','chu','wei','han','yan','qi'):
        m=j(f'state/mounts/{s}.json'); ok(sum(m['types'].values())==m['total'] and sum(m['health'].values())==m['total'],s)
check('mount_conservation',mounts)
check('champions_protection_doctrine',lambda: ok(all(j(f'state/formations/{n}.json')['doctrine_behavior']['primary_success_condition']=='Tang Wei returns alive' for n in ('tang-champions-first','tang-champions-second'))))
check('ownership_command_distinction',lambda: (lambda f: ok(f['owner_force_ref']=='force_house_tang' and 'command_authority' in f and f['administrative_owner']!=f['owner_force_ref']))(j('state/formations/tang-champions-first.json')))
check('formation_material_units_explicit',lambda: ok(all('equipment_units_by_role' in json.load(open(p)) and 'logistics' in json.load(open(p)) and 'mounts' in json.load(open(p)) for p in (ROOT/'state/formations').glob('*.json'))))
check('house_tang_single_treasury_authority',lambda: (lambda h,idx: ok('treasury_silver' not in h and h.get('treasury_ref')=='treasury_house_tang' and idx.get('treasury_house_tang')=='state/treasury/treasury-house-tang.json'))(j('state/houses/house_tang.json'),j('state/index/owner-index-gold.json')['owners']))
check('information_knowledge_boundary',lambda: ok('knowers' in j('game/schemas/sword-information.schema.json')['required']))
check('canon_future_not_predetermined',lambda: (lambda c: ok(c.get('future_commitments') in ([],None) and bool(c.get('conditional_future_pressures'))))(j('game/data/history/canon-background.json')))
check('world_density',lambda: ok(len(j('game/data/world/noble-houses.json')['houses'])>=40 and len(j('game/data/world/locations.json')['locations'])>=70 and len(j('game/data/world/routes.json')['routes'])>=50))
check('location_functionality',lambda: ok(any('supply' in x.get('functions',[]) for x in j('game/data/world/locations.json')['locations']) and any(x.get('flavor_only') for x in j('game/data/world/locations.json')['locations'])))
def routes():
    refs={x['ref'] for x in j('game/data/world/locations.json')['locations']}
    for r in j('game/data/world/routes.json')['routes']: ok(r['a'] in refs and r['b'] in refs and r['hours']>0)
check('route_integrity',routes)
check('economy_balance',lambda: (lambda e,t: ok(e['service_issue']['standard_service_kit_is_state_issue'] and float(e['wages']['professional_soldier_monthly_silver'])>float(e['wages']['unskilled_monthly_silver']) and e['prices_silver']['common_sword']<=2*float(e['wages']['professional_soldier_monthly_silver']) and t['stable_monthly_flows']['revenue_silver']>t['stable_monthly_flows']['expense_silver'] and t['silver']>=t['stable_monthly_flows']['expense_silver']*12))(j('game/data/mechanics/economy-gold.json'),j('state/treasury/treasury-house-tang.json')))
check('institution_functionality',lambda: ok(len(list((ROOT/'state/institutions').glob('*.json')))==42 and all('capacity' in json.load(open(p)) for p in (ROOT/'state/institutions').glob('*.json'))))
check('siege_fail_closed_authority',lambda: ok(j('game/data/world/fortification-profiles.json')['profiles'][0]['materialization_required'] is True and 'garrison_formation_refs' in j('game/schemas/sword-fortification.schema.json')['required']))
check('railway_service_readiness',lambda: ok((ROOT/'railway.json').is_file() and (ROOT/'runtime/sword_runtime/bootstrap.py').is_file() and (ROOT/'runtime/sword_runtime/api/mcp.py').is_file() and 'mcp==2.0.0' in (ROOT/'pyproject.toml').read_text() and 'from mcp.server import MCPServer' in (ROOT/'runtime/sword_runtime/api/mcp.py').read_text() and 'mcp.server.fastmcp' not in (ROOT/'runtime/sword_runtime/api/mcp.py').read_text()))
check('player_interface_semantic_only',lambda: ok('do not edit campaign json manually' in (ROOT/'PLAYER_INTERFACE.md').read_text().lower() and 'semantic command' in (ROOT/'PLAYER_INTERFACE.md').read_text().lower()))
check('git_campaign_canonical',lambda: ok((ROOT/'.git').is_dir() and 'state' in (ROOT/'RUNTIME.md').read_text() and 'Git' in (ROOT/'RUNTIME.md').read_text()))
check('gold_ci_release_gate',lambda: (lambda w: ok('tools/run_gold_suite.py' in w and 'tools/run_validators.py' not in w))((ROOT/'.github/workflows/audit.yml').read_text()))
check('wal_pending_only_hot_recovery',lambda: (lambda w,c: ok('recoverable_records' in w and 'pending_directory' in w and 'terminal_directory' in w and 'self.wal.recoverable_records()' in c))((ROOT/'runtime/sword_runtime/tx/wal.py').read_text(),(ROOT/'runtime/sword_runtime/tx/coordinator.py').read_text()))
check('gold_soak_is_mandatory',lambda: (lambda suite,gate: ok('tools/run_gold_soak_gate.py' in suite and 'TRANSACTIONS = 1000' in gate and "run_one('replay-a'" in gate and "run_one('replay-b'" in gate and 'final_root_hash' in gate and 'MAX_GROWTH_RATIO' in gate))((ROOT/'tools/run_gold_suite.py').read_text(),(ROOT/'tools/run_gold_soak_gate.py').read_text()))


check('no_shadow_legacy_indexes',lambda: ok(not (ROOT/'state/index/owners').exists() and not (ROOT/'state/index/owners.json').exists() and not (ROOT/'state/index/units.json').exists() and not (ROOT/'state/reg').exists() and not (ROOT/'state/org').exists() and not (ROOT/'state/train').exists()))
check('no_retired_process_refs',lambda: ok(not re.search(r'registry_processes#|state/(?:process-state|unit|force-pool|reg|org)/', '\n'.join(p.read_text(errors='ignore') for p in list((ROOT/'state').rglob('*.json'))+list((ROOT/'game').rglob('*.json'))), re.I)))
check('sword_only_schema_vocabulary',lambda: ok('\"shinobi\"' not in '\n'.join(p.read_text(errors='ignore').lower() for p in (ROOT/'game/schemas').glob('*.json'))))

failed=[x for x in checks if not x[1]]
for name,passed,detail in checks: print(('PASS' if passed else 'FAIL'),name,detail)
print(f'PRODUCTION AUDIT: {len(checks)-len(failed)}/{len(checks)} PASS')
if failed: raise SystemExit(1)
