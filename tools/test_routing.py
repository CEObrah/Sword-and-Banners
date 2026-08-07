from pathlib import Path
import json,glob,sys,re
R=Path(__file__).resolve().parents[1]
GAME='sword' if (R/'state/char-roster').exists() else 'shinobi'
errs=[]
def err(x): errs.append(x)
def rj(rel):
    try:return json.loads((R/rel).read_text(encoding='utf-8'))
    except Exception as e:err(f'json:{rel}:{e}');return {}

m=rj('data/runtime/repository-map.json')
# Hot startup contract exists exactly as declared.
for rel in m.get('hot',[]):
    if not (R/rel).exists():err(f'hot_missing:{rel}')
# Route shards and route_index must agree.
all_routes=dict(m.get('routes',{})); shard_routes={}
for shard,rel in m.get('route_shards',{}).items():
    if not (R/rel).exists():err(f'route_shard_missing:{shard}:{rel}');continue
    d=rj(rel); rs=d.get('routes',{}); shard_routes[shard]=rs; all_routes.update(rs)
for name,shard in m.get('route_index',{}).items():
    if shard not in shard_routes:err(f'route_index_unknown_shard:{name}:{shard}')
    elif name not in shard_routes[shard]:err(f'route_index_route_missing_from_shard:{name}:{shard}')
# Direct route references must exist. Globs are allowed to be empty only for on-demand state.
for name,spec in all_routes.items():
    if not isinstance(spec,dict):continue
    for key in ('r','w','i'):
        for rel in spec.get(key,[]) or []:
            if not (R/rel).exists():err(f'route_ref_missing:{name}:{key}:{rel}')
    for pat in spec.get('g',[]) or []:
        parent=pat.split('*',1)[0].rstrip('/')
        pp=R/parent
        if parent and not pp.exists() and not pp.parent.exists():err(f'route_glob_parent_missing:{name}:{pat}')
# Rule router refs must exist.
rr=rj('data/runtime/rule-router.json')
for dom,refs in rr.get('domains',{}).items():
    if not isinstance(refs,list):err(f'rule_domain_not_list:{dom}');continue
    for rel in refs:
        if not (R/rel).exists():err(f'rule_ref_missing:{dom}:{rel}')
# Structural indexes and every system contract target must exist.
for rel in ('data/runtime/template-index.json','data/runtime/system-contract-index.json','data/runtime/narration-router.json'):
    if not (R/rel).exists():err(f'router_support_missing:{rel}')
sc=rj('data/runtime/system-contract-index.json')
for sid,rel in sc.get('systems',{}).items():
    if not (R/rel).exists():err(f'system_contract_missing:{sid}:{rel}')
# Human map must be an operating cookbook, not only a directory list.
h=(R/'REPOSITORY_MAP.md').read_text(encoding='utf-8')
for phrase in ('Minimum-context routes','Structural write contract','Common update matrix','Updating a unit','Updating an NPC','Large battle workflow'):
    if phrase.lower() not in h.lower():err(f'human_map_missing:{phrase}')
for phrase in ('template-index.json','system-contract-index.json','authority first','validator'):
    if phrase.lower() not in h.lower():err(f'human_map_write_contract_missing:{phrase}')
# Family direct kinship and behavior-depth routing should be discoverable.
for route in ('family_kinship','character_behavior'):
    if route not in all_routes:err(f'important_route_missing:{route}')
# Game isolation: routing/runtime docs may not teach the other game's vocabulary/representation.
texts=[]
for rel in ('RUNTIME.md','VOICE.md','REPOSITORY_MAP.md','PLAYER_INTERFACE.md','data/runtime/repository-map.json','data/runtime/rule-router.json'):
    texts.append((rel,(R/rel).read_text(encoding='utf-8').lower()))
if GAME=='sword':
    banned=('shinobi','konoha','anbu','chakra','jutsu')
else:
    banned=('qin infantry','zhao army','household champion unit','sword and banners')
for rel,t in texts:
    for b in banned:
        if b in t:err(f'cross_game_routing_leak:{rel}:{b}')
if errs:
    print('ROUTING CONTRACT FAIL',len(errs));print('\n'.join('- '+x for x in errs));sys.exit(1)
print(f'ROUTING CONTRACT OK game={GAME} routes={len(all_routes)} rule_domains={len(rr.get("domains",{}))} systems={len(sc.get("systems",{}))}')
