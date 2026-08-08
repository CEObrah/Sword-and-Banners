#!/usr/bin/env python3
from __future__ import annotations
import json,re,sys
from pathlib import Path
try: import jsonschema
except Exception: jsonschema=None
ROOT=Path(__file__).resolve().parents[1]
errors=[]
def err(x):errors.append(x)
def rj(p):
 try:return json.loads(Path(p).read_text(encoding='utf-8'))
 except Exception as e:err(f'json:{Path(p).relative_to(ROOT)}:{e}');return None
def walk(x):
 if isinstance(x,dict):
  yield x
  for v in x.values():yield from walk(v)
 elif isinstance(x,list):
  for v in x:yield from walk(v)
for p in ROOT.rglob('*'):
 if '.git' in p.parts or not p.is_file():continue
 rel=p.relative_to(ROOT)
 if len(str(rel))>120:err(f'path_too_long:{rel}')
 if len(p.name)>64:err(f'filename_too_long:{rel}')
 if p.suffix=='.json':rj(p)
meta=rj(ROOT/'state/meta.json') or {}
if meta.get('schema')!='meta':err('meta_schema')
_version=(ROOT/'VERSION').read_text(encoding='utf-8').strip()
if meta.get('version')!=_version:err(f'meta_version:{meta.get("version")}!={_version}')
registry=rj(ROOT/'schemas/registry.json') or {}
for p in ROOT.rglob('*.json'):
 if 'schemas' in p.parts:continue
 d=rj(p)
 if d is None:continue
 for o in walk(d):
  s=o.get('schema') if isinstance(o,dict) else None
  if not isinstance(s,str):continue
  target=registry.get(s)
  if not target:err(f'unmapped_schema:{s}:{p.relative_to(ROOT)}');continue
  if jsonschema:
   spec=rj(ROOT/'schemas'/target)
   if spec:
    try:jsonschema.validate(o,spec)
    except Exception as e:err(f'schema:{s}:{p.relative_to(ROOT)}:{getattr(e,"message",e)}')
# people
people=[ROOT/'state/player.json']+list((ROOT/'state/char').glob('*.json'))+list((ROOT/'state/person').rglob('*.json'))
for p in people:
 d=rj(p) or {}
 for k in ('age','age_current','age_at_anchor'):
  if k in d:err(f'age_cache_present:{p.relative_to(ROOT)}:{k}')
 if not d.get('birth_date'):err(f'missing_birth:{p.relative_to(ROOT)}')
 b=d.get('body')
 if not isinstance(b,dict):err(f'missing_body:{p.relative_to(ROOT)}');continue
 for k in ('adult_height_cm','growth_end_age','current_weight_kg','frame'):
  if b.get(k) is None:err(f'missing_body_field:{p.relative_to(ROOT)}:{k}')
 if b.get('growth_end_age')!=18:err(f'growth_end_not_18:{p.relative_to(ROOT)}')
 if not (0<=d.get('appearance',-1)<=100):err(f'appearance:{p.relative_to(ROOT)}')
# Age is derived from birth_date + current meta time; standard audit does not lock release-opening ages/heights.
# named characters preserved
for rel in ['state/char/tang-zhu.json','state/char/tang-ling.json','state/char/tang-kai.json','state/char/wei-jian.json','state/char/duan-jin.json','state/char/shen-rui.json']:
 if not (ROOT/rel).exists():err(f'missing_named_house_character:{rel}')
# Personal force membership is mutable; validate current references and uniqueness only.
pf=rj(ROOT/'state/pforce/wei.json') or {}; members=pf.get('members',[])
if len(members)!=len(set(members)):err('personal_force_duplicate_member')
known=set()
for p in [ROOT/'state/player.json']+list((ROOT/'state/char').glob('*.json'))+list((ROOT/'state/person').rglob('*.json')):
 d=rj(p) or {}; oid=d.get('owner_id') or d.get('id');
 if oid:known.add(oid)
for m in members:
 if m not in known:err(f'personal_force_missing_person:{m}')
def _sharded_registry(_index_rel,_field):
 _idx=rj(ROOT/_index_rel) or {}; _out={}
 if isinstance(_idx.get(_field),dict):_out.update(_idx.get(_field,{}))
 for _sh in _idx.get('shards',[]):
  _path=_sh.get('path') if isinstance(_sh,dict) else _sh
  if _path:_out.update((rj(ROOT/_path) or {}).get(_field,{}))
 if _field=='loadouts' and isinstance(_idx.get('ids'),list) and _idx.get('path_template'):
  for _id in _idx['ids']:
   _path=_idx['path_template'].replace('{loadout_id}',_id)
   _d=rj(ROOT/_path) or {}
   if isinstance(_d.get('loadout'),dict):_out[_id]=_d['loadout']
 for _id,_path in _idx.get('record_index',{}).items():
  _d=rj(ROOT/_path) or {}
  if _field=='loadouts' and isinstance(_d.get('loadout'),dict):_out[_id]=_d['loadout']
  elif _field=='items' and isinstance(_d.get('item'),dict):_out[_id]=_d['item']
 return _out
def command_people():
 _idx=rj(ROOT/'state/cmd/command-personnel.json') or {}; _out=[]
 if isinstance(_idx.get('personnel'),list): return _idx.get('personnel',[])
 for _pid,_rel in _idx.get('record_index',{}).items():
  _d=rj(ROOT/_rel) or {}; _c=dict(_d.get('command',{})); _c['id']=_d.get('id'); _c['person_id']=_d.get('person_id') or _pid; _out.append(_c)
 return _out
# item/loadout registry
items=_sharded_registry('data/items.json','items'); loads=_sharded_registry('data/loadouts.json','loadouts')
def resolve(lid,seen=None):
 seen=seen or set()
 if lid in seen:err(f'loadout_cycle:{lid}');return
 if lid not in loads:err(f'undefined_loadout:{lid}');return
 seen.add(lid); l=loads[lid]
 if l.get('inherits'):resolve(l['inherits'],seen)
 for k,v in l.items():
  if isinstance(v,str) and v.startswith(('weapon_','armor_','helmet_','shield_','ammo_','horse_','tack_','quiver_','item_','tool_')) and v not in items:err(f'loadout_item_missing:{lid}:{v}')
for lid in loads:resolve(lid)
mechanic={'base_force_cut','base_force_thrust','reach_m','mass_kg','protection','integrity_max'}
for p in (ROOT/'state').rglob('*.json'):
 d=rj(p)
 if d is None:continue
 for o in walk(d):
  for k in ('equipment_loadout_id','equipment_standard','loadout'):
   v=o.get(k) if isinstance(o,dict) else None
   if isinstance(v,str) and v not in loads:err(f'state_undefined_loadout:{p.relative_to(ROOT)}:{v}')
  if not isinstance(o,dict):continue
  iid=o.get('item_id') or o.get('item_profile_id')
  if iid:
   if iid not in items:err(f'state_item_missing:{p.relative_to(ROOT)}:{iid}')
   if mechanic.intersection(o.keys()):err(f'local_item_mechanics:{p.relative_to(ROOT)}:{iid}')
# body distributions for mass formations/units where added/appropriate
for p in (ROOT/'state/form').glob('*.json'):
 d=rj(p) or {}
 if any(k in d for k in ('personnel','headcount','count')) and 'body_distribution' not in d:err(f'formation_missing_body_distribution:{p.name}')
 for c in d.get('troop_pools',[]) if isinstance(d.get('troop_pools'),list) else []:
  if 'body_distribution' not in c:err(f'unit_missing_body_distribution:{p.name}:{c.get("unit_id")}')
# Temporal frontier
def tkey(s):
 m=re.match(r'(\d+)-BCE-(\d+)-(\d+)T(\d+):(\d+):(\d+)',s or '')
 if not m:return None
 y,mo,da,h,mi,se=map(int,m.groups());return (-y,mo,da,h,mi,se)
front=rj(ROOT/'state/time/frontier.json') or {}; world=tkey(meta.get('time')); covered=set()
_covreq=rj(ROOT/'data/runtime/coverage-requirements.json') or {}
def _process_coverage(_p):
 _cov=list(_p.get('coverage',[]))
 _ref=_p.get('coverage_ref')
 if _ref:
  _d=rj(ROOT/_ref) or {}
  if _d.get('process_id')!=_p.get('id'):err(f'process_coverage_ref_mismatch:{_p.get("id")}:{_ref}')
  _cov=list(_d.get('owner_ids',[]))
 return _cov
for p in front.get('processes',[]):
 covered.update(_process_coverage(p))
 if p.get('status')=='active' and p.get('settlement_mode')!='triggered':
  nd=tkey(p.get('next_due'))
  if not nd or not world or nd<=world:err(f'overdue_or_missing_next_due:{p.get("id")}:{p.get("next_due")}')
for oid in _covreq.get('required_owner_ids',[]):
 if oid not in covered:err(f'uncovered_owner:{oid}')
# issued vs personal assignments
for p in (ROOT/'state').rglob('*.json'):
 d=rj(p)
 if not isinstance(d,dict):continue
 if d.get('kind')=='command_assignment' and d.get('representation_rule')!='source_retained':err(f'issued_troop_representation:{d.get("id")}')
# true calendar-quarter rule
q=[p for p in front.get('processes',[]) if p.get('id')=='process_house_tang_development_aggregate']
if not q or q[0].get('recurrence',{}).get('kind')!='calendar_quarter_end' or q[0].get('next_due')!='244-BCE-03-31T23:59:00+08:00':err('quarter_boundary_drift')
if (ROOT/'state/schedule').exists():err('duplicate_schedule_layer_reintroduced')
pr=rj(ROOT/'state/reg/registry-processes.json') or {}
for pid,rec in pr.get('processes',{}).items():
 if isinstance(rec,dict) and 'runtime' in rec:err(f'process_registry_runtime_cache:{pid}')

# Dedicated reputation authority.
_repidx=rj(ROOT/'state/reputation/index.json') or {}
if _repidx.get('schema')!='reputation-index.v1' or _repidx.get('authority') is not False:err('reputation_index_invalid')
_reps=list((ROOT/'state/reputation/subjects').glob('*.json'))
if len(_reps)!=_repidx.get('subject_count'):err(f'reputation_subject_count:{len(_reps)}:{_repidx.get("subject_count")}')
for _p in _reps:
 _d=rj(_p) or {}
 if _d.get('schema')!='reputation-subject.v1' or _d.get('authority') is not True:err(f'reputation_subject_invalid:{_p.name}')
 for _aud,_ref in _d.get('audience_profiles',{}).items():
  if not (ROOT/_ref).exists():err(f'reputation_audience_missing:{_p.name}:{_aud}:{_ref}')
if not (ROOT/'data/mechanics/reputation.json').exists():err('reputation_mechanics_missing')

# owner index
ind=rj(ROOT/'state/index/owners.json') or {}
if ind.get('schema')!='owner_index':err('owner_index_schema')
if ind.get('authority') is not False:err('index_must_be_non_authoritative')
_owner_total=0
for _prefix,_shrel in ind.get('prefix_index',{}).items():
 _sh=rj(ROOT/_shrel) or {}
 if _sh.get('prefix')!=_prefix or _sh.get('authority') is not False:err(f'owner_index_shard_header:{_prefix}')
 for oid,rel in _sh.get('owners',{}).items():
  _owner_total+=1
  if not (ROOT/rel).exists():err(f'index_missing_file:{oid}:{rel}')
if _owner_total!=ind.get('owner_count'):err(f'owner_index_count:{_owner_total}:{ind.get("owner_count")}')
# Character, force, and development invariants
# aptitude and persistent exact-character depth
for pth in people:
 d=rj(pth) or {}; ap=d.get('aptitude')
 if not isinstance(ap,dict):err(f'missing_aptitude:{pth.relative_to(ROOT)}')
 else:
  for k in ('physical_learning','technical_learning','tactical_learning','academic_learning','social_learning'):
   if not isinstance(ap.get(k),(int,float)) or not 0<=ap.get(k)<=200:err(f'bad_aptitude:{pth.relative_to(ROOT)}:{k}')
for pth in (ROOT/'state/char').glob('*.json'):
 d=rj(pth) or {}
 if 'character_profile' in d:err(f'deprecated_character_profile:{pth.name}')
 if 'personality_signature' in d:err(f'deprecated_personality_signature:{pth.name}')
 for k in ('goal_state','background'):
  if not isinstance(d.get(k),dict):err(f'missing_{k}:{pth.name}')
 if not isinstance(d.get('knowledge_state'),dict) and not isinstance(d.get('knowledge_profile_ref'),str):err(f'missing_knowledge_authority:{pth.name}')
 if 'relationships' in d and not isinstance(d.get('relationships'),list):err(f'bad_relationships:{pth.name}')
 if isinstance(d.get('behavior'),dict):
  _ct=d['behavior'].get('core_traits')
  if _ct is not None and not isinstance(_ct,(list,str)):err(f'bad_behavior_traits:{pth.name}')
# Tang family aptitude deliberately extraordinary
for rel in ('state/player.json','state/char/tang-zhu.json','state/char/tang-ling.json','state/char/tang-kai.json'):
 d=rj(ROOT/rel) or {}; ap=d.get('aptitude',{})
 if min(ap.get('physical_learning',0),ap.get('technical_learning',0),ap.get('tactical_learning',0))<180:err(f'tang_family_aptitude:{rel}')
# Current Household Champions must satisfy the role standard; their count is mutable through legal play.
champ=list((ROOT/'state/person/wei').glob('*.json'))
_role_profiles=(rj(ROOT/'data/people/role-profiles.json') or {}).get('profiles',{})
for pth in champ:
 d=rj(pth) or {}
 if d.get('rank')!='household_champion':continue
 _prof=_role_profiles.get(d.get('role_profile_ref'),{})
 _role=d.get('role',_prof.get('role'))
 _load=d.get('equipment_standard',_prof.get('equipment_standard'))
 _mount=d.get('mount',_prof.get('mount'))
 _loyal=d.get('loyalty',_prof.get('loyalty'))
 if _role!='guardian_cavalry':err(f'household_champion_role:{pth.name}')
 if _load!='loadout_house_guardian_cavalry':err(f'household_champion_loadout:{pth.name}')
 if _mount!='horse_tang_heavy_war':err(f'household_champion_mount:{pth.name}')
 if _loyal!='lifetime_vow':err(f'household_champion_loyalty:{pth.name}')
 if d.get('role_profile_ref')!='role.household_champion.guardian_cavalry':err(f'household_champion_role_profile:{pth.name}')
 s=d.get('stats',{}).get('skills',{})
 for k,v in {'Sword':150,'Spear':155,'Bow':150,'Shield':150,'Defense':160,'Riding':160,'Formation Fighting':155}.items():
  if s.get(k,0)<v:err(f'household_champion_skill:{pth.name}:{k}')
# Institutions and independent forces validate their CURRENT internal conservation, never release-opening totals.
for pth in (ROOT/'state/inst').glob('school-*.json'):
 d=rj(pth) or {}
 if sum(c.get('count',0) for c in d.get('troop_pools',[]))!=d.get('direct_members'):err(f'school_conservation:{pth.name}')
 if d.get('direct_members',0)<0 or d.get('affiliate_network_members',0)<0:err(f'school_negative_members:{pth.name}')
for pth in (ROOT/'state/inst').glob('escort-*.json'):
 d=rj(pth) or {}; total=sum(c.get('count',0) for c in d.get('troop_pools',[]))
 if d.get('direct_members')!=total:err(f'escort_conservation:{pth.name}')
 if d.get('support_members',0)<0 or d.get('armed_members',0)<0 or d.get('support_members',0)+d.get('armed_members',0)!=total:err(f'escort_armed_support_conservation:{pth.name}')
regi=rj(ROOT/'state/inst/regional-kernels.json') or {}
for x in regi.get('institutions',[]):
 if x.get('name','').startswith('Regional '):err(f'regional_placeholder_name:{x.get("id")}')
 if x.get('armed_members',0)+x.get('support_members',0)!=x.get('members',0):err(f'regional_membership_conservation:{x.get("id")}')
 if x.get('field_ready_members',0)>x.get('armed_members',0):err(f'regional_field_ready_over_armed:{x.get("id")}')
 if x.get('elite_members',0)>x.get('field_ready_members',0):err(f'regional_elite_over_field:{x.get("id")}')
mount=rj(ROOT/'state/force/independent-mountain-units.json') or {}; yr=None
for x in mount.get('records',[]):
 if x.get('record_id')=='mountain_confederation_yotanwa':yr=x.get('facts',{})
if not yr:err('missing_yotanwa_force_record')
else:
 wc=yr.get('warrior_units',[]); sm=sum(x.get('count',0) for x in wc)
 if yr.get('armed_warriors')!=sm:err(f'yotanwa_current_conservation:{yr.get("armed_warriors")}:{sm}')
 if not yr.get('support_is_separate_from_armed_count'):err('yotanwa_support_separation_policy_missing')
ff=rj(ROOT/'state/force/frontier-forces.json') or {}
for _rec in ff.get('records',[]):
 _facts=_rec.get('facts',{})
 if isinstance(_facts.get('headcount'),(int,float)) and _facts.get('headcount')<0:err(f'negative_frontier_force:{_rec.get("record_id")}')
q=rj(ROOT/'state/force/quanrong.json') or {}
if q and q.get('armed_reservoir')!=sum(c.get('count',0) for c in q.get('troop_pools',[])):err('quanrong_current_conservation')
o=rj(ROOT/'state/force/ordo-army.json') or {}

# major mercs are no longer one generic unit; regional merc total preserved and sizes vary
# major mercs are no longer one generic unit; regional merc total preserved and sizes vary
for i in range(1,13):
 d=rj(ROOT/f'state/merc/major-{i:02d}.json') or {}
 if len(d.get('troop_pools',[]))<4:err(f'major_merc_blob:{i}')
 if sum(c.get('count',0) for c in d.get('troop_pools',[]))!=d.get('headcount'):err(f'major_merc_conservation:{i}')
rm=rj(ROOT/'state/merc/regional.json') or {}; cs=[rj(ROOT/e.get('path','')) or {} for e in rm.get('entries',[])]
if rm.get('armed_total')!=sum(x.get('count',0) for x in cs):err('regional_merc_current_conservation')
if len({x.get('count') for x in cs})<8:err('regional_merc_sizes_still_uniform')
if any(x.get('name','').startswith('Regional Company') for x in cs):err('regional_merc_names_still_placeholder')
# state quality pyramids conserve pool manpower
for st in ('qin','zhao','wei','chu','yan','qi','han'):
 d=rj(ROOT/f'state/force-pool/{st}.json') or {}; qd=d.get('quality_distribution',{})
 if sum(qd.values())!=d.get('headcount'):err(f'state_quality_conservation:{st}')
 if qd.get('elite',0)>=qd.get('veteran',0):err(f'state_elite_not_smaller:{st}')
# commander army registry exists and all commanders resolve to exact characters
ar=rj(ROOT/'state/cmd/army-registry.json') or {}; exact=set()
for pth in (ROOT/'state/char').glob('*.json'):
 d=rj(pth) or {}; exact.add(d.get('owner_id'))
for a in ar.get('armies',[]):
 if a.get('commander_id') not in exact:err(f'commander_army_missing_character:{a.get("id")}:{a.get("commander_id")}')


# Representation-neutral development model
_dev=rj(ROOT/'data/development/model.json') or {}
_eff=_dev.get('representation_efficiency',{})
if set(_eff.keys())!=set(('exact','individual_lite','unit')):err('development_representation_classes')
if any(v!=1.0 for v in _eff.values()):err(f'development_compression_bonus:{_eff}')
if not _dev.get('capacity_rules',{}).get('instructor_time_conserved'):err('development_instructor_capacity_not_conserved')
if not _dev.get('capacity_rules',{}).get('facility_capacity_conserved'):err('development_facility_capacity_not_conserved')
if _dev.get('promotion_rule',{}).get('mode')!='qualified_subset_transfer':err('development_promotion_mode')
if not _dev.get('batching_rule',{}).get('batch_equivalence_required'):err('development_batch_equivalence_missing')
_dt=rj(ROOT/'tests/development-fairness.json') or {}
if len(_dt.get('tests',[]))<6:err('development_fairness_regressions_missing')
# Seven States require explicit, distinct role-kernel identities
_ext=rj(ROOT/'state/reg/registry-external-capabilities.json') or {}; _ks={}
for _p in (ROOT/'state/reg/external-capabilities/records').glob('*.json'):
 _rd=rj(_p) or {}; _kid=_rd.get('kernel_id'); _kv=_rd.get('kernel')
 if _kid and isinstance(_kv,dict): _ks[_kid]=_kv
if _ext.get('schema')!='external-capability-registry.v40' or int(_ext.get('kernel_count',-1))!=len(_ks):err('external_capability_router_count')
_state_sig={}
for _st in ('QIN','ZHAO','WEI','CHU','YAN','QI','HAN'):
 _parts=[]
 for _kid,_k in sorted(_ks.items()):
  if _k.get('state')==_st:
   if not _k.get('identity_notes') or not _k.get('balance_adjustment'):err(f'missing_state_kernel_identity:{_kid}')
   _parts.append(json.dumps(_k.get('capabilities',{}),sort_keys=True))
 _state_sig[_st]='|'.join(_parts)
if len(set(_state_sig.values()))!=7:err('state_kernel_identities_not_distinct')
# Tang Wei's named personal retinue must not have an authoritative unit-mean combat kernel.
_cap=rj(ROOT/'state/cap/internal-unit-combat-kernels.json') or {}
if any(_r.get('record_id')=='unit_tang_wei_household_champions' for _r in _cap.get('records',[])):err('personal_lite_force_aggregate_kernel_forbidden')
_bal=rj(ROOT/'data/balance/state-military-identities.json') or {}
if len(_bal.get('states',{}))!=7:err('state_military_identity_registry')

# Cleanup and mechanical closure
if (ROOT/'schemas/compat').exists():err('compat_schema_directory_present')
for pth in (ROOT/'state').rglob('*.json'):
 d=rj(pth) or {}
 for o in walk(d):
  if isinstance(o,dict):
   for k in o:
    if k in ('legacy_owner_ids','legacy_size_preserved_not_template','migration_alias','migration_aliases','old_id','former_id'):err(f'obsolete_runtime_key:{pth.relative_to(ROOT)}:{k}')
# obsolete references must be gone
_bad=('GAME_RUNTIME.md','PROJECT_INSTRUCTIONS.md','state/campaign.json','state/active_scene.json','state/derived/owner_index.json','state/scheduler/events.json','06_DEVELOPMENT_AND_AGING.md','07_RECRUITMENT_SERVICE_AND_CAREERS.md','01_COMMANDS_ACTIONS_CONSENT_AND_NARRATION.md','09_PERSONAL_RANGED_MOUNTED_AND_HEROIC_COMBAT.md','10_FORMATION_COMBAT_AND_RESOLUTION_TABLES.md')
for pth in ROOT.rglob('*.md'):
 txt=pth.read_text(encoding='utf-8')
 for b in _bad:
  if b in txt:err(f'obsolete_rule_reference:{pth.relative_to(ROOT)}:{b}')
# all named exact characters have explicit legal loadouts
for pth in (ROOT/'state/char').glob('*.json'):
 d=rj(pth) or {}; lid=d.get('equipment_loadout_id')
 if not lid or lid not in loads:err(f'named_character_loadout_missing:{pth.name}:{lid}')
# escort loadouts are explicit
for pth in (ROOT/'state/inst').glob('escort-*.json'):
 d=rj(pth) or {}
 for c in d.get('troop_pools',[]):
  if c.get('loadout_id') not in loads:err(f'escort_loadout_missing:{pth.name}:{c.get("role")}')
if not (ROOT/'tests/mechanics-v38.json').exists():err('mechanics_regression_missing')
# Final mechanical-closure release gate
_required_mechanics=('body.json','career.json','combat.json','core.json','economy.json','formation.json','injury.json','logistics.json','memory.json','morale.json','narrative-recall.json','politics.json','settlement.json','siege.json','time.json','training.json')
_sreg=rj(ROOT/'schemas/registry.json') or {}
for _fn in _required_mechanics:
 _p=ROOT/'data/mechanics'/_fn
 if not _p.exists():err(f'missing_mechanics_authority:{_fn}');continue
 _d=rj(_p) or {}; _sid=_d.get('schema')
 if not _sid or _sid not in _sreg:err(f'unregistered_mechanics_schema:{_fn}:{_sid}')
if not (ROOT/'tests/invariants-v38.json').exists():err('current_invariants_missing')
_obsolete_inv=ROOT/'tests'/('v'+'36-invariants.json')
if _obsolete_inv.exists():err('obsolete_invariants_file_present')
# No release-history aliases/debris inside canonical gameplay data/rules/docs.
for _base in ('state','data','rules'):
 for _pth in (ROOT/_base).rglob('*'):
  if not _pth.is_file() or _pth.suffix not in ('.json','.md','.txt'):continue
  _text=_pth.read_text(encoding='utf-8')
  _forbidden=(['V3.'+x for x in ('5','6','7')]+['v'+x for x in ('35','36','37')]+['legacy '+'alias','migration '+'alias'])
  for _badword in _forbidden:
   if _badword in _text:err(f'canonical_history_debris:{_pth.relative_to(ROOT)}:{_badword}')
# Current champion files and Yotanwa force are evolution-safe; opening headcounts are not runtime invariants.


# Canonical runtime state must not carry OOC wishlists or redundant campaign-opening snapshots that duplicate current authority.
_forbidden_ooc_keys={'preferred_allocation_if_assets_are_recovered','desired_roster','wishlist','future_roster','player_preference','ooc_plan','desired_recruit','story_plan','possible_future_team','user_wants'}
_forbidden_ooc_values={'planned_player_objective_not_started','inactive_player_goal'}
_forbidden_opening_keys={'opening_tang_contract','opening_assigned_personnel','opening_occupancy','opening_claims'}
for _pth in (ROOT/'state').rglob('*.json'):
 _d=rj(_pth) or {}
 for _o in walk(_d):
  if not isinstance(_o,dict):continue
  if _forbidden_ooc_keys.intersection(_o):err(f'ooc_player_wishlist_state:{_pth.relative_to(ROOT)}')
  if any(v in _forbidden_ooc_values for v in _o.values() if isinstance(v,str)):err(f'ooc_player_wishlist_state:{_pth.relative_to(ROOT)}')
  if _forbidden_opening_keys.intersection(_o):err(f'redundant_opening_snapshot:{_pth.relative_to(ROOT)}:{sorted(_forbidden_opening_keys.intersection(_o))}')
# Living-world content, named officer representation, and runtime hardening
_fac=rj(ROOT/'state/reg/living-factions.json') or {}; _factions=[(rj(ROOT/_p) or {}).get('faction',{}) for _p in _fac.get('record_index',{}).values()] if _fac.get('record_index') else _fac.get('factions',[])
if len(_factions)<12:err(f'living_faction_count:{len(_factions)}')
for _f in _factions:
 if not _f.get('goals') or not _f.get('resources') or not _f.get('constraints'):err(f'thin_faction:{_f.get("id")}')
 if 'pursue goal with existing people/resources' in str(_f.get('current_plan','')):err(f'generic_faction_plan:{_f.get("id")}')
_ma=rj(ROOT/'data/content/mission-archetypes.json') or {}; _mt=_ma.get('archetypes',[])
_ea=rj(ROOT/'data/content/world-event-archetypes.json') or {}; _wa=_ea.get('archetypes',[])
if len(_mt)<20:err(f'mission_archetype_count:{len(_mt)}')
if len(_wa)<15:err(f'world_event_archetype_count:{len(_wa)}')
_cp=rj(ROOT/'state/contract/contracts-companions-projects.json') or {}
if 'mission_templates' in _cp:err('mission_templates_in_active_state')
_ev=rj(ROOT/'state/event/living-world-events.json') or {}
if _ev.get('events'):err('dormant_event_templates_in_active_state')
_sc=rj(ROOT/'state/scene.json') or {}
if 'action_packages' in _sc or 'decision_packages' in _sc:err('cached_scene_choices')
_cmd_people=command_people()
if len(_cmd_people)<40:err(f'command_personnel_count:{len(_cmd_people)}')
_seen_person=set(); _all_people_ids=set()
for _pth in people:
 _d=rj(_pth) or {}; _oid=_d.get('owner_id') or _d.get('id')
 if _oid:_all_people_ids.add(_oid)
for _u in _cmd_people:
 _pid=_u.get('person_id')
 if _pid not in _all_people_ids:err(f'command_person_missing_person:{_u.get("id")}:{_pid}')
 if _pid in _seen_person:err(f'duplicate_command_person:{_pid}')
 if not isinstance(_u.get('current_unit_ids'),list):err(f'command_person_bad_unit_links:{_pid}')
 _seen_person.add(_pid)
_mil_roles={'great_general','strategist_general','martial_general','general','young_commander','officer','irregular_general','mountain_ruler'}
for _pth in (ROOT/'state/char').glob('*.json'):
 _d=rj(_pth) or {}
 if _d.get('role_archetype') in _mil_roles and _d.get('owner_id') not in _seen_person:err(f'named_officer_missing_command_person:{_d.get("owner_id")}')
# Newly named staff are individually useful rather than generic placeholders.
for _pth in (ROOT/'state/person/staff').glob('*.json'):
 _d=rj(_pth) or {}
 if not _d.get('history',{}).get('service'):err(f'thin_staff_history:{_pth.name}')
 if 'build a record through actual service' in str(_d.get('current_goal','')):err(f'generic_staff_goal:{_pth.name}')
# Dormant event archetypes use causal wake-up, not monthly polling.
if (ROOT/'state/player.json').stat().st_size>6500:err('startup_player_bloat')
if (ROOT/'state/scene.json').stat().st_size>6000:err('startup_scene_bloat')
_voice=(ROOT/'VOICE.md').read_text(encoding='utf-8')
for _phrase in ('Repository memory is not player memory','estimated in-world','medium','long'):
 if _phrase not in _voice:err(f'narrator_contract_missing:{_phrase}')
# Autonomous-world contract linkage and evolution-safe current-authority checks.
_pc=rj(ROOT/'state/reg/registry-process-contracts.json') or {}
if _pc.get('schema')!='process-contract-registry':err('process_contract_registry_schema')
_pcrecs=list((ROOT/'state/reg/process-contracts').glob('*.json'))
if len(_pcrecs)!=_pc.get('record_count'):err(f'process_contract_count:{len(_pcrecs)}:{_pc.get("record_count")}')
for _pcr in _pcrecs:
 _prd=rj(_pcr) or {}
 if _prd.get('owner_id')!=_pcr.stem:err(f'process_contract_owner_path:{_pcr.name}:{_prd.get("owner_id")}')
 if not _prd.get('contract_id') or not _prd.get('domain') or not _prd.get('cadence'):err(f'process_contract_incomplete:{_pcr.name}')
_autoref=_pc.get('autonomous_world_contract')
if not _autoref or not (ROOT/_autoref).exists():err('process_autonomous_world_contract_missing')
# Command personnel store one current attachment, not repeated campaign-start prose or duplicate accounting rules.
for _u in command_people():
 if 'active_assignment' in _u:err(f'command_person_redundant_active_assignment:{_u.get("id")}')
 if 'personnel_count' in _u or 'unit_personnel_delta' in _u or 'embedded_in_unit' in _u:err(f'command_person_still_encoded_as_unit:{_u.get("id")}')
# Strategic macro state must reference exact mutable force/resource authorities rather than cache them.
_sm=rj(ROOT/'state/polity/external-state-macros.json') or {}
for _rec in _sm.get('records',[]):
 _facts=_rec.get('facts',{}) if isinstance(_rec,dict) else {}
 for _bad in ('grain_units','horse_units','military_total','field_pool','garrison_pool','reserve_pool'):
  if _bad in _facts:err(f'strategic_macro_duplicate_current_value:{_rec.get("record_id")}:{_bad}')
# Seven state depots must be structured current stock owners.
_dp=rj(ROOT/'state/market/regional-depots.json') or {}
_dep={x.get('record_id'):x for x in _dp.get('records',[]) if isinstance(x,dict)}
for _st in ('qin','zhao','chu','wei','han','yan','qi'):
 _r=_dep.get('state_depot_'+_st)
 if not _r:err(f'missing_structured_state_depot:{_st}');continue
 _f=_r.get('facts',{})
 for _k in ('grain_kg','fodder_kg','war_arrows','crossbow_bolts','timber_tonnes','iron_tonnes','medicine_lots','carts'):
  if not isinstance(_f.get(_k),(int,float)):err(f'state_depot_field_missing:{_st}:{_k}')
# Institution summaries point to appointment authority rather than copy current incumbents/staff.
_inst=rj(ROOT/'state/inst/institutions-and-households.json') or {}
_badinst={'heir','named_command_and_staff','owner_principal','commander','escort_captains','senior_instructors','master','named_department_processes'}
for _r in _inst.get('records',[]):
 if not isinstance(_r,dict):continue
 _hits=_badinst.intersection(_r.keys())
 if _hits:err(f'institution_duplicate_current_appointment:{_r.get("record_id")}:{sorted(_hits)}')
 _facts=_r.get('facts',{}) if isinstance(_r.get('facts'),dict) else {}
 _hits=_badinst.intersection(_facts.keys())
 if _hits:err(f'institution_duplicate_current_appointment:{_r.get("record_id")}:{sorted(_hits)}')

# Mutable process state is sharded; the orphan world-runtime monolith may not return.
if (ROOT/'state/runtime.json').exists():err('orphan_world_runtime_monolith_present')
_psi=rj(ROOT/'state/process-state/index.json') or {}; _preg=(rj(ROOT/'state/reg/registry-processes.json') or {}).get('processes',{})
_seen_ps=set()
for _e in _psi.get('entries',[]):
 _pid=_e.get('process_id'); _rel=_e.get('path'); _ps=rj(ROOT/_rel) or {}
 if _pid in _seen_ps:err(f'duplicate_process_state:{_pid}')
 _seen_ps.add(_pid)
 if _ps.get('process_id')!=_pid:err(f'process_state_id_mismatch:{_pid}:{_rel}')
 if _pid not in _preg:err(f'process_state_without_process_contract:{_pid}')

# Release-only opening metrics and duplicate scheduler layers may not reappear.
if (ROOT/'data/runtime/opening-metrics.json').exists():err('release_opening_metrics_in_runtime')
if (ROOT/'state/schedule').exists():err('duplicate_schedule_layer_present')
# OOC player wishlist keys/statuses are forbidden in canonical state.
_ooc_keys={'preferred_allocation_if_assets_are_recovered','desired_roster','planned_player_objective','player_wishlist','wishlist','future_roster','player_preference','ooc_plan','desired_recruit','story_plan','possible_future_team','user_wants'}
_ooc_vals={'planned_player_objective_not_started','inactive_player_goal'}
def _walk_ooc(_x):
 if isinstance(_x,dict):
  yield _x
  for _v in _x.values():yield from _walk_ooc(_v)
 elif isinstance(_x,list):
  for _v in _x:yield from _walk_ooc(_v)
for _pth in (ROOT/'state').rglob('*.json'):
 _dd=rj(_pth) or {}
 for _o in _walk_ooc(_dd):
  if _ooc_keys.intersection(_o):err(f'ooc_player_wishlist_state:{_pth.relative_to(ROOT)}')
  if any(_v in _ooc_vals for _v in _o.values() if isinstance(_v,str)):err(f'ooc_player_wishlist_state:{_pth.relative_to(ROOT)}')

# Release packaging provenance belongs outside the live gameplay tree.
if (ROOT/'data/provenance.json').exists():err('release_provenance_in_live_gameplay_tree')
if (ROOT/'schemas/release-provenance-v38.schema.json').exists():err('release_provenance_schema_in_live_gameplay_tree')


# Normalized character/interface/standing-order invariants.
_forbidden_maintenance_keys={'audit_notes','developer_notes','migration_notes','balance_notes','recalibration_notes','version_change_notes','release_notes','conversion_notes'}
for _pth in (ROOT/'state').rglob('*.json'):
 _d=rj(_pth) or {}
 for _o in walk(_d):
  if not isinstance(_o,dict):continue
  for _k in _forbidden_maintenance_keys:
   if _k in _o:err(f'maintenance_key_in_state:{_pth.relative_to(ROOT)}:{_k}')
  for _r in _o.get('relationships',[]) if isinstance(_o.get('relationships'),list) else []:
   if isinstance(_r,dict) and _r.get('source')=='simulation_fill_noncanonical_acquaintance':err(f'synthetic_acquaintance_in_state:{_pth.relative_to(ROOT)}')
_iface=(ROOT/'PLAYER_INTERFACE.md').read_text(encoding='utf-8') if (ROOT/'PLAYER_INTERFACE.md').exists() else ''
for _phrase in ('OOC:','No special gameplay command prefix is required.','FORM UNIT','FORMATION SETUP','CHECKPOINT'):
 if _phrase not in _iface:err(f'player_interface_missing:{_phrase}')
for _phrase in ('PRE'+'VIEW:','OR'+'DER:'):
 if _phrase in _iface:err(f'player_interface_obsolete_token:{_phrase}')
_so_text=(ROOT/'state/order/standing-orders.json').read_text(encoding='utf-8')
for _phrase in ('Project commands:','CONTINUE GAME','CHECKPOINT','Generated status cards'):
 if _phrase in _so_text:err(f'project_control_in_standing_orders:{_phrase}')
_chars_text=(ROOT/'rules/characters.md').read_text(encoding='utf-8')
if 'A character-lite owner is an unnamed exact person' in _chars_text:err('old_character_lite_contradiction')
if 'persistent named person' not in _chars_text:err('named_individual_lite_rule_missing')


# Central relationship and reusable knowledge reference integrity.
_relreg=rj(ROOT/'state/rel/relationships-knowledge.json') or {}
_reledges={}
for _rsh in (ROOT/'state/rel/relationship-edges').glob('*.json'):
 _rsd=rj(_rsh) or {}
 _src=_rsd.get('source_id')
 for _eid,_edge in _rsd.get('relationship_edges',{}).items():
  if _eid in _reledges:err(f'duplicate_relationship_edge:{_eid}')
  if _edge.get('source_id')!=_src:err(f'relationship_shard_wrong_source:{_rsh.name}:{_eid}')
  _reledges[_eid]=_edge
_ridx=rj(ROOT/'state/rel/relationship-edge-index.json') or {}
if _ridx.get('edge_count')!=len(_reledges):err(f'relationship_edge_count:{len(_reledges)}:{_ridx.get("edge_count")}')
for _eid,_path in _ridx.get('edge_index',{}).items():
 if _eid not in _reledges or not (ROOT/_path).exists():err(f'relationship_edge_index_dangling:{_eid}:{_path}')
_kprofiles=(rj(ROOT/'data/people/knowledge-profiles.json') or {}).get('profiles',{})
for _pth in (ROOT/'state/char').glob('*.json'):
 _d=rj(_pth) or {}
 if 'relationships' in _d:err(f'exact_relationships_not_centralized:{_pth.name}')
 for _ref in _d.get('relationship_refs',[]):
  _edge=_reledges.get(_ref)
  if not isinstance(_edge,dict):err(f'missing_relationship_ref:{_pth.name}:{_ref}')
  elif _edge.get('source_id')!=_d.get('owner_id'):err(f'relationship_ref_wrong_source:{_pth.name}:{_ref}')
 _kp=_d.get('knowledge_profile_ref')
 if _kp and _kp not in _kprofiles:err(f'missing_knowledge_profile:{_pth.name}:{_kp}')
for _eid,_edge in _reledges.items():
 if not isinstance(_edge,dict) or _edge.get('id')!=_eid:err(f'bad_relationship_edge_id:{_eid}')



# Sharded home-establishment loader
def home_records():
 idx=rj(ROOT/'state/org/home-establishments.json') or {}
 out=[]
 if isinstance(idx.get('records'),list): return idx.get('records',[])
 for _oid,_path in idx.get('record_index',{}).items():
  sh=rj(ROOT/_path) or {}; rec=sh.get('record')
  if isinstance(rec,dict):out.append(rec)
 if out:return out
 for ent in idx.get('entries',[]):
  sh=rj(ROOT/ent.get('path','')) or {}; rec=sh.get('record')
  if isinstance(rec,dict):out.append(rec)
 return out

# Home-establishment and return invariants
_hrs=home_records(); _he={'records':_hrs}
if len(_hrs)<35:err(f'home_establishment_count:{len(_hrs)}')
_howners={x.get('owner_id') for x in _hrs}
for _st in ('qin','zhao','chu','wei','han','yan','qi'):
 if f'force_pool_{_st}' not in _howners:err(f'state_pool_missing_establishment:{_st}')
for _pth in (ROOT/'state/inst').glob('escort-*.json'):
 _d=rj(_pth) or {}
 if _d.get('owner_id') not in _howners:err(f'escort_missing_establishment:{_pth.name}')
 if not _d.get('formation_library_ref'):err(f'escort_missing_formation_library:{_pth.name}')
for _pth in (ROOT/'state/inst').glob('school-*.json'):
 _d=rj(_pth) or {}
 if _d.get('owner_id') not in _howners:err(f'school_missing_establishment:{_pth.name}')
for _r in _hrs:
 for _s in _r.get('unit_series',[])+_r.get('organizational_unit_series',[]):
  _n=int(_s.get('unit_count',0));_nom=int(_s.get('nominal_strength',0));_fin=int(_s.get('final_unit_strength',0))
  if _n<1 or _nom<1 or _fin<1 or _fin>_nom:err(f'bad_unit_series:{_r.get("id")}:{_s.get("series_id")}')
_pf=rj(ROOT/'state/pforce/wei.json') or {}
_punit_index=(rj(ROOT/'state/index/units.json') or {}).get('units',{})
_pmembers=set(_pf.get('members',[]) or [])
_punassigned=set(_pf.get('unassigned_members',[]) or [])
for _uid in _pf.get('permanent_units',[]) or []:
 _urel=_punit_index.get(_uid)
 if not _urel or not (ROOT/_urel).exists():err(f'personal_force_unit_missing:{_uid}')
 else:
  _ud=rj(ROOT/_urel) or {}
  if _ud.get('owner')!='char_tang_wei':err(f'personal_force_unit_wrong_owner:{_uid}:{_ud.get("owner")}')
  _umembers=set((_ud.get('personnel') or {}).get('member_ids',[]) or [])
  if not _umembers.issubset(_pmembers):err(f'personal_force_unit_member_outside_retinue:{_uid}')
  if _umembers.intersection(_punassigned):err(f'personal_force_unit_member_also_unassigned:{_uid}')
_ca=rj(ROOT/'state/cmd/assignments.json') or {}
if not _ca.get('return_rule'):err('assignment_return_rule_missing')



# Commanders/staff are people, not one-person units.
if (ROOT/'state/cmd/officer-units.json').exists():err('officer_unit_registry_reintroduced')
for _p in (ROOT/'state/person').rglob('*.json'):
 _d=rj(_p) or {}
 if 'officer_unit.' in json.dumps(_d):err(f'stale_officer_unit_ref:{_p.relative_to(ROOT)}')
 _cr=_d.get('command_record_ref')
 if _cr and not (ROOT/_cr).exists():err(f'command_record_ref_missing:{_p.relative_to(ROOT)}:{_cr}')
if not (ROOT/'state/cmd/command-personnel.json').exists():err('command_personnel_registry_missing')

# External armed-owner establishment coverage
_he={'records':home_records()}; _howners={x.get('owner_id') for x in _he.get('records',[])}
for _oid in ('northern_steppe_confederation','mountain_confederation_yotanwa','independent_highland_communities','local.community.three_passes','local.community.silver_ford','local.community.pine_border','local.raider.black_ravine','local.raider.red_marsh','local.raider.broken_cart','local.raider.white_fang'):
 if _oid not in _howners:err(f'external_force_missing_establishment:{_oid}')
for _r in _he.get('records',[]):
 if not _r.get('formation_library_ref'):err(f'establishment_missing_formation_library:{_r.get("owner_id")}')
 if not _r.get('reconstitution_policy_ref'):err(f'establishment_missing_reconstitution:{_r.get("owner_id")}')
 if not _r.get('standing_procedure_ref'):err(f'establishment_missing_standing_procedure:{_r.get("owner_id")}')



def sharded_records(_index_rel,_field):
 _idx=rj(ROOT/_index_rel) or {}; _out={}
 if isinstance(_idx.get(_field),dict):_out.update(_idx.get(_field,{}))
 for _sh in _idx.get('shards',[]):
  _path=_sh.get('path') if isinstance(_sh,dict) else _sh
  if _path:_out.update((rj(ROOT/_path) or {}).get(_field,{}))
 # direct-record registries
 if _field=='loadouts' and isinstance(_idx.get('ids'),list) and _idx.get('path_template'):
  for _id in _idx['ids']:
   _path=_idx['path_template'].replace('{loadout_id}',_id)
   _d=rj(ROOT/_path) or {}
   if isinstance(_d.get('loadout'),dict):_out[_id]=_d['loadout']
 for _id,_path in _idx.get('record_index',{}).items():
  _d=rj(ROOT/_path) or {}
  if _field=='doctrines' and isinstance(_d.get('doctrine'),dict): _out[_id]=_d['doctrine']
  elif _field=='profiles' and isinstance(_d.get('profile'),dict): _out[_id]=_d['profile']
 return _out

# Unit-standard, service-support and doctrine/training reference integrity
_docs=sharded_records('data/mil/doctrines.json','doctrines')
_trains=sharded_records('data/mil/training.json','profiles')
_ttypes=(rj(ROOT/'data/organization/troop-types.json') or {}).get('types',{})
for _r in home_records():
 for _s in _r.get('unit_series',[])+_r.get('organizational_unit_series',[]):
  _tt=_s.get('troop_type')
  if not _tt or _tt not in _ttypes:err(f'undefined_troop_type:{_r.get("owner_id")}:{_tt}')
  if not _s.get('loadout_standard') or _s.get('loadout_standard') not in loads:err(f'undefined_unit_series_loadout:{_r.get("owner_id")}:{_s.get("loadout_standard")}')
  if isinstance(_s.get('doctrine'),str) and _s['doctrine'] not in _docs:err(f'undefined_doctrine:{_s["doctrine"]}')
  if isinstance(_s.get('training'),str) and _s['training'] not in _trains:err(f'undefined_training:{_s["training"]}')
  if 'combat_class' in _s:err(f'unit_series_duplicate_combat_class:{_r.get("owner_id")}:{_tt}')


# Materialized unit invariants. Unit is the only aggregate combat organization.
_unit_index=rj(ROOT/'state/index/units.json') or {}; _ui=_unit_index.get('units',{})
for _pth in (ROOT/'state/unit').glob('*.json'):
 _d=rj(_pth) or {}; _uid=_d.get('id'); _tt=_d.get('troop_type')
 if _tt not in _ttypes:err(f'materialized_unit_undefined_type:{_pth.name}:{_tt}')
 elif 'combat_class' in _d:err(f'materialized_unit_duplicate_combat_class:{_pth.name}:{_tt}')
 if not isinstance(_d.get('loadout_standard'),str):err(f'materialized_unit_missing_standard_loadout:{_pth.name}')
 elif _d.get('loadout_standard') not in loads:err(f'materialized_unit_unknown_loadout:{_pth.name}:{_d.get("loadout_standard")}')
 for _bad in ('loadout_distribution','troop_type_distribution','specialization_distribution','doctrine_distribution','training_distribution','commander_distribution'):
  if _bad in _d:err(f'materialized_unit_internal_standard_distribution:{_pth.name}:{_bad}')
 _rep=(_d.get('personnel') or {}).get('representation'); _cnt=int((_d.get('personnel') or {}).get('count',0))
 if _cnt<1:err(f'materialized_unit_empty:{_pth.name}')
 if _rep=='named_members' and len((_d.get('personnel') or {}).get('member_ids',[]))!=_cnt:err(f'named_unit_member_count:{_pth.name}')
 if _rep=='aggregate':
  _claims=(_d.get('personnel') or {}).get('source_claims',[])
  if not _claims or sum(int(x.get('count',0)) for x in _claims if isinstance(x,dict))!=_cnt:err(f'aggregate_unit_source_claim_conservation:{_pth.name}')
 if isinstance(_d.get('doctrine'),str) and _d['doctrine'] not in _docs:err(f'materialized_unit_undefined_doctrine:{_pth.name}:{_d["doctrine"]}')
 if isinstance(_d.get('training'),str) and _d['training'] not in _trains:err(f'materialized_unit_undefined_training:{_pth.name}:{_d["training"]}')
 if _ui.get(_uid)!=str(_pth.relative_to(ROOT)):err(f'materialized_unit_index_mismatch:{_uid}')
for _uid,_rel in _ui.items():
 if not (ROOT/_rel).exists():err(f'materialized_unit_index_dangling:{_uid}:{_rel}')

# Strategic military pools are accounting owners, never formations.
for _st in ('qin','zhao','chu','wei','han','yan','qi'):
 _p=ROOT/f'state/force-pool/{_st}.json'; _d=rj(_p) or {}
 if _d.get('schema')!='force_pool.v1' or _d.get('owner_type')!='force_pool' or _d.get('accounting_only') is not True:err(f'bad_force_pool_semantics:{_st}')
 if (ROOT/f'state/form/pool-{_st}.json').exists():err(f'strategic_pool_still_formation:{_st}')
 for _u in _d.get('troop_pools',[]):
  if _u.get('pool_kind')=='command_personnel':
   if _u.get('troop_type') or _u.get('combat_class'):err(f'command_personnel_pool_must_not_be_unit_type:{_st}:{_u.get("id")}')
   if _u.get('accounting_only') is not True:err(f'force_pool_child_not_accounting:{_st}:{_u.get("id")}')
   continue
  _tt=_u.get('troop_type')
  if not _tt or _tt not in _ttypes:err(f'force_pool_undefined_type:{_st}:{_tt}')
  if 'combat_class' in _u:err(f'force_pool_duplicate_combat_class:{_st}:{_tt}')
  if _u.get('accounting_only') is not True:err(f'force_pool_child_not_accounting:{_st}:{_u.get("id")}')


# Every source manpower pool is accounting-only; capability payloads are cold refs.
for _pth in (ROOT/'state').rglob('*.json'):
 if 'manpower-capability' in str(_pth):continue
 _d=rj(_pth)
 if not isinstance(_d,dict) or not isinstance(_d.get('troop_pools'),list):continue
 if _d.get('accounting_only') is not True:err(f'source_owner_not_accounting_only:{_pth.relative_to(ROOT)}')
 for _pool in _d.get('troop_pools',[]):
  if not isinstance(_pool,dict):continue
  if _pool.get('accounting_only') is not True:err(f'source_pool_not_accounting_only:{_pth.relative_to(ROOT)}:{_pool.get("id") or _pool.get("pool_id")}')
  if 'resolution_scale' in _pool:err(f'source_pool_combat_resolution_scale:{_pth.relative_to(ROOT)}:{_pool.get("id") or _pool.get("pool_id")}')
  for _bad in ('stats','capabilities','body_distribution','aptitude_distribution','tendencies','combat_tendencies','experience_distribution'):
   if _bad in _pool:err(f'inline_source_capability_bloat:{_pth.relative_to(ROOT)}:{_bad}')
  _cr=_pool.get('capability_ref')
  if _pool.get('pool_kind')!='command_personnel' and (not _cr or not (ROOT/_cr).exists()):err(f'source_pool_missing_capability_ref:{_pth.relative_to(ROOT)}:{_pool.get("id") or _pool.get("pool_id")}')

# No latent identity directory after cold-active roster migration.
if (ROOT/'data/latent-identities').exists():err('latent_identity_directory_still_present')
_car=rj(ROOT/'state/char-roster/index.json') or {}
if int(_car.get('count',0))!=len(list((ROOT/'state/char-roster/active-canon').glob('*.json'))):err('active_roster_count_mismatch')
if int(_car.get('count',0))!=306:err(f'active_roster_expected_306:{_car.get("count")}')
for _e in _car.get('entries',[]):
 _sh=rj(ROOT/_e.get('path','')) or {}
 if len(_sh.get('characters',[]))!=int(_e.get('count',-1)):err(f'active_roster_shard_count:{_e.get("shard")}')
if 'lookup' in _car:err('active_roster_monolithic_lookup_reintroduced')
_lbi=_car.get('lookup_by_initial',{})
if sum(int(x.get('count',0)) for x in _lbi.values())!=int(_car.get('count',0)):err('active_roster_lookup_shard_count')
for _initial,_e in _lbi.items():
 _sh=rj(ROOT/_e.get('path','')) or {}
 if len(_sh.get('lookup',{}))!=int(_e.get('count',-1)):err(f'active_lookup_shard_count:{_initial}')
 for _cid,_x in _sh.get('lookup',{}).items():
  if not (ROOT/_x.get('path','')).exists():err(f'active_lookup_dangling:{_cid}:{_x.get("path")}')

# Troop pools are accounting objects but must declare the homogeneous troop type they can allocate.
for _p in (ROOT/'state').rglob('*.json'):
 _d=rj(_p)
 if _d is None:continue
 for _o in walk(_d):
  if isinstance(_o,dict) and _o.get('schema')=='troop_pool.v1':
   if not _o.get('troop_type'):err(f'troop_pool_missing_type:{_p.relative_to(ROOT)}:{_o.get("id")}')

# Refit targets must resolve to a real loadout and never masquerade as an instant completed refit.
for _pth in (ROOT/'state/unit').glob('*.json'):
 _d=rj(_pth) or {}; _rf=_d.get('refit_state')
 if isinstance(_rf,dict):
  _target=_rf.get('target_loadout_standard')
  if _target not in loads:err(f'unit_refit_unknown_loadout:{_pth.name}:{_target}')
  if _rf.get('progress')==1:err(f'unit_completed_refit_not_promoted:{_pth.name}')

# Unit transaction receipts must conserve headcount and lineage evidence.
_tx=rj(ROOT/'state/org/unit-transactions.json') or {}
if _tx.get('schema')!='unit-transaction-registry.v2':err('unit_transaction_registry_v2_missing')
_seen_tx=set()
for _r in _tx.get('records',[]):
 _tid=_r.get('id')
 if not _tid or _tid in _seen_tx:err(f'unit_transaction_duplicate_or_missing_id:{_tid}')
 _seen_tx.add(_tid)
 _b=_r.get('before') or {}; _a=_r.get('after') or {}; _c=_r.get('conservation') or {}; _method=_r.get('method')
 if _method not in ('neutral_proportional','explicit_selection','merge_pooling','structural_reorganization'):err(f'unit_transaction_method_missing:{_tid}')
 _ev=_r.get('capability_evidence') or {}
 if _ev.get('partition_authority')!='data/mechanics/unit-partition.json':err(f'unit_transaction_partition_evidence_missing:{_tid}')
 if int(_b.get('personnel_total',-1))!=int(_a.get('personnel_total',-2)):err(f'unit_transaction_personnel_not_conserved:{_tid}')
 if _c.get('personnel_delta')!=0:err(f'unit_transaction_nonzero_personnel_delta:{_tid}:{_c.get("personnel_delta")}')
 if not _a.get('unit_ids'):err(f'unit_transaction_missing_result_unit_lineage:{_tid}')
 if _method=='structural_reorganization':
  if not (_b.get('unit_ids') or _b.get('named_member_ids')):err(f'unit_transaction_missing_source_lineage:{_tid}')
 elif not _b.get('unit_ids'):err(f'unit_transaction_missing_source_unit_lineage:{_tid}')


# Command hierarchy v4: one ownership-agnostic two-axis direct budget.
_cmd=rj(ROOT/'data/mechanics/command.json') or {}
if _cmd.get('schema')!='hierarchical_command_mechanics.v4':err('command_schema_v4_missing')
_pa=_cmd.get('comfortable_direct_personnel_anchors',[]); _sa=_cmd.get('comfortable_direct_command_slots_anchors',[])
if not _pa or _pa[-1][1]<100000:err('command_personnel_scale_too_low')
if not _sa or _sa[-1][1]<8:err('command_slot_scale_missing')
if 'ownership' not in str(_cmd.get('principle','')).lower():err('command_ownership_agnostic_missing')
_we=_cmd.get('worked_example',{})
if '10000' not in str(_we) or '5000' not in str(_we) or '1 subordinate' not in str(_we).lower():err('command_delegation_reference_case_missing')
# Unit-resolution authority keeps large ordinary units aggregate and forbids scalar-only power collapse.
_ur=rj(ROOT/'data/mechanics/unit-resolution.json') or {}
if _ur.get('schema')!='unit_resolution_mechanics.v1':err('unit_resolution_missing')
if 'one aggregate combat actor' not in str(_ur.get('principle','')).lower():err('aggregate_unit_principle_missing')
if 'one scalar power score' not in str(_ur.get('anti_overcompression','')).lower():err('anti_overcompression_missing')
_um=rj(ROOT/'data/organization/unit-model.json') or {}
_part=rj(ROOT/'data/mechanics/unit-partition.json') or {}
if _part.get('schema')!='unit_partition_mechanics.v1':err('unit_partition_mechanics_missing')
if _um.get('schema')!='unit_model.v2':err('unit_model_v2_missing')
# Cold active roster, never obsolete latent authority.
_life=rj(ROOT/'state/life/identity-life-course.json') or {}; _roster=rj(ROOT/'state/char-roster/index.json') or {}
if (_life.get('records') or [{}])[0].get('facts',{}).get('canon_roster_owner')!='state/char-roster/index.json':err('life_course_cold_roster_route_missing')
if _roster.get('count',0)<1:err('cold_active_roster_empty')
if _roster.get('schema')!='active_character_roster_index.v4':err('cold_active_roster_index_v4_missing')
if 'record_index' in _roster:err('cold_active_roster_redundant_record_index')
# Command-person direct records must all resolve to current people.
_cidx=rj(ROOT/'state/cmd/command-personnel.json') or {}
if _cidx.get('schema')!='command-personnel-index.v2':err('command_personnel_index_v2_missing')
for _pid,_rel in _cidx.get('record_index',{}).items():
 if not (ROOT/_rel).exists():err(f'command_person_record_missing:{_pid}:{_rel}')
if errors:
 print('AUDIT FAILED');[print('-',e) for e in errors];sys.exit(1)
print('AUDIT OK')
print(f"people={len(people)} items={len(items)} loadouts={len(loads)} frontier_processes={len(front.get('processes',[]))}")
