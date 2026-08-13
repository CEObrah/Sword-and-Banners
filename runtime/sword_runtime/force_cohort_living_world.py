from __future__ import annotations
from collections.abc import Mapping, MutableMapping
from copy import deepcopy
from typing import Any
from sword_runtime.cohort_personnel import add_recruits, advance_cohort_training, advance_service_months, append_formation_slices, ensure_cohort_ledger, ensure_formation_composition, record_recruitment_cohort, take_reserve_slices, validate_cohort_ledger

P='game/data/mil/recruitment-cohort-profiles.json'; T='game/data/mechanics/training.json'; MONTH=30*86400

def ac(v:Any)->int: return int(v.get('personnel',0)) if isinstance(v,Mapping) else int(v)

class ForceCohortLivingWorldMixin:
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
 def _autonomy_state(self,host:Mapping[str,Any],occurrences:int,at:str)->None:
  state=str(host['owner_ref']).replace('state_',''); fp=f'state/forces/state-{state}.json'; before=deepcopy(self._fc_prepare(fp,at)); bh=int(before.get('headcount',0)); ba={str(k):ac(v) for k,v in before.get('allocated_to_formations',{}).items()}
  for ref in ba:
   try:self._fc_prepare_form(ref,at)
   except ValueError:pass
  super()._autonomy_state(host,occurrences,at); actual=deepcopy(self.read(fp)); work=deepcopy(before); growth=int(actual.get('headcount',0))-bh
  if growth>0:
   loc=str(work.get('source_location_ref')); add_recruits(work,'line_infantry',growth,location_ref=loc); record_recruitment_cohort(work,role='line_infantry',count=growth,location_ref=loc,source_population_ref=f'population_{state}',source_stratum='agricultural',recruited_at=at,profile_registry=self._fc_profiles(),selection_profile='state_basic_military_screen',provenance_ref=f'autonomy_state:{at}')
  aa={str(k):ac(v) for k,v in actual.get('allocated_to_formations',{}).items()}
  for ref,n in aa.items():
   d=n-ba.get(ref,0)
   if d<=0:continue
   try:p,x0=self._load_formation(ref)
   except ValueError:continue
   x=deepcopy(x0); a=actual.get('allocated_to_formations',{}).get(ref); role=str(a.get('role')) if isinstance(a,Mapping) and a.get('role') else next(iter(x.get('composition',{})),'line_infantry'); loc=str(x.get('location_ref')); self._take_force_personnel(work,role,d,loc); work.setdefault('allocated_to_formations',{})[ref]=deepcopy(a); append_formation_slices(x,take_reserve_slices(work,role=role,count=d,location_ref=loc,formation_ref=ref)); self.put(p,x)
  actual['cohort_ledger']=deepcopy(work['cohort_ledger']); validate_cohort_ledger(actual); months=int(host.get('recurrence_seconds',MONTH))*max(0,int(occurrences))/MONTH; self._fc_train(actual,'regular_army',months,f'state:{state}:{at}'); self.put(fp,actual)
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
