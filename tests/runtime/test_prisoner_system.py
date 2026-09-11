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


def test_prisoner_provision_draws_nested_fort_water_without_duplicate_water_authority(campaign):
    from types import SimpleNamespace
    p=planner_for(campaign); group=make_group(p,20)
    depot_ref='state_depot_qin_kankoku'; depot_path=p.owner_path(depot_ref); before=copy.deepcopy(p.read(depot_path))
    group_before=p.read(p.owner_path(group['owner_id']))
    meta=p.read('state/meta.json')
    cmd=SimpleNamespace(command_type='custody_action',actor_id=p.INTERNAL_ACTOR,expected_revision=int(meta['revision']),submitted_at=str(meta['time']),digest='custody-water-test', semantic_digest='custody-water-test',mode='gameplay')
    result=p._dispatch(cmd,{'action':'provision','prisoner_group_ref':group['owner_id'],'depot_ref':depot_ref,'food_kg':40,'water_person_days':20})
    after=p.read(depot_path); held=p.read(p.owner_path(group['owner_id']))
    assert result['prisoner_group_ref']==group['owner_id']
    assert int(after['water_reserve']['current_person_days'])==int(before['water_reserve']['current_person_days'])-20
    assert 'water_reserve_person_days' not in after
    assert int(held['water_person_days'])==int(group_before.get('water_person_days',0))+20
    assert int(held['food_kg'])==int(group_before.get('food_kg',0))+40


def test_named_prisoner_release_fails_closed_if_exact_person_authority_is_missing(campaign):
    import pytest
    from types import SimpleNamespace

    p=planner_for(campaign); group=make_group(p,20); path=p.owner_path(group['owner_id'])
    held=copy.deepcopy(p.read(path)); held['named_prisoner_refs']=['char_missing_prisoner_authority']; p.put(path,held)
    meta=p.read('state/meta.json')
    cmd=SimpleNamespace(command_type='custody_action',actor_id=p.INTERNAL_ACTOR,expected_revision=int(meta['revision']),submitted_at=str(meta['time']),digest='custody-missing-person-test',semantic_digest='custody-missing-person-test',mode='gameplay')
    with pytest.raises((KeyError,ValueError,FileNotFoundError)):
        p._dispatch(cmd,{'action':'release','prisoner_group_ref':group['owner_id']})


def _stage_named_capture(p, *, person_ref='char_kisui', battle_ref='battle_named_custody_fixture'):
    source_ref='formation_zhao_retsubi_gate_command'; cust_ref='formation_qin_kankoku_central_gate'; loc='loc_kankoku_pass'
    cp,c0=p._load_formation(cust_ref); cust=copy.deepcopy(c0); cust['location_ref']=loc; p.put(cp,cust)
    pp,p0=p._exact_person(person_ref,active=False); person=copy.deepcopy(p0); p._set_person_location(person,loc); p.put(pp,person)
    group_ref=p._custody_attach_named_capture(
        person_ref,cust_ref,battle_ref,str(p._world_time()),source_formation_ref=source_ref,
    )
    return person_ref,group_ref,cust_ref,loc


def test_named_prisoner_moves_with_custodian_and_person_location_index(campaign):
    from types import SimpleNamespace

    p=planner_for(campaign)
    person_ref,group_ref,cust_ref,_start=_stage_named_capture(p)
    destination='loc_qin_regional_01'
    command=SimpleNamespace(command_type='formation_move')

    def move_custodian():
        fp,f0=p._load_formation(cust_ref); formation=copy.deepcopy(f0); formation['location_ref']=destination; p.put(fp,formation)
        return {'formation_ref':cust_ref,'destination':destination}

    p._command_layer_prisoner_system(command,{'formation_ref':cust_ref},move_custodian)
    group=p.read(p.owner_path(group_ref)); person=p.read(p.owner_path(person_ref)); index=p.read('state/index/person-location-index.json')
    assert group['location_ref']==destination
    assert p._person_location(person)==destination
    assert person['custody_state']['location_ref']==destination
    assert person['custody_state']['prisoner_group_ref']==group_ref
    assert index['person_location'][person_ref]==destination


def test_named_only_release_closes_custody_and_keeps_release_location(campaign):
    from types import SimpleNamespace

    p=planner_for(campaign)
    person_ref,group_ref,_cust_ref,loc=_stage_named_capture(p,battle_ref='battle_named_release_fixture')
    meta=p.read('state/meta.json')
    cmd=SimpleNamespace(command_type='custody_action',actor_id=p.INTERNAL_ACTOR,expected_revision=int(meta['revision']),submitted_at=str(meta['time']),digest='named-release-test',semantic_digest='named-release-test',mode='gameplay')
    p._dispatch(cmd,{'action':'release','prisoner_group_ref':group_ref})
    group=p.read(p.owner_path(group_ref)); person=p.read(p.owner_path(person_ref))
    assert group['personnel']==0
    assert group['named_prisoner_refs']==[]
    assert group['status']=='released'
    assert group['legal_status']=='released'
    assert person['custody_state']['status']=='released'
    assert person['custody_state']['former_prisoner_group_ref']==group_ref
    assert p._person_location(person)==loc
    assert group_ref not in p.read('state/custody/index.json')['active_refs']


def test_named_prisoner_exchange_releases_both_exact_people(campaign):
    from types import SimpleNamespace

    p=planner_for(campaign)
    person_a,group_a,cust_ref,loc=_stage_named_capture(p,person_ref='char_kisui',battle_ref='battle_named_exchange_a')
    # A second exact person captured into a separate battle/source group at the same exchange point.
    pp,p0=p._exact_person('char_shin',active=False); person=copy.deepcopy(p0); p._set_person_location(person,loc); p.put(pp,person)
    group_b=p._custody_attach_named_capture('char_shin',cust_ref,'battle_named_exchange_b',str(p._world_time()),source_formation_ref='formation_zhao_retsubi_gate_command')
    path_a=p.owner_path(group_a); a=copy.deepcopy(p.read(path_a)); a['exchange_offer']={'status':'offered','other_prisoner_group_ref':group_b,'offered_at':str(p._world_time()),'offered_by_ref':p.INTERNAL_ACTOR}; p.put(path_a,a)
    meta=p.read('state/meta.json')
    cmd=SimpleNamespace(command_type='custody_action',actor_id=p.INTERNAL_ACTOR,expected_revision=int(meta['revision']),submitted_at=str(meta['time']),digest='named-exchange-test',semantic_digest='named-exchange-test',mode='gameplay')
    p._dispatch(cmd,{'action':'accept_exchange','prisoner_group_ref':group_a,'other_prisoner_group_ref':group_b})
    for group_ref,person_ref in ((group_a,person_a),(group_b,'char_shin')):
        group=p.read(p.owner_path(group_ref)); person=p.read(p.owner_path(person_ref))
        assert group['status']=='exchanged'
        assert group['named_prisoner_refs']==[]
        assert person['custody_state']['status']=='exchanged'
        assert person['custody_state']['former_prisoner_group_ref']==group_ref
        assert p._person_location(person)==loc
        assert group_ref not in p.read('state/custody/index.json')['active_refs']


def test_named_battle_prisoner_carries_source_authority_for_ransom(campaign):
    from types import SimpleNamespace

    p=planner_for(campaign)
    person_ref,group_ref,_cust_ref,loc=_stage_named_capture(p,battle_ref='battle_named_ransom_fixture')
    path=p.owner_path(group_ref); group=copy.deepcopy(p.read(path))
    assert group['source_force_ref']=='force_state_zhao'
    assert group['source_formation_ref']=='formation_zhao_retsubi_gate_command'
    amount=1000
    group['ransom_offer']={'status':'offered','amount_silver':amount}
    p.put(path,group)
    zpath=p.owner_path('state_zhao'); qpath=p.owner_path('state_qin')
    z_before=int(p.read(zpath)['treasury_silver']); q_before=int(p.read(qpath)['treasury_silver'])
    meta=p.read('state/meta.json')
    cmd=SimpleNamespace(command_type='custody_action',actor_id=p.INTERNAL_ACTOR,expected_revision=int(meta['revision']),submitted_at=str(meta['time']),digest='named-ransom-test',semantic_digest='named-ransom-test',mode='gameplay')
    p._dispatch(cmd,{'action':'accept_ransom','prisoner_group_ref':group_ref})
    group=p.read(path); person=p.read(p.owner_path(person_ref))
    assert group['status']=='ransomed'
    assert group['named_prisoner_refs']==[]
    assert person['custody_state']['status']=='ransomed'
    assert p._person_location(person)==loc
    assert int(p.read(zpath)['treasury_silver'])==z_before-amount
    assert int(p.read(qpath)['treasury_silver'])==q_before+amount


def test_stale_custody_route_cannot_substitute_different_exact_group(campaign):
    import json

    p = planner_for(campaign)
    group = make_group(p, 20)
    group_ref = group['owner_id']
    canonical_path = p.owner_path(group_ref)

    decoy_ref = 'prisoners_stale_route_decoy'
    decoy_path = 'state/custody/groups/prisoners_stale_route_decoy.json'
    decoy = copy.deepcopy(group)
    decoy['owner_id'] = decoy_ref
    p.put(decoy_path, decoy)

    index = copy.deepcopy(p.read('state/custody/index.json'))
    index.setdefault('groups', {})[group_ref] = decoy_path
    p.put('state/custody/index.json', index)

    resolved_path, resolved = p._custody_group(group_ref)
    assert resolved_path == canonical_path
    assert resolved['owner_id'] == group_ref
    assert resolved['owner_id'] != decoy_ref


def test_exact_active_custody_repairs_missing_route_and_capacity_cache(campaign):
    p = planner_for(campaign)
    ref = "prisoners_route_recovery"
    path = f"state/custody/groups/{ref}.json"
    p.put(path, {
        "schema": "sword-prisoner-group", "owner_id": ref,
        "source_formation_ref": "formation_zhao_border_line",
        "source_force_ref": "force_state_zhao",
        "custodian_formation_ref": "formation_red_lance_a",
        "captor_authority_ref": "house_tang",
        "location_ref": "loc_tang_manor", "personnel": 9,
        "by_role": {"line_infantry": 9}, "cohort_slices": [],
        "named_prisoner_refs": [], "guards_allocated": 2,
        "guard_requirement": 2, "restraint_condition_milli": 700,
        "enclosure_condition_milli": 650, "health_milli": 900,
        "food_kg": 0, "water_person_days": 0,
        "legal_status": "prisoner_of_war", "status": "held",
        "holding_capacity": {"holding_site_ref": "loc_tang_manor"},
    })
    p._register_owner(ref, path)
    idx = copy.deepcopy(p.read("state/custody/index.json"))
    idx.setdefault("groups", {}).pop(ref, None)
    idx["active_refs"] = [x for x in idx.get("active_refs", []) if x != ref]
    p.put("state/custody/index.json", idx)

    rows = p._custody_active_groups()
    assert any(row[0] == ref and row[1] == path for row in rows)
    repaired = p.read("state/custody/index.json")
    assert repaired["groups"][ref] == path
    assert ref in repaired["active_refs"]
    occupancy = p._custody_existing_occupancy(
        custodian_formation_ref="formation_red_lance_a",
        holding_site_ref="loc_tang_manor",
    )
    assert occupancy["custodian_people"] >= 9
    assert occupancy["site_people"] >= 9
    p._custody_ensure_review_host()
    runtime = p.read("state/runtime.json")
    assert ref in runtime["hosts"]["host_prisoner_custody_review"]["routed_group_refs"]
