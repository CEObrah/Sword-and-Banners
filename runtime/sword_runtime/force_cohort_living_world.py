from __future__ import annotations
from collections.abc import Mapping, MutableMapping
from copy import deepcopy
from typing import Any
from sword_runtime.cohort_personnel import add_recruits, advance_cohort_training, advance_service_months, append_formation_slices, ensure_cohort_ledger, ensure_formation_composition, record_recruitment_cohort, take_reserve_slices, validate_cohort_ledger
from sword_runtime.military_career_loyalty_integrity import MilitaryCareerLoyaltyIntegrityMixin

P='game/data/mil/recruitment-cohort-profiles.json'; T='game/data/mechanics/training.json'; MONTH=30*86400

def ac(v:Any)->int: return int(v.get('personnel',0)) if isinstance(v,Mapping) else int(v)

class ForceCohortLivingWorldMixin(MilitaryCareerLoyaltyIntegrityMixin):
 def _fc_profiles(self): return self.read(P)
 def _fc_train(self,force:dict[str,Any],regimen:str,months:float,ref:str)->None:
  profiles=self._fc_profiles(); r=profiles.get('training_regimens',{}).get(regimen,{}); rp=profiles.get('role_training_profiles',{}); rules=self.read(T); ledger=ensure_cohort_ledger(force); whole=int(months); rem=max(0.,months-whole)
  for bi,block in enumerate([1.]*whole+([rem] if rem>1e-9 else [])):
   dh=float(r.get('deliberate_hours_per_30d',56))*block; eh=float(r.get('role_exposure_hours_per_30d',48))*block
   for c in ledger['cohorts'].values():
    if not isinstance(c,MutableMapping) or sum(map(int,c.get('reserve_by_location',{}).values()))+sum(map(int,c.get('allocated_by_formation',{}).values()))<=0: continue
    focus=rp.get(str(c.get('role','')),{}); advance_service_months(c,block)
    if c.get('attribute_means') or c.get('skill_means'):
     advance_cohort_training(c,deliberate_hours=dh,role_exposure_hours=eh,skill_focuses=focus.get('skills',[]),attribute_focuses=focus.get('attributes',[]),training_rules=rules,facility_grade=str(r.get('facility_grade','adequate')),equipment_grade=str(r.get('equipment_grade','adequate')),recovery_grade=str(r.get('recovery_grade','adequate')),evidence_ref=f'{ref}:{bi}')
    else:
     c['verified_training_hours_per_person']=round(float(c.get('verified_training_hours_per_person',0))+dh,3); c['verified_role_exposure_hours_per_person']=round(float(c.get('verified_role_exposure_hours_per_person',0))+eh,3)
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
  months=int(host.get('recurrence_seconds',MONTH))*max(0,int(occurrences))/MONTH; self._fc_train(actual,'regular_army',months,f'state:{state}:{at}'); validate_cohort_ledger(actual); self.put(fp,actual)
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
  months=int(host.get('recurrence_seconds',90*86400))*max(0,int(occurrences))/MONTH; self._fc_train(f,'house_tang_max_sustainable' if fr=='force_house_tang' else 'household_professional',months,f'house:{hr}:{at}'); validate_cohort_ledger(f); self.put(fp,f)
  if fr=='force_house_tang': self._fc_procure_ammunition(f,depot_path='state/depots/house-tang.json',treasury_path='state/treasury/treasury-house-tang.json',treasury_field='silver',occurrences=occurrences,at=at,owner_ref='house_tang')
