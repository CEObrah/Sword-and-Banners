from __future__ import annotations
import copy
from sword_runtime.production_planner import ProductionCampaignPlanner


def planner_for(root):
    p=ProductionCampaignPlanner(root); p.PLAYER_ACTOR=str(p.read('state/meta.json')['player_id']); return p


def make_group(p, count=100):
    source_ref='formation_zhao_retsubi_gate_command'; cust_ref='formation_qin_kankoku_central_gate'; loc='loc_kankoku_pass'
    sp,s0=p._load_formation(source_ref); source=copy.deepcopy(s0); source['location_ref']=loc; source['surrender_state']={'status':'offered','offered_to_formation_ref':cust_ref,'offered_personnel':count,'offered_at':str(p._world_time())}; p.put(sp,source)
    cp,c0=p._load_formation(cust_ref); cust=copy.deepcopy(c0); cust['location_ref']=loc; p.put(cp,cust)
    return p._custody_new_group(source_formation_ref=source_ref,custodian_formation_ref=cust_ref,count=count,at=str(p._world_time()))


def test_aggregate_surrender_conserves_source_force_bodies(campaign):
    p=planner_for(campaign); source_before=int(p.read(p.owner_path('force_state_zhao'))['headcount']); form_before=int(p._load_formation('formation_zhao_retsubi_gate_command')[1]['personnel'])
    group=make_group(p,100)
    source=p.read(p.owner_path('force_state_zhao')); formation=p._load_formation('formation_zhao_retsubi_gate_command')[1]
    assert int(source['headcount'])==source_before
    assert int(formation['personnel'])==form_before-100
    assert sum(source['external_personnel_allocations'][group['owner_id']].values())==100
    assert group['personnel']==100


def test_ransom_moves_exact_silver_and_releases_exact_bodies(campaign):
    p=planner_for(campaign); group=make_group(p,50); path=p.owner_path(group['owner_id'])
    zpath=p.owner_path('state_zhao'); qpath=p.owner_path('state_qin'); zb=int(p.read(zpath)['treasury_silver']); qb=int(p.read(qpath)['treasury_silver'])
    group['ransom_offer']={'status':'offered','amount_silver':1000}; p._custody_transfer_silver('state_zhao','state_qin',1000,at=str(p._world_time()),reason='test-ransom'); released=p._custody_release_aggregate(group,status='ransomed',at=str(p._world_time())); p.put(path,group)
    assert released==50 and group['personnel']==0
    assert int(p.read(zpath)['treasury_silver'])==zb-1000
    assert int(p.read(qpath)['treasury_silver'])==qb+1000


def test_prisoner_testimony_is_unverified_information_not_truth(campaign):
    p=planner_for(campaign); group=make_group(p,25); ref=p._custody_testimony(group,'state_zhao','We were told the western road was watched.',at=str(p._world_time()),knower_ref=p.PLAYER_ACTOR); info=p.read(p.owner_path(ref))
    assert info['world_truth_authority'] is False
    assert info['claim_status']=='unverified_prisoner_testimony'
    assert info['provenance']==group['owner_id']


def test_voluntary_recruitment_moves_force_and_population_without_cloning(campaign):
    p=planner_for(campaign); group=make_group(p,40); path=p.owner_path(group['owner_id']); group['recruitment_offer']={'status':'accepted','destination_force_ref':'force_state_qin'}
    zforce_before=int(p.read(p.owner_path('force_state_zhao'))['headcount']); qforce_before=int(p.read(p.owner_path('force_state_qin'))['headcount']); zpop_before=int(p.read('state/population/zhao.json')['population_total']); qpop_before=int(p.read('state/population/qin.json')['population_total'])
    moved=p._custody_finalize_recruitment(group,'force_state_qin',at=str(p._world_time())); p.put(path,group)
    assert moved==40 and group['status']=='recruited' and group['personnel']==0
    assert int(p.read(p.owner_path('force_state_zhao'))['headcount'])==zforce_before-40
    assert int(p.read(p.owner_path('force_state_qin'))['headcount'])==qforce_before+40
    assert int(p.read('state/population/zhao.json')['population_total'])==zpop_before-40
    assert int(p.read('state/population/qin.json')['population_total'])==qpop_before+40


def test_prisoner_provision_draws_nested_fort_water_without_creating_legacy_water_field(campaign):
    from types import SimpleNamespace
    p=planner_for(campaign); group=make_group(p,20)
    depot_ref='state_depot_qin_kankoku'; depot_path=p.owner_path(depot_ref); before=copy.deepcopy(p.read(depot_path))
    group_before=p.read(p.owner_path(group['owner_id']))
    meta=p.read('state/meta.json')
    cmd=SimpleNamespace(command_type='custody_action',actor_id=p.INTERNAL_ACTOR,expected_revision=int(meta['revision']),submitted_at=str(meta['time']),digest='custody-water-test',mode='gameplay')
    result=p._dispatch(cmd,{'action':'provision','prisoner_group_ref':group['owner_id'],'depot_ref':depot_ref,'food_kg':40,'water_person_days':20})
    after=p.read(depot_path); held=p.read(p.owner_path(group['owner_id']))
    assert result['prisoner_group_ref']==group['owner_id']
    assert int(after['water_reserve']['current_person_days'])==int(before['water_reserve']['current_person_days'])-20
    assert 'water_reserve_person_days' not in after
    assert int(held['water_person_days'])==int(group_before.get('water_person_days',0))+20
    assert int(held['food_kg'])==int(group_before.get('food_kg',0))+40
