import copy

from sword_runtime.production_planner import ProductionCampaignPlanner


def planner_for(campaign):
    p=ProductionCampaignPlanner(campaign); p._reset(); return p


def test_sword_manor_fort_supply_is_house_tang_owned_not_qin_state(campaign):
    p=planner_for(campaign)
    depot=p.read('state/depots/fort-tang-inner-walls.json')
    assert depot['source_aggregate_depot_ref']=='depot_house_tang'
    assert depot['resupply_sources']['strategic_depot_ref']=='depot_house_tang'
    assert 'rule' not in depot['resupply_sources'], 'resupply semantics belong in runtime/game data, not hot-state prose'
    assert depot['artillery_ref']=='artillery_fort_sword_manor'
    assert p.owner_path('artillery_fort_sword_manor')=='state/art/fort-sword-manor.json'
    assert 'artillery_fort_tang_inner_walls' not in p.read('state/index/owner-index.json').get('owners', {})
    assert p.read_optional('state/art/fort-tang-inner-walls.json') is None
    for ref in p._formations_at('loc_tang_inner_walls'):
        _fp,f=p._load_formation(ref)
        assert f['supply_depot_ref']=='depot_fort_tang_inner_walls'
        assert f['logistics']['source_depot_ref']=='depot_fort_tang_inner_walls'


def test_hot_fort_materialization_does_not_create_population_and_cold_blueprint_stays_cold(campaign):
    p=planner_for(campaign)
    assert p.read_optional('state/depots/fort-gyou.json') is None
    profile=p._fortification_profile_for_site('loc_gyou')
    assert profile['logistics_blueprint']['authority'] is True
    expected_garrison=sum(int(p._load_formation(ref)[1].get('personnel',0)) for ref in p._formations_at('loc_gyou'))
    pop_before={s:int(p.read(f'state/population/{s}.json')['population_total']) for s in ('qin','zhao','chu','wei','han','yan','qi')}
    result=p._ensure_hot_fortified_site_resources('loc_gyou',at=str(p._world_time()),authority_ref='state_zhao')
    assert result['site_ref']=='loc_gyou'
    assert result['depot_ref']=='depot_fort_gyou'
    depot=p.read('state/depots/fort-gyou.json')
    assert depot['geography']['owns_local_population'] is False
    assert depot['garrison_summary']['personnel']==expected_garrison
    assert result['garrison_personnel']==expected_garrison
    assert depot['stocks'].get('construction_material_units',0)==0
    art=p.read('state/art/fort-gyou.json')
    assert art['site_ref']=='loc_gyou' and art['depot_ref']=='depot_fort_gyou'
    pop_after={s:int(p.read(f'state/population/{s}.json')['population_total']) for s in pop_before}
    assert pop_after==pop_before


def test_stale_location_index_cannot_create_phantom_fort_garrison(campaign):
    p=planner_for(campaign)
    remote_ref='formation_high_guard_qin_a'
    # Pin the premise owned by this regression instead of depending on the live
    # campaign snapshot's current movement of the formation.
    remote_path, remote = p._load_formation(remote_ref)
    remote = copy.deepcopy(remote)
    remote['location_ref']='loc_kanyou'
    p.put(remote_path, remote)
    assert p._load_formation(remote_ref)[1]['location_ref']=='loc_kanyou'
    expected_garrison=sum(int(p._load_formation(ref)[1].get('personnel',0)) for ref in p._formations_at('loc_gyou'))
    idx=copy.deepcopy(p.read('state/index/location-formation-index.json'))
    idx.setdefault('locations',{}).setdefault('loc_gyou',[]).append(remote_ref)
    p.put('state/index/location-formation-index.json',idx)

    assert remote_ref not in p._formations_at('loc_gyou')
    result=p._ensure_hot_fortified_site_resources('loc_gyou',at=str(p._world_time()),authority_ref='state_zhao')
    assert result['garrison_personnel']==expected_garrison


def test_kankoku_uses_exact_specialized_hot_owners(campaign):
    p=planner_for(campaign)
    result=p._ensure_hot_fortified_site_resources('loc_kankoku_pass',at=str(p._world_time()),authority_ref='state_qin')
    expected=sum(int(p._load_formation(ref)[1].get('personnel',0)) for ref in p._formations_at('loc_kankoku_pass'))
    assert result['garrison_personnel']==expected
    assert expected > 0
    assert result['depot_ref']=='state_depot_qin_kankoku'
    assert result['artillery_ref']=='artillery_qin_kankoku'
    assert p.owner_path('state_depot_qin_kankoku')=='state/depots/qin-kankoku.json'
    assert p.owner_path('artillery_qin_kankoku')=='state/art/kankoku-artillery.json'


def test_tang_manor_uses_one_canonical_storage_capacity_and_finite_siege_stock(campaign):
    p=planner_for(campaign)
    depot=p.read('state/depots/house-tang.json')
    assert 'infrastructure_capacity' not in depot
    assert depot['storage_capacity']['grain_kg']==760_000_000
    assert depot['storage_capacity']['war_arrows']==180_000_000
    assert depot['storage_capacity']['war_bolts']==35_000_000
    assert depot['stocks']['grain_kg'] <= depot['storage_capacity']['grain_kg']
    assert depot['stocks']['war_arrows'] <= depot['storage_capacity']['war_arrows']
    before=int(depot['stocks']['grain_kg'])
    water_before=int(depot['water_reserve']['current_person_days'])
    fort={'site_ref':'loc_tang_inner_citadel','location_ref':'loc_tang_inner_citadel','garrison_formation_refs':p._formations_at('loc_tang_inner_citadel')}
    result=p._siege_defender_reserve_draw(fort,days=1,defenders=1000,at=str(p._world_time()))
    after=p.read('state/depots/house-tang.json')
    assert result['consumed']['grain_kg']==2000
    assert int(after['stocks']['grain_kg'])==before-2000
    assert int(after['water_reserve']['current_person_days'])==water_before-1000


def test_fort_resupply_convoy_owns_stock_in_transit(campaign):
    p=planner_for(campaign)
    source=p.read('state/depots/zhao.json')
    before=int(source['stocks']['grain_kg'])
    result=p._fort_dispatch_resupply_convoy(site_ref='loc_gyou',source_depot_ref='state_depot_zhao',cargo={'grain_kg':1000},at=str(p._world_time()))
    source_after=p.read('state/depots/zhao.json')
    assert int(source_after['stocks']['grain_kg'])==before-1000
    path=p.owner_path(result['convoy_ref'])
    convoy=p.read(path)
    assert convoy['cargo']=={'grain_kg':1000}
    assert convoy['status']=='in_transit'
    dest=p.read('state/depots/fort-gyou.json')
    dest_before=int(dest['stocks'].get('grain_kg',0))
    settled=p._fort_settle_resupply_convoy(result['convoy_ref'],at=convoy['arrives_at'])
    dest_after=p.read('state/depots/fort-gyou.json')
    assert settled['delivered']['grain_kg']==1000
    assert int(dest_after['stocks']['grain_kg'])==dest_before+1000


def test_tang_strategic_reserve_is_inner_citadel_authority_and_outer_review_cannot_move_it(campaign):
    p=planner_for(campaign)
    inner=p._fortification_profile_for_site('loc_tang_inner_citadel')['logistics_blueprint']
    outer=p._fortification_profile_for_site('loc_tang_manor')['logistics_blueprint']
    depot=p.read('state/depots/house-tang.json')
    master=p.read('game/data/world/tang-manor-master-plan.json')['strategic_storage']
    canonical=inner['storage_capacity']
    for key,value in canonical.items():
        assert depot['storage_capacity'][key] == value
    assert depot['site_ref']=='loc_tang_inner_citadel'
    assert depot['location_ref']=='loc_tang_inner_citadel_strategic_depot'
    assert depot['storage_capacity']['grain_kg']==master['grain_capacity_kg']==760_000_000
    assert depot['storage_capacity']['carts']==inner['storage_capacity']['carts']==12_000
    assert depot['medical_reserve']['bed_capacity']==master['medical_bed_capacity']==12_000
    assert depot['wagon_staging']['covered_cart_capacity']==inner['wagon_staging']['covered_cart_capacity']==12_000
    assert depot['water_reserve']['capacity_person_days']==inner['water_system']['reserve_capacity_person_days']==master['water_reserve_capacity_person_days']==9_000_000
    assert 0 <= depot['water_reserve']['current_person_days'] <= depot['water_reserve']['capacity_person_days']
    strategic_stock=dict(depot['stocks'])
    # Reviewing the outer enclosure materializes/refreshes a routine local depot;
    # it may reference the strategic reserve upstream but cannot move or duplicate it.
    result=p._ensure_hot_fortified_site_resources('loc_tang_manor',at=str(p._world_time()),authority_ref='house_tang')
    assert result['depot_ref']=='depot_fort_tang_manor'
    after=p.read('state/depots/house-tang.json')
    assert after['site_ref']=='loc_tang_inner_citadel'
    assert after['stocks']==strategic_stock
    outer_depot=p.read('state/depots/fort-tang-manor.json')
    assert outer_depot['storage_capacity']==outer['storage_capacity']
    assert outer_depot['source_aggregate_depot_ref']=='depot_house_tang'


def test_exact_convoy_survives_missing_active_and_route_cache(campaign):
    p=planner_for(campaign)
    result=p._fort_dispatch_resupply_convoy(
        site_ref='loc_gyou', source_depot_ref='state_depot_zhao',
        cargo={'grain_kg':1000}, at=str(p._world_time()),
    )
    convoy_ref=result['convoy_ref']
    convoy=p.read(p.owner_path(convoy_ref))
    idx=copy.deepcopy(p.read('state/logistics/fortification-convoys/index.json'))
    idx['active_refs']=[ref for ref in idx.get('active_refs',[]) if ref!=convoy_ref]
    idx.get('convoys',{}).pop(convoy_ref,None)
    p.put('state/logistics/fortification-convoys/index.json',idx)

    assert p._fort_active_convoy_for_site('loc_gyou') is True
    repaired=p.read('state/logistics/fortification-convoys/index.json')
    assert convoy_ref in repaired['active_refs']
    assert repaired['convoys'][convoy_ref]==p.owner_path(convoy_ref)

    dest_before=int(p.read('state/depots/fort-gyou.json')['stocks'].get('grain_kg',0))
    settled=p._fort_settle_resupply_convoy(convoy_ref,at=convoy['arrives_at'])
    dest_after=int(p.read('state/depots/fort-gyou.json')['stocks'].get('grain_kg',0))
    assert settled['delivered']['grain_kg']==1000
    assert dest_after==dest_before+1000
