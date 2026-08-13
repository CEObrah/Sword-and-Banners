from __future__ import annotations
import re
from collections.abc import Mapping
from copy import deepcopy
from sword_runtime.cohort_personnel import add_recruits, consume_population_recruits, ensure_cohort_ledger, qualification_capacity, record_recruitment_cohort, role_count, transfer_between_forces, transfer_role, validate_cohort_ledger
S='state/forces/sword-manor.json'; H='state/forces/house-tang.json'; Q='state/population/qin.json'; M='state/population/tang-manor.json'; PR='state/prog/sword-manor-progression.json'; CR='state/prog/house-tang-champion-progression.json'; TG='loc_tang_manor_training_ground'; G='loc_tang_manor_garrison_yard'
def R(d):return {str(x['record_id']):x for x in d.get('records',[]) if isinstance(x,Mapping) and x.get('record_id')}
def A(v):return int(v.get('personnel',0)) if isinstance(v,Mapping) else int(v)
def MTH(v,d=0):
 x=re.search(r'\d+',str(v));return int(x.group()) if x else d
class HouseTangDevelopmentMixin:
 def _hq(self,f,role,row,loc,service=0):
  facts=row.get('facts',{}) if isinstance(row,Mapping) else {};total=0
  for c in f.get('cohort_ledger',{}).get('cohorts',{}).values():
   if isinstance(c,Mapping) and str(c.get('role'))==role:
    n=int(c.get('reserve_by_location',{}).get(loc,0));total+=qualification_capacity(c,minimum_attribute_values=facts.get('minimum_attribute_values'),minimum_skill_values=facts.get('minimum_skill_values'),minimum_service_months=service,available_count=n) if n>0 else 0
  return total
 def _autonomy_manor(self,host:Mapping,occurrences:int,at:str)->None:
  occ=max(0,int(occurrences))
  if not occ:return
  sword=deepcopy(self.read(S));house=deepcopy(self.read(H));qin=deepcopy(self.read(Q));manor=deepcopy(self.read(M));prog=deepcopy(self.read(PR));cprog=deepcopy(self.read(CR));ensure_cohort_ledger(sword,at=at);ensure_cohort_ledger(house,at=at);rs=R(prog);cs=R(cprog);profiles=self._fc_profiles()
  for cycle in range(occ):
   ev=f'sword_manor:{at}:{cycle}';self._fc_train(sword,'house_tang_max_sustainable',1,ev);self._fc_train(house,'house_tang_max_sustainable',1,ev+':house')
   for src,dst,rid,key in [('trainee','junior_disciple','trainee_to_junior_disciple','required_verified_training_months'),('junior_disciple','general_disciple','junior_to_general_disciple','required_verified_service_months_at_junior'),('general_disciple','senior_disciple','general_to_senior_disciple','required_verified_service_months_at_general')]:
    row=rs.get(rid,{});facts=row.get('facts',{}) if isinstance(row,Mapping) else {};n=self._hq(sword,src,row,TG,MTH(facts.get(key),0));transfer_role(sword,src,dst,n,location_ref=TG,evidence_ref=f'{ev}:{rid}')
   row=rs.get('sword_manor_officer',{});vac=max(0,int(sword.get('authorized_by_role',{}).get('officer',50))-role_count(sword,'officer'));transfer_role(sword,'senior_disciple','officer',min(vac,self._hq(sword,'senior_disciple',row,TG)),location_ref=TG,evidence_ref=f'{ev}:officer')
   caps=house.setdefault('authorized_by_role',{'house_guard':700,'guardian_cavalry':300,'tang_champion':100});vac=max(0,int(caps.get('house_guard',700))-role_count(house,'house_guard'));row=rs.get('house_guard_candidate',{});transfer_between_forces(sword,house,source_role='senior_disciple',destination_role='house_guard',count=min(vac,self._hq(sword,'senior_disciple',row,TG)),source_location_ref=TG,destination_location_ref=G,evidence_ref=f'{ev}:guard')
   vac=max(0,int(caps.get('guardian_cavalry',300))-role_count(house,'guardian_cavalry'));row=rs.get('house_guard_to_house_guardian_cavalry',{});transfer_role(house,'house_guard','guardian_cavalry',min(vac,self._hq(house,'house_guard',row,G)),location_ref=G,evidence_ref=f'{ev}:cavalry')
   alloc=sum(A(v) for v in house.get('allocated_to_formations',{}).values() if not isinstance(v,Mapping) or str(v.get('role',''))=='tang_champion');vac=max(0,int(caps.get('tang_champion',100))-role_count(house,'tang_champion')-alloc);row=cs.get('guardian_cavalry_to_tang_champion',{});facts=row.get('facts',{}) if isinstance(row,Mapping) else {};transfer_role(house,'guardian_cavalry','tang_champion',min(vac,self._hq(house,'guardian_cavalry',row,G,int(facts.get('minimum_verified_service_months_at_guardian_cavalry',24)))),location_ref=G,evidence_ref=f'{ev}:champion')
   count=role_count(sword,'trainee');cap=int(manor.get('sword_manor',{}).get('monthly_intake_capacity',500));housing=int(manor.get('sword_manor',{}).get('trainee_housing_capacity',6000));wanted=max(0,min(cap,housing-count));moved,mix=consume_population_recruits(qin,wanted,source_roles=('agricultural','craft_and_industry','household_and_service','merchant_and_transport'),destination_role='private_household_military')
   for source,n in mix.items():
    add_recruits(sword,'trainee',n,location_ref=TG);record_recruitment_cohort(sword,role='trainee',count=n,location_ref=TG,source_population_ref='population_qin',source_stratum=source,recruited_at=at,profile_registry=profiles,selection_profile='sword_manor_screened_initiate',provenance_ref=f'{ev}:intake:{source}')
   manor.setdefault('sword_manor',{})['provisional_trainees']=role_count(sword,'trainee');manor.setdefault('recruitment_runtime',{})['last_sword_manor_intake']=moved
  sword['cohort_training_closes']=int(sword.get('cohort_training_closes',0))+occ;sword['last_review']=at;manor.setdefault('recruitment_runtime',{})['last_review']=at;prog.setdefault('runtime',{})['last_settled_at']=at;prog['runtime']['completed_monthly_reviews']=int(prog['runtime'].get('completed_monthly_reviews',0))+occ;validate_cohort_ledger(sword);validate_cohort_ledger(house);self.put(S,sword);self.put(H,house);self.put(Q,qin);self.put(M,manor);self.put(PR,prog);self.put(CR,cprog)
