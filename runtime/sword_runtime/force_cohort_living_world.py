from __future__ import annotations
from collections.abc import Mapping, MutableMapping
from copy import deepcopy
from typing import Any
from sword_runtime.cohort_personnel import add_recruits, advance_cohort_training, advance_service_months, append_formation_slices, ensure_cohort_ledger, ensure_formation_composition, record_recruitment_cohort, take_reserve_slices, validate_cohort_ledger
from sword_runtime.military_career_commit_integrity import MilitaryCareerCommitIntegrityMixin
from sword_runtime.smart_training import select_cohort_focuses, train_person_lite

P='game/data/mil/recruitment-cohort-profiles.json'; T='game/data/mechanics/training.json'; MONTH=30*86400

def ac(v:Any)->int: return int(v.get('personnel',0)) if isinstance(v,Mapping) else int(v)

class ForceCohortLivingWorldMixin(MilitaryCareerCommitIntegrityMixin):
 def _fc_profiles(self): return self.read(P)
 def _fc_promotion_facts(self, force: Mapping[str, Any], role: str) -> Mapping[str, Any]:
  owner=str(force.get('owner_id',''))
  record_id=None; path=None
  if owner=='institution_sword_manor':
   record_id={'trainee':'trainee_to_junior_disciple','junior_disciple':'junior_to_general_disciple','general_disciple':'general_to_senior_disciple','senior_disciple':'house_guard_candidate'}.get(role)
   path='state/prog/sword-manor-progression.json'
  elif owner=='force_house_tang':
   if role=='house_guard': record_id='house_guard_to_house_guardian_cavalry'; path='state/prog/sword-manor-progression.json'
   elif role=='guardian_cavalry': record_id='guardian_cavalry_to_tang_champion'; path='state/prog/house-tang-champion-progression.json'
  if not record_id or not path: return {}
  doc=self.read(path)
  for row in doc.get('records',[]) if isinstance(doc,Mapping) else []:
   if isinstance(row,Mapping) and str(row.get('record_id'))==record_id:
    facts=row.get('facts',{}); return facts if isinstance(facts,Mapping) else {}
  return {}

 def _fc_regimen(self, name:str)->Mapping[str,Any]:
  profiles=self._fc_profiles(); row=profiles.get('training_regimens',{}).get(name,{}) if isinstance(profiles,Mapping) else {}
  return row if isinstance(row,Mapping) else {}

 def _fc_train(self,force:dict[str,Any],regimen:str,months:float,ref:str)->None:
  # Generic force development owns both aggregate cohorts and any named
  # person-lite bodies materialized from those same conserved forces. Seed
  # inherited standing capability before applying later verified training so a
  # newly introduced force cannot accumulate empty training hours forever.
  if hasattr(self,'_seed_force_baselines'): self._seed_force_baselines(force)
  profiles=self._fc_profiles(); r=self._fc_regimen(regimen); rp=profiles.get('role_training_profiles',{}); rules=self.read(T); ledger=ensure_cohort_ledger(force); whole=int(months); rem=max(0.,months-whole)
  for bi,block in enumerate([1.]*whole+([rem] if rem>1e-9 else [])):
   dh=float(r.get('deliberate_hours_per_30d',56))*block; eh=float(r.get('role_exposure_hours_per_30d',48))*block
   for c in ledger['cohorts'].values():
    if not isinstance(c,MutableMapping) or sum(map(int,c.get('reserve_by_location',{}).values()))+sum(map(int,c.get('allocated_by_formation',{}).values()))+sum(map(int,c.get('allocated_external_by_formation',{}).values()))<=0: continue
    role=str(c.get('role','')); profile=rp.get(role,{}) if isinstance(rp,Mapping) else {}; cursor=max(0,int(c.get('smart_training_cursor',0))); facts=self._fc_promotion_facts(force,role)
    skill_focuses,attribute_focuses=select_cohort_focuses(c,role=role,role_profile=profile if isinstance(profile,Mapping) else {},promotion_facts=facts,cursor=cursor)
    advance_service_months(c,block)
    if c.get('attribute_means') or c.get('skill_means'):
     advance_cohort_training(c,deliberate_hours=dh,role_exposure_hours=eh,skill_focuses=skill_focuses,attribute_focuses=attribute_focuses,training_rules=rules,facility_grade=str(r.get('facility_grade','adequate')),equipment_grade=str(r.get('equipment_grade','adequate')),recovery_grade=str(r.get('recovery_grade','adequate')),evidence_ref=f'{ref}:{bi}:smart')
    else:
     c['verified_training_hours_per_person']=round(float(c.get('verified_training_hours_per_person',0))+dh,3); c['verified_role_exposure_hours_per_person']=round(float(c.get('verified_role_exposure_hours_per_person',0))+eh,3)
    c['smart_training_cursor']=cursor+1
  # Person-lite officers remain conserved inside the force headcount, but their
  # individual stats need the same elapsed training owner as the aggregate
  # cohort they came from. This call changes no manpower accounting.
  self._fc_train_person_lites(force,regimen,months,ref)

 def _fc_train_person_lites(self, force: Mapping[str, Any], regimen: str, months: float, ref: str, *, ref_prefix: str | None = None) -> int:
  if months<=0: return 0
  r=self._fc_regimen(regimen); rules=self.read(T); trained=0
  dh=float(r.get('deliberate_hours_per_30d',56))*months; eh=float(r.get('role_exposure_hours_per_30d',48))*months
  materialized=force.get('materialized_people',{}) if isinstance(force,Mapping) else {}
  if not isinstance(materialized,Mapping): return 0
  for person_ref in sorted(str(x) for x in materialized if not ref_prefix or str(x).startswith(ref_prefix)):
   try: pp=self.owner_path(person_ref); person=deepcopy(self.read(pp))
   except (KeyError,ValueError,FileNotFoundError): continue
   if str(person.get('schema',''))!='person-lite': continue
   train_person_lite(person,deliberate_hours=dh,role_exposure_hours=eh,training_rules=rules,facility_grade=str(r.get('facility_grade','adequate')),equipment_grade=str(r.get('equipment_grade','adequate')),recovery_grade=str(r.get('recovery_grade','adequate')),evidence_ref=f'{ref}:person_lite:{person_ref}')
   self.put(pp,person); trained+=1
  return trained

 def _fc_train_person_lites_extra(self, force: Mapping[str, Any], *, target_regimen: str, baseline_regimen: str, months: float, ref: str, ref_prefix: str | None = None) -> int:
  """Apply only the verified training-rate delta above a force baseline.

  This is used for named officers assigned to a higher-tempo establishment so
  they receive the same total target regimen as their formation rather than a
  full second copy of both baseline and target training.
  """
  if months<=0: return 0
  target=self._fc_regimen(target_regimen); base=self._fc_regimen(baseline_regimen); rules=self.read(T); trained=0
  dh=max(0.0,float(target.get('deliberate_hours_per_30d',0))-float(base.get('deliberate_hours_per_30d',0)))*months
  eh=max(0.0,float(target.get('role_exposure_hours_per_30d',0))-float(base.get('role_exposure_hours_per_30d',0)))*months
  if dh<=0 and eh<=0: return 0
  materialized=force.get('materialized_people',{}) if isinstance(force,Mapping) else {}
  if not isinstance(materialized,Mapping): return 0
  for person_ref in sorted(str(x) for x in materialized if not ref_prefix or str(x).startswith(ref_prefix)):
   try: pp=self.owner_path(person_ref); person=deepcopy(self.read(pp))
   except (KeyError,ValueError,FileNotFoundError): continue
   if str(person.get('schema',''))!='person-lite': continue
   train_person_lite(person,deliberate_hours=dh,role_exposure_hours=eh,training_rules=rules,facility_grade=str(target.get('facility_grade','adequate')),equipment_grade=str(target.get('equipment_grade','adequate')),recovery_grade=str(target.get('recovery_grade','adequate')),evidence_ref=f'{ref}:person_lite_extra:{person_ref}')
   self.put(pp,person); trained+=1
  return trained

 def _fc_train_formation_extra(self, force: dict[str, Any], formation_ref: str, *, target_regimen: str, baseline_regimen: str, months: float, ref: str) -> int:
  if months<=0: return 0
  try: _fp,formation=self._load_formation(formation_ref)
  except (KeyError,ValueError,FileNotFoundError): return 0
  if str(formation.get('owner_force_ref',''))!=str(force.get('owner_id','')): return 0
  target=self._fc_regimen(target_regimen); base=self._fc_regimen(baseline_regimen); profiles=self._fc_profiles(); rp=profiles.get('role_training_profiles',{}); rules=self.read(T); ledger=ensure_cohort_ledger(force)
  dh=max(0.0,float(target.get('deliberate_hours_per_30d',0))-float(base.get('deliberate_hours_per_30d',0)))*months
  eh=max(0.0,float(target.get('role_exposure_hours_per_30d',0))-float(base.get('role_exposure_hours_per_30d',0)))*months
  changed=0
  for item in formation.get('cohort_composition',[]) if isinstance(formation,Mapping) else []:
   if not isinstance(item,Mapping) or int(item.get('count',0))<=0: continue
   c=ledger.get('cohorts',{}).get(str(item.get('cohort_id')))
   if not isinstance(c,MutableMapping): continue
   role=str(c.get('role') or next(iter(formation.get('composition',{})),'line_infantry')); profile=rp.get(role,{}) if isinstance(rp,Mapping) else {}; cursor=max(0,int(c.get('smart_training_extra_cursor',0)))
   skills,attrs=select_cohort_focuses(c,role=role,role_profile=profile if isinstance(profile,Mapping) else {},promotion_facts={},cursor=cursor)
   if dh>0 or eh>0:
    advance_cohort_training(c,deliberate_hours=dh,role_exposure_hours=eh,skill_focuses=skills,attribute_focuses=attrs,training_rules=rules,facility_grade=str(target.get('facility_grade','adequate')),equipment_grade=str(target.get('equipment_grade','adequate')),recovery_grade=str(target.get('recovery_grade','adequate')),evidence_ref=f'{ref}:formation_extra:{formation_ref}')
   c['smart_training_extra_cursor']=cursor+1; changed+=1
  return changed

 def _fc_prepare(self,path:str,at:str):
  f=deepcopy(self.read(path)); ensure_cohort_ledger(f,at=at); self.put(path,f); return f
 def _fc_prepare_form(self,ref:str,at:str):
  p,x0=self._load_formation(ref); x=deepcopy(x0); fp=self.owner_path(str(x['owner_force_ref'])); f=deepcopy(self.read(fp)); ensure_cohort_ledger(f,at=at); ensure_formation_composition(f,x,at=at); self.put(fp,f); self.put(p,x)

 def _fc_role_totals(self, force: Mapping[str, Any]) -> dict[str, int]:
  totals: dict[str, int] = {}
  available=force.get('available_by_role', {})
  if isinstance(available, Mapping):
   for role, raw in available.items(): totals[str(role)] = totals.get(str(role), 0) + max(0, ac(raw))
  allocated=force.get('allocated_to_formations', {})
  if isinstance(allocated, Mapping):
   for raw in allocated.values():
    if isinstance(raw, Mapping):
     role=str(raw.get('role') or '')
     if role: totals[role]=totals.get(role,0)+max(0,ac(raw))
  return totals

 def _fc_ammunition_target(self, force: Mapping[str, Any], carried_loads: float) -> dict[str, int]:
  targets={'war_arrows':0,'war_bolts':0}
  if not hasattr(self, '_combat_role_profile') or not hasattr(self, '_combat_loadout'): return targets
  for role, count in self._fc_role_totals(force).items():
   if count<=0: continue
   profile=self._combat_role_profile(role); loadout=self._combat_loadout(str(profile.get('loadout_id',''))) if isinstance(profile,Mapping) else {}
   if not isinstance(loadout, Mapping): continue
   item=str(loadout.get('ammunition_item','')); resource=getattr(self,'AMMO_RESOURCE_BY_ITEM',{}).get(item)
   if resource not in targets: continue
   carried=max(0,int(loadout.get('carried_ammunition',0) or 0)); targets[resource]+=int(round(count*carried*max(0.,carried_loads)))
  return targets

 def _fc_procure_ammunition(self, force: Mapping[str, Any], *, depot_path: str, treasury_path: str, treasury_field: str, occurrences: int, at: str, owner_ref: str) -> dict[str, int]:
  economy=self.read('game/data/mechanics/economy.json'); rule=economy.get('ammunition_procurement',{}) if isinstance(economy,Mapping) else {}
  if not isinstance(rule,Mapping): return {'war_arrows':0,'war_bolts':0,'silver_spent':0}
  depot=deepcopy(self.read(depot_path)); treasury=deepcopy(self.read(treasury_path)); stocks=depot.setdefault('stocks',{})
  loads=float(rule.get('central_reserve_carried_loads',1.0)); targets=self._fc_ammunition_target(force,loads)
  lot_size=rule.get('lot_size',{}); price_key=rule.get('price_key',{}); caps=rule.get('monthly_purchase_cap',{}); prices=economy.get('prices_silver',{})
  balance=max(0,int(treasury.get(treasury_field,0))); bought={'war_arrows':0,'war_bolts':0}; spent=0
  for resource in ('war_arrows','war_bolts'):
   short=max(0,int(targets.get(resource,0))-int(stocks.get(resource,0)))
   lot=max(1,int(lot_size.get(resource,20))) if isinstance(lot_size,Mapping) else 20
   cap=max(0,int(caps.get(resource,0))) * max(0,int(occurrences)) if isinstance(caps,Mapping) else short
   price_name=str(price_key.get(resource,'')) if isinstance(price_key,Mapping) else ''
   lot_price=float(prices.get(price_name,0)) if isinstance(prices,Mapping) else 0.0
   if short<=0 or cap<=0 or lot_price<=0: continue
   wanted=min(short,cap); lots=(wanted+lot-1)//lot; affordable=int(balance//lot_price); lots=min(lots,affordable)
   if lots<=0: continue
   qty=lots*lot; cost=int(round(lots*lot_price)); qty=min(qty,cap if cap>0 else qty)
   qty=(qty//lot)*lot; cost=int(round((qty//lot)*lot_price))
   if qty<=0 or cost>balance: continue
   stocks[resource]=int(stocks.get(resource,0))+qty; balance-=cost; spent+=cost; bought[resource]=qty
  if spent:
   treasury[treasury_field]=balance
   depot.setdefault('procurement_history',[]).append({'at':at,'owner_ref':owner_ref,'war_arrows':bought['war_arrows'],'war_bolts':bought['war_bolts'],'silver_spent':spent})
   depot['procurement_history']=depot['procurement_history'][-24:]
   self.put(depot_path,depot); self.put(treasury_path,treasury)
  return {'war_arrows':bought['war_arrows'],'war_bolts':bought['war_bolts'],'silver_spent':spent}

 def _autonomy_state(self,host:Mapping[str,Any],occurrences:int,at:str)->None:
  super()._autonomy_state(host,occurrences,at)
  state=str(host['owner_ref']).replace('state_',''); fp=f'state/forces/state-{state}.json'; actual=deepcopy(self.read(fp)); validate_cohort_ledger(actual)
  months=int(host.get('recurrence_seconds',MONTH))*max(0,int(occurrences))/MONTH; self._fc_train(actual,'regular_army',months,f'state:{state}:{at}')
  if state=='qin':
   self._fc_train_formation_extra(actual,'formation_qin_border_line',target_regimen='house_tang_max_sustainable',baseline_regimen='regular_army',months=months,ref=f'wei_designated_qin:{at}')
   self._fc_train_person_lites_extra(actual,target_regimen='house_tang_max_sustainable',baseline_regimen='regular_army',months=months,ref=f'wei_designated_qin:{at}',ref_prefix='officer.qin.wei_designated.')
  validate_cohort_ledger(actual); self.put(fp,actual)
  self._fc_procure_ammunition(actual,depot_path=f'state/depots/{state}.json',treasury_path=f'state/states/{state}.json',treasury_field='treasury_silver',occurrences=occurrences,at=at,owner_ref=f'state_{state}')
 def _autonomy_house(self,host:Mapping[str,Any],occurrences:int,at:str)->None:
  hr=str(host['owner_ref']); hp=self.owner_path(hr); house=deepcopy(self.read(hp)); fr=house.get('military_force_ref'); no=deepcopy(house); no.pop('military_force_ref',None); self.put(hp,no); super()._autonomy_house(host,occurrences,at); settled=deepcopy(self.read(hp))
  if not isinstance(fr,str): self.put(hp,settled); return
  settled['military_force_ref']=fr; self.put(hp,settled); fp=self.owner_path(fr); f=self._fc_prepare(fp,at)
  if fr!='force_house_tang':
   short=max(0,int(f.get('authorized_strength',f.get('headcount',0)))-int(f.get('headcount',0)))
   if short:
    state=self._state_key(house.get('state')); pp=f'state/population/{state}.json'; pop=deepcopy(self.read(pp)); n=min(short,int(pop.get('strata',{}).get('household_and_service',0)),max(1,25*int(occurrences)))
    if n:
     pop['strata']['household_and_service']-=n; pop['strata']['private_household_military']=int(pop['strata'].get('private_household_military',0))+n; loc=str(f.get('source_location_ref') or house.get('location_ref') or 'loc_kanyou'); add_recruits(f,'household_retainer',n,location_ref=loc); record_recruitment_cohort(f,role='household_retainer',count=n,location_ref=loc,source_population_ref=f'population_{state}',source_stratum='household_and_service',recruited_at=at,profile_registry=self._fc_profiles(),selection_profile='household_retainer_screen',provenance_ref=f'autonomy_house:{at}'); self.put(pp,pop)
  months=int(host.get('recurrence_seconds',90*86400))*max(0,int(occurrences))/MONTH
  # House Tang's force has a dedicated monthly manor development clock. Do not
  # award the same bodies a second quarterly training settlement here. Other
  # Houses continue to train through their ordinary House review.
  if fr!='force_house_tang': self._fc_train(f,'household_professional',months,f'house:{hr}:{at}')
  validate_cohort_ledger(f); self.put(fp,f)
  if fr=='force_house_tang': self._fc_procure_ammunition(f,depot_path='state/depots/house-tang.json',treasury_path='state/treasury/treasury-house-tang.json',treasury_field='silver',occurrences=occurrences,at=at,owner_ref='house_tang')
